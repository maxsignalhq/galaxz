import json
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
