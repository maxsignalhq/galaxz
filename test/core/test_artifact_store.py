import pytest

from core.artifacts.store import ArtifactStore, identity_key


@pytest.fixture
def store(tmp_path):
    return ArtifactStore(db_path=str(tmp_path / "artifacts.db"))


def test_record_first_version_is_recorded(store):
    results = store.record(
        [{"filename": "out.py", "content": "x = 1", "language": "python", "artifact_type": "code"}],
        workspace_root="/tmp/ws",
        task_id="task-1",
        skill="rigel.skill.code_generation",
    )
    assert results == [{"identity_key": "/tmp/ws::out.py", "version": 1, "recorded": True}]

    row = store.get_version("/tmp/ws::out.py", 1)
    assert row["content"] == "x = 1"
    assert row["task_id"] == "task-1"
    assert row["skill"] == "rigel.skill.code_generation"


def test_record_identical_content_is_deduped(store):
    artifact = {"filename": "out.py", "content": "x = 1", "language": "python", "artifact_type": "code"}
    store.record([artifact], workspace_root="/tmp/ws", task_id="task-1", skill="s")
    results = store.record([artifact], workspace_root="/tmp/ws", task_id="task-2", skill="s")

    assert results == [{"identity_key": "/tmp/ws::out.py", "version": 1, "recorded": False}]
    assert store.latest_version_number("/tmp/ws::out.py") == 1


def test_record_changed_content_creates_new_version(store):
    key = "/tmp/ws::out.py"
    store.record(
        [{"filename": "out.py", "content": "x = 1"}], workspace_root="/tmp/ws", task_id="t1", skill="s"
    )
    results = store.record(
        [{"filename": "out.py", "content": "x = 2"}], workspace_root="/tmp/ws", task_id="t2", skill="s"
    )

    assert results == [{"identity_key": key, "version": 2, "recorded": True}]
    history = store.history(key)
    assert [h["version"] for h in history] == [2, 1]


def test_history_on_unknown_identity_key_is_empty(store):
    assert store.history("nope::nope.py") == []


def test_diff_between_two_versions(store):
    key = "/tmp/ws::out.py"
    store.record([{"filename": "out.py", "content": "a\nb\n"}], workspace_root="/tmp/ws", task_id="t1", skill="s")
    store.record([{"filename": "out.py", "content": "a\nc\n"}], workspace_root="/tmp/ws", task_id="t2", skill="s")

    result = store.diff(key, 1, 2)
    assert "-b" in result
    assert "+c" in result


def test_diff_missing_version_raises_key_error(store):
    key = "/tmp/ws::out.py"
    store.record([{"filename": "out.py", "content": "a\n"}], workspace_root="/tmp/ws", task_id="t1", skill="s")
    with pytest.raises(KeyError):
        store.diff(key, 1, 2)


def test_empty_workspace_root_is_tracked_correctly(store):
    store.record([{"filename": "out.py", "content": "x = 1"}], workspace_root="", task_id="t1", skill="s")
    assert identity_key("", "out.py") == "::out.py"
    assert store.get_version("::out.py", 1) is not None


def test_list_files_returns_latest_version_per_identity_key(store):
    store.record([{"filename": "a.py", "content": "1"}], workspace_root="/w", task_id="t1", skill="s")
    store.record([{"filename": "a.py", "content": "2"}], workspace_root="/w", task_id="t2", skill="s")
    store.record([{"filename": "b.py", "content": "1"}], workspace_root="/w", task_id="t3", skill="s")

    files = {f["identity_key"]: f for f in store.list_files()}
    assert files["/w::a.py"]["latest_version"] == 2
    assert files["/w::a.py"]["task_id"] == "t2"
    assert files["/w::b.py"]["latest_version"] == 1


def test_attempt_scoped_artifact_is_immutable_across_duplicate_delivery(store):
    first = store.record(
        [{"filename": "result.py", "content": "first"}],
        workspace_root="/workspace", task_id="task", skill="skill",
        attempt_id="attempt-1",
    )
    duplicate = store.record(
        [{"filename": "result.py", "content": "different late payload"}],
        workspace_root="/workspace", task_id="task", skill="skill",
        attempt_id="attempt-1",
    )

    assert first[0]["recorded"] is True
    assert duplicate == [{**first[0], "recorded": False}]
    version = store.get_version(first[0]["identity_key"], first[0]["version"])
    assert version["content"] == "first"
