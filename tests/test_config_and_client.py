import pytest

from support_assistant import llm_client
from support_assistant.config import ConfigError, load_settings
from support_assistant.llm_client import LLMAuthError, LLMError, LLMResponse, call_with_retries


def test_missing_key_is_a_clear_error(tmp_path):
    with pytest.raises(ConfigError, match="OPENROUTER_API_KEY"):
        load_settings(env_file=tmp_path / ".env")
    assert load_settings(require_api_key=False, env_file=tmp_path / ".env").api_key == ""


def test_repr_never_shows_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "segredo-123")
    settings = load_settings(env_file=tmp_path / ".env")
    assert settings.api_key == "segredo-123"
    assert "segredo-123" not in repr(settings)
    assert "api_key" not in settings.generation_params()


@pytest.mark.parametrize("name, value", [
    ("LLM_TEMPERATURE", "quente"), ("LLM_TEMPERATURE", "5"), ("LLM_PROVIDER", "outro"),
    ("LLM_SEED", "abc"), ("LOG_LEVEL", "VERBOSO"),
])
def test_invalid_settings_are_rejected(tmp_path, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigError):
        load_settings(require_api_key=False, env_file=tmp_path / ".env")


def test_seed_none_disables_it(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_SEED", "none")
    assert load_settings(require_api_key=False, env_file=tmp_path / ".env").seed is None


class _Temporary(Exception):
    pass


def _classify(exc):
    error = LLMError(str(exc))
    error.retryable = isinstance(exc, _Temporary)
    return error


def test_retries_temporary_errors_then_succeeds(monkeypatch):
    monkeypatch.setattr(llm_client, "_backoff", lambda attempt: 0)
    calls = []

    def call():
        calls.append(1)
        if len(calls) < 3:
            raise _Temporary("503")
        return LLMResponse(text="{}", model="m")

    assert call_with_retries(call, _classify, max_retries=3).text == "{}"
    assert len(calls) == 3


def test_does_not_retry_permanent_errors(monkeypatch):
    monkeypatch.setattr(llm_client, "_backoff", lambda attempt: 0)
    calls = []

    def call():
        calls.append(1)
        raise ValueError("401")

    with pytest.raises(LLMError):
        call_with_retries(call, _classify, max_retries=3)
    assert len(calls) == 1


def test_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(llm_client, "_backoff", lambda attempt: 0)
    calls = []

    def call():
        calls.append(1)
        raise _Temporary("429")

    with pytest.raises(LLMError):
        call_with_retries(call, _classify, max_retries=2)
    assert len(calls) == 3


def test_already_classified_errors_are_not_retried():
    calls = []

    def call():
        calls.append(1)
        raise LLMAuthError("chave inválida")

    with pytest.raises(LLMAuthError):
        call_with_retries(call, _classify, max_retries=3)
    assert len(calls) == 1
