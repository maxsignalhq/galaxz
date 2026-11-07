import sqlite3

import pytest
from cryptography.fernet import Fernet

from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.task_log import TaskLog
from core.artifacts.store import ArtifactStore
from core.contracts import GoalContract, SkillDefinition, SkillManifest, TaskContract
from core.goals.store import GoalStore
from core.pulsar.registry import PulsarRegistry
from core.secrets import SecretScope, SecretStore
from core.secrets.resolver import SecretResolver

SKILL = "quasar.github.create_issue"
TOKEN = "ghp_supersecret_token_value"


class Provider:
    def __init__(self, key):
        self._key = key

    def key(self):
        return self._key


class ToolAgent:
    def __init__(self, mode="echo"):
        self.mode = mode
        self.calls = []

    def run(self, skill_id, payload, context):
        self.calls.append(payload)
        if self.mode == "raise":
            raise RuntimeError(f"401 for token {payload['token']}")
        return {
            "result": {"echo": payload["token"], "nested": [f"Authorization: {payload['token']}"]},
            "artifacts": [{"filename": "out.txt", "content": f"token={payload['token']}"}],
            "confidence": 0.95,
        }


@pytest.fixture
def env(tmp_path):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    for skill in (SKILL, "fake.skill.echo"):
        registry.register(
            SkillManifest(
                agent_id=skill.split(".")[0], agent_name="A", version="1.0.0",
                skills=[SkillDefinition(skill_id=skill, description="d", input_schema={}, output_schema={})],
                health_endpoint="/health",
            )
        )
    store = SecretStore(tmp_path / "secrets.db", Provider(Fernet.generate_key()))
    return registry, store, tmp_path


def _andromeda(env, agent, *, goal_store=None, agent_id="quasar"):
    registry, store, tmp_path = env
    return Andromeda(
        registry=registry,
        task_log=TaskLog(db_path=str(tmp_path / "tasks.db")),
        agents={agent_id: agent},
        artifact_store=ArtifactStore(db_path=str(tmp_path / "artifacts.db")),
        goal_store=goal_store,
        secret_resolver=SecretResolver(lambda: store, organization_id="org-1"),
    )


def _secret(store, *, repo="default", skill=SKILL):
    secret_id = store.put(TOKEN, SecretScope("org-1", repo, "*", skill))["secret_id"]
    return "${{ secrets." + secret_id + " }}"


def _task(**kwargs):
    return TaskContract(confidence_threshold=0.65, **kwargs)


def _dump(path):
    return "\n".join(sqlite3.connect(path).iterdump())


def test_tool_receives_value_but_nothing_persisted_or_returned_contains_it(env):
    registry, store, tmp_path = env
    agent = ToolAgent()
    reference = _secret(store)
    result = _andromeda(env, agent).route(
        task=_task(origin="test", skill=SKILL, payload={"token": reference})
    )
    assert agent.calls == [{"token": TOKEN}]
    assert TOKEN not in str(result)
    assert "[REDACTED]" in str(result)
    for db in ("tasks.db", "artifacts.db"):
        assert TOKEN not in _dump(tmp_path / db)
    assert reference in _dump(tmp_path / "tasks.db")


def test_exception_text_from_the_tool_is_redacted(env):
    result = _andromeda(env, ToolAgent("raise")).route(
        task=_task(origin="test", skill=SKILL, payload={"token": _secret(env[1])})
    )
    assert result["status"] == "escalated"
    assert TOKEN not in str(result) and "[REDACTED]" in str(result)


def test_non_tool_skill_with_a_reference_fails_without_calling_the_agent(env):
    agent = ToolAgent()
    reference = _secret(env[1], skill="fake.skill.echo")
    result = _andromeda(env, agent, agent_id="fake").route(
        task=_task(origin="test", skill="fake.skill.echo", payload={"token": reference})
    )
    assert result["status"] == "escalated"
    assert result["failure_reason"] == "secret_not_permitted_for_skill"
    assert agent.calls == [] and TOKEN not in str(result)


def test_unknown_reference_fails_with_fixed_reason(env):
    agent = ToolAgent()
    result = _andromeda(env, agent).route(
        task=_task(origin="test", skill=SKILL, payload={"token": "${{ secrets.nope }}"})
    )
    assert result["status"] == "escalated"
    assert result["failure_reason"] == "secret_reference_unavailable"
    assert agent.calls == []


def test_secret_is_scoped_to_the_goals_bound_repository(env):
    registry, store, tmp_path = env
    goals = GoalStore(db_path=str(tmp_path / "goals.db"))
    goal = GoalContract(origin="test", objective="x", confidence_threshold=0.65)
    goals.create_goal(goal)
    goals.bind_repository(goal.goal_id, "repo-1", "main", "a" * 40)
    ok, other = ToolAgent(), ToolAgent()
    task = lambda ref: _task(origin=f"goal:{goal.goal_id}", skill=SKILL, payload={"token": ref})

    good = _andromeda(env, ok, goal_store=goals).route(task=task(_secret(store, repo="repo-1")))
    assert good["status"] == "complete" and ok.calls == [{"token": TOKEN}]

    bad = _andromeda(env, other, goal_store=goals).route(task=task(_secret(store, repo="other-repo")))
    assert bad["failure_reason"] == "secret_reference_unavailable" and other.calls == []


def test_payload_without_references_is_unchanged(env):
    class Plain:
        def run(self, skill_id, payload, context):
            return {"result": {"seen": payload}, "confidence": 0.95}

    result = _andromeda(env, Plain()).route(
        task=_task(origin="test", skill=SKILL, payload={"a": "b"})
    )
    assert result["status"] == "complete"
