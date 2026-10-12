from types import SimpleNamespace

import pytest

from core.contracts import GoalContract, TaskContract
from core.goals import GoalStore
from core.goals.executor import make_goal_executor
from core.llm import provider
from core.llm.provider import ProviderConfig, call_llm

PRIMARY = ProviderConfig(provider="openai", model="primary")
BACKUP = ProviderConfig(provider="openai", model="backup")


class _Token:
    def raise_if_cancelled(self):
        pass


def _llm(monkeypatch, seen):
    def completion(**kw):
        seen.append(kw["model"])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=6, completion_tokens=4),
        )

    monkeypatch.setattr(provider.litellm, "completion", completion)


def _route(task):
    call_llm([{"role": "user", "content": "hi"}], PRIMARY)
    return {"status": "complete", "confidence": 0.9}


def _setup(tmp_path):
    store = GoalStore(str(tmp_path / "g.db"))
    goal = GoalContract(origin="t", objective="x", confidence_threshold=0.65)
    store.create_goal(goal)
    task = TaskContract(
        origin=f"goal:{goal.goal_id}", skill="s", payload={}, confidence_threshold=0.65
    )
    return store, goal, task


def test_non_goal_origin_passes_through(tmp_path, monkeypatch):
    _llm(monkeypatch, [])
    store, _, _ = _setup(tmp_path)
    task = TaskContract(origin="api", skill="s", payload={}, confidence_threshold=0.65)
    result = make_goal_executor(_route, store, BACKUP)(task, _Token())
    assert result == {"status": "complete", "confidence": 0.9}


def test_tokens_persisted_and_tier_primary(tmp_path, monkeypatch):
    seen = []
    _llm(monkeypatch, seen)
    store, goal, task = _setup(tmp_path)
    result = make_goal_executor(_route, store, BACKUP)(task, _Token())
    assert result["model_tier"] == "primary"
    assert seen == ["openai/primary"]
    assert store.get_goal(goal.goal_id).tokens_used == 10


def test_fallback_used_routes_to_fallback_model(tmp_path, monkeypatch):
    seen = []
    _llm(monkeypatch, seen)
    store, goal, task = _setup(tmp_path)
    store.set_fallback_used(goal.goal_id, True)
    result = make_goal_executor(_route, store, BACKUP)(task, _Token())
    assert result["model_tier"] == "fallback"
    assert seen == ["openai/backup"]


def test_fallback_flag_without_configured_fallback_stays_primary(tmp_path, monkeypatch):
    seen = []
    _llm(monkeypatch, seen)
    store, goal, task = _setup(tmp_path)
    store.set_fallback_used(goal.goal_id, True)
    result = make_goal_executor(_route, store, None)(task, _Token())
    assert result["model_tier"] == "primary"
    assert seen == ["openai/primary"]


def test_tokens_persisted_even_when_route_raises(tmp_path, monkeypatch):
    _llm(monkeypatch, [])
    store, goal, task = _setup(tmp_path)

    def failing(task):
        call_llm([{"role": "user", "content": "hi"}], PRIMARY)
        raise RuntimeError("after the call")

    with pytest.raises(RuntimeError):
        make_goal_executor(failing, store, BACKUP)(task, _Token())
    assert store.get_goal(goal.goal_id).tokens_used == 10
