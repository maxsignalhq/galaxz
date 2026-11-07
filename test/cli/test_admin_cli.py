from click.testing import CliRunner

from cli.run import galaxz
from core.accounts import get_account_store
from core.security.audit import default_audit_log


def _run(*args):
    return CliRunner().invoke(galaxz, ["admin", *args])


def test_user_create_and_list():
    result = _run("user-create", "Alice@Example.com", "--role", "operator", "--name", "Alice")
    assert result.exit_code == 0, result.output
    assert "alice@example.com" in result.output and "operator" in result.output
    listing = _run("user-list")
    assert listing.exit_code == 0 and "alice@example.com" in listing.output and "operator" in listing.output


def test_user_create_rejects_bad_role_and_duplicates():
    assert _run("user-create", "a@x.io", "--role", "root").exit_code != 0
    assert _run("user-create", "a@x.io", "--role", "admin").exit_code == 0
    again = _run("user-create", "a@x.io", "--role", "admin")
    assert again.exit_code != 0 and "already exists" in again.output


def test_token_create_prints_a_working_token_once():
    _run("user-create", "a@x.io", "--role", "reviewer")
    result = _run("token-create", "a@x.io", "--ttl-days", "30")
    assert result.exit_code == 0, result.output
    token = result.output.strip().splitlines()[-1]
    assert token.startswith("gzt_")
    principal = get_account_store().authenticate(token)
    assert principal.id == "user:a@x.io" and principal.role == "reviewer"


def test_token_create_cannot_escalate_and_unknown_user_fails():
    _run("user-create", "op@x.io", "--role", "operator")
    assert _run("token-create", "op@x.io", "--role", "admin").exit_code != 0
    assert _run("token-create", "ghost@x.io").exit_code != 0


def test_token_revoke_and_user_deactivate():
    _run("user-create", "a@x.io", "--role", "operator")
    token_out = _run("token-create", "a@x.io").output.strip().splitlines()
    token = token_out[-1]
    token_id = get_account_store().list_tokens("a@x.io")[0]["id"]
    assert _run("token-revoke", token_id).exit_code == 0
    assert get_account_store().authenticate(token) is None
    other = _run("token-create", "a@x.io").output.strip().splitlines()[-1]
    assert _run("user-deactivate", "a@x.io").exit_code == 0
    assert get_account_store().authenticate(other) is None


def test_admin_actions_are_audited_without_the_token():
    _run("user-create", "a@x.io", "--role", "admin")
    token = _run("token-create", "a@x.io").output.strip().splitlines()[-1]
    events = [e["event"] for e in default_audit_log().export()]
    assert [e["action"] for e in events] == ["admin.user.create", "admin.token.create"]
    assert all(e["actor"] == "cli" for e in events)
    assert events[1]["extra"]["email"] == "a@x.io" and events[1]["extra"]["role"] == "admin"
    assert token not in str(events)
