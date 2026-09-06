import subprocess

from agents.rigel.execution import execute_generated_output


def test_no_workspace_root_uses_sandbox(monkeypatch):
    """workspace_root=None → executed_from="sandbox"."""

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr("agents.rigel.execution.subprocess.run", fake_run)

    result = execute_generated_output(
        skill_id="rigel.skill.code_generation",
        payload={"tests": "def test_x(): assert 1 == 1"},
        result={"code": "x = 1", "language": "python"},
        workspace_root=None,
    )
    assert result is not None
    assert result.executed_from == "sandbox"
    assert result.outcome == "pass"


def test_workspace_root_runs_in_disposable_sandbox(tmp_path, monkeypatch):
    """Workspace files are mounted read-only into the disposable sandbox."""
    script = tmp_path / "hello.py"
    script.write_text("print('hello')\n")
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, returncode=0, stdout="hello\n", stderr="")

    monkeypatch.setattr("agents.rigel.execution.subprocess.run", fake_run)

    result = execute_generated_output(
        skill_id="rigel.skill.code_generation",
        payload={},
        result={"code": "x=1"},
        workspace_root=str(tmp_path),
        file_path=str(script),
    )

    assert result is not None
    assert result.executed_from == "sandbox"
    assert result.outcome == "pass"
    assert result.exit_code == 0
    assert "--network" in commands[0] and commands[0][commands[0].index("--network") + 1] == "none"
    assert "--user" in commands[0] and commands[0][commands[0].index("--user") + 1] == "65534:65534"
    assert any(value.endswith(",readonly") for value in commands[0])


def test_workspace_timeout(tmp_path, monkeypatch):
    """Slow script in workspace mode → outcome="timeout"."""
    script = tmp_path / "slow.py"
    script.write_text("import time; time.sleep(10)\n")

    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"], output="", stderr="")

    monkeypatch.setattr("agents.rigel.execution.subprocess.run", _timeout)
    result = execute_generated_output(
        skill_id="rigel.skill.code_generation",
        payload={},
        result={"code": "x=1"},
        workspace_root=str(tmp_path),
        file_path=str(script),
        timeout_s=1,
    )

    assert result is not None
    assert result.outcome == "timeout"
    assert result.executed_from == "sandbox"


def test_workspace_root_set_no_file_path_returns_none():
    """workspace_root set but file_path=None → returns None."""
    result = execute_generated_output(
        skill_id="rigel.skill.code_generation",
        payload={},
        result={"code": "x=1"},
        workspace_root="/nonexistent",
        file_path=None,
    )
    assert result is None


def test_workspace_nonexistent_file_returns_error(tmp_path, monkeypatch):
    """workspace_root set + file_path does not exist → outcome="fail"."""
    monkeypatch.setattr(
        "agents.rigel.execution.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], returncode=1, stdout="", stderr="missing"),
    )
    result = execute_generated_output(
        skill_id="rigel.skill.code_generation",
        payload={"tests": "def test_x(): assert 1 == 1"},
        result={"code": "x = 1", "language": "python"},
        workspace_root=str(tmp_path),
        file_path=str(tmp_path / "nonexistent.py"),
    )
    assert result is not None
    assert result.outcome == "fail"
    assert result.executed_from == "sandbox"
