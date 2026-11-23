"""O ponto de entrada da Vercel (api/index.py) sobe a mesma aplicação web, como WSGI, com padrões públicos."""

import importlib.util
import io
import json
from wsgiref.util import setup_testing_defaults

import pytest
from conftest import ROOT


@pytest.fixture
def vercel_module(monkeypatch, tmp_path):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "out"))
    for name in ("WEB_RATE_LIMIT", "WEB_DAILY_MODEL_CALLS", "WEB_SEED_SAMPLES", "WEB_TRUST_PROXY"):
        monkeypatch.delenv(name, raising=False)
    spec = importlib.util.spec_from_file_location("vercel_index", ROOT / "api" / "index.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def call(app, method, path, body=None, headers=None):
    """Chama a aplicação WSGI como a Vercel faria e devolve (status, cabeçalhos, corpo)."""
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path.split("?")[0],
               "QUERY_STRING": path.split("?")[1] if "?" in path else ""}
    data = json.dumps(body).encode() if body is not None else b""
    if body is not None:
        environ.update({"CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(data))})
    for name, value in (headers or {}).items():
        environ[f"HTTP_{name.upper().replace('-', '_')}"] = value
    setup_testing_defaults(environ)
    environ["wsgi.input"] = io.BytesIO(data)
    captured = {}

    def start_response(status, response_headers):
        captured["status"], captured["headers"] = int(status.split()[0]), dict(response_headers)

    payload = b"".join(app(environ, start_response))
    return captured["status"], captured["headers"], payload


def test_entrypoint_exposes_a_wsgi_app_with_public_defaults(vercel_module):
    assert callable(vercel_module.app)
    limits = vercel_module.assistant.limits()
    assert limits["rate_limit"] == 10 and limits["daily_model_calls"] == 200
    assert vercel_module.assistant.web.trust_proxy is True
    assert len(vercel_module.assistant.service.store.load()) >= 20, "histórico de demonstração semeado"


def test_wsgi_serves_the_page_the_api_and_errors(vercel_module):
    app = vercel_module.app
    status, headers, body = call(app, "GET", "/")
    assert status == 200 and "Assistente de Suporte" in body.decode("utf-8")
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]

    status, _, body = call(app, "GET", "/api/health")
    assert status == 200 and json.loads(body)["status"] == "ok"

    status, _, body = call(app, "GET", "/api/options")
    shown = json.loads(body)["history_path"]
    assert shown.endswith("history.json") and ":" not in shown, "a página não expõe o caminho do servidor"

    status, _, body = call(app, "GET", "/api/run?id=nao-existe")
    assert status == 404
    assert call(app, "GET", "/nada")[0] == 404
    assert call(app, "DELETE", "/api/health")[0] == 405


def test_wsgi_generate_from_the_seeded_cache_and_rate_limit(vercel_module):
    import dataclasses

    service = vercel_module.assistant.service
    service.settings = dataclasses.replace(service.settings, model="nvidia/nemotron-3.5-super-vl:free",
                                           provider="openrouter", temperature=0.2, max_output_tokens=2048,
                                           seed=42, thinking_budget=0)
    body = {"customer_id": "joao-leigo-chat", "ticket_id": "T004", "content_types": ["diagnosis"], "versions": ["v3"]}
    status, _, payload = call(vercel_module.app, "POST", "/api/generate", body, {"X-Forwarded-For": "1.2.3.4"})
    result = json.loads(payload)["results"][0]
    assert status == 200 and result["cache_hit"] is True and result["source_evaluation"]["total"] == 13

    for _ in range(9):
        call(vercel_module.app, "POST", "/api/generate", body, {"X-Forwarded-For": "1.2.3.4"})
    status, headers, _ = call(vercel_module.app, "POST", "/api/generate", body, {"X-Forwarded-For": "1.2.3.4"})
    assert status == 429 and int(headers["Retry-After"]) > 0


def test_unwritable_output_dir_falls_back_to_the_temp_dir(monkeypatch, tmp_path, capsys):
    """Um OUTPUT_DIR que não aceita escrita (o ``outputs`` do .env na Vercel) não derruba a função."""
    import tempfile

    blocker = tmp_path / "arquivo"
    blocker.write_text("não é pasta", encoding="utf-8")
    monkeypatch.setenv("OUTPUT_DIR", str(blocker / "outputs"))
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "sys-tmp"))
    for name in ("WEB_RATE_LIMIT", "WEB_DAILY_MODEL_CALLS", "WEB_SEED_SAMPLES", "WEB_TRUST_PROXY"):
        monkeypatch.delenv(name, raising=False)
    spec = importlib.util.spec_from_file_location("vercel_index_fallback", ROOT / "api" / "index.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    expected = tmp_path / "sys-tmp" / "outputs"
    assert module.assistant.service.settings.output_dir == expected
    assert (expected / "history.json").exists(), "o histórico semeado foi gravado no diretório temporário"
    assert "não aceita escrita" in capsys.readouterr().err
    assert call(module.app, "GET", "/api/health")[0] == 200


def test_vercel_config_bundles_what_the_function_reads():
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    include = config["functions"]["api/index.py"]["includeFiles"]
    for folder in ("src", "prompts", "schemas", "data", "samples"):
        assert folder in include
    ignored = (ROOT / ".vercelignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignored and "outputs/" in ignored
