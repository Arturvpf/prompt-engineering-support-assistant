"""Cliente do OpenRouter (API compatível com OpenAI), via httpx.

O OpenRouter dá acesso a vários modelos com uma única chave, incluindo
modelos gratuitos (sufixo ``:free``).
"""

from __future__ import annotations

import time

import httpx

from .config import Settings
from .llm_client import (
    RETRYABLE_STATUS,
    LLMAuthError,
    LLMEmptyResponseError,
    LLMError,
    LLMRateLimitError,
    LLMResponse,
    call_with_retries,
)

API_URL = "https://openrouter.ai/api/v1/chat/completions"


class _HTTPStatusError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class OpenRouterClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.api_key:
            raise LLMAuthError("OPENROUTER_API_KEY ausente.")
        self.settings = settings
        self._http = httpx.Client(
            timeout=settings.timeout_seconds,
            headers={"Authorization": f"Bearer {settings.api_key}"},
        )

    def generate(self, system: str, user: str) -> LLMResponse:
        payload = self._payload(system, user)

        def call() -> LLMResponse:
            started = time.perf_counter()
            response = self._http.post(API_URL, json=payload)
            return self._to_response(response, started)

        return call_with_retries(call, self._classify, self.settings.max_retries)

    # ---------------------------------------------------------------- internos

    def _payload(self, system: str, user: str) -> dict:
        s = self.settings
        payload = {
            "model": s.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": s.temperature,
            "max_tokens": s.max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        if s.seed is not None:
            payload["seed"] = s.seed
        if s.thinking_budget == 0:
            payload["reasoning"] = {"enabled": False}
        elif s.thinking_budget is not None:
            payload["reasoning"] = {"max_tokens": s.thinking_budget}
        return payload

    def _to_response(self, response: httpx.Response, started: float) -> LLMResponse:
        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            body = response.json()
        except ValueError:
            body = {}

        # O OpenRouter às vezes devolve o erro do provedor com HTTP 200 e campo "error".
        error = body.get("error") if isinstance(body, dict) else None
        if response.status_code >= 400 or error:
            status = (error or {}).get("code") if isinstance(error, dict) else None
            status = status if isinstance(status, int) else response.status_code
            message = (error or {}).get("message") if isinstance(error, dict) else None
            # "Provider returned error" é genérico; o motivo real vem em metadata.raw.
            raw = ((error or {}).get("metadata") or {}).get("raw") if isinstance(error, dict) else None
            if isinstance(raw, str) and raw:
                message = f"{message}: {raw}" if message else raw
            raise _HTTPStatusError(status, message or response.text[:300])

        choices = body.get("choices") or []
        if not choices:
            raise LLMEmptyResponseError("O OpenRouter não retornou nenhuma resposta (choices vazio).")
        choice = choices[0]
        text = ((choice.get("message") or {}).get("content") or "").strip()
        finish = choice.get("finish_reason") or ""
        if not text:
            raise LLMEmptyResponseError(f"O modelo não retornou texto (finish_reason={finish or 'vazio'}).")

        usage = body.get("usage") or {}
        return LLMResponse(
            text=text,
            model=body.get("model") or self.settings.model,
            # Normaliza para o mesmo valor usado com o Gemini.
            finish_reason="MAX_TOKENS" if finish == "length" else finish.upper(),
            usage={
                "prompt_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            },
            latency_ms=latency_ms,
        )

    @staticmethod
    def _classify(exc: Exception) -> LLMError:
        if isinstance(exc, _HTTPStatusError):
            code, message = exc.status, exc.message[:300]
            if code in (401, 403):
                error: LLMError = LLMAuthError(f"Chave do OpenRouter inválida ou sem permissão ({code}): {message}")
            elif code == 402:
                error = LLMError(f"Sem créditos no OpenRouter (402). Use um modelo ':free'. {message}")
            elif code == 429:
                error = LLMRateLimitError(f"Limite de requisições do OpenRouter atingido (429): {message}")
            elif code == 404:
                error = LLMError(f"Modelo não encontrado (404). Confira OPENROUTER_MODEL. {message}")
            else:
                error = LLMError(f"Erro da API do OpenRouter ({code}): {message}")
            error.retryable = code in RETRYABLE_STATUS  # type: ignore[attr-defined]
            return error

        if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
            error = LLMError(f"Falha de rede ou timeout ao chamar o OpenRouter: {exc}")
            error.retryable = True  # type: ignore[attr-defined]
            return error

        return LLMError(f"Erro inesperado ao chamar o OpenRouter: {type(exc).__name__}: {exc}")
