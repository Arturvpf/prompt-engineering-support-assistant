"""Interface web local, só com a biblioteca padrão (http.server).

Rotas:

- ``GET  /``              página única (static/index.html)
- ``GET  /api/options``   perfis, tickets, tipos de conteúdo e versões
- ``POST /api/generate``  gera (ou busca no cache) e devolve os registros
- ``GET  /api/history``   últimas execuções, com filtro opcional por cliente e ticket
- ``GET  /api/stats``     métricas do histórico

Escuta em 127.0.0.1 por padrão. As gerações são serializadas com um lock para
que duas requisições não gravem o histórico ao mesmo tempo.
"""

from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import ConfigError, load_settings
from .content_types import CONTENT_TYPES
from .data_loader import DataValidationError, load_customers, load_tickets, make_adhoc_ticket
from .formatting import render_output
from .history import HistoryError
from .llm_client import LLMError
from .observability import history_stats
from .prompt_engine import PromptEngine, PromptError
from .service import AssistantService

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BODY_BYTES = 32_000
MAX_TICKET_CHARS = 4_000
HISTORY_LIMIT = 50


class BadRequest(ValueError):
    """Requisição inválida (vira HTTP 400)."""


class App:
    """Lógica das rotas, separada do servidor HTTP para poder ser testada sem rede."""

    def __init__(self, service: AssistantService | None = None) -> None:
        self.service = service or AssistantService(load_settings(require_api_key=False))
        self.engine: PromptEngine = self.service.engine
        self.customers = load_customers()
        self.tickets = load_tickets()
        self._lock = threading.Lock()

    def options(self) -> dict:
        return {
            "customers": [
                {"id": c.id, "name": c.name, "technical_level": c.technical_level,
                 "communication_style": c.communication_style, "channel": c.channel}
                for c in self.customers.values()
            ],
            "tickets": [{"id": t.id, "title": t.title, "description": t.description} for t in self.tickets.values()],
            "content_types": [{"id": ct.id, "label": ct.label} for ct in CONTENT_TYPES.values()],
            "versions": [
                {"id": v, "description": self.engine.manifest(v).get("description", "")}
                for v in self.engine.available_versions()
            ],
            "model": f"{self.service.settings.provider}/{self.service.settings.model}",
            "history_path": str(self.service.store.path),
        }

    def generate(self, body: dict) -> dict:
        customer = self.customers.get(body.get("customer_id"))
        if customer is None:
            raise BadRequest("perfil inválido")

        text = (body.get("ticket_text") or "").strip()
        if text:
            if len(text) > MAX_TICKET_CHARS:
                raise BadRequest(f"o ticket pode ter no máximo {MAX_TICKET_CHARS} caracteres")
            ticket = make_adhoc_ticket(text)
        else:
            ticket = self.tickets.get(body.get("ticket_id"))
            if ticket is None:
                raise BadRequest("escolha um ticket ou digite um novo")

        types = _string_list(body.get("content_types"), "content_types")
        if not types or any(t not in CONTENT_TYPES for t in types):
            raise BadRequest("tipos de conteúdo inválidos")
        versions = _string_list(body.get("versions"), "versions")
        available = self.engine.available_versions()
        if not versions or any(v not in available for v in versions):
            raise BadRequest("versões de prompt inválidas")
        use_cache = body.get("use_cache", True) is not False

        results = []
        with self._lock:
            for version in dict.fromkeys(versions):
                for content_type in dict.fromkeys(types):
                    try:
                        record = self.service.generate(customer, ticket, content_type, version, use_cache=use_cache)
                    except LLMError as exc:
                        results.append({"content_type": content_type, "prompt_version": version, "error": str(exc)})
                        continue
                    results.append({**record, "rendered": render_output(content_type, record["output"], wrap=False)})
        return {"results": results, "history_path": str(self.service.store.path)}

    def history(self, query: dict) -> dict:
        customer = (query.get("customer") or [""])[0]
        ticket = (query.get("ticket") or [""])[0]
        records = [
            r for r in self.service.store.load()
            if (not customer or r.get("customer_id") == customer) and (not ticket or r.get("ticket_id") == ticket)
        ][-HISTORY_LIMIT:]
        return {"runs": [_summary(r) for r in reversed(records)]}

    def stats(self) -> dict:
        return history_stats(self.service.store.load())


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SupportAssistant/1.0"

        def do_GET(self) -> None:  # noqa: N802 - nome exigido pelo http.server
            url = urlparse(self.path)
            routes = {
                "/api/options": app.options,
                "/api/stats": app.stats,
                "/api/history": lambda: app.history(parse_qs(url.query)),
            }
            if url.path in ("/", "/index.html"):
                return self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            if url.path in routes:
                return self._handle(routes[url.path])
            self._send_json({"error": "rota não encontrada"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/api/generate":
                return self._send_json({"error": "rota não encontrada"}, HTTPStatus.NOT_FOUND)
            self._handle(lambda: app.generate(self._read_json()))

        # ---------------------------------------------------------- helpers

        def _handle(self, action) -> None:
            try:
                self._send_json(action())
            except BadRequest as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except (ConfigError, DataValidationError, PromptError, HistoryError, LLMError) as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def _read_json(self) -> dict:
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                raise BadRequest("envie Content-Type: application/json")
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise BadRequest("Content-Length inválido") from None
            if length <= 0 or length > MAX_BODY_BYTES:
                raise BadRequest(f"corpo vazio ou maior que {MAX_BODY_BYTES} bytes")
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise BadRequest("JSON inválido") from None
            if not isinstance(data, dict):
                raise BadRequest("o corpo deve ser um objeto JSON")
            return data

        def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path, content_type: str) -> None:
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                                                        "script-src 'self' 'unsafe-inline'")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:  # silencia o log padrão por requisição
            pass

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8000) -> int:
    app = App()
    server = ThreadingHTTPServer((host, port), make_handler(app))
    print(f"Interface web em http://{host}:{port}  (Ctrl+C para parar)")
    print(f"Modelo: {app.options()['model']}  |  histórico: {app.service.store.path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
    finally:
        server.server_close()
    return 0


def _string_list(value, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise BadRequest(f"'{name}' deve ser uma lista de textos")
    return value


def _summary(r: dict) -> dict:
    ev = r.get("evaluation")
    return {
        "run_id": r.get("run_id"),
        "timestamp": r.get("timestamp"),
        "customer_id": r.get("customer_id"),
        "ticket_id": r.get("ticket_id"),
        "content_type": r.get("content_type"),
        "prompt_version": r.get("prompt_version"),
        "cache_hit": r.get("cache_hit"),
        "source_run_id": r.get("source_run_id"),
        "score": ev.get("total") if ev else None,
    }
