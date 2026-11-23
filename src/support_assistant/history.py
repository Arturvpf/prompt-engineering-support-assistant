"""Histórico de execuções em JSON, que também serve de base para o cache.

Todas as execuções ficam em um único arquivo (``outputs/history.json``), uma
lista de registros. Cada registro guarda cliente, ticket, tipo de conteúdo,
versão do prompt, provedor/modelo, configurações, saída e, depois da Fase 6,
a avaliação da rubrica.

A gravação é atômica (arquivo temporário + ``os.replace``) para que uma
interrupção no meio da escrita não corrompa o histórico.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path


class HistoryError(RuntimeError):
    """Histórico ilegível ou registro inexistente."""


class RunNotFound(HistoryError):
    """Não há execução com esse run_id no histórico."""


class HistoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    # ---------------------------------------------------------------- leitura

    def load(self) -> list[dict]:
        if not self.path.is_file():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            # Não sobrescreve: o usuário decide o que fazer com o arquivo danificado.
            raise HistoryError(f"Histórico corrompido em {self.path}: {exc}. Corrija ou mova o arquivo.") from exc
        if not isinstance(data, list):
            raise HistoryError(f"{self.path} deve conter uma lista de execuções.")
        return data

    def get(self, run_id: str) -> dict:
        for record in self.load():
            if record.get("run_id") == run_id:
                return record
        raise RunNotFound(f"Execução {run_id!r} não encontrada no histórico.")

    def find_cached(self, cache_key: str) -> dict | None:
        """Execução original mais recente com a mesma chave (ignora registros que já vieram do cache)."""
        for record in reversed(self.load()):
            if record.get("cache_key") == cache_key and not record.get("cache_hit"):
                return record
        return None

    # ---------------------------------------------------------------- escrita

    def append(self, record: dict) -> dict:
        record = {"run_id": new_run_id(), "timestamp": now_iso(), **record}
        records = self.load()
        records.append(record)
        self._write(records)
        return record

    def seed(self, records: list[dict]) -> int:
        """Preenche um histórico VAZIO com registros prontos (ex.: os de samples/), mantendo run_id e chaves.

        Usado no deploy de demonstração: os cenários de exemplo já aparecem avaliados
        e repetir um deles vem do cache. Um histórico com dados nunca é sobrescrito.
        """
        if self.load():
            return 0
        unique = {r["run_id"]: {**r, "seeded": True}
                  for r in records if isinstance(r, dict) and r.get("run_id") and r.get("output")}
        ordered = sorted(unique.values(), key=lambda r: r.get("timestamp", ""))
        if ordered:
            self._write(ordered)
        return len(ordered)

    def update(self, run_id: str, **fields) -> dict:
        records = self.load()
        for record in records:
            if record.get("run_id") == run_id:
                record.update(fields)
                self._write(records)
                return record
        raise RunNotFound(f"Execução {run_id!r} não encontrada no histórico.")

    def _write(self, records: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".history-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(records, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
