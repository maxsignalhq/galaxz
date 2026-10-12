import sqlite3
from datetime import datetime, timezone
from uuid import UUID

from core.contracts import GoalContract
from core.goals import GoalStore


def _goal(**kw) -> GoalContract:
    return GoalContract(origin="t", objective="x", confidence_threshold=0.65, **kw)


def test_budget_fields_round_trip(tmp_path):
    store = GoalStore(str(tmp_path / "g.db"))
    goal = _goal(token_budget=500)
    store.create_goal(goal)
    got = store.get_goal(goal.goal_id)
    assert got.token_budget == 500
    assert got.tokens_used == 0
    assert got.fallback_used is False
    assert got.pause_reason is None and got.resume_after is None


def test_add_tokens_used_accumulates(tmp_path):
    store = GoalStore(str(tmp_path / "g.db"))
    goal = _goal()
    store.create_goal(goal)
    store.add_tokens_used(goal.goal_id, 30)
    store.add_tokens_used(goal.goal_id, 12)
    assert store.get_goal(goal.goal_id).tokens_used == 42


def test_pause_with_reason_then_clear(tmp_path):
    store = GoalStore(str(tmp_path / "g.db"))
    goal = _goal()
    store.create_goal(goal)
    when = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    store.pause_with_reason(goal.goal_id, "provider_quota", when)
    store.set_fallback_used(goal.goal_id, True)
    got = store.get_goal(goal.goal_id)
    assert got.status == "paused"
    assert got.pause_reason == "provider_quota"
    assert got.resume_after == when
    assert got.fallback_used is True

    store.clear_pause(goal.goal_id)
    got = store.get_goal(goal.goal_id)
    assert got.status == "paused"  # clear_pause does not change status
    assert got.pause_reason is None and got.resume_after is None
    assert got.fallback_used is False


def test_set_token_budget(tmp_path):
    store = GoalStore(str(tmp_path / "g.db"))
    goal = _goal(token_budget=10)
    store.create_goal(goal)
    store.set_token_budget(goal.goal_id, 99)
    assert store.get_goal(goal.goal_id).token_budget == 99
    store.set_token_budget(goal.goal_id, None)
    assert store.get_goal(goal.goal_id).token_budget is None


def test_existing_database_is_migrated(tmp_path):
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE goals (goal_id TEXT PRIMARY KEY, origin TEXT NOT NULL, "
        "objective TEXT NOT NULL, confidence_threshold REAL NOT NULL, "
        "status TEXT NOT NULL, plan_confidence REAL, created_at TEXT NOT NULL)"
    )
    gid = "11111111-1111-1111-1111-111111111111"
    conn.execute(
        "INSERT INTO goals VALUES (?, 'o', 'obj', 0.65, 'running', NULL, "
        "'2026-01-01T00:00:00+00:00')",
        (gid,),
    )
    conn.commit()
    conn.close()

    store = GoalStore(path)
    got = store.get_goal(UUID(gid))
    assert got.token_budget is None
    assert got.tokens_used == 0
    assert got.fallback_used is False
    # the new columns must exist on the migrated row, not just default in Python
    store.add_tokens_used(UUID(gid), 5)
    store.set_token_budget(UUID(gid), 50)
    got = store.get_goal(UUID(gid))
    assert (got.tokens_used, got.token_budget) == (5, 50)


def test_goal_tree_exposes_budget_fields(tmp_path):
    store = GoalStore(str(tmp_path / "g.db"))
    goal = _goal(token_budget=250)
    store.create_goal(goal)
    store.add_tokens_used(goal.goal_id, 7)
    tree = store.goal_tree(goal.goal_id)["goal"]
    assert tree["token_budget"] == 250
    assert tree["tokens_used"] == 7
    assert tree["fallback_used"] is False
    assert tree["pause_reason"] is None
    assert tree["resume_after"] is None
