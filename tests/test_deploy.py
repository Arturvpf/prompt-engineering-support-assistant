"""Recursos para rodar a web exposta na nuvem: limites, teto diário, histórico de demonstração e config."""

import dataclasses
import json
import threading
import urllib.error
import urllib.request

import pytest

from support_assistant.config import ConfigError, WebSettings, load_web_settings
from support_assistant.history import HistoryStore
from support_assistant.service import ModelCallBlocked
from support_assistant.web import App, Forbidden, RateLimiter, TooManyRequests, make_server

BODY = {"customer_id": "joao-leigo-chat", "ticket_id": "T004", "content_types": ["diagnosis"], "versions": ["v2"]}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_rate_limiter_sliding_window():
    clock = Clock()
    limiter = RateLimiter(limit=2, window=60, clock=clock)
    limiter.check("a")
    limiter.check("a")
    limiter.check("b")  # cada pessoa tem a sua cota
    with pytest.raises(TooManyRequests) as exc:
        limiter.check("a")
    assert exc.value.retry_after == 61 and "2 gerações a cada 1 minuto" in str(exc.value)
    clock.now += 60
    limiter.check("a")  # a janela andou


def test_rate_limiter_disabled_by_default():
    limiter = RateLimiter(limit=0, window=60)
    for _ in range(100):
        limiter.check("a")


def test_generate_respects_rate_limit_and_invalid_requests_do_not_count(service):
    from support_assistant.web import BadRequest

    app = App(service, WebSettings(rate_limit=1))
    with pytest.raises(BadRequest):
        app.generate({**BODY, "customer_id": "x"}, client="1.1.1.1")
    app.generate(BODY, client="1.1.1.1")
    with pytest.raises(TooManyRequests):
        app.generate(BODY, client="1.1.1.1")
    app.generate(BODY, client="2.2.2.2")


def test_daily_cap_blocks_model_calls_but_cache_still_works(service, fake_client):
    app = App(service, WebSettings(daily_model_calls=1))
    first = app.generate(BODY)["results"][0]
    assert first["cache_hit"] is False and app.model_calls_today() == 1
    again = app.generate(BODY)["results"][0]
    assert again["cache_hit"] is True, "o cache não conta para o teto"
    blocked = app.generate({**BODY, "ticket_id": "T001"})["results"][0]
    assert "Limite de chamadas ao modelo" in blocked["error"]
    assert len(fake_client.calls) == 1
    assert app.options()["limits"]["model_calls_left_today"] == 0


def test_blocked_call_raises_in_the_service(service, customers, tickets):
    service.can_call_model = lambda: False
    with pytest.raises(ModelCallBlocked):
        service.generate(customers["joao-leigo-chat"], tickets["T004"], "diagnosis", "v2")


def test_demo_history_is_seeded_from_samples_only_when_empty(service):
    app = App(service, WebSettings(seed_samples=True))
    records = service.store.load()
    ids = {r["run_id"] for r in records}
    assert {"a2cf94288d19", "524bbca9b910", "bedf735a659b", "b767498dbb1c"} <= ids
    assert len(ids) == len(records), "sem registros repetidos"
    assert all(r["seeded"] for r in records)


def test_seeded_records_do_not_count_against_the_daily_cap(service):
    from support_assistant.history import now_iso

    service.store.seed([{"run_id": f"s{i}", "timestamp": now_iso(), "output": {"x": 1}} for i in range(5)])
    app = App(service, WebSettings(daily_model_calls=3))
    assert app.model_calls_today() == 0
    assert app.limits()["model_calls_left_today"] == 3
    assert app.history({})["runs"]
    assert service.store.seed([{"run_id": "novo", "output": {}}]) == 0, "histórico com dados não é sobrescrito"


def test_seeded_demo_serves_the_sample_scenario_from_cache(service, fake_client):
    app = App(service, WebSettings(seed_samples=True))
    # Mesmo modelo e parâmetros das amostras: os prompts v2 do João + T004 já estão no cache.
    service.settings = dataclasses.replace(service.settings, model="nvidia/nemotron-3.5-super-vl:free")
    result = app.generate({**BODY, "content_types": ["diagnosis", "clarifying_questions"]})["results"]
    assert [r["cache_hit"] for r in result] == [True, True]
    assert fake_client.calls == []


def test_evaluation_can_be_disabled(service):
    app = App(service, WebSettings(allow_evaluation=False))
    run_id = app.generate({**BODY, "versions": ["v1"]})["results"][0]["run_id"]
    with pytest.raises(Forbidden):
        app.evaluate({"run_id": run_id, "scores": {}})
    assert app.options()["limits"]["allow_evaluation"] is False


def test_http_health_429_and_proxy_ip(service):
    app = App(service, WebSettings(rate_limit=1, trust_proxy=True))
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def post(ip):
        req = urllib.request.Request(base + "/api/generate", method="POST", data=json.dumps(BODY).encode(),
                                     headers={"Content-Type": "application/json", "X-Forwarded-For": f"{ip}, 10.0.0.1"})
        return urllib.request.urlopen(req)

    try:
        with urllib.request.urlopen(base + "/api/health") as r:
            assert json.loads(r.read())["status"] == "ok"
            assert r.headers["X-Frame-Options"] == "DENY"
        post("9.9.9.9").close()
        with pytest.raises(urllib.error.HTTPError) as exc:
            post("9.9.9.9")
        assert exc.value.code == 429 and int(exc.value.headers["Retry-After"]) > 0
        post("8.8.8.8").close()  # outro IP do X-Forwarded-For, outra cota
    finally:
        server.shutdown()
        server.server_close()


def test_web_settings_from_environment(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    for name, value in {"HOST": "0.0.0.0", "PORT": "10000", "WEB_TRUST_PROXY": "true", "WEB_RATE_LIMIT": "5",
                        "WEB_RATE_WINDOW_SECONDS": "600", "WEB_DAILY_MODEL_CALLS": "200",
                        "WEB_SEED_SAMPLES": "1", "WEB_ALLOW_EVALUATION": "false"}.items():
        monkeypatch.setenv(name, value)
    assert load_web_settings(env) == WebSettings("0.0.0.0", 10000, True, 5, 600, 200, True, False)
    monkeypatch.setenv("WEB_TRUST_PROXY", "talvez")
    with pytest.raises(ConfigError, match="WEB_TRUST_PROXY"):
        load_web_settings(env)


def test_web_settings_default_to_local_only(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    for name in ("HOST", "PORT", "WEB_TRUST_PROXY", "WEB_RATE_LIMIT", "WEB_DAILY_MODEL_CALLS", "WEB_SEED_SAMPLES",
                 "WEB_ALLOW_EVALUATION", "WEB_RATE_WINDOW_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    assert load_web_settings(env) == WebSettings()
    assert WebSettings().host == "127.0.0.1"


def test_seed_ignores_records_without_output(tmp_path):
    store = HistoryStore(tmp_path / "h.json")
    assert store.seed([{"run_id": "a"}, {"output": {}}, "lixo"]) == 0
    assert store.load() == []
