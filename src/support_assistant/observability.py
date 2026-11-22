"""Observabilidade: log estruturado de eventos e estatísticas do histórico.

Cada evento (geração, cache hit, retry, correção de JSON, falha) vira uma
linha JSON em ``outputs/logs/events.jsonl``. O mesmo evento aparece no
terminal (stderr) quando ``LOG_LEVEL`` permite, por padrão só avisos e erros.

O log nunca recebe a chave de API nem o texto do ticket: só ids, métricas e
mensagens de erro.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path

LOGGER_NAME = "support_assistant"
EVENTS_FILENAME = "events.jsonl"

logger = logging.getLogger(LOGGER_NAME)
logger.addHandler(logging.NullHandler())  # sem configurar, os eventos são descartados


class _JsonLinesFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created).astimezone().isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "event": record.getMessage(),
            **getattr(record, "fields", {}),
        }
        return json.dumps(entry, ensure_ascii=False, default=str)


class _ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = " ".join(f"{k}={v}" for k, v in getattr(record, "fields", {}).items() if v not in (None, "", []))
        return f"[{record.levelname.lower()}] {record.getMessage()} {fields}".rstrip()


def configure_logging(log_dir: Path, level: str = "WARNING") -> Path:
    """Liga o arquivo de eventos (sempre INFO) e o console (no nível pedido). Idempotente."""
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / EVENTS_FILENAME
    for handler in list(logger.handlers):
        if getattr(handler, "_support_assistant", False):
            logger.removeHandler(handler)
            handler.close()

    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(_JsonLinesFormatter())

    console = logging.StreamHandler()
    console.setLevel(getattr(logging, level.upper(), logging.WARNING))
    console.setFormatter(_ConsoleFormatter())

    for handler in (file_handler, console):
        handler._support_assistant = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return path


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"fields": fields})


# ------------------------------------------------------------------ estatísticas

def history_stats(records: list[dict]) -> dict:
    """Resumo do histórico: volume, cache, latência, tokens e correções."""
    originals = [r for r in records if not r.get("cache_hit")]
    hits = [r for r in records if r.get("cache_hit")]
    tokens_saved = 0
    by_id = {r.get("run_id"): r for r in originals}
    for r in hits:
        source = by_id.get(r.get("source_run_id"), {})
        tokens_saved += _tokens(source) or 0

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in originals:
        groups[(r.get("prompt_version", "?"), r.get("content_type", "?"))].append(r)

    return {
        "total_runs": len(records),
        "model_calls": len(originals),
        "cache_hits": len(hits),
        "cache_hit_rate": round(len(hits) / len(records), 3) if records else 0.0,
        "tokens_total": sum(_tokens(r) or 0 for r in originals),
        "tokens_saved_by_cache": tokens_saved,
        "runs_with_repair": sum(1 for r in originals if (r.get("metrics") or {}).get("attempts", 1) > 1),
        "runs_with_warnings": sum(1 for r in originals if r.get("warnings")),
        "evaluated_runs": sum(1 for r in records if r.get("evaluation")),
        "by_version_and_type": [
            {
                "prompt_version": v,
                "content_type": t,
                "runs": len(rs),
                "avg_latency_ms": round(_avg([(r.get("metrics") or {}).get("latency_ms") for r in rs])),
                "avg_tokens": round(_avg([_tokens(r) for r in rs])),
            }
            for (v, t), rs in sorted(groups.items())
        ],
    }


def _tokens(record: dict) -> int | None:
    return ((record.get("metrics") or {}).get("usage") or {}).get("total_tokens")


def _avg(values) -> float:
    nums = [v for v in values if isinstance(v, (int, float))]
    return sum(nums) / len(nums) if nums else 0.0
