import time
from uuid import uuid4

import pytest

from core.contracts import MemoryEntry
from core.nebula.store import NebulaStore


@pytest.fixture
def store(tmp_path):
    return NebulaStore(db_path=str(tmp_path / "nebula.db"))


def test_contract_rejects_blank_fields():
    with pytest.raises(ValueError):
        MemoryEntry(namespace=" ", content="x")
    with pytest.raises(ValueError):
        MemoryEntry(namespace="global", content="")


def test_remember_and_list_round_trip(store):
    task_id = uuid4()
    entry = store.remember("global", "Use type hints", tags=["style"], source_task_id=task_id)
    assert entry.namespace == "global"
    [got] = store.list("global")
    assert got.memory_id == entry.memory_id
    assert got.tags == ["style"]
    assert got.source_task_id == task_id


def test_recall_ranks_by_keyword_overlap(store):
    store.remember("global", "The billing service uses Postgres")
    store.remember("global", "Prefer pytest fixtures for database setup")
    store.remember("global", "Unrelated note about lunch")
    hits = store.recall(["global"], query="write pytest database fixtures", limit=5)
    assert [h.content for h in hits][0] == "Prefer pytest fixtures for database setup"
    assert "Unrelated note about lunch" not in [h.content for h in hits]


def test_recall_matches_tags(store):
    store.remember("global", "Follow the house rules", tags=["python", "style"])
    hits = store.recall(["global"], query="python function", limit=5)
    assert len(hits) == 1


def test_recall_without_query_returns_most_recent_first(store):
    store.remember("global", "old")
    time.sleep(0.01)
    store.remember("global", "new")
    assert [h.content for h in store.recall(["global"], limit=5)] == ["new", "old"]


def test_recall_spans_namespaces_and_respects_limit(store):
    store.remember("goal:1", "goal note")
    store.remember("global", "global note")
    store.remember("other", "other note")
    hits = store.recall(["goal:1", "global"], limit=5)
    assert {h.content for h in hits} == {"goal note", "global note"}
    assert len(store.recall(["goal:1", "global"], limit=1)) == 1


def test_forget(store):
    entry = store.remember("global", "temp")
    assert store.forget(entry.memory_id) is True
    assert store.forget(entry.memory_id) is False
    assert store.list("global") == []


def test_persists_across_instances(tmp_path):
    path = str(tmp_path / "nebula.db")
    NebulaStore(db_path=path).remember("global", "durable")
    assert [e.content for e in NebulaStore(db_path=path).list("global")] == ["durable"]


def test_namespaces_lists_counts(store, tmp_path):
    store.remember("global", "a")
    store.remember("global", "b")
    store.remember("goal:1", "c")
    assert store.namespaces() == [{"namespace": "global", "count": 2}, {"namespace": "goal:1", "count": 1}]
    assert NebulaStore(db_path=str(tmp_path / "empty.db")).namespaces() == []
