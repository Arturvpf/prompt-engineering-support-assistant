"""Fixtures comuns. Nenhum teste chama a API real: o modelo é substituído por FakeClient."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_assistant.config import Settings  # noqa: E402
from support_assistant.data_loader import load_customers, load_tickets  # noqa: E402
from support_assistant.history import HistoryStore  # noqa: E402
from support_assistant.llm_client import LLMResponse  # noqa: E402
from support_assistant.prompt_engine import PromptEngine  # noqa: E402
from support_assistant.service import HISTORY_FILENAME, AssistantService  # noqa: E402

VALID_OUTPUTS = {
    "diagnosis": {
        "hypotheses": [{"id": "H1", "description": "Senha incorreta", "likelihood": "média"},
                       {"id": "H2", "description": "Verificação do novo aparelho", "likelihood": "baixa"}],
        "evidence": [{"signal": "\"diz que não foi possível entrar\"", "supports": ["H1", "H2"]}],
        "missing_information": [{"item": "Mensagem exata", "why_it_matters": "separa H1 de H2"}],
        "probable_conclusion": {"hypothesis_id": "H1", "summary": "Provável senha", "confidence": "média",
                                "how_to_confirm": "Redefinir a senha"},
    },
    "resolution_steps": {
        "opening": "Oi, João.",
        "steps": [{"number": 1, "action": "Toque em Esqueci minha senha", "why": "", "expected_result": "Chega um e-mail"}],
        "if_not_resolved": "Envie o modelo do celular.",
    },
    "clarifying_questions": {
        "questions": [{"priority": 1, "question": "Aparece alguma mensagem?", "reason": "...", "how_to_find": "Na tela"}],
    },
    "flow_summary": {
        "ascii_flowchart": "+-----+\n| Inicio |\n+-----+",
        "decision_points": [{"question": "Entrou?", "if_yes": "RESOLVIDO", "if_no": "ESCALAR PARA N2"}],
        "escalation": {"when": "Se não entrar", "attach": ["print"]},
    },
}

# Campo que identifica, no texto do prompt, qual tipo de conteúdo foi pedido.
_MARKERS = {
    "ascii_flowchart": "flow_summary",
    "hypotheses": "diagnosis",
    '"questions"': "clarifying_questions",
    '"steps"': "resolution_steps",
}


def detect_content_type(user_prompt: str) -> str:
    for marker, content_type in _MARKERS.items():
        if marker in user_prompt:
            return content_type
    raise AssertionError("prompt sem tipo de conteúdo reconhecível")


class FakeClient:
    """Cliente LLM falso: devolve respostas da fila ou uma saída válida para o tipo pedido."""

    def __init__(self, responses: list[str] | None = None, finish_reason: str = "stop") -> None:
        self.responses = list(responses or [])
        self.finish_reason = finish_reason
        self.calls: list[tuple[str, str]] = []

    def generate(self, system: str, user: str) -> LLMResponse:
        self.calls.append((system, user))
        text = self.responses.pop(0) if self.responses else json.dumps(VALID_OUTPUTS[detect_content_type(user)])
        return LLMResponse(text=text, model="fake-model", finish_reason=self.finish_reason,
                           usage={"prompt_tokens": 80, "output_tokens": 20, "total_tokens": 100}, latency_ms=5)


def make_settings(output_dir: Path, **overrides) -> Settings:
    values = dict(api_key="test-key", model="fake-model", temperature=0.2, max_output_tokens=2048, seed=42,
                  thinking_budget=0, timeout_seconds=5, max_retries=0, output_dir=output_dir, provider="openrouter")
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def customers():
    return load_customers()


@pytest.fixture
def tickets():
    return load_tickets()


@pytest.fixture
def engine():
    return PromptEngine()


@pytest.fixture
def fake_client():
    return FakeClient()


@pytest.fixture
def service(tmp_path, engine, fake_client):
    settings = make_settings(tmp_path)
    return AssistantService(settings, engine=engine, store=HistoryStore(tmp_path / HISTORY_FILENAME),
                            client_factory=lambda _s: fake_client)


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Evita que testes da CLI escrevam em outputs/ do projeto ou usem a chave real."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
