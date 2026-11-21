"""Carga e validação dos perfis de cliente e dos tickets de exemplo."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

TECHNICAL_LEVELS = ("leigo", "intermediário", "avançado")
COMMUNICATION_STYLES = ("direto", "detalhado", "didático")
CHANNELS = ("chat", "e-mail", "telefone")


class DataValidationError(ValueError):
    """Erro de dados inválidos em perfis ou tickets."""


@dataclass(frozen=True)
class CustomerProfile:
    id: str
    name: str
    technical_level: str
    communication_style: str
    channel: str
    context: str = ""

    def __post_init__(self) -> None:
        _require_text(self.id, "id do cliente")
        _require_text(self.name, f"name do cliente '{self.id}'")
        _require_choice(self.technical_level, TECHNICAL_LEVELS, "technical_level", self.id)
        _require_choice(self.communication_style, COMMUNICATION_STYLES, "communication_style", self.id)
        _require_choice(self.channel, CHANNELS, "channel", self.id)


@dataclass(frozen=True)
class Ticket:
    id: str
    title: str
    description: str
    product: str = ""
    # Gabarito interno usado só na avaliação das perguntas de esclarecimento.
    # Nunca entra no prompt, senão o modelo "saberia" o que falta.
    missing_on_purpose: tuple[str, ...] = field(default=(), compare=False)

    def __post_init__(self) -> None:
        _require_text(self.id, "id do ticket")
        _require_text(self.title, f"title do ticket '{self.id}'")
        _require_text(self.description, f"description do ticket '{self.id}'")


def load_customers(path: Path | None = None) -> dict[str, CustomerProfile]:
    items = _read_json_list(path or DATA_DIR / "customers.json")
    customers = [_build(CustomerProfile, item) for item in items]
    result = _index_by_id(customers, "cliente")
    if not 3 <= len(result) <= 5:
        raise DataValidationError(f"São esperados de 3 a 5 perfis; encontrados {len(result)}.")
    return result


def load_tickets(path: Path | None = None) -> dict[str, Ticket]:
    items = _read_json_list(path or DATA_DIR / "tickets.json")
    tickets = []
    for item in items:
        item = dict(item)
        item["missing_on_purpose"] = tuple(item.get("missing_on_purpose", ()))
        tickets.append(_build(Ticket, item))
    return _index_by_id(tickets, "ticket")


def make_adhoc_ticket(description: str, title: str = "Ticket informado pelo usuário") -> Ticket:
    """Cria um ticket a partir de texto livre digitado na interface."""
    return Ticket(id="ADHOC", title=title, description=description.strip())


# ---------------------------------------------------------------- helpers

def _read_json_list(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DataValidationError(f"Arquivo não encontrado: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DataValidationError(f"JSON inválido em {path}: {exc}") from exc
    if not isinstance(data, list):
        raise DataValidationError(f"{path} deve conter uma lista JSON.")
    return data


def _build(cls, item: dict):
    if not isinstance(item, dict):
        raise DataValidationError(f"Item inválido (esperado objeto): {item!r}")
    try:
        return cls(**item)
    except TypeError as exc:
        raise DataValidationError(f"Campos inválidos em {item.get('id', '?')}: {exc}") from exc


def _index_by_id(items, label: str) -> dict:
    result = {}
    for item in items:
        if item.id in result:
            raise DataValidationError(f"id de {label} duplicado: {item.id}")
        result[item.id] = item
    return result


def _require_text(value, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise DataValidationError(f"Campo obrigatório vazio: {label}")


def _require_choice(value, options: tuple[str, ...], fieldname: str, owner: str) -> None:
    if value not in options:
        raise DataValidationError(
            f"{fieldname} inválido em '{owner}': {value!r}. Opções: {', '.join(options)}"
        )
