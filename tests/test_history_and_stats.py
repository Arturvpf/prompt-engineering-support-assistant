import pytest

from support_assistant.history import HistoryError, HistoryStore
from support_assistant.observability import history_stats


def test_append_get_update_roundtrip(tmp_path):
    store = HistoryStore(tmp_path / "sub" / "history.json")
    record = store.append({"content_type": "diagnosis"})
    assert len(record["run_id"]) == 12 and record["timestamp"]
    store.update(record["run_id"], evaluation={"total": 10})
    assert store.get(record["run_id"])["evaluation"] == {"total": 10}
    assert not list(store.path.parent.glob(".history-*.tmp")), "arquivo temporário não pode sobrar"


def test_missing_run_raises(tmp_path):
    store = HistoryStore(tmp_path / "history.json")
    with pytest.raises(HistoryError):
        store.get("nao-existe")
    with pytest.raises(HistoryError):
        store.update("nao-existe", x=1)


def test_corrupted_history_is_not_overwritten(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("{quebrado", encoding="utf-8")
    store = HistoryStore(path)
    with pytest.raises(HistoryError, match="corrompido"):
        store.append({"a": 1})
    assert path.read_text(encoding="utf-8") == "{quebrado"


def test_find_cached_ignores_cache_hit_records(tmp_path):
    store = HistoryStore(tmp_path / "history.json")
    original = store.append({"cache_key": "k", "cache_hit": False})
    store.append({"cache_key": "k", "cache_hit": True, "source_run_id": original["run_id"]})
    assert store.find_cached("k")["run_id"] == original["run_id"]
    assert store.find_cached("outra") is None


def test_history_stats():
    records = [
        {"run_id": "a", "prompt_version": "v1", "content_type": "diagnosis", "cache_hit": False,
         "metrics": {"attempts": 1, "latency_ms": 1000, "usage": {"total_tokens": 300}}},
        {"run_id": "b", "prompt_version": "v2", "content_type": "diagnosis", "cache_hit": False, "warnings": ["x"],
         "metrics": {"attempts": 2, "latency_ms": 3000, "usage": {"total_tokens": 700}}, "evaluation": {"total": 12}},
        {"run_id": "c", "prompt_version": "v2", "content_type": "diagnosis", "cache_hit": True, "source_run_id": "b",
         "metrics": {"attempts": 0, "latency_ms": 0, "usage": {}}},
    ]
    s = history_stats(records)
    assert s["total_runs"] == 3 and s["model_calls"] == 2 and s["cache_hits"] == 1
    assert s["tokens_total"] == 1000 and s["tokens_saved_by_cache"] == 700
    assert s["runs_with_repair"] == 1 and s["runs_with_warnings"] == 1 and s["evaluated_runs"] == 1
    assert [g["prompt_version"] for g in s["by_version_and_type"]] == ["v1", "v2"]
    assert history_stats([])["cache_hit_rate"] == 0.0
