from datetime import date
import json

import pytest

from orion.core.dataset_store import DatasetStore


def make_example(index: int, *, human_verified: bool = True) -> dict:
    return {
        "prompt": f"prompt {index}",
        "completion": f"completion {index}",
        "skill_id": "qa.test_generation",
        "confidence": 0.91,
        "human_verified": human_verified,
        "task_id": f"task-{index}",
        "created_at": "2026-04-27T00:00:00Z",
    }


def test_dataset_store_initializes_directories_and_empty_stats(tmp_path):
    store = DatasetStore(str(tmp_path / "datasets"))

    assert (tmp_path / "datasets" / "vega").is_dir()
    assert (tmp_path / "datasets" / "rigel").is_dir()
    assert (tmp_path / "heuristics").is_dir()
    assert store.stats("vega") == {
        "buffered": 0,
        "versions": 0,
        "latest_version": 0,
        "latest_path": None,
    }


def test_append_example_requires_all_training_keys(tmp_path):
    store = DatasetStore(str(tmp_path / "datasets"))
    example = make_example(1)
    example.pop("completion")

    with pytest.raises(ValueError, match="completion"):
        store.append_example("vega", example)


def test_flush_writes_versioned_jsonl_and_updates_latest(tmp_path):
    store = DatasetStore(str(tmp_path / "datasets"))

    for index in range(5):
        store.append_example("vega", make_example(index))
    first_path = store.flush("vega")

    first = tmp_path / "datasets" / "vega" / f"v1_{date.today().isoformat()}.jsonl"
    latest = tmp_path / "datasets" / "vega" / "latest"
    assert first_path == str(first)
    assert first.exists()
    assert len(first.read_text(encoding="utf-8").splitlines()) == 5
    assert latest.is_symlink()
    assert latest.readlink().name == first.name
    assert store.stats("vega")["buffered"] == 0

    for index in range(5, 10):
        store.append_example("vega", make_example(index))
    second_path = store.flush("vega")

    second = tmp_path / "datasets" / "vega" / f"v2_{date.today().isoformat()}.jsonl"
    assert second_path == str(second)
    assert len(second.read_text(encoding="utf-8").splitlines()) == 5
    assert latest.readlink().name == second.name
    assert store.get_latest_path("vega") == str(second)
    assert json.loads(second.read_text(encoding="utf-8").splitlines()[0])["task_id"] == "task-5"


def test_should_flush_thresholds(tmp_path):
    store = DatasetStore(str(tmp_path / "datasets"))

    for index in range(4):
        store.append_example("rigel", make_example(index))
    assert store.should_flush("rigel") is False

    for index in range(4, 100):
        store.append_example("rigel", make_example(index))
    assert store.should_flush("rigel") is True

    store = DatasetStore(str(tmp_path / "other-datasets"))
    for index in range(500):
        store.append_example("rigel", make_example(index, human_verified=False))
    assert store.should_flush("rigel") is True
