from datetime import datetime, timezone
from typing import Callable

from agents.andromeda.state import AndromedaState
from core.pulsar.registry import PulsarRegistry


def make_skill_match_node(registry: PulsarRegistry) -> Callable[[AndromedaState], dict]:
    def skill_match_node(state: AndromedaState) -> dict:
        required = state["required_skills"]
        agent_sets = []
        for skill_id in required:
            matches = registry.get_agents_for_skill(skill_id)
            agent_sets.append({agent.agent_id for agent in matches})

        if not agent_sets:
            capable = set()
        else:
            capable = agent_sets[0].intersection(*agent_sets[1:])

        matched = sorted(capable)

        if not matched:
            return {
                "matched_agents": [],
                "status": "no_agent_found",
                "failure_reason": "no_skill_match",
            }

        return {
            "matched_agents": matched,
            "assignment_reason": f"skill_match: found {len(matched)} agents",
        }

    return skill_match_node


def make_load_check_node(registry: PulsarRegistry) -> Callable[[AndromedaState], dict]:
    def load_check_node(state: AndromedaState) -> dict:
        matched = state["matched_agents"]
        if not matched:
            return {"status": "no_agent_found", "failure_reason": "no_agents_available"}

        prior_reason = state.get("assignment_reason", "")
        required_skills = state.get("required_skills", [])
        ranked = sorted(
            matched,
            key=lambda agent_id: _score_agent_for_skills(registry, agent_id, required_skills),
            reverse=True,
        )
        selected_agent = ranked[0]
        selected_score = _score_agent_for_skills(registry, selected_agent, required_skills)
        return {
            "assigned_agent": selected_agent,
            "assignment_reason": (
                prior_reason
                + f" -> load_check: selected {selected_agent} (avg_confidence={selected_score:.2f})"
            ),
        }

    return load_check_node


def make_assign_node() -> Callable[[AndromedaState], dict]:
    def assign_node(state: AndromedaState) -> dict:
        issued_at = state.get("issued_at") or datetime.now(timezone.utc).isoformat()
        return {"status": "assigned", "issued_at": issued_at}

    return assign_node


def make_handle_failure_node() -> Callable[[AndromedaState], dict]:
    def handle_failure_node(state: AndromedaState) -> dict:
        retry_count = state.get("retry_count", 0)
        confidence = state.get("confidence") or 0.0

        if retry_count < 1 and confidence >= 0.60:
            return {"retry_count": retry_count + 1, "status": "routing"}

        return {"escalated_to_human": True, "status": "escalated"}

    return handle_failure_node


def make_escalate_node() -> Callable[[AndromedaState], dict]:
    def escalate_node(state: AndromedaState) -> dict:
        prior_reason = state.get("assignment_reason", "")
        failure_reason = state.get("failure_reason", "unknown")
        return {
            "status": "escalated",
            "escalated_to_human": True,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "assignment_reason": prior_reason + f" → escalated: {failure_reason}",
        }

    return escalate_node


def _score_agent_for_skills(
    registry: PulsarRegistry,
    agent_id: str,
    required_skills: list[str],
) -> float:
    agent = registry.get_agent(agent_id)
    if agent is None or not agent.skills:
        return 0.0

    scores: list[float] = []
    for skill_id in required_skills:
        for skill in agent.skills:
            if skill.skill_id == skill_id:
                scores.append(skill.avg_confidence)
                break

    if not scores:
        return 0.0
    return sum(scores) / len(scores)
