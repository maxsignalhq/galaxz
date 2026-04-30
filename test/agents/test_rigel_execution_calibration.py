import subprocess

import pytest

from agents.rigel.agent import RigelAgent
from agents.rigel.config import RigelConfig
from core.pulsar.registry import PulsarRegistry


class _FakeAether:
    def __init__(self):
        self.events = []

    def publish_event(self, stream: str, payload: dict) -> None:
        self.events.append((stream, payload))

    def close(self) -> None:
        pass


@pytest.fixture
def temp_registry(tmp_path):
    return PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))


@pytest.fixture
def rigel_codegen_llm():
    def llm(system: str, user: str) -> str:
        if "Rate whether this output fully satisfies the task" in user:
            return '{"score": 0.92, "gaps": []}'
        return "def add(a, b):\n    return a + b\n"

    return llm


def _build_agent(temp_registry, monkeypatch, llm, execution_enabled: bool = True):
    fake_aether = _FakeAether()
    monkeypatch.setattr("agents.rigel.agent.get_aether_client", lambda: fake_aether)
    agent = RigelAgent(
        temp_registry,
        rigel_config=RigelConfig(
            execution_calibration_enabled=execution_enabled,
            execution_timeout_s=30,
            _env_file=None,
        ),
    )
    agent.llm = llm
    return agent, fake_aether


def test_rigel_calibrates_confidence_from_passing_execution(
    temp_registry,
    monkeypatch,
    rigel_codegen_llm,
):
    agent, fake_aether = _build_agent(temp_registry, monkeypatch, rigel_codegen_llm)
    monkeypatch.setattr(
        "agents.rigel.execution.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="PASS test_add\n",
            stderr="",
        ),
    )

    result = agent.run(
        "rigel.skill.code_generation",
        {
            "spec": "Create a simple add function",
            "language": "python",
            "tests": "def test_add():\n    assert add(1, 2) == 3\n",
        },
    )

    assert result["confidence"] >= 0.9
    assert result["execution_result"]["exit_code"] == 0
    assert result["execution_result"]["outcome"] == "pass"
    assert result["externally_calibrated"] is True
    assert fake_aether.events[0][1]["execution_outcome"] == "pass"


def test_rigel_penalizes_failing_execution(
    temp_registry,
    monkeypatch,
    rigel_codegen_llm,
):
    agent, _ = _build_agent(temp_registry, monkeypatch, rigel_codegen_llm)
    monkeypatch.setattr(
        "agents.rigel.execution.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=1,
            stdout="",
            stderr="AssertionError",
        ),
    )

    result = agent.run(
        "rigel.skill.code_generation",
        {
            "spec": "Create a simple add function",
            "language": "python",
            "tests": "def test_add():\n    assert add(1, 2) == 3\n",
        },
    )

    assert result["confidence"] <= 0.20
    assert result["execution_result"]["outcome"] == "fail"


def test_rigel_timeout_maps_to_low_confidence(
    temp_registry,
    monkeypatch,
    rigel_codegen_llm,
):
    agent, _ = _build_agent(temp_registry, monkeypatch, rigel_codegen_llm)

    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"], output="", stderr="")

    monkeypatch.setattr("agents.rigel.execution.subprocess.run", _timeout)

    result = agent.run(
        "rigel.skill.code_generation",
        {
            "spec": "Create a simple add function",
            "language": "python",
            "tests": "def test_add():\n    assert add(1, 2) == 3\n",
        },
    )

    assert result["confidence"] == pytest.approx(0.05)
    assert result["execution_result"]["outcome"] == "timeout"


def test_rigel_uses_soft_confidence_when_execution_calibration_disabled(
    temp_registry,
    monkeypatch,
    rigel_codegen_llm,
):
    agent, _ = _build_agent(
        temp_registry,
        monkeypatch,
        rigel_codegen_llm,
        execution_enabled=False,
    )

    def _should_not_run(*args, **kwargs):
        raise AssertionError("subprocess.run should not be called when execution calibration is disabled")

    monkeypatch.setattr("agents.rigel.execution.subprocess.run", _should_not_run)

    result = agent.run(
        "rigel.skill.code_generation",
        {
            "spec": "Create a simple add function",
            "language": "python",
            "tests": "def test_add():\n    assert add(1, 2) == 3\n",
        },
    )

    assert result["confidence"] == pytest.approx(0.668)
    assert result["execution_result"] is None
    assert result["externally_calibrated"] is False


def test_rigel_falls_back_when_execution_sandbox_is_unavailable(
    temp_registry,
    monkeypatch,
    rigel_codegen_llm,
    caplog,
):
    agent, _ = _build_agent(temp_registry, monkeypatch, rigel_codegen_llm)

    def _unavailable(*args, **kwargs):
        raise FileNotFoundError("python not available")

    monkeypatch.setattr("agents.rigel.execution.subprocess.run", _unavailable)

    with caplog.at_level("WARNING"):
        result = agent.run(
            "rigel.skill.code_generation",
            {
                "spec": "Create a simple add function",
                "language": "python",
                "tests": "def test_add():\n    assert add(1, 2) == 3\n",
            },
        )

    assert result["confidence"] == pytest.approx(0.668)
    assert result["execution_result"] is None
    assert result["externally_calibrated"] is False
    assert "execution calibration unavailable" in caplog.text.lower()


def test_rigel_falls_back_when_docker_daemon_is_unavailable(
    temp_registry,
    monkeypatch,
    rigel_codegen_llm,
    caplog,
):
    agent, _ = _build_agent(temp_registry, monkeypatch, rigel_codegen_llm)

    monkeypatch.setattr(
        "agents.rigel.execution.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=1,
            stdout="",
            stderr="permission denied while trying to connect to the docker API at unix:///var/run/docker.sock",
        ),
    )

    with caplog.at_level("WARNING"):
        result = agent.run(
            "rigel.skill.code_generation",
            {
                "spec": "Create a simple add function",
                "language": "python",
                "tests": "def test_add():\n    assert add(1, 2) == 3\n",
            },
        )

    assert result["confidence"] == pytest.approx(0.668)
    assert result["execution_result"] is None
    assert result["externally_calibrated"] is False
    assert "execution calibration unavailable" in caplog.text.lower()
