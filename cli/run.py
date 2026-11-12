import json
import os
import sys
from uuid import uuid4

import click

from agents.vega.pipeline import run_vega_pipeline
from core.contracts import TaskContract


@click.group()
def galaxz():
    pass


@galaxz.command()
@click.option("--input", "input_path", required=True, help="Path to requirements file")
@click.option("--results", default=None, help="Path to test results JSON file (optional)")
@click.option("--config", default="config/providers.yaml", help="Path to providers.yaml")
@click.option("--output", default=None, help="Path to save JSON output (optional)")
def vega(input_path, results, config, output):
    """Run the Vega QA pipeline."""
    try:
        with open(input_path) as f:
            raw_requirements = f.read()

        test_results = None
        if results is not None:
            with open(results) as f:
                test_results = json.load(f)

        result = run_vega_pipeline(
            raw_requirements=raw_requirements,
            test_results=test_results,
            config_path=config,
        )

        print(f"run_id: {result['run_id']}")
        print(f"Requirements found: {result['analyzer']['total_count']}")
        print(f"Test cases generated: {result['test_designer']['total_count']}")
        if result["bug_reporter"] is None:
            print("Bugs reported: Stage 3 skipped")
        else:
            print(f"Bugs reported: {result['bug_reporter']['total_bugs']}")

        if output is not None:
            with open(output, "w") as f:
                json.dump(result, f, indent=2, default=str)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


@galaxz.command()
@click.option("--skill",   required=True, help="Skill ID e.g. rigel.skill.code_generation")
@click.option("--payload", required=True, help="JSON string of task payload")
@click.option("--config",  default="config/providers.yaml")
@click.option("--output",  default=None, help="Path to save result JSON")
def route(skill, payload, config, output):
    """Route a task through Andromeda to the correct agent."""
    try:
        payload_dict = json.loads(payload)

        from boot import boot
        andromeda = boot(config_path=config)

        task = TaskContract(
            task_id=uuid4(),
            origin="cli",
            skill=skill,
            payload=payload_dict,
            confidence_threshold=0.65,
        )
        final_state = andromeda.route(task=task)

        print(f"task_id:        {final_state['task_id']}")
        print(f"assigned_agent: {final_state.get('assigned_agent')}")
        print(f"status:         {final_state.get('status')}")
        print(f"confidence:     {final_state.get('confidence')}")

        if output is not None:
            with open(output, "w") as f:
                json.dump(final_state, f, indent=2, default=str)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


@galaxz.group()
def catalog():
    """Browse and install agents from the local Constellation catalog."""


@catalog.command("list")
def catalog_list():
    from core.constellation.catalog import Catalog

    entries = Catalog().list()
    if not entries:
        print("No agents in the catalog.")
    for e in entries:
        installed = e["installed_version"] or "-"
        print(f"{e['agent_id']:<16} {e['version']:<8} installed={installed:<8} {e['description']}")


@catalog.command("install")
@click.argument("agent_id")
@click.option("--version", default=None, help="Version to install (default: latest)")
@click.option("--force", is_flag=True, help="Overwrite an existing, different config/agents file")
def catalog_install(agent_id, version, force):
    """Install AGENT_ID into config/agents/ (takes effect after a restart)."""
    from core.constellation.catalog import Catalog, CatalogError

    try:
        result = Catalog().install(agent_id, version=version, force=force)
    except CatalogError as e:
        print(f"Error: {e}")
        sys.exit(1)
    print(f"{result['status']}: {result['agent_id']} {result['version']}")
    if result["restart_required"]:
        print("Restart Galaxz to load the new agent.")


if __name__ == "__main__":
    galaxz()


@galaxz.group()
def scorecard():
    """Signed Orion scorecards."""


@scorecard.command("keygen")
@click.option("--out", "out_path", default="scorecard-signing-key.pem", help="Where to write the private key (PEM)")
def scorecard_keygen(out_path):
    """Create an Ed25519 signing key. Point GALAXZ_SCORECARD_KEY_PATH at the file."""
    import os

    from core.scorecards import ScorecardSigner, generate_private_key_pem

    pem = generate_private_key_pem()
    try:
        fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise click.ClickException(f"{out_path} already exists; refusing to overwrite a key")
    with os.fdopen(fd, "w") as f:
        f.write(pem)
    signer = ScorecardSigner.from_pem(pem)
    click.echo(f"private key written to {out_path} (keep it secret)")
    click.echo(f"kid: {signer.kid}")
    click.echo(f"public key: {signer.public_key_b64}")


@scorecard.command("verify")
@click.argument("envelope_path")
@click.option("--public-key", required=True, help="Base64url raw Ed25519 public key (from /scorecards/key)")
def scorecard_verify(envelope_path, public_key):
    """Verify a signed scorecard envelope (a file holding one envelope as JSON)."""
    from core.scorecards import ScorecardError, verify_envelope

    with open(envelope_path) as f:
        envelope = json.load(f)
    try:
        card = verify_envelope(envelope, public_key)
    except ScorecardError as exc:
        raise click.ClickException(f"INVALID: {exc}")
    subject = card.get("subject", {})
    click.echo(f"VALID: {card.get('issuer')} attests {subject.get('agent_id')} / {subject.get('skill_id')}")
    click.echo(json.dumps(card.get("metrics", {}), indent=2))


@galaxz.group()
def audit():
    """Tamper-evident audit log."""


@audit.command("verify")
def audit_verify():
    """Verify the audit hash chain. Exits 1 if it has been altered."""
    from core.security.audit import default_audit_log

    result = default_audit_log().verify_chain()
    if result["valid"]:
        click.echo(f"audit chain valid: {result['events']} event(s), head {result['head']}")
        return
    click.echo(f"audit chain BROKEN at sequence {result['broken_at']} ({result['events']} valid event(s) before it)")
    sys.exit(1)


@galaxz.group()
def secret():
    """Encrypted secret references for tool skills."""


@secret.command("put")
@click.option("--skill", required=True, help="The only skill allowed to use this secret, e.g. quasar.github.create_issue")
@click.option("--repository", default="default", show_default=True, help="Repository the secret is bound to")
@click.option("--task", default="*", show_default=True, help="Task id, or * for any task")
@click.option("--organization", "organization_id", default=None, help="Organization the secret belongs to (default: GALAXZ_ORGANIZATION_ID or 'default')")
def secret_put(skill, repository, task, organization_id):
    """Store a secret (value from stdin or a hidden prompt) and print its reference."""
    from core.secrets import SecretScope
    from core.secrets.resolver import SECRET_SKILL_PREFIXES, configured_organization_id, open_default_store

    if not skill.startswith(SECRET_SKILL_PREFIXES):
        raise click.ClickException(f"secrets can only be bound to skills starting with {', '.join(SECRET_SKILL_PREFIXES)}")
    value = click.get_text_stream("stdin").read() if not sys.stdin.isatty() else click.prompt("Secret value", hide_input=True)
    value = value.rstrip("\r\n")
    if not value:
        raise click.ClickException("secret value must not be empty")
    try:
        store = open_default_store()
    except (RuntimeError, ValueError) as exc:
        raise click.ClickException(f"{exc}. Set GALAXZ_SECRETS_KEY to a Fernet key.")
    organization = organization_id or configured_organization_id()
    reference = store.put(value, SecretScope(organization, repository, task, skill))
    from core.security.audit import audit_event

    audit_event(
        "cli", "secret.put", "created",
        secret_id=reference["secret_id"], skill=skill, repository=repository, task=task, organization_id=organization,
    )
    click.echo("Use this as the whole value of a string in a task payload:", err=True)
    click.echo(f"${{{{ secrets.{reference['secret_id']} }}}}")


@galaxz.group()
def admin():
    """Manage users and API tokens (run on the host or inside the galaxz container)."""


def _accounts():
    from core.accounts import AccountError, get_account_store
    from core.security.audit import audit_event

    return get_account_store(), AccountError, audit_event


@admin.command("org-create")
@click.argument("organization_id")
@click.option("--name", default="", help="Display name")
def admin_org_create(organization_id, name):
    """Create an organization (a tenant). Its users see only its own data."""
    store, AccountError, audit_event = _accounts()
    try:
        store.create_organization(organization_id, name)
    except AccountError as exc:
        raise click.ClickException(str(exc))
    audit_event("cli", "admin.org.create", "created", organization_id=organization_id)
    click.echo(f"created organization {organization_id}")


@admin.command("org-list")
def admin_org_list():
    store, _, _ = _accounts()
    for organization in store.list_organizations():
        click.echo(f"{organization['id']}\t{organization['name']}")


@admin.command("user-create")
@click.argument("email")
@click.option("--role", required=True, help="viewer, operator, reviewer or admin")
@click.option("--name", "display_name", default="", help="Display name")
@click.option("--organization", "organization_id", default="default", help="Organization id (see org-create)")
def admin_user_create(email, role, display_name, organization_id):
    store, AccountError, audit_event = _accounts()
    if organization_id != "default" and not store.organization_exists(organization_id):
        raise click.ClickException(f"unknown organization {organization_id}; create it with: galaxz admin org-create {organization_id}")
    if not os.environ.get("GALAXZ_API_KEY") and not store.has_users():
        click.echo(
            "warning: this is the first user and GALAXZ_API_KEY is not set. Authentication becomes required now; "
            "Prism (which sends GALAXZ_API_KEY) will get 401 until you set GALAXZ_API_KEY.",
            err=True,
        )
    try:
        user = store.create_user(email, role, display_name=display_name, organization_id=organization_id)
    except AccountError as exc:
        raise click.ClickException(str(exc))
    audit_event("cli", "admin.user.create", "created", email=user.email, role=user.role, organization_id=user.organization_id)
    click.echo(f"created {user.email} ({user.role}) in organization {user.organization_id}")


@admin.command("user-list")
def admin_user_list():
    store, _, _ = _accounts()
    for user in store.list_users():
        click.echo(f"{user.email}\t{user.role}\t{'active' if user.active else 'inactive'}\t{user.organization_id}")


@admin.command("user-deactivate")
@click.argument("email")
def admin_user_deactivate(email):
    store, AccountError, audit_event = _accounts()
    try:
        store.deactivate_user(email)
    except AccountError as exc:
        raise click.ClickException(str(exc))
    audit_event("cli", "admin.user.deactivate", "deactivated", email=email.strip().lower())
    click.echo(f"deactivated {email.strip().lower()}; their tokens no longer work")


@admin.command("token-create")
@click.argument("email")
@click.option("--role", default=None, help="Defaults to the user's role; may only be lowered")
@click.option("--ttl-days", type=click.IntRange(min=1), default=None, help="Expire after this many days")
def admin_token_create(email, role, ttl_days):
    """Create an API token. It is printed once and cannot be recovered."""
    store, AccountError, audit_event = _accounts()
    try:
        token, record = store.create_token(email, role=role, ttl_days=ttl_days)
    except AccountError as exc:
        raise click.ClickException(str(exc))
    audit_event("cli", "admin.token.create", "created", email=email.strip().lower(), role=record["role"],
                token_id=record["id"], prefix=record["prefix"], expires_at=record["expires_at"])
    click.echo(f"token id {record['id']}; shown once, store it now:", err=True)
    click.echo(token)


@admin.command("token-revoke")
@click.argument("token_id")
def admin_token_revoke(token_id):
    store, AccountError, audit_event = _accounts()
    try:
        store.revoke_token(token_id)
    except AccountError as exc:
        raise click.ClickException(str(exc))
    audit_event("cli", "admin.token.revoke", "revoked", token_id=token_id)
    click.echo(f"revoked {token_id}")
