"""Parse e validação da saída do modelo.

A estrutura de cada tipo de conteúdo é descrita em ``schemas/<tipo>.schema.json``
(JSON Schema 2020-12). Os schemas aceitam as duas versões de prompt: os campos
que só a v2 pede são opcionais.

- Erros de estrutura (JSON inválido, campo obrigatório ausente ou vazio, tipo
  errado, valor fora da lista permitida) fazem a geração ser repetida com um
  pedido de correção.
- Problemas de coerência ou de forma (conclusão apontando para uma hipótese que
  não existe, fluxograma com linhas longas) viram avisos e não bloqueiam.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

from .config import PROJECT_ROOT
from .content_types import get_content_type

SCHEMAS_DIR = PROJECT_ROOT / "schemas"
MAX_REPORTED_ERRORS = 5


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
    """Valida contra o schema do tipo. Lança erro se a estrutura estiver errada; retorna avisos."""
    get_content_type(content_type)  # tipo desconhecido gera erro claro
    errors = sorted(validator(content_type).iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        unique = list(dict.fromkeys(_describe(e) for e in errors))  # "" falha em minLength e pattern
        messages = unique[:MAX_REPORTED_ERRORS]
        if len(unique) > MAX_REPORTED_ERRORS:
            messages.append(f"e mais {len(unique) - MAX_REPORTED_ERRORS} problema(s)")
        raise OutputValidationError("; ".join(messages))
    return _WARNINGS.get(content_type, lambda _d: [])(data)


@lru_cache(maxsize=None)
def load_schema(content_type: str, schemas_dir: Path = SCHEMAS_DIR) -> dict:
    path = schemas_dir / f"{content_type}.schema.json"
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise OutputValidationError(f"Schema não encontrado: {path}") from None
    Draft202012Validator.check_schema(schema)
    return schema


@lru_cache(maxsize=None)
def validator(content_type: str) -> Draft202012Validator:
    return Draft202012Validator(load_schema(content_type))


# --------------------------------------------------- mensagens em português

def _describe(error) -> str:
    path = _path(error.absolute_path)
    v = error.validator
    if v == "required":
        missing = error.message.split("'")[1] if "'" in error.message else error.message
        where = f"{path}." if path != "raiz" else ""
        return f"campo '{where}{missing}' ausente"
    if v == "type":
        return f"'{path}' deve ser do tipo {_type_name(error.validator_value)}"
    if v in ("minLength", "pattern"):
        return f"'{path}' está vazio"
    if v == "minItems":
        return f"'{path}' precisa de pelo menos {error.validator_value} item(ns)"
    if v == "maxItems":
        return f"'{path}' tem itens demais (máximo {error.validator_value})"
    if v == "enum":
        options = ", ".join(map(str, error.validator_value))
        return f"'{path}' = {error.instance!r} não é permitido (use: {options})"
    if v == "minimum":
        return f"'{path}' deve ser no mínimo {error.validator_value}"
    return f"'{path}': {error.message}"


def _path(parts) -> str:
    out = ""
    for p in parts:
        out += f"[{p + 1}]" if isinstance(p, int) else (f".{p}" if out else str(p))
    return out or "raiz"


def _type_name(t) -> str:
    names = {"string": "texto", "array": "lista", "object": "objeto", "integer": "inteiro", "number": "número"}
    if isinstance(t, list):
        return " ou ".join(names.get(x, x) for x in t)
    return names.get(t, t)


# ------------------------------------------------------- avisos por tipo

def _warn_diagnosis(d: dict) -> list[str]:
    ids = {h.get("id") for h in d.get("hypotheses", [])}
    warnings = []
    referenced = set()
    for e in d.get("evidence", []):
        referenced |= set(e.get("supports", [])) | set(e.get("weakens", []))
    unknown = sorted(referenced - ids)
    if unknown:
        warnings.append(f"evidências citam hipóteses que não existem: {', '.join(unknown)}")
    conclusion_id = (d.get("probable_conclusion") or {}).get("hypothesis_id")
    if conclusion_id and conclusion_id not in ids:
        warnings.append(f"a conclusão aponta para a hipótese {conclusion_id}, que não existe")
    return warnings


def _warn_questions(d: dict) -> list[str]:
    priorities = [q.get("priority") for q in d.get("questions", []) if q.get("priority") is not None]
    if len(priorities) != len(set(priorities)):
        return ["perguntas com prioridade repetida"]
    return []


def _warn_flow(d: dict) -> list[str]:
    chart = d.get("ascii_flowchart", "")
    warnings = []
    if any(ord(ch) > 127 for ch in chart if ch not in "áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ"):
        warnings.append("fluxograma usa caracteres fora do ASCII (setas ou caixas Unicode)")
    if any(len(line) > 80 for line in chart.splitlines()):
        warnings.append("fluxograma tem linhas com mais de 80 caracteres")
    for i, p in enumerate(d.get("decision_points", []), start=1):
        if p.get("if_yes", "").strip().lower() == p.get("if_no", "").strip().lower():
            warnings.append(f"decisão {i} tem a mesma ação no sim e no não")
    return warnings


_WARNINGS = {
    "diagnosis": _warn_diagnosis,
    "clarifying_questions": _warn_questions,
    "flow_summary": _warn_flow,
}
