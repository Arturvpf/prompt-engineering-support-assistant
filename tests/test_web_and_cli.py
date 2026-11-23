import json
import socket
import threading
import urllib.error
import urllib.request

import pytest

from support_assistant.cli import main
from support_assistant.web import App, BadRequest, make_server


@pytest.fixture
def app(service):
    return App(service)


def test_options_lists_everything(app):
    o = app.options()
    assert len(o["customers"]) == 5 and len(o["content_types"]) == 4
    assert {"v1", "v2"} <= {v["id"] for v in o["versions"]}


def test_generate_returns_rendered_records(app, fake_client):
    body = {"customer_id": "joao-leigo-chat", "ticket_id": "T004",
            "content_types": ["diagnosis", "clarifying_questions"], "versions": ["v1", "v2"]}
    results = app.generate(body)["results"]
    assert [(r["prompt_version"], r["content_type"]) for r in results] == [
        ("v1", "diagnosis"), ("v1", "clarifying_questions"), ("v2", "diagnosis"), ("v2", "clarifying_questions")]
    assert all("HIPÓTESES" in r["rendered"] for r in results if r["content_type"] == "diagnosis")
    assert app.generate(body)["results"][0]["cache_hit"] is True
    assert len(fake_client.calls) == 4


def test_generate_accepts_free_text_ticket(app):
    body = {"customer_id": "rafael-avancado-chat", "ticket_text": "API devolve 500",
            "content_types": ["diagnosis"], "versions": ["v2"]}
    assert app.generate(body)["results"][0]["ticket_id"] == "ADHOC"


@pytest.mark.parametrize("body", [
    {"customer_id": "x", "ticket_id": "T004", "content_types": ["diagnosis"], "versions": ["v2"]},
    {"customer_id": "joao-leigo-chat", "ticket_id": "T999", "content_types": ["diagnosis"], "versions": ["v2"]},
    {"customer_id": "joao-leigo-chat", "ticket_id": "T004", "content_types": [], "versions": ["v2"]},
    {"customer_id": "joao-leigo-chat", "ticket_id": "T004", "content_types": "diagnosis", "versions": ["v2"]},
    {"customer_id": "joao-leigo-chat", "ticket_id": "T004", "content_types": ["diagnosis"], "versions": ["../v1"]},
    {"customer_id": "joao-leigo-chat", "ticket_text": "x" * 5000, "content_types": ["diagnosis"], "versions": ["v2"]},
])
def test_generate_rejects_bad_input(app, body):
    with pytest.raises(BadRequest):
        app.generate(body)


def test_http_roundtrip(app):
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/") as r:
            assert "Assistente de Suporte" in r.read().decode("utf-8")
        req = urllib.request.Request(base + "/api/generate", method="POST",
                                     data=json.dumps({"customer_id": "joao-leigo-chat", "ticket_id": "T004",
                                                      "content_types": ["diagnosis"], "versions": ["v2"]}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            assert json.loads(r.read())["results"][0]["content_type"] == "diagnosis"
        with urllib.request.urlopen(base + "/api/stats") as r:
            assert json.loads(r.read())["model_calls"] == 1
        bad = urllib.request.Request(base + "/api/generate", method="POST", data=b"{quebrado",
                                     headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(bad)
        assert exc.value.code == 400
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def busy_port():
    """Uma porta já ocupada por outro programa (socket com as opções padrão)."""
    other = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    other.bind(("127.0.0.1", 0))
    other.listen()
    try:
        yield other.getsockname()[1]
    finally:
        other.close()


def test_server_refuses_a_port_in_use(app, busy_port):
    with pytest.raises(OSError):
        make_server(app, "127.0.0.1", busy_port)


def test_cli_web_reports_port_in_use(capsys, busy_port):
    assert main(["web", "--port", str(busy_port)]) == 1
    err = capsys.readouterr().err
    assert "porta está em uso" in err and f"--port {busy_port + 1}" in err


def test_cli_list_and_invalid_input(capsys):
    assert main(["list"]) == 0
    assert "joao-leigo-chat" in capsys.readouterr().out
    assert main(["generate", "-c", "nao-existe", "-t", "T004"]) == 2
    assert main(["generate", "-c", "joao-leigo-chat", "-t", "T004", "-v", "v9"]) == 2


def test_cli_generate_without_key_fails_cleanly(capsys):
    assert main(["generate", "-c", "joao-leigo-chat", "-t", "T004", "--type", "diagnosis", "--no-cache"]) == 1
    assert "OPENROUTER_API_KEY" in capsys.readouterr().err


def test_cli_stats_on_empty_history(capsys):
    assert main(["stats", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["total_runs"] == 0


SCORES = {"clarity": {"score": 4, "justification": "organizado"},
          "customer_fit": {"score": 5, "justification": "linguagem simples"},
          "actionability": {"score": 3, "justification": "falta o próximo passo"}}


def _two_versions(app):
    body = {"customer_id": "joao-leigo-chat", "ticket_id": "T004", "content_types": ["diagnosis"], "versions": ["v1", "v2"]}
    return [r["run_id"] for r in app.generate(body)["results"]]


def test_options_expose_rubric_and_default_version(app):
    o = app.options()
    assert o["default_version"] == "v3"
    assert [c["id"] for c in o["rubric"]["criteria"]] == ["clarity", "customer_fit", "actionability"]
    assert o["rubric"]["scale"]["5"] == "excelente"


def test_run_returns_record_with_rendered_output(app):
    run_id = _two_versions(app)[0]
    run = app.run({"id": [run_id]})
    assert run["run_id"] == run_id and "HIPÓTESES" in run["rendered"]


def test_evaluate_and_compare_from_the_web(app, tmp_path):
    v1, v2 = _two_versions(app)
    for run_id in (v1, v2):
        out = app.evaluate({"run_id": run_id, "scores": SCORES, "evaluator": "teste"})
        assert out["evaluation"]["total"] == 12 and out["run"]["score"] == 12
    result = app.compare({"run_ids": [v1, v2], "verdict": "empate técnico"})
    assert result["comparison"]["overall_totals"] == {"v1": 12, "v2": 12}
    assert result["saved_to"] and json.loads(open(result["saved_to"], encoding="utf-8").read())["verdict"] == "empate técnico"
    summaries = app.history({})["runs"]
    assert len({s["scenario"] for s in summaries}) == 1, "mesmo cenário, mesma chave"


@pytest.mark.parametrize("body", [
    {"run_id": "x", "scores": SCORES},
    {"scores": SCORES},
    {"run_id": "RUN", "scores": "4"},
    {"run_id": "RUN", "scores": {**SCORES, "clarity": {"score": 9, "justification": "x"}}},
    {"run_id": "RUN", "scores": {**SCORES, "clarity": {"score": 4, "justification": "  "}}},
    {"run_id": "RUN", "scores": {**SCORES, "clarity": {"score": 4, "justification": "x" * 2000}}},
])
def test_evaluate_rejects_bad_input(app, body):
    from support_assistant.web import NotFound
    run_id = _two_versions(app)[0]
    if body.get("run_id") == "RUN":
        body = {**body, "run_id": run_id}
    with pytest.raises((BadRequest, NotFound)):
        app.evaluate(body)


def test_compare_rejects_unevaluated_or_cached_runs(app):
    v1, v2 = _two_versions(app)
    with pytest.raises(BadRequest, match="ainda não foi avaliada"):
        app.compare({"run_ids": [v1, v2]})
    cached = _two_versions(app)[0]
    app.evaluate({"run_id": v1, "scores": SCORES})
    with pytest.raises(BadRequest, match="veio do cache"):
        app.evaluate({"run_id": cached, "scores": SCORES})
    with pytest.raises(BadRequest):
        app.compare({"run_ids": [v1]})


def test_http_evaluate_and_missing_run(app):
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        run_id = _two_versions(app)[0]
        req = urllib.request.Request(base + "/api/evaluate", method="POST",
                                     data=json.dumps({"run_id": run_id, "scores": SCORES}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            assert json.loads(r.read())["evaluation"]["total"] == 12
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(base + "/api/run?id=nao-existe")
        assert exc.value.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_cache_hit_carries_the_original_evaluation(app):
    body = {"customer_id": "joao-leigo-chat", "ticket_id": "T004", "content_types": ["diagnosis"], "versions": ["v2"]}
    first = app.generate(body)["results"][0]
    assert "source_evaluation" not in first
    app.evaluate({"run_id": first["run_id"], "scores": SCORES})
    again = app.generate(body)["results"][0]
    assert again["cache_hit"] is True and again["evaluation"] is None
    assert again["source_evaluation"]["total"] == 12
