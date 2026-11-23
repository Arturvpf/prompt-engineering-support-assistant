"""O ponto de entrada da Vercel (api/index.py) sobe a mesma aplicação web, com padrões de instalação pública."""

import importlib.util
import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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


def test_entrypoint_exposes_a_handler_with_public_defaults(vercel_module):
    assert issubclass(vercel_module.handler, BaseHTTPRequestHandler)
    limits = vercel_module.app.limits()
    assert limits["rate_limit"] == 10 and limits["daily_model_calls"] == 200
    assert vercel_module.app.web.trust_proxy is True
    assert len(vercel_module.app.service.store.load()) >= 20, "histórico de demonstração semeado"


def test_entrypoint_serves_the_page_and_the_api(vercel_module):
    server = ThreadingHTTPServer(("127.0.0.1", 0), vercel_module.handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/") as r:
            assert "Assistente de Suporte" in r.read().decode("utf-8")
        with urllib.request.urlopen(base + "/api/health") as r:
            assert json.loads(r.read())["status"] == "ok"
        with urllib.request.urlopen(base + "/api/options") as r:
            shown = json.loads(r.read())["history_path"]
            assert shown.endswith("history.json") and ":" not in shown, "a página não expõe o caminho do servidor"
    finally:
        server.shutdown()
        server.server_close()


def test_vercel_config_bundles_what_the_function_reads():
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    include = config["functions"]["api/index.py"]["includeFiles"]
    for folder in ("src", "prompts", "schemas", "data", "samples"):
        assert folder in include
    assert config["rewrites"][0]["destination"] == "/api/index"
    ignored = (ROOT / ".vercelignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignored and "outputs/" in ignored
