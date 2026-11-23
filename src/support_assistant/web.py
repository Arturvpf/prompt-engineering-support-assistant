"""Interface web local, só com a biblioteca padrão (http.server).

Rotas:

- ``GET  /``              página única (static/index.html)
- ``GET  /api/options``   perfis, tickets, tipos de conteúdo e versões
- ``POST /api/generate``  gera (ou busca no cache) e devolve os registros
- ``GET  /api/history``   últimas execuções, com filtro opcional por cliente, ticket e versão
- ``GET  /api/run?id=``   um registro completo, com a saída formatada
- ``POST /api/evaluate``  grava as notas da rubrica numa execução
- ``POST /api/compare``   compara execuções avaliadas do mesmo cenário e salva o JSON
- ``GET  /api/stats``     métricas do histórico

Escuta em 127.0.0.1 por padrão. As gerações são serializadas com um lock para
que duas requisições não gravem o histórico ao mesmo tempo.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import threading
import time
from collections import deque
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import PROJECT_ROOT, ConfigError, WebSettings, load_settings, load_web_settings
from .content_types import CONTENT_TYPES
from .data_loader import DataValidationError, load_customers, load_tickets, make_adhoc_ticket
from .evaluation import (
    RUBRIC,
    SCALE,
    EvaluationError,
    build_comparison,
    default_comparison_path,
    evaluate_run,
    save_comparison,
)
from .formatting import render_output
from .history import HistoryError, RunNotFound
from .llm_client import LLMError
from .observability import history_stats, log_event
from .prompt_engine import DEFAULT_VERSION, PromptEngine, PromptError
from .service import AssistantService

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BODY_BYTES = 32_000
MAX_TICKET_CHARS = 4_000
MAX_JUSTIFICATION_CHARS = 1_000
MAX_VERDICT_CHARS = 4_000
MAX_COMPARE_RUNS = 16
HISTORY_LIMIT = 200


class BadRequest(ValueError):
    """Requisição inválida (vira HTTP 400)."""


class NotFound(LookupError):
    """Execução ou rota inexistente (vira HTTP 404)."""


class Forbidden(PermissionError):
    """Ação desativada nesta instalação (vira HTTP 403)."""


class TooManyRequests(RuntimeError):
    """Limite de gerações por pessoa atingido (vira HTTP 429 com Retry-After)."""

    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class RateLimiter:
    """Janela deslizante por chave (IP): no máximo ``limit`` eventos a cada ``window`` segundos."""

    def __init__(self, limit: int, window: int, clock=time.monotonic) -> None:
        self.limit, self.window, self.clock = limit, window, clock
        self._events: dict[str, deque] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        if self.limit <= 0:
            return
        now = self.clock()
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and now - events[0] >= self.window:
                events.popleft()
            if len(events) >= self.limit:
                retry = int(self.window - (now - events[0])) + 1
                raise TooManyRequests(
                    f"Limite de {self.limit} gerações a cada {_duration(self.window)} atingido. "
                    f"Tente de novo em {_duration(retry)}; resultados já gerados continuam no histórico.", retry)
            events.append(now)
            if len(self._events) > 10_000:  # não deixa a memória crescer com IPs antigos
                for k in [k for k, v in self._events.items() if not v or now - v[-1] >= self.window]:
                    del self._events[k]


class App:
    """Lógica das rotas, separada do servidor HTTP para poder ser testada sem rede."""

    def __init__(self, service: AssistantService | None = None, web: WebSettings | None = None) -> None:
        self.service = service or AssistantService(load_settings(require_api_key=False))
        self.web = web or WebSettings()
        self.engine: PromptEngine = self.service.engine
        self.customers = load_customers()
        self.tickets = load_tickets()
        self._lock = threading.Lock()
        self.limiter = RateLimiter(self.web.rate_limit, self.web.rate_window_seconds)
        if self.web.daily_model_calls > 0:
            self.service.can_call_model = lambda: self.model_calls_today() < self.web.daily_model_calls
        if self.web.seed_samples:
            seeded = self.service.store.seed(_sample_records())
            if seeded:
                log_event("history_seeded", records=seeded)

    def model_calls_today(self) -> int:
        """Chamadas reais ao modelo hoje (fuso do servidor). Registros de demonstração não contam."""
        now = datetime.now().astimezone()
        count = 0
        for r in self.service.store.load():
            if r.get("cache_hit") or r.get("seeded"):
                continue
            try:
                when = datetime.fromisoformat(str(r.get("timestamp")))
            except ValueError:
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=now.tzinfo)
            if when.astimezone(now.tzinfo).date() == now.date():
                count += 1
        return count

    def health(self) -> dict:
        return {"status": "ok", "default_version": DEFAULT_VERSION}

    def limits(self) -> dict:
        cap = self.web.daily_model_calls
        return {
            "rate_limit": self.web.rate_limit,
            "rate_window_seconds": self.web.rate_window_seconds,
            "daily_model_calls": cap,
            "model_calls_left_today": max(0, cap - self.model_calls_today()) if cap else None,
            "allow_evaluation": self.web.allow_evaluation,
        }

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
            "default_version": DEFAULT_VERSION,
            "rubric": {
                "criteria": [{"id": c.id, "label": c.label, "description": c.description} for c in RUBRIC],
                "scale": {str(k): v for k, v in SCALE.items()},
            },
            "model": f"{self.service.settings.provider}/{self.service.settings.model}",
            "generation_params": self.service.settings.generation_params(),
            "history_path": str(self.service.store.path),
            "limits": self.limits(),
        }

    def generate(self, body: dict, client: str = "local") -> dict:
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
        self.limiter.check(client)  # depois da validação: pedido inválido não gasta a cota

        results = []
        with self._lock:
            for version in dict.fromkeys(versions):
                produced: dict[str, dict] = {}
                for content_type in sorted(dict.fromkeys(types), key=list(CONTENT_TYPES).index):
                    try:
                        record = self.service.generate(customer, ticket, content_type, version,
                                                       use_cache=use_cache, upstream_records=produced)
                        produced[content_type] = record
                    except LLMError as exc:
                        results.append({"content_type": content_type, "prompt_version": version, "error": str(exc)})
                        continue
                    results.append({**record, "rendered": render_output(content_type, record["output"], wrap=False)})
        return {"results": results, "history_path": str(self.service.store.path)}

    def history(self, query: dict) -> dict:
        def arg(name: str) -> str:
            return (query.get(name) or [""])[0]

        customer, ticket, version = arg("customer"), arg("ticket"), arg("version")
        records = [
            r for r in self.service.store.load()
            if (not customer or r.get("customer_id") == customer)
            and (not ticket or r.get("ticket_id") == ticket)
            and (not version or r.get("prompt_version") == version)
        ][-HISTORY_LIMIT:]
        return {"runs": [_summary(r) for r in reversed(records)]}

    def run(self, query: dict) -> dict:
        record = self._get((query.get("id") or [""])[0])
        return {**record, "rendered": render_output(record["content_type"], record["output"], wrap=False)}

    def evaluate(self, body: dict) -> dict:
        if not self.web.allow_evaluation:
            raise Forbidden("A avaliação pela web está desativada nesta instalação (WEB_ALLOW_EVALUATION=false).")
        run_id = body.get("run_id")
        raw = body.get("scores")
        if not isinstance(run_id, str) or not run_id:
            raise BadRequest("informe 'run_id'")
        if not isinstance(raw, dict):
            raise BadRequest("'scores' deve ser um objeto {criterio: {score, justification}}")
        scores = {}
        for cid, value in raw.items():
            if not isinstance(value, dict):
                raise BadRequest(f"'{cid}' deve ter 'score' e 'justification'")
            justification = value.get("justification")
            if not isinstance(justification, str) or len(justification) > MAX_JUSTIFICATION_CHARS:
                raise BadRequest(f"a justificativa de '{cid}' deve ser um texto de até {MAX_JUSTIFICATION_CHARS} caracteres")
            scores[cid] = (value.get("score"), justification)
        evaluator = body.get("evaluator") or "manual"
        if not isinstance(evaluator, str) or len(evaluator) > 60:
            raise BadRequest("'evaluator' deve ser um texto curto")
        self._get(run_id)  # 404 antes de validar as notas
        with self._lock:
            try:
                record = evaluate_run(self.service.store, run_id, scores, evaluator)
            except EvaluationError as exc:
                raise BadRequest(str(exc)) from None
        return {"run": _summary(record), "evaluation": record["evaluation"]}

    def compare(self, body: dict) -> dict:
        run_ids = _string_list(body.get("run_ids"), "run_ids")
        if not 2 <= len(run_ids) <= MAX_COMPARE_RUNS:
            raise BadRequest(f"escolha de 2 a {MAX_COMPARE_RUNS} execuções")
        verdict = body.get("verdict") or ""
        if not isinstance(verdict, str) or len(verdict) > MAX_VERDICT_CHARS:
            raise BadRequest(f"o veredito deve ser um texto de até {MAX_VERDICT_CHARS} caracteres")
        for run_id in run_ids:
            self._get(run_id)
        with self._lock:
            try:
                comparison = build_comparison(self.service.store, run_ids, verdict)
            except EvaluationError as exc:
                raise BadRequest(str(exc)) from None
            saved_to = None
            if body.get("save", True) is not False and self.web.allow_evaluation:
                path = default_comparison_path(self.service.settings.output_dir, comparison)
                saved_to = str(save_comparison(comparison, path))
        return {"comparison": comparison, "saved_to": saved_to}

    def stats(self) -> dict:
        return history_stats(self.service.store.load())

    def _get(self, run_id: str) -> dict:
        try:
            return self.service.store.get(run_id)
        except RunNotFound as exc:
            raise NotFound(str(exc)) from None


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SupportAssistant/1.0"

        def do_GET(self) -> None:  # noqa: N802 - nome exigido pelo http.server
            url = urlparse(self.path)
            query = parse_qs(url.query)
            routes = {
                "/api/options": app.options,
                "/api/health": app.health,
                "/api/stats": app.stats,
                "/api/history": lambda: app.history(query),
                "/api/run": lambda: app.run(query),
            }
            if url.path in ("/", "/index.html"):
                return self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            if url.path in routes:
                return self._handle(routes[url.path])
            self._send_json({"error": "rota não encontrada"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            routes = {
                "/api/generate": lambda body: app.generate(body, client=self._client_id()),
                "/api/evaluate": app.evaluate,
                "/api/compare": app.compare,
            }
            action = routes.get(urlparse(self.path).path)
            if action is None:
                return self._send_json({"error": "rota não encontrada"}, HTTPStatus.NOT_FOUND)
            self._handle(lambda: action(self._read_json()))

        # ---------------------------------------------------------- helpers

        def _handle(self, action) -> None:
            try:
                self._send_json(action())
            except BadRequest as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except NotFound as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
            except Forbidden as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.FORBIDDEN)
            except TooManyRequests as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.TOO_MANY_REQUESTS,
                                {"Retry-After": str(exc.retry_after)})
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

        def _client_id(self) -> str:
            """IP de quem pediu. Atrás do proxy da plataforma, vem no X-Forwarded-For (só se confiável)."""
            if app.web.trust_proxy:
                forwarded = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
                if forwarded:
                    return forwarded[:64]
            return self.client_address[0]

        def _security_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")

        def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK, extra: dict | None = None) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self._security_headers()
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path, content_type: str) -> None:
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self._security_headers()
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                                                        "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:  # silencia o log padrão por requisição
            pass

    return Handler


class ExclusiveHTTPServer(ThreadingHTTPServer):
    """Servidor que falha se a porta já estiver em uso, em vez de dividi-la com outro programa.

    O HTTPServer padrão liga SO_REUSEADDR. No Windows essa opção deixa dois programas
    escutarem na mesma porta, e o navegador cai no programa errado sem nenhum erro.
    Lá usamos SO_EXCLUSIVEADDRUSE; nos outros sistemas, SO_REUSEADDR só permite
    reaproveitar uma porta em TIME_WAIT e continua seguro.
    """

    daemon_threads = True
    allow_reuse_address = os.name != "nt"

    def server_bind(self) -> None:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(app: App, host: str, port: int) -> ExclusiveHTTPServer:
    return ExclusiveHTTPServer((host, port), make_handler(app))


def serve(host: str | None = None, port: int | None = None) -> int:
    """Sobe a interface. Host e porta vêm dos argumentos, senão de HOST/PORT, senão 127.0.0.1:8000."""
    web = load_web_settings()
    host, port = host or web.host, port or web.port
    app = App(web=web)
    try:
        server = make_server(app, host, port)
    except OSError as exc:
        print(f"Não foi possível abrir a interface em http://{host}:{port}: a porta está em uso por outro "
              f"programa ou bloqueada ({exc.strerror or exc}).\n"
              f"Escolha outra porta, por exemplo: python main.py web --port {port + 1}", file=sys.stderr)
        return 1
    print(f"Interface web em http://{host}:{port}  (Ctrl+C para parar)", flush=True)
    print(f"Modelo: {app.options()['model']}  |  histórico: {app.service.store.path}", flush=True)
    if host not in ("127.0.0.1", "localhost", "::1"):
        limits = app.limits()
        print(f"Aberta para a rede ({host}). Limites: {limits['rate_limit'] or 'sem limite'} gerações por pessoa "
              f"a cada {_duration(limits['rate_window_seconds'])}; teto diário de chamadas: "
              f"{limits['daily_model_calls'] or 'sem teto'}; avaliação pela web: "
              f"{'ligada' if limits['allow_evaluation'] else 'desligada'}.", flush=True)
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
        "upstream": r.get("upstream"),
        "score": ev.get("total") if ev else None,
        "tokens": ((r.get("metrics") or {}).get("usage") or {}).get("total_tokens"),
        # Execuções com o mesmo cenário podem ser comparadas entre si (só a versão muda).
        "scenario": _scenario_key(r),
    }


def _sample_records() -> list[dict]:
    """Todos os registros de histórico guardados em samples/ (arquivos que são listas de registros)."""
    records = []
    for path in sorted((PROJECT_ROOT / "samples").rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, list):
            records += [r for r in data if isinstance(r, dict)]
    return records


def _duration(seconds: int) -> str:
    if seconds >= 3600 and seconds % 3600 == 0:
        hours = seconds // 3600
        return "1 hora" if hours == 1 else f"{hours} horas"
    if seconds >= 60:
        minutes = -(-seconds // 60)
        return "1 minuto" if minutes == 1 else f"{minutes} minutos"
    return "1 segundo" if seconds == 1 else f"{seconds} segundos"


def _scenario_key(r: dict) -> str:
    material = json.dumps([r.get("customer_id"), r.get("ticket"), r.get("generation_params")],
                          sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
