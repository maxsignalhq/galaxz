import json
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from langgraph.graph import END, StateGraph

from agents.andromeda.nodes import (
    make_assign_node,
    make_escalate_node,
    make_handle_failure_node,
    make_load_check_node,
)
from agents.andromeda.review_queue import ReviewQueue
from agents.andromeda.state import AndromedaState
from agents.andromeda.task_log import TaskLog
from agents.rigel.agent import RigelAgent
from agents.vega.agent import VegaAgent
from core.artifacts.store import ArtifactStore
from core.contracts import TaskContract
from core.pulsar.registry import PulsarRegistry
from orion.core.weights_loader import RoutingWeightsLoader
from workspace.config import load_workspace_config


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setLevel(logging.INFO)
    _handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    logger.addHandler(_handler)
ROUTING_WEIGHTS_PATH = Path("orion/config/routing_weights.yaml")


def _after_skill_match(state: AndromedaState) -> str:
    if state.get("matched_agents"):
        return "load_check"
    if state.get("status") == "no_agent_found":
        return "no_agent_found"
    return "escalate"


def _after_load_check(state: AndromedaState) -> str:
    if state.get("assigned_agent"):
        return "assign"
    if state.get("status") == "no_agent_found":
        return "no_agent_found"
    return "escalate"


def _make_after_execute(completion_threshold: float, failure_threshold: float):
    def _after_execute(state: AndromedaState) -> str:
        confidence = state.get("confidence") or 0.0
        # A caller-supplied TaskContract.confidence_threshold overrides the agent's
        # global default completion threshold; the failure threshold stays global.
        threshold = state.get("confidence_threshold")
        if threshold is None:
            threshold = completion_threshold
        if state.get("status") == "failed":
            return "escalate"
        if confidence >= threshold:
            return "complete"
        if confidence >= failure_threshold:
            return "handle_failure"
        return "escalate"
    return _after_execute


def _after_handle_failure(state: AndromedaState) -> str:
    if state.get("status") == "routing":
        return "skill_match"
    return "escalate"


def _complete_node(state: AndromedaState) -> dict:
    return {
        "status": "complete",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


def _no_agent_found_node(state: AndromedaState) -> dict:
    return {
        "status": "no_agent_found",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "failure_reason": state.get("failure_reason", "no_agent_found"),
    }


def _make_weighted_skill_match_node(
    registry: PulsarRegistry,
    weights_loader: RoutingWeightsLoader,
):
    def skill_match_node(state: AndromedaState) -> dict:
        required = state["required_skills"]
        agent_sets = []
        weighted_scores: dict[str, float] = {}
        has_seed_weights = False

        for skill_id in required:
            matches = registry.get_agents_for_skill(skill_id)
            agent_ids = {agent.agent_id for agent in matches}
            agent_sets.append(agent_ids)

            weights = weights_loader.get_weights(skill_id)
            if weights:
                has_seed_weights = True
                for agent_id in agent_ids:
                    weighted_scores[agent_id] = weighted_scores.get(agent_id, 0.0) + weights.get(agent_id, 0.0)

        if not agent_sets:
            capable = set()
        else:
            capable = agent_sets[0].intersection(*agent_sets[1:])

        if not capable:
            return {
                "matched_agents": [],
                "status": "no_agent_found",
                "failure_reason": "no_skill_match",
            }

        if has_seed_weights:
            selected_agent = max(
                sorted(capable),
                key=lambda agent_id: weighted_scores.get(agent_id, 0.0),
            )
            selected_weight = weighted_scores.get(selected_agent, 0.0) / max(len(required), 1)
            return {
                "matched_agents": [selected_agent],
                "assignment_reason": (
                    f"skill_match: selected {selected_agent} "
                    f"(routing_weight={selected_weight:.2f})"
                ),
            }

        matched = sorted(capable)
        return {
            "matched_agents": matched,
            "assignment_reason": f"skill_match: found {len(matched)} agents",
        }

    return skill_match_node


class Andromeda:
    def __init__(
        self,
        registry: PulsarRegistry,
        task_log: TaskLog,
        agents: Optional[dict[str, object]] = None,
        review_queue: Optional[ReviewQueue] = None,
        artifact_store: Optional[ArtifactStore] = None,
    ):
        self.registry = registry
        self.task_log = task_log
        self.review_queue = review_queue or ReviewQueue()
        self.artifact_store = artifact_store or ArtifactStore()
        self.routing_weights = RoutingWeightsLoader(str(ROUTING_WEIGHTS_PATH))
        self._workspace_config = load_workspace_config()
        self._routing_weights_stop = threading.Event()
        self._agents = agents or {
            "rigel": RigelAgent(registry),
            "vega": VegaAgent(registry),
        }
        self.graph = self._build_graph()
        self._start_routing_weights_poll_loop()

    def _build_graph(self):
        skill_match = _make_weighted_skill_match_node(self.registry, self.routing_weights)
        load_check = make_load_check_node(self.registry)
        assign = make_assign_node()
        handle_failure = make_handle_failure_node()
        escalate = make_escalate_node()

        rigel = self._agents.get("rigel")
        rigel_cfg = getattr(rigel, "config", None)
        after_execute = _make_after_execute(
            completion_threshold=getattr(rigel_cfg, "confidence_completion_threshold", 0.65),
            failure_threshold=getattr(rigel_cfg, "confidence_failure_threshold", 0.40),
        )

        g = StateGraph(AndromedaState)

        g.add_node("skill_match", skill_match)
        g.add_node("load_check", load_check)
        g.add_node("assign", assign)
        g.add_node("execute", self._execute_node)
        g.add_node("handle_failure", handle_failure)
        g.add_node("escalate", escalate)
        g.add_node("complete", _complete_node)
        g.add_node("no_agent_found", _no_agent_found_node)

        g.set_entry_point("skill_match")

        g.add_conditional_edges("skill_match", _after_skill_match, {
            "load_check": "load_check",
            "no_agent_found": "no_agent_found",
            "escalate": "escalate",
        })
        g.add_conditional_edges("load_check", _after_load_check, {
            "assign": "assign",
            "no_agent_found": "no_agent_found",
            "escalate": "escalate",
        })
        g.add_edge("assign", "execute")
        g.add_conditional_edges("execute", after_execute, {
            "complete": "complete",
            "handle_failure": "handle_failure",
            "escalate": "escalate",
        })
        g.add_conditional_edges("handle_failure", _after_handle_failure, {
            "skill_match": "skill_match",
            "escalate": "escalate",
        })
        g.add_edge("escalate", END)
        g.add_edge("complete", END)
        g.add_edge("no_agent_found", END)

        return g.compile()

    def _start_routing_weights_poll_loop(self) -> None:
        thread = threading.Thread(
            target=self._poll_routing_weights,
            name="andromeda-routing-weights",
            daemon=True,
        )
        thread.start()

    def _poll_routing_weights(self) -> None:
        while not self._routing_weights_stop.wait(60):
            old_version = self.routing_weights.last_version()
            try:
                self.routing_weights.reload()
            except Exception:
                logger.exception("Routing weights reload failed")
                continue

            new_version = self.routing_weights.last_version()
            if new_version != old_version:
                logger.info(
                    "Routing weights updated: v%s → v%s (source: %s)",
                    old_version,
                    new_version,
                    self.routing_weights.source,
                )

    def _execute_node(self, state: AndromedaState) -> dict:
        agent_id = state.get("assigned_agent", "")
        skill_id = state["required_skills"][0]
        payload = state.get("payload", {})
        context = {**state.get("context", {}), "task_id": state["task_id"]}

        try:
            agent = self._agents.get(agent_id)
            if agent is None:
                return {
                    "status": "failed",
                    "failure_reason": f"unknown agent: {agent_id}",
                    "confidence": 0.0,
                }
            result = agent.run(skill_id, payload, context)

            return {
                "result": result.get("result", result),
                "artifacts": result.get("artifacts", []),
                "writable": result.get("writable", False),
                "summary": result.get("summary", ""),
                "confidence": result.get("confidence", 0.80),
                "confidence_breakdown": result.get("confidence_breakdown", {}),
                "gaps": result.get("gaps", []),
                "execution_result": result.get("execution_result", None),
                "externally_calibrated": result.get("externally_calibrated", False),
                "status": "complete",
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                "status": "failed",
                "failure_reason": str(e),
                "confidence": 0.0,
            }

    def route(
        self,
        task: TaskContract | None = None,
        task_type: str | None = None,
        required_skills: list | None = None,
        payload: dict | None = None,
        context: Optional[dict] = None,
        priority: str = "NORMAL",
    ) -> AndromedaState:
        if task is None:
            if not required_skills or payload is None:
                raise ValueError("route requires a TaskContract or legacy required_skills + payload")
            task = TaskContract(
                task_id=uuid.uuid4(),
                origin="legacy_route",
                skill=required_skills[0],
                payload=payload,
                confidence_threshold=0.65,
            )

        ws = self._workspace_config
        if ws.enabled:
            task = task.model_copy(update={"workspace_root": ws.workspace_root})
            context_update = {"workspace_root": ws.workspace_root}
            if task.output_path is not None:
                context_update["output_path"] = task.output_path
            context = {**(context or {}), **context_update}

        task_type = task_type or task.skill.split(".")[-1]
        required_skills = required_skills or [task.skill]
        initial_state = AndromedaState(
            task_id=str(task.task_id),
            task_type=task_type,
            required_skills=required_skills,
            priority=priority,
            payload=task.payload,
            context=context or {},
            timeout_ms=task.deadline_ms or 30000,
            status="routing",
            issued_at=task.created_at.isoformat(),
            confidence_threshold=task.confidence_threshold,
        )

        self.task_log.write(initial_state.model_copy(update={"status": "received"}))
        final_state = self.graph.invoke(initial_state.model_dump(mode="python"))
        validated_state = AndromedaState.model_validate(final_state)
        self.task_log.write(validated_state)
        result = validated_state.model_dump(mode="python")
        # LangGraph drops unknown fields during state merge (AndromedaState has extra="forbid").
        # The full agent output is preserved in AndromedaState.result — lift passthrough fields
        # from there so they appear at the top level of the route() return dict.
        skill_output = result.get("result") if isinstance(result.get("result"), dict) else {}
        result["artifacts"] = skill_output.get("artifacts", [])
        result["writable"] = skill_output.get("writable", False)
        result["summary"] = skill_output.get("summary", "")
        result["execution_result"] = skill_output.get("execution_result")
        result["externally_calibrated"] = skill_output.get("externally_calibrated", False)
        if result["artifacts"]:
            self.artifact_store.record(
                result["artifacts"],
                workspace_root=task.workspace_root or "",
                task_id=str(task.task_id),
                skill=task.skill,
            )
        if validated_state.status == "escalated":
            sla_deadline = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            self.review_queue.enqueue(
                task_id=validated_state.task_id,
                task_type=validated_state.task_type or "",
                confidence=validated_state.confidence or 0.0,
                payload=validated_state.payload or {},
                skill_id=validated_state.required_skills[0] if validated_state.required_skills else "",
                agent_id=validated_state.assigned_agent or "",
                agent_output=validated_state.result if isinstance(validated_state.result, dict) else {},
                sla_deadline=sla_deadline,
            )
            result["review_pending"] = True
        return result
