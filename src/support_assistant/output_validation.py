"""Parse e validação da saída do modelo.

Erros estruturais (JSON inválido, campo obrigatório ausente ou vazio) fazem a
geração ser repetida com um pedido de correção. Problemas de forma (fluxograma
com caracteres não ASCII, por exemplo) viram avisos e não bloqueiam.
"""

from __future__ import annotations

import json
import re

from .content_types import get_content_type


class OutputValidationError(ValueError):
    """A saída do modelo não segue o formato pedido."""


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_json_output(text: str) -> dict:
    """Converte o texto do modelo em dict, tolerando cercas de código e texto ao redor."""
    cleaned = _FENCE.sub("", text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise OutputValidationError("A resposta não contém um objeto JSON.") from None
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise OutputValidationError(f"JSON inválido: {exc.msg} (posição {exc.pos}).") from None
    if not isinstance(data, dict):
        raise OutputValidationError("O JSON deve ser um objeto, não uma lista ou valor solto.")
    return data


def validate_output(content_type: str, data: dict) -> list[str]:
    """Valida os campos obrigatórios. Lança erro se faltar algo; retorna avisos não bloqueantes."""
    ct = get_content_type(content_type)
    problems = [f"campo '{name}' ausente ou vazio" for name in ct.required_fields if _is_empty(data.get(name))]
    problems += _CHECKS[content_type](data)
    if problems:
        raise OutputValidationError("; ".join(problems))
    return _WARNINGS.get(content_type, lambda _d: [])(data)


# ------------------------------------------------------- checagens por tipo

def _check_diagnosis(d: dict) -> list[str]:
    problems = _list_of_objects(d, "hypotheses", ("id", "description"))
    problems += _list_of_objects(d, "evidence", ("signal",))
    problems += _list_of_objects(d, "missing_information", ("item",))
    conclusion = d.get("probable_conclusion")
    if conclusion is not None and (not isinstance(conclusion, dict) or _is_empty(conclusion.get("summary"))):
        problems.append("'probable_conclusion' precisa ser objeto com 'summary'")
    return problems


def _check_steps(d: dict) -> list[str]:
    return _list_of_objects(d, "steps", ("action",))


def _check_questions(d: dict) -> list[str]:
    return _list_of_objects(d, "questions", ("question",))


def _check_flow(d: dict) -> list[str]:
    problems = []
    if not _is_empty(d.get("ascii_flowchart")) and not isinstance(d["ascii_flowchart"], str):
        problems.append("'ascii_flowchart' deve ser texto")
    problems += _list_of_objects(d, "decision_points", ("question",))
    return problems


def _warn_flow(d: dict) -> list[str]:
    chart = d.get("ascii_flowchart", "")
    warnings = []
    if any(ord(ch) > 127 for ch in chart if ch not in "áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ"):
        warnings.append("fluxograma usa caracteres fora do ASCII (setas ou caixas Unicode)")
    if any(len(line) > 80 for line in chart.splitlines()):
        warnings.append("fluxograma tem linhas com mais de 80 caracteres")
    return warnings


_CHECKS = {
    "diagnosis": _check_diagnosis,
    "resolution_steps": _check_steps,
    "clarifying_questions": _check_questions,
    "flow_summary": _check_flow,
}
_WARNINGS = {"flow_summary": _warn_flow}


# ------------------------------------------------------------------ helpers

def _is_empty(value) -> bool:
    return value is None or (isinstance(value, (str, list, dict)) and len(value) == 0) or (
        isinstance(value, str) and not value.strip()
    )


def _list_of_objects(d: dict, key: str, required: tuple[str, ...]) -> list[str]:
    value = d.get(key)
    if _is_empty(value):
        return []  # já reportado como obrigatório (ou opcional)
    if not isinstance(value, list):
        return [f"'{key}' deve ser uma lista"]
    problems = []
    for i, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            problems.append(f"'{key}[{i}]' deve ser objeto")
            continue
        problems += [f"'{key}[{i}].{field}' vazio" for field in required if _is_empty(item.get(field))]
    return problems
