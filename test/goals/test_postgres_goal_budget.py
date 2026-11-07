from datetime import datetime, timezone

from sqlalchemy import create_engine, text

from core.contracts import GoalContract
from core.goals.postgres_store import PostgresGoalStore

DDL = """CREATE TABLE goals (
    goal_id TEXT PRIMARY KEY, origin TEXT NOT NULL, objective TEXT NOT NULL,
    confidence_threshold REAL NOT NULL, status TEXT NOT NULL, plan_confidence REAL,
    created_at TEXT NOT NULL, token_budget INTEGER,
    tokens_used INTEGER NOT NULL DEFAULT 0, fallback_used BOOLEAN NOT NULL DEFAULT 0,
    resume_after TEXT, pause_reason TEXT, workspace_root TEXT)"""


def _store(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'pg.db'}")
    with engine.begin() as c:
        c.execute(text(DDL))
    return PostgresGoalStore("postgresql://test/test", engine=engine)


def test_round_trip_and_methods(tmp_path):
    store = _store(tmp_path)
    goal = GoalContract(origin="t", objective="x", confidence_threshold=0.65, token_budget=500)
    store.create_goal(goal)
    store.add_tokens_used(goal.goal_id, 25)
    when = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    store.pause_with_reason(goal.goal_id, "provider_quota", when)
    store.set_fallback_used(goal.goal_id, True)
    got = store.get_goal(goal.goal_id)
    assert got.token_budget == 500 and got.tokens_used == 25
    assert got.status == "paused" and got.pause_reason == "provider_quota"
    assert got.resume_after == when and got.fallback_used is True

    store.clear_pause(goal.goal_id)
    store.set_token_budget(goal.goal_id, None)
    got = store.get_goal(goal.goal_id)
    assert got.pause_reason is None and got.fallback_used is False
    assert got.token_budget is None


def test_workspace_root_round_trip(tmp_path):
    store = _store(tmp_path)
    with_root = GoalContract(origin="t", objective="x", confidence_threshold=0.65, workspace_root="/ws/a")
    without = GoalContract(origin="t", objective="y", confidence_threshold=0.65)
    store.create_goal(with_root)
    store.create_goal(without)
    assert store.get_goal(with_root.goal_id).workspace_root == "/ws/a"
    assert store.get_goal(without.goal_id).workspace_root is None
