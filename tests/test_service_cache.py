import json

from conftest import FakeClient, make_settings

from support_assistant.history import HistoryStore
from support_assistant.service import AssistantService


def test_first_call_hits_the_model_and_second_comes_from_cache(service, fake_client, customers, tickets):
    joao, t004 = customers["joao-leigo-chat"], tickets["T004"]
    first = service.generate(joao, t004, "diagnosis", "v2")
    second = service.generate(joao, t004, "diagnosis", "v2")

    assert len(fake_client.calls) == 1
    assert first["cache_hit"] is False and second["cache_hit"] is True
    assert second["source_run_id"] == first["run_id"]
    assert second["output"] == first["output"]
    assert second["metrics"]["usage"] == {}
    assert len(service.store.load()) == 2, "o cache hit também é registrado no histórico"


def test_cache_is_not_shared_between_versions_types_profiles_or_tickets(service, fake_client, customers, tickets):
    joao, marta = customers["joao-leigo-chat"], customers["marta-leigo-telefone"]
    service.generate(joao, tickets["T004"], "diagnosis", "v2")
    service.generate(joao, tickets["T004"], "diagnosis", "v1")
    service.generate(joao, tickets["T004"], "clarifying_questions", "v2")
    service.generate(marta, tickets["T004"], "diagnosis", "v2")
    service.generate(joao, tickets["T001"], "diagnosis", "v2")
    assert len(fake_client.calls) == 5


def test_changing_generation_params_invalidates_the_cache(tmp_path, engine, customers, tickets):
    store = HistoryStore(tmp_path / "history.json")
    client = FakeClient()
    for temperature in (0.2, 0.7, 0.2):
        svc = AssistantService(make_settings(tmp_path, temperature=temperature), engine=engine, store=store,
                               client_factory=lambda _s: client)
        svc.generate(customers["joao-leigo-chat"], tickets["T004"], "diagnosis", "v2")
    assert len(client.calls) == 2  # a terceira (0.2 de novo) veio do cache


def test_no_cache_flag_forces_a_new_call(service, fake_client, customers, tickets):
    args = (customers["joao-leigo-chat"], tickets["T004"], "diagnosis", "v2")
    service.generate(*args)
    record = service.generate(*args, use_cache=False)
    assert record["cache_hit"] is False
    assert len(fake_client.calls) == 2


def test_cache_hit_does_not_need_an_api_key(tmp_path, engine, customers, tickets):
    store = HistoryStore(tmp_path / "history.json")
    client = FakeClient()
    AssistantService(make_settings(tmp_path), engine=engine, store=store, client_factory=lambda _s: client).generate(
        customers["joao-leigo-chat"], tickets["T004"], "diagnosis", "v2")

    def no_client(_settings):
        raise AssertionError("não deveria criar o cliente num cache hit")

    svc = AssistantService(make_settings(tmp_path, api_key=""), engine=engine, store=store, client_factory=no_client)
    assert svc.generate(customers["joao-leigo-chat"], tickets["T004"], "diagnosis", "v2")["cache_hit"] is True


def test_record_has_required_fields_and_no_answer_key(service, customers, tickets):
    record = service.generate(customers["joao-leigo-chat"], tickets["T004"], "diagnosis", "v2")
    for field in ("run_id", "timestamp", "customer_id", "ticket", "content_type", "prompt_version", "provider",
                  "model", "generation_params", "output", "metrics", "evaluation"):
        assert field in record
    assert "missing_on_purpose" not in json.dumps(record)
    assert record["evaluation"] is None


def test_events_are_logged(tmp_path, service, customers, tickets):
    from support_assistant.observability import configure_logging

    log_path = configure_logging(tmp_path / "logs", "ERROR")
    service.generate(customers["joao-leigo-chat"], tickets["T004"], "diagnosis", "v2")
    service.generate(customers["joao-leigo-chat"], tickets["T004"], "diagnosis", "v2")
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert [e["event"] for e in events] == ["generation", "cache_hit"]
    assert events[0]["total_tokens"] == 100 and events[1]["tokens_saved"] == 100
    assert "test-key" not in log_path.read_text(encoding="utf-8")
