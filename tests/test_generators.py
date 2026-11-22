import json

import pytest
from conftest import VALID_OUTPUTS, FakeClient

from support_assistant.generators import GENERATORS, GenerationError


@pytest.mark.parametrize("content_type", list(GENERATORS))
def test_each_generator_returns_validated_output(content_type, engine, customers, tickets):
    client = FakeClient()
    result = GENERATORS[content_type](client, engine, customers["joao-leigo-chat"], tickets["T004"], "v2")
    assert result.output == VALID_OUTPUTS[content_type]
    assert result.attempts == 1
    assert len(client.calls) == 1


def test_invalid_output_triggers_one_repair_with_the_error(engine, customers, tickets):
    client = FakeClient(responses=['{"questions": []}'])
    result = GENERATORS["clarifying_questions"](client, engine, customers["joao-leigo-chat"], tickets["T004"], "v2")
    assert result.attempts == 2
    repair_prompt = client.calls[1][1]
    assert "## Correção" in repair_prompt
    assert "'questions' precisa de pelo menos 1 item" in repair_prompt


def test_gives_up_after_the_repair_attempt(engine, customers, tickets):
    client = FakeClient(responses=["não é json", "ainda não"])
    with pytest.raises(GenerationError, match="após 2 tentativas"):
        GENERATORS["diagnosis"](client, engine, customers["joao-leigo-chat"], tickets["T004"], "v1")
    assert len(client.calls) == 2


def test_truncated_response_is_treated_as_invalid(engine, customers, tickets):
    client = FakeClient(responses=[json.dumps(VALID_OUTPUTS["diagnosis"])] * 2, finish_reason="MAX_TOKENS")
    with pytest.raises(GenerationError, match="limite de tokens"):
        GENERATORS["diagnosis"](client, engine, customers["joao-leigo-chat"], tickets["T004"], "v2")
