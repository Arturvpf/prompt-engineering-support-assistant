"""Orquestra uma geração: monta o prompt, consulta o cache, chama o modelo e grava o histórico.

É a camada que a CLI usa. A chave de cache combina:

- o hash do prompt renderizado (cobre template da versão, perfil e ticket);
- o tipo de conteúdo e a versão do prompt;
- as configurações que afetam a saída (provedor, modelo, temperatura, max tokens, seed...).

Se tudo isso for igual a uma execução anterior, a saída é reaproveitada sem
chamar a API, e o reaproveitamento também é registrado no histórico.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Callable

from .config import Settings
from .data_loader import CustomerProfile, Ticket
from .generators import GENERATORS
from .history import HistoryStore
from .llm_client import LLMClient, create_client
from .prompt_engine import PromptEngine, PromptPackage

HISTORY_FILENAME = "history.json"


def cache_key(prompt: PromptPackage, generation_params: dict) -> str:
    material = {
        "prompt_fingerprint": prompt.fingerprint,
        "content_type": prompt.content_type,
        "prompt_version": prompt.version,
        "generation_params": generation_params,
    }
    encoded = json.dumps(material, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class AssistantService:
    def __init__(
        self,
        settings: Settings,
        engine: PromptEngine | None = None,
        store: HistoryStore | None = None,
        client_factory: Callable[[Settings], LLMClient] = create_client,
    ) -> None:
        self.settings = settings
        self.engine = engine or PromptEngine()
        self.store = store or HistoryStore(settings.output_dir / HISTORY_FILENAME)
        self._client_factory = client_factory
        self._client: LLMClient | None = None

    @property
    def client(self) -> LLMClient:
        # Criado só quando há chamada real: resultados em cache não exigem chave de API.
        if self._client is None:
            self._client = self._client_factory(self.settings)
        return self._client

    def generate(
        self,
        customer: CustomerProfile,
        ticket: Ticket,
        content_type: str,
        version: str,
        use_cache: bool = True,
    ) -> dict:
        """Gera (ou reaproveita do cache) um conteúdo e devolve o registro salvo no histórico."""
        prompt = self.engine.build(content_type, customer, ticket, version)
        params = self.settings.generation_params()
        key = cache_key(prompt, params)

        base = {
            "customer_id": customer.id,
            "customer": asdict(customer),
            "ticket_id": ticket.id,
            "ticket": _ticket_snapshot(ticket),
            "content_type": content_type,
            "prompt_version": version,
            "prompt_fingerprint": prompt.fingerprint,
            "provider": params["provider"],
            "model": params["model"],
            "generation_params": params,
            "cache_key": key,
        }

        cached = self.store.find_cached(key) if use_cache else None
        if cached is not None:
            return self.store.append({
                **base,
                "cache_hit": True,
                "source_run_id": cached["run_id"],
                "output": cached["output"],
                "warnings": cached.get("warnings", []),
                "metrics": {"attempts": 0, "latency_ms": 0, "usage": {}},
                "evaluation": None,
            })

        result = GENERATORS[content_type](self.client, self.engine, customer, ticket, version)
        return self.store.append({
            **base,
            "cache_hit": False,
            "source_run_id": None,
            "output": result.output,
            "warnings": result.warnings,
            "metrics": {
                "attempts": result.attempts,
                "latency_ms": result.response.latency_ms,
                "usage": result.response.usage,
                "model_reported": result.response.model,
                "finish_reason": result.response.finish_reason,
            },
            # Reservado para as notas da rubrica (Fase 6).
            "evaluation": None,
        })


def _ticket_snapshot(ticket: Ticket) -> dict:
    # O gabarito missing_on_purpose fica fora do histórico do ticket: não é entrada do modelo.
    return {"id": ticket.id, "title": ticket.title, "product": ticket.product, "description": ticket.description}
