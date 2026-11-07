import pytest

from agents.rigel.confidence import _self_critique
from agents.vega.agent import VegaAgent
from core.llm.provider import LLMQuotaError
from core.pulsar.registry import PulsarRegistry


def _raise_quota(**kwargs):
    raise LLMQuotaError("LLM quota exhausted: 429")


def test_vega_does_not_turn_a_quota_error_into_canned_output(tmp_path, monkeypatch):
    agent = VegaAgent(PulsarRegistry(db_path=str(tmp_path / "p.db")))
    monkeypatch.setattr("agents.vega.agent.run_vega_pipeline", _raise_quota)
    with pytest.raises(LLMQuotaError):
        agent.run("vega.skill.requirements_to_test_cases", {"raw_requirements": "users can log in"})


def test_rigel_self_critique_does_not_swallow_quota_error():
    with pytest.raises(LLMQuotaError):
        _self_critique("rigel.skill.code_generation", {}, {"code": "x"}, _raise_quota)
