import json

from click.testing import CliRunner

from cli.run import galaxz


def test_help_lists_supported_commands():
    result = CliRunner().invoke(galaxz, ["--help"])

    assert result.exit_code == 0
    assert "route" in result.output
    assert "vega" in result.output


def test_vega_help_lists_required_input_and_config_options():
    result = CliRunner().invoke(galaxz, ["vega", "--help"])

    assert result.exit_code == 0
    assert "--input" in result.output
    assert "--config" in result.output


def test_route_reports_success_with_stubbed_andromeda(monkeypatch):
    class StubAndromeda:
        def route(self, task):
            return {
                "task_id": task.task_id,
                "assigned_agent": "rigel",
                "status": "complete",
                "confidence": 0.91,
            }

    monkeypatch.setattr("boot.boot", lambda config_path: StubAndromeda())
    result = CliRunner().invoke(
        galaxz,
        ["route", "--skill", "rigel.skill.code_generation", "--payload", json.dumps({"spec": "hello"})],
    )

    assert result.exit_code == 0
    assert "assigned_agent: rigel" in result.output
    assert "status:         complete" in result.output


def test_vega_reports_success_with_stubbed_pipeline(monkeypatch, tmp_path):
    requirements = tmp_path / "requirements.md"
    requirements.write_text("The API must return a health response.", encoding="utf-8")
    monkeypatch.setattr(
        "cli.run.run_vega_pipeline",
        lambda **kwargs: {
            "run_id": "run-123",
            "analyzer": {"total_count": 1},
            "test_designer": {"total_count": 2},
            "bug_reporter": None,
        },
    )

    result = CliRunner().invoke(galaxz, ["vega", "--input", str(requirements)])

    assert result.exit_code == 0
    assert "Requirements found: 1" in result.output
    assert "Test cases generated: 2" in result.output


def test_route_forwards_config_and_reports_invalid_configuration(monkeypatch, tmp_path):
    missing_config = tmp_path / "missing-providers.yaml"

    def fail_boot(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    monkeypatch.setattr("boot.boot", fail_boot)
    result = CliRunner().invoke(
        galaxz,
        [
            "route",
            "--skill",
            "rigel.skill.code_generation",
            "--payload",
            json.dumps({"spec": "hello"}),
            "--config",
            str(missing_config),
        ],
    )

    assert result.exit_code != 0
    assert f"Config file not found: {missing_config}" in result.output


def test_route_rejects_malformed_payload():
    result = CliRunner().invoke(
        galaxz,
        ["route", "--skill", "rigel.skill.code_generation", "--payload", "not-json"],
    )

    assert result.exit_code != 0
    assert "Error:" in result.output
