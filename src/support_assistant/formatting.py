"""Formata a saída JSON de cada tipo de conteúdo como texto legível no terminal.

Os campos opcionais (que só a v2 pede, por exemplo) são exibidos quando
existem, então o mesmo formatador serve para todas as versões.
"""

from __future__ import annotations

import textwrap
from contextvars import ContextVar

from .content_types import get_content_type
from .evaluation import CRITERIA

WIDTH = 88


def render_record(record: dict, history_path) -> str:
    """Cabeçalho, conteúdo, avisos, métricas e onde o JSON foi salvo."""
    ct = get_content_type(record["content_type"])
    lines = [
        "=" * WIDTH,
        f"{ct.label}  |  prompt {record['prompt_version']}  |  {record['provider']}/{record['model']}",
        f"Cliente: {record['customer']['name']} ({record['customer_id']})  |  Ticket: {record['ticket_id']}",
        "=" * WIDTH,
        render_output(record["content_type"], record["output"]),
    ]

    if record.get("warnings"):
        lines.append("")
        lines += [f"[aviso] {w}" for w in record["warnings"]]

    lines.append("-" * WIDTH)
    if record.get("cache_hit"):
        lines.append(f"[cache] Resultado reaproveitado da execução {record['source_run_id']} (nenhuma chamada à API).")
    else:
        m = record.get("metrics", {})
        tokens = (m.get("usage") or {}).get("total_tokens")
        lines.append(
            f"Gerado em {m.get('latency_ms', 0) / 1000:.1f}s | tokens: {tokens if tokens is not None else '?'} "
            f"| tentativas: {m.get('attempts', 1)}"
        )
    lines.append(f"Salvo em: {history_path}  (run_id {record['run_id']})")
    if record.get("evaluation"):
        lines += ["", render_evaluation(record["evaluation"])]
    return "\n".join(lines)


def render_evaluation(ev: dict) -> str:
    out = [f"AVALIAÇÃO (total {ev['total']}/{5 * len(ev['criteria'])}, média {ev['average']}, por {ev['evaluator']})"]
    for cid, c in ev["criteria"].items():
        label = CRITERIA[cid].label if cid in CRITERIA else cid
        out.append(_item(f"- {label}: {c['score']} ({c['level']}).", c["justification"]))
    return "\n".join(out)


def render_comparison(comp: dict) -> str:
    s = comp["scenario"]
    versions = comp["versions"]
    col = 10
    lines = [
        "=" * WIDTH,
        f"COMPARAÇÃO {' x '.join(versions)}  |  {s['provider']}/{s['model']}",
        f"Cliente: {s['customer']['name']} ({s['customer_id']})  |  Ticket: {s['ticket_id']}",
        f"Só muda: {s['only_difference']}  |  temperatura {s['generation_params'].get('temperature')}, "
        f"seed {s['generation_params'].get('seed')}",
        "=" * WIDTH,
    ]
    for group in comp["by_content_type"]:
        names = list(group["versions"])
        lines.append(f"\n{group['content_type']}  (vencedor: {group['winner']})")
        lines.append(f"  {'critério':<32}" + "".join(f"{n:>{col}}" for n in names) + f"{'Δ':>{col}}")
        for cid, crit in CRITERIA.items():
            row = "".join(f"{group['versions'][n]['scores'][cid]:>{col}}" for n in names)
            lines.append(f"  {crit.label:<32}{row}{group['delta'][cid]:>+{col}}")
        totals = "".join(f"{group['versions'][n]['total']:>{col}}" for n in names)
        delta_total = group["versions"][names[-1]]["total"] - group["versions"][names[0]]["total"]
        lines.append(f"  {'TOTAL':<32}{totals}{delta_total:>+{col}}")

    lines.append("\nTOTAL GERAL: " + ", ".join(f"{v} = {t}" for v, t in comp["overall_totals"].items())
                 + f"  |  vencedor: {comp['overall_winner']}")
    if comp.get("verdict"):
        lines += ["", "POR QUÊ", _wrap(comp["verdict"])]
    return "\n".join(lines)


def render_output(content_type: str, output: dict, wrap: bool = True) -> str:
    """Texto legível da saída. ``wrap=False`` não quebra linhas (a web quebra sozinha)."""
    token = _WRAP.set(wrap)
    try:
        return _RENDERERS[content_type](output).rstrip()
    finally:
        _WRAP.reset(token)


# ------------------------------------------------------------- por tipo

def _diagnosis(o: dict) -> str:
    out = ["HIPÓTESES"]
    for h in o.get("hypotheses", []):
        likelihood = f" [{h['likelihood']}]" if h.get("likelihood") else ""
        out.append(_item(f"{h.get('id', '-')}{likelihood}", h.get("description", "")))

    out += ["", "EVIDÊNCIAS"]
    for e in o.get("evidence", []):
        refs = []
        if e.get("supports"):
            refs.append("apoia " + ", ".join(e["supports"]))
        if e.get("weakens"):
            refs.append("enfraquece " + ", ".join(e["weakens"]))
        suffix = f"  ({'; '.join(refs)})" if refs else ""
        out.append(_item("-", f"{e.get('signal', '')}{suffix}"))

    out += ["", "INFORMAÇÕES FALTANTES"]
    for m in o.get("missing_information", []):
        why = f": {m['why_it_matters']}" if m.get("why_it_matters") else ""
        out.append(_item("-", f"{m.get('item', '')}{why}"))

    c = o.get("probable_conclusion") or {}
    out += ["", "CONCLUSÃO PROVÁVEL"]
    head = " ".join(x for x in (c.get("hypothesis_id"), f"(confiança {c['confidence']})" if c.get("confidence") else "") if x)
    out.append(_item(head or "-", c.get("summary", "")))
    if c.get("how_to_confirm"):
        out.append(_item("Como confirmar:", c["how_to_confirm"]))
    return "\n".join(out)


def _resolution_steps(o: dict) -> str:
    out = []
    if o.get("opening"):
        out += [_wrap(o["opening"]), ""]
    for i, s in enumerate(o.get("steps", []), start=1):
        out.append(_item(f"{s.get('number', i)}.", s.get("action", "")))
        if s.get("why"):
            out.append(_item("   Por quê:", s["why"]))
        if s.get("expected_result"):
            out.append(_item("   Resultado esperado:", s["expected_result"]))
    out += ["", _item("Se não resolver:", o.get("if_not_resolved", ""))]
    return "\n".join(out)


def _clarifying_questions(o: dict) -> str:
    out = []
    questions = sorted(o.get("questions", []), key=lambda q: q.get("priority") if isinstance(q.get("priority"), int) else 99)
    for i, q in enumerate(questions, start=1):
        out.append(_item(f"{q.get('priority', i)}.", q.get("question", "")))
        if q.get("reason"):
            out.append(_item("   Motivo:", q["reason"]))
        if q.get("how_to_find"):
            out.append(_item("   Onde encontrar:", q["how_to_find"]))
    return "\n".join(out)


def _flow_summary(o: dict) -> str:
    out = [o.get("ascii_flowchart", "").rstrip(), "", "PONTOS DE DECISÃO"]
    for d in o.get("decision_points", []):
        out.append(_item("?", d.get("question", "")))
        out.append(_item("   sim ->", d.get("if_yes", "")))
        out.append(_item("   não ->", d.get("if_no", "")))
    esc = o.get("escalation")
    if isinstance(esc, dict) and esc:
        out += ["", _item("Escalar quando:", esc.get("when", ""))]
        attach = esc.get("attach")
        if attach:
            out.append(_item("Anexar:", ", ".join(attach) if isinstance(attach, list) else str(attach)))
    return "\n".join(out)


_RENDERERS = {
    "diagnosis": _diagnosis,
    "resolution_steps": _resolution_steps,
    "clarifying_questions": _clarifying_questions,
    "flow_summary": _flow_summary,
}


# ------------------------------------------------------------- helpers

_WRAP: ContextVar[bool] = ContextVar("wrap", default=True)


def _item(label: str, text) -> str:
    """Rótulo seguido de texto com quebra de linha alinhada."""
    text = str(text) if text is not None else ""
    line = f"{label} {text}".rstrip()
    if not _WRAP.get():
        return line
    indent = " " * (len(label) - len(label.lstrip()) + 2)
    return textwrap.fill(line, width=WIDTH, subsequent_indent=indent)


def _wrap(text: str) -> str:
    return textwrap.fill(str(text), width=WIDTH) if _WRAP.get() else str(text)
