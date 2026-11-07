from __future__ import annotations

from typing import Callable
from uuid import UUID

from core.contracts import TaskContract
from core.llm.provider import ProviderConfig, UsageMeter, metered_call


def goal_id_from_origin(origin: str) -> UUID | None:
    if not origin.startswith("goal:"):
        return None
    try:
        return UUID(origin.removeprefix("goal:"))
    except ValueError:
        return None


def make_goal_executor(
    route: Callable[..., dict],
    store,
    fallback: ProviderConfig | None,
) -> Callable[[TaskContract, object], dict]:
    """Wrap ``Andromeda.route`` so goal tasks are metered and honour failover."""

    def execute(task: TaskContract, token) -> dict:
        token.raise_if_cancelled()
        goal_id = goal_id_from_origin(task.origin)
        if goal_id is None:
            result = route(task=task)
            token.raise_if_cancelled()
            return result

        goal = store.get_goal(goal_id)
        use_fallback = bool(goal is not None and goal.fallback_used and fallback is not None)
        meter = UsageMeter()
        try:
            with metered_call(meter, fallback if use_fallback else None):
                result = route(task=task)
        finally:
            if meter.tokens:
                store.add_tokens_used(goal_id, meter.tokens)
        token.raise_if_cancelled()
        return {**result, "model_tier": "fallback" if use_fallback else "primary"}

    return execute
