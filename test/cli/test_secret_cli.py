import sqlite3

from click.testing import CliRunner
from cryptography.fernet import Fernet

from cli.run import galaxz
from core.secrets import SecretScope
from core.secrets.resolver import SecretResolver

SKILL = "quasar.github.create_issue"


def _env(tmp_path, monkeypatch, key=True):
    monkeypatch.setenv("GALAXZ_SECRETS_DB", str(tmp_path / "secrets.db"))
    monkeypatch.setenv("GALAXZ_ORGANIZATION_ID", "org-1")
    if key:
        monkeypatch.setenv("GALAXZ_SECRETS_KEY", Fernet.generate_key().decode())
    else:
        monkeypatch.delenv("GALAXZ_SECRETS_KEY", raising=False)


def _put(*args, value="tok-abc\n"):
    return CliRunner().invoke(galaxz, ["secret", "put", *args], input=value)


def test_put_stores_an_encrypted_scoped_secret_and_prints_only_the_reference(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    result = _put("--skill", SKILL, "--repository", "repo-1")
    assert result.exit_code == 0, result.output
    assert "tok-abc" not in result.output
    reference = result.output.strip().splitlines()[-1]
    assert reference.startswith("${{ secrets.") and reference.endswith(" }}")

    resolved, values = SecretResolver().resolve(
        {"t": reference}, skill_id=SKILL, repository_id="repo-1", task_id="any-task"
    )
    assert resolved == {"t": "tok-abc"} and values == ["tok-abc"]
    assert "tok-abc" not in str(sqlite3.connect(tmp_path / "secrets.db").execute(
        "SELECT * FROM secret_references").fetchall())


def test_put_rejects_skills_that_cannot_receive_secrets(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    result = _put("--skill", "rigel.skill.code_generation")
    assert result.exit_code != 0 and "quasar." in result.output
    assert not (tmp_path / "secrets.db").exists()


def test_put_without_a_key_explains_how_to_configure_one(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, key=False)
    result = _put("--skill", SKILL)
    assert result.exit_code != 0 and "GALAXZ_SECRETS_KEY" in result.output


def test_put_rejects_an_empty_value(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    result = _put("--skill", SKILL, value="\n")
    assert result.exit_code != 0 and "empty" in result.output


def test_put_is_audited_without_the_value(tmp_path, monkeypatch):
    from core.security.audit import default_audit_log

    _env(tmp_path, monkeypatch)
    result = _put("--skill", SKILL, "--repository", "repo-1")
    assert result.exit_code == 0
    [event] = [item["event"] for item in default_audit_log().export()]
    assert event["action"] == "secret.put" and event["actor"] == "cli" and event["reason"] == "created"
    assert event["extra"]["skill"] == SKILL and event["extra"]["repository"] == "repo-1"
    assert event["extra"]["organization_id"] == "org-1"
    assert "tok-abc" not in str(event) and event["extra"]["secret_id"] in result.output
