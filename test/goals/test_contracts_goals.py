import uuid
import pytest
from pydantic import ValidationError
from core.contracts import GoalContract, ProjectNode, PlannedTask


def test_goal_contract_defaults():
    g = GoalContract(origin="test", objective="build a todo API", confidence_threshold=0.65)
    assert g.status == "planning"
    assert g.plan_confidence is None
    assert isinstance(g.goal_id, uuid.UUID)
    assert g.created_at is not None


def test_goal_contract_rejects_blank_objective():
    with pytest.raises(ValidationError):
        GoalContract(origin="test", objective="   ", confidence_threshold=0.65)


def test_goal_contract_threshold_bounds():
    with pytest.raises(ValidationError):
        GoalContract(origin="t", objective="x", confidence_threshold=1.5)


def test_planned_task_defaults():
    gid, pid = uuid.uuid4(), uuid.uuid4()
    t = PlannedTask(project_id=pid, goal_id=gid, skill="rigel.skill.code_generation", payload={"spec": "x"})
    assert t.status == "pending"
    assert t.depends_on == []
    assert t.confidence is None


def test_project_node_defaults():
    p = ProjectNode(goal_id=uuid.uuid4(), title="API layer")
    assert p.description == ""
    assert isinstance(p.project_id, uuid.UUID)
