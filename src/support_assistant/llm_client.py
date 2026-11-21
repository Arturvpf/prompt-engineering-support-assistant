"""Cliente do LLM (Google Gemini) com timeout, retry e erros tratados.

O resto do projeto depende só do protocolo ``LLMClient``, então trocar de
provedor ou usar um cliente falso nos testes não exige mudar os geradores.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Protocol

from .config import Settings


class LLMError(RuntimeError):
    """Falha ao obter resposta do modelo."""


class LLMAuthError(LLMError):
    """Chave inválida ou sem permissão. Não adianta tentar de novo."""


class LLMRateLimitError(LLMError):
    """Limite de requisições ou cota esgotada."""


class LLMEmptyResponseError(LLMError):
    """O modelo não devolveu texto (bloqueio de segurança, por exemplo)."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    finish_reason: str = ""
    usage: dict = field(default_factory=dict)
    latency_ms: int = 0

    @property
    def truncated(self) -> bool:
        return self.finish_reason == "MAX_TOKENS"


class LLMClient(Protocol):
    def generate(self, system: str, user: str) -> LLMResponse: ...


# Códigos HTTP em que vale tentar de novo.
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class GeminiClient:
    def __init__(self, settings: Settings) -> None:
        from google import genai
        from google.genai import types

        if not settings.api_key:
            raise LLMAuthError("GEMINI_API_KEY ausente.")
        self.settings = settings
        self._types = types
        self._client = genai.Client(
            api_key=settings.api_key,
            http_options=types.HttpOptions(timeout=int(settings.timeout_seconds * 1000)),
        )

    def generate(self, system: str, user: str) -> LLMResponse:
        config = self._build_config(system)

        def call() -> LLMResponse:
            started = time.perf_counter()
            response = self._client.models.generate_content(
                model=self.settings.model, contents=user, config=config
            )
            return self._to_response(response, started)

        return call_with_retries(call, self._classify, self.settings.max_retries)

    # ---------------------------------------------------------------- internos

    def _build_config(self, system: str):
        types = self._types
        s = self.settings
        kwargs = dict(
            system_instruction=system,
            temperature=s.temperature,
            max_output_tokens=s.max_output_tokens,
            response_mime_type="application/json",
        )
        if s.seed is not None:
            kwargs["seed"] = s.seed
        if s.thinking_budget is not None:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=s.thinking_budget)
        return types.GenerateContentConfig(**kwargs)

    def _to_response(self, response, started: float) -> LLMResponse:
        latency_ms = int((time.perf_counter() - started) * 1000)
        candidates = getattr(response, "candidates", None) or []
        finish_reason = ""
        if candidates and candidates[0].finish_reason is not None:
            finish_reason = getattr(candidates[0].finish_reason, "name", str(candidates[0].finish_reason))

        text = (getattr(response, "text", None) or "").strip()
        if not text:
            feedback = getattr(response, "prompt_feedback", None)
            reason = getattr(feedback, "block_reason", None) or finish_reason or "sem motivo informado"
            raise LLMEmptyResponseError(f"O modelo não retornou texto ({reason}).")

        meta = getattr(response, "usage_metadata", None)
        usage = {
            "prompt_tokens": getattr(meta, "prompt_token_count", None),
            "output_tokens": getattr(meta, "candidates_token_count", None),
            "total_tokens": getattr(meta, "total_token_count", None),
        }
        return LLMResponse(
            text=text,
            model=getattr(response, "model_version", None) or self.settings.model,
            finish_reason=finish_reason,
            usage=usage,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _classify(exc: Exception) -> LLMError:
        from google.genai import errors

        if isinstance(exc, errors.APIError):
            code = exc.code
            message = (exc.message or str(exc))[:300]
            # O Gemini responde 400 (e não 401) para chave inválida.
            if code in (401, 403) or "api key" in message.lower():
                error: LLMError = LLMAuthError(f"Chave do Gemini inválida ou sem permissão ({code}): {message}")
            elif code == 429:
                error = LLMRateLimitError(f"Limite de requisições do Gemini atingido (429): {message}")
            elif code == 404:
                error = LLMError(f"Modelo não encontrado (404). Confira GEMINI_MODEL. {message}")
            else:
                error = LLMError(f"Erro da API do Gemini ({code}): {message}")
            error.retryable = code in RETRYABLE_STATUS  # type: ignore[attr-defined]
            return error

        name = type(exc).__name__.lower()
        if "timeout" in name or "connect" in name or "network" in name:
            error = LLMError(f"Falha de rede ou timeout ao chamar o Gemini: {exc}")
            error.retryable = True  # type: ignore[attr-defined]
            return error

        return LLMError(f"Erro inesperado ao chamar o Gemini: {type(exc).__name__}: {exc}")


def call_with_retries(call, classify, max_retries: int) -> LLMResponse:
    """Executa ``call``; em erro, classifica e tenta de novo só se for temporário."""
    attempts = max_retries + 1
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except LLMError:
            raise  # já classificado (ex.: resposta vazia): não adianta repetir
        except Exception as exc:  # noqa: BLE001 - classificado abaixo
            error = classify(exc)
            if not getattr(error, "retryable", False) or attempt == attempts:
                raise error from exc
            time.sleep(_backoff(attempt))
    raise LLMError("Nenhuma tentativa executada.")  # só se max_retries < 0


def _backoff(attempt: int) -> float:
    """Espera exponencial com jitter: ~1s, 2s, 4s... limitado a 20s."""
    return min(20.0, 2 ** (attempt - 1)) + random.uniform(0, 0.5)


def create_client(settings: Settings) -> LLMClient:
    """Instancia o cliente do provedor configurado em LLM_PROVIDER."""
    if settings.provider == "openrouter":
        from .openrouter_client import OpenRouterClient

        return OpenRouterClient(settings)
    if settings.provider == "gemini":
        return GeminiClient(settings)
    raise LLMError(f"Provedor não suportado: {settings.provider}")
