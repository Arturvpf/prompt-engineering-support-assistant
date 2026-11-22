"""Rubrica fixa, avaliação de execuções e comparação entre versões de prompt.

A avaliação é feita por uma pessoa (o avaliador) e fica gravada no próprio
registro do histórico, no campo ``evaluation``. A comparação junta execuções do
mesmo cenário (mesmo cliente, ticket, tipo de conteúdo, modelo e configurações)
que diferem apenas na versão do prompt, e verifica isso antes de comparar.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .history import HistoryStore, now_iso


@dataclass(frozen=True)
class Criterion:
    id: str
    label: str
    description: str


RUBRIC: tuple[Criterion, ...] = (
    Criterion("clarity", "Clareza", "Resposta compreensível, organizada, sem ambiguidade desnecessária."),
    Criterion("customer_fit", "Adequação ao nível do cliente", "Vocabulário, profundidade e explicações combinam com o perfil."),
    Criterion("actionability", "Acionabilidade", "Cliente ou atendente sabe o que fazer a seguir."),
)
CRITERIA = {c.id: c for c in RUBRIC}
SCALE = {1: "insuficiente", 2: "fraco", 3: "adequado", 4: "bom", 5: "excelente"}

# Campos que precisam ser idênticos para a comparação ser justa (só o prompt muda).
SAME_SCENARIO_FIELDS = ("customer_id", "ticket", "content_type", "generation_params")


class EvaluationError(ValueError):
    """Avaliação ou comparação inválida."""


# ------------------------------------------------------------------ avaliação

def build_evaluation(scores: dict[str, tuple[int, str]], evaluator: str) -> dict:
    """Valida as notas e monta o bloco ``evaluation`` do registro.

    ``scores`` mapeia o id do critério para (nota, justificativa).
    """
    missing = [c for c in CRITERIA if c not in scores]
    unknown = [c for c in scores if c not in CRITERIA]
    if missing or unknown:
        raise EvaluationError(
            f"critérios faltando: {missing or '-'}; desconhecidos: {unknown or '-'}. "
            f"Use exatamente: {', '.join(CRITERIA)}"
        )

    criteria = {}
    for cid in CRITERIA:  # ordem fixa da rubrica
        score, justification = scores[cid]
        if not isinstance(score, int) or isinstance(score, bool) or score not in SCALE:
            raise EvaluationError(f"nota de {cid} deve ser um inteiro de 1 a 5 (recebido {score!r}).")
        justification = (justification or "").strip()
        if not justification:
            raise EvaluationError(f"a justificativa de {cid} não pode ficar vazia.")
        criteria[cid] = {"score": score, "level": SCALE[score], "justification": justification}

    total = sum(c["score"] for c in criteria.values())
    return {
        "rubric": [c.id for c in RUBRIC],
        "scale": "1 a 5",
        "criteria": criteria,
        "total": total,
        "average": round(total / len(criteria), 2),
        "evaluator": evaluator.strip() or "manual",
        "evaluated_at": now_iso(),
    }


def evaluate_run(store: HistoryStore, run_id: str, scores: dict[str, tuple[int, str]], evaluator: str) -> dict:
    """Grava a avaliação no registro do histórico e devolve o registro atualizado."""
    record = store.get(run_id)
    if record.get("cache_hit"):
        # A avaliação vale para a saída original; o registro de cache é só um reaproveitamento.
        raise EvaluationError(
            f"{run_id} veio do cache. Avalie a execução original {record.get('source_run_id')}."
        )
    return store.update(run_id, evaluation=build_evaluation(scores, evaluator))


# ------------------------------------------------------------------ comparação

def build_comparison(store: HistoryStore, run_ids: list[str], verdict: str = "") -> dict:
    """Compara execuções do mesmo cenário que diferem só na versão do prompt.

    Aceita vários tipos de conteúdo de uma vez: as execuções são agrupadas por
    tipo e, dentro de cada grupo, cada versão pode aparecer uma única vez.
    """
    if len(run_ids) < 2:
        raise EvaluationError("informe pelo menos duas execuções para comparar.")
    if len(set(run_ids)) != len(run_ids):
        raise EvaluationError("há execuções repetidas na lista.")

    records = [store.get(rid) for rid in run_ids]
    for r in records:
        if r.get("cache_hit"):
            raise EvaluationError(f"{r['run_id']} veio do cache; use a execução original {r.get('source_run_id')}.")
        if not r.get("evaluation"):
            raise EvaluationError(f"{r['run_id']} ({r['prompt_version']}, {r['content_type']}) ainda não foi avaliada.")

    _check_same_scenario(records)

    groups: dict[str, list[dict]] = {}
    for r in records:
        groups.setdefault(r["content_type"], []).append(r)

    comparisons = []
    for content_type, group in groups.items():
        versions = [r["prompt_version"] for r in group]
        if len(group) < 2:
            raise EvaluationError(f"{content_type} tem só a versão {versions[0]}; é preciso ao menos duas.")
        if len(set(versions)) != len(versions):
            raise EvaluationError(f"{content_type} tem a mesma versão mais de uma vez: {versions}.")
        group.sort(key=lambda r: r["prompt_version"])
        comparisons.append(_compare_group(content_type, group))

    first = records[0]
    versions = sorted({r["prompt_version"] for r in records})
    overall = {
        v: sum(c["versions"][v]["total"] for c in comparisons if v in c["versions"]) for v in versions
    }
    best = max(overall.values())
    winners = [v for v, t in overall.items() if t == best]

    return {
        "created_at": now_iso(),
        "scenario": {
            "customer_id": first["customer_id"],
            "customer": first["customer"],
            "ticket_id": first["ticket_id"],
            "ticket": first["ticket"],
            "provider": first["provider"],
            "model": first["model"],
            "generation_params": first["generation_params"],
            "only_difference": "versão do prompt",
        },
        "rubric": {
            "criteria": [{"id": c.id, "label": c.label, "description": c.description} for c in RUBRIC],
            "scale": SCALE,
        },
        "versions": versions,
        "by_content_type": comparisons,
        "overall_totals": overall,
        "overall_winner": winners[0] if len(winners) == 1 else "empate",
        "verdict": verdict.strip(),
    }


def save_comparison(comparison: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def default_comparison_path(output_dir: Path, comparison: dict) -> Path:
    s = comparison["scenario"]
    stamp = comparison["created_at"][:19].replace(":", "").replace("-", "").replace("T", "-")
    return output_dir / "comparisons" / f"{s['customer_id']}_{s['ticket_id']}_{stamp}.json"


def _check_same_scenario(records: list[dict]) -> None:
    first = records[0]
    for r in records[1:]:
        for field in SAME_SCENARIO_FIELDS:
            if field == "content_type":
                continue  # tipos diferentes são agrupados separadamente
            if r.get(field) != first.get(field):
                raise EvaluationError(
                    f"{r['run_id']} difere de {first['run_id']} em '{field}'. "
                    "Na comparação só a versão do prompt pode mudar."
                )


def _compare_group(content_type: str, group: list[dict]) -> dict:
    versions = {}
    for r in group:
        ev = r["evaluation"]
        versions[r["prompt_version"]] = {
            "run_id": r["run_id"],
            "timestamp": r["timestamp"],
            "prompt_fingerprint": r["prompt_fingerprint"],
            "scores": {cid: ev["criteria"][cid]["score"] for cid in CRITERIA},
            "justifications": {cid: ev["criteria"][cid]["justification"] for cid in CRITERIA},
            "total": ev["total"],
            "average": ev["average"],
            "metrics": r.get("metrics", {}),
            "output": r["output"],
        }

    names = list(versions)
    base, other = names[0], names[-1]
    delta = {cid: versions[other]["scores"][cid] - versions[base]["scores"][cid] for cid in CRITERIA}
    best = max(v["total"] for v in versions.values())
    winners = [n for n, v in versions.items() if v["total"] == best]
    return {
        "content_type": content_type,
        "versions": versions,
        "delta": {"from": base, "to": other, **delta},
        "winner": winners[0] if len(winners) == 1 else "empate",
    }


def load_scores_file(path: Path) -> dict[str, tuple[int, str]]:
    """Lê notas de um JSON no formato {"clarity": {"score": 4, "justification": "..."}, ...}."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"não foi possível ler {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise EvaluationError(f"{path} deve conter um objeto JSON.")
    try:
        return {cid: (v["score"], v["justification"]) for cid, v in data.items()}
    except (TypeError, KeyError) as exc:
        raise EvaluationError(f"{path}: cada critério precisa de 'score' e 'justification'.") from exc

