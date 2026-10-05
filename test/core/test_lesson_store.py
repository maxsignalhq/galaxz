import threading

import pytest

from orion.core.lesson_store import LessonStore


@pytest.fixture
def store(tmp_path):
    return LessonStore(str(tmp_path / "sub" / "lessons.db"))


def test_add_and_list_pending(store):
    candidate = store.add("rigel.skill.code_generation", "rigel", "  Prefer   type hints.  ", ["e1", "e2"])
    assert candidate.content == "Prefer type hints."
    assert candidate.status == "pending" and candidate.evidence == ["e1", "e2"]
    assert [c.candidate_id for c in store.list()] == [candidate.candidate_id]
    assert store.get(candidate.candidate_id) == candidate
    assert store.get("missing") is None


def test_adding_marks_the_evidence_as_used(store):
    store.add("s", "a", "lesson", ["e1", "e2"])
    assert store.used_event_ids() == {"e1", "e2"}
    store.mark_used(["e3"], "duplicate")
    assert store.used_event_ids() == {"e1", "e2", "e3"}


def test_claim_is_atomic_and_single_shot(store):
    candidate = store.add("s", "a", "lesson", [])
    assert store.claim(candidate.candidate_id, "approved", "alice", "ok") is True
    assert store.claim(candidate.candidate_id, "approved", "bob") is False
    assert store.claim(candidate.candidate_id, "rejected", "bob") is False
    done = store.get(candidate.candidate_id)
    assert (done.status, done.reviewed_by, done.reviewer_note) == ("approved", "alice", "ok")
    assert done.reviewed_at is not None
    assert store.list() == []


def test_claim_with_edited_content_replaces_the_lesson(store):
    candidate = store.add("s", "a", "original", [])
    assert store.claim(candidate.candidate_id, "approved", "alice", content="  edited   text ")
    assert store.get(candidate.candidate_id).content == "edited text"


def test_concurrent_claims_have_exactly_one_winner(store):
    candidate = store.add("s", "a", "lesson", [])
    results = []
    threads = [
        threading.Thread(target=lambda i=i: results.append(store.claim(candidate.candidate_id, "approved", f"r{i}")))
        for i in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1


def test_revert_returns_the_candidate_to_pending(store):
    candidate = store.add("s", "a", "lesson", [])
    store.claim(candidate.candidate_id, "approved", "alice", "note")
    store.attach_memory(candidate.candidate_id, "m1")
    store.revert(candidate.candidate_id)
    back = store.get(candidate.candidate_id)
    assert (back.status, back.reviewed_by, back.reviewer_note, back.memory_id) == ("pending", None, None, None)
    assert store.claim(candidate.candidate_id, "approved", "bob") is True


def test_has_content_matches_pending_and_approved_only_case_and_space_insensitively(store):
    pending = store.add("s", "a", "Use UTC.", [])
    assert store.has_content("s", "  use   utc. ")
    assert not store.has_content("other.skill", "Use UTC.")
    store.claim(pending.candidate_id, "approved", "alice")
    assert store.has_content("s", "use utc.")
    rejected = store.add("s", "a", "Rejected idea", [])
    store.claim(rejected.candidate_id, "rejected", "alice")
    assert not store.has_content("s", "Rejected idea")


def test_list_filters_by_status_and_orders_by_creation(store):
    first = store.add("s", "a", "one", [])
    second = store.add("s", "a", "two", [])
    store.claim(first.candidate_id, "rejected", "alice")
    assert [c.content for c in store.list("pending")] == ["two"]
    assert [c.content for c in store.list("rejected")] == ["one"]
    assert [c.content for c in store.list(None)] == ["one", "two"]
    assert second.candidate_id in {c.candidate_id for c in store.list(None)}


def test_data_survives_reopening(tmp_path):
    path = str(tmp_path / "lessons.db")
    LessonStore(path).add("s", "a", "kept", ["e1"])
    reopened = LessonStore(path)
    assert [c.content for c in reopened.list()] == ["kept"]
    assert reopened.used_event_ids() == {"e1"}
