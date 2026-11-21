"""Os quatro tipos de conteúdo gerados e os campos mínimos de cada saída.

Os campos obrigatórios são os mesmos em todas as versões de prompt, para que
a validação e a comparação entre versões sejam justas. Uma versão pode pedir
campos extras, mas nunca remover estes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContentType:
    id: str
    label: str
    required_fields: tuple[str, ...]


CONTENT_TYPES: dict[str, ContentType] = {
    ct.id: ct
    for ct in (
        ContentType(
            "diagnosis",
            "Diagnóstico",
            ("hypotheses", "evidence", "missing_information", "probable_conclusion"),
        ),
        ContentType(
            "resolution_steps",
            "Passo a passo de resolução",
            ("steps", "if_not_resolved"),
        ),
        ContentType(
            "clarifying_questions",
            "Perguntas de esclarecimento",
            ("questions",),
        ),
        ContentType(
            "flow_summary",
            "Resumo visual do fluxo",
            ("ascii_flowchart", "decision_points"),
        ),
    )
}


def get_content_type(content_type_id: str) -> ContentType:
    try:
        return CONTENT_TYPES[content_type_id]
    except KeyError:
        options = ", ".join(CONTENT_TYPES)
        raise ValueError(f"Tipo de conteúdo inválido: {content_type_id!r}. Opções: {options}") from None
