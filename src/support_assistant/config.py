"""Configuração lida do ambiente (.env). Nenhum segredo fica no código."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(ValueError):
    """Configuração ausente ou inválida."""


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str
    temperature: float
    max_output_tokens: int
    seed: int | None
    thinking_budget: int | None
    timeout_seconds: float
    max_retries: int
    output_dir: Path
    cache_dir: Path
    provider: str = "gemini"

    def generation_params(self) -> dict:
        """Parâmetros que afetam a saída do modelo.

        Entram no registro do histórico e na chave do cache. A chave de API,
        o timeout e as pastas ficam de fora porque não mudam o conteúdo gerado.
        """
        return {
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "seed": self.seed,
            "thinking_budget": self.thinking_budget,
        }

    def __repr__(self) -> str:  # nunca exibir a chave em logs ou tracebacks
        return f"Settings(model={self.model!r}, params={self.generation_params()!r})"


def load_settings(require_api_key: bool = True, env_file: Path | None = None) -> Settings:
    load_dotenv(env_file or PROJECT_ROOT / ".env")

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if require_api_key and not api_key:
        raise ConfigError(
            "GEMINI_API_KEY não definida. Copie .env.example para .env e preencha a chave "
            "(https://aistudio.google.com/apikey)."
        )

    return Settings(
        api_key=api_key,
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip(),
        temperature=_number("LLM_TEMPERATURE", 0.2, float, 0.0, 2.0),
        max_output_tokens=_number("LLM_MAX_OUTPUT_TOKENS", 2048, int, 1, 65536),
        seed=_optional_int("LLM_SEED", 42),
        thinking_budget=_optional_int("LLM_THINKING_BUDGET", 0),
        timeout_seconds=_number("LLM_TIMEOUT_SECONDS", 60, float, 1, 600),
        max_retries=_number("LLM_MAX_RETRIES", 3, int, 0, 10),
        output_dir=_path("OUTPUT_DIR", "outputs"),
        cache_dir=_path("CACHE_DIR", ".cache"),
    )


def _number(name: str, default, cast, minimum, maximum):
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = cast(raw)
    except ValueError:
        raise ConfigError(f"{name} deve ser numérico; recebido {raw!r}.") from None
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} deve estar entre {minimum} e {maximum}; recebido {value}.")
    return value


def _optional_int(name: str, default: int | None) -> int | None:
    """Vazio usa o padrão; 'none' desativa o parâmetro."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    if raw.lower() == "none":
        return None
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{name} deve ser inteiro ou 'none'; recebido {raw!r}.") from None


def _path(name: str, default: str) -> Path:
    path = Path(os.getenv(name, "").strip() or default)
    return path if path.is_absolute() else PROJECT_ROOT / path
