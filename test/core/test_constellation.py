from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from cli.run import galaxz
from core.constellation.catalog import Catalog, CatalogConflict, CatalogError


def _package(root: Path, agent_id="demo", version="0.1.0", **overrides):
    cfg = {
        "agent_id": agent_id,
        "agent_name": "Demo",
        "version": version,
        "catalog": {"description": "A demo agent", "tags": ["demo"]},
        "skills": [
            {
                "skill_id": f"{agent_id}.skill.hello",
                "description": "Say hello",
                "steps": [{"user": "Say hello to {name}"}],
            }
        ],
    }
    cfg.update(overrides)
    folder = root / agent_id / version
    folder.mkdir(parents=True)
    (folder / "agent.yaml").write_text(yaml.safe_dump(cfg))
    return cfg


@pytest.fixture
def dirs(tmp_path):
    catalog, agents = tmp_path / "catalog", tmp_path / "agents"
    catalog.mkdir()
    agents.mkdir()
    return catalog, agents


def test_list_returns_latest_version_and_metadata(dirs):
    catalog, agents = dirs
    _package(catalog, version="0.1.0")
    _package(catalog, version="0.10.0")
    _package(catalog, version="0.2.0")
    [entry] = Catalog(catalog, agents).list()
    assert entry["agent_id"] == "demo"
    assert entry["version"] == "0.10.0"  # numeric, not lexicographic
    assert entry["versions"] == ["0.1.0", "0.2.0", "0.10.0"]
    assert entry["description"] == "A demo agent"
    assert entry["tags"] == ["demo"]
    assert entry["skills"] == ["demo.skill.hello"]
    assert entry["installed_version"] is None


def test_install_copies_and_reports_installed(dirs):
    catalog, agents = dirs
    _package(catalog)
    result = Catalog(catalog, agents).install("demo")
    assert result == {"agent_id": "demo", "version": "0.1.0", "status": "installed", "restart_required": True}
    assert yaml.safe_load((agents / "demo.yaml").read_text())["agent_id"] == "demo"
    assert Catalog(catalog, agents).list()[0]["installed_version"] == "0.1.0"


def test_install_is_idempotent_and_guards_overwrite(dirs):
    catalog, agents = dirs
    _package(catalog, version="0.1.0")
    c = Catalog(catalog, agents)
    c.install("demo")
    assert c.install("demo")["status"] == "unchanged"
    _package(catalog, version="0.2.0")
    with pytest.raises(CatalogConflict):
        c.install("demo", version="0.2.0")
    assert c.install("demo", version="0.2.0", force=True)["status"] == "installed"
    assert yaml.safe_load((agents / "demo.yaml").read_text())["version"] == "0.2.0"


def test_hand_written_agent_not_overwritten_without_force(dirs):
    catalog, agents = dirs
    _package(catalog)
    (agents / "demo.yaml").write_text("agent_id: demo\nagent_name: Mine\nskills: []\n")
    with pytest.raises(CatalogConflict):
        Catalog(catalog, agents).install("demo")
    assert "Mine" in (agents / "demo.yaml").read_text()


@pytest.mark.parametrize("agent_id", ["rigel", "vega", "quasar", "wormhole", "andromeda"])
def test_reserved_agent_ids_rejected(dirs, agent_id):
    catalog, agents = dirs
    _package(catalog, agent_id=agent_id)
    with pytest.raises(CatalogError, match="reserved"):
        Catalog(catalog, agents).install(agent_id)
    assert not (agents / f"{agent_id}.yaml").exists()


def test_invalid_packages_are_skipped_in_list_and_rejected_on_install(dirs):
    catalog, agents = dirs
    _package(catalog, agent_id="good")
    _package(catalog, agent_id="badskill", skills=[{"skill_id": "rigel.skill.code_generation", "description": "x", "steps": [{"user": "y"}]}])
    _package(catalog, agent_id="nosteps", skills=[{"skill_id": "nosteps.skill.a", "description": "x", "steps": []}])
    c = Catalog(catalog, agents)
    assert [e["agent_id"] for e in c.list()] == ["good"]
    for bad in ("badskill", "nosteps"):
        with pytest.raises(CatalogError):
            c.install(bad)


def test_mismatched_id_or_version_rejected(dirs):
    catalog, agents = dirs
    folder = catalog / "demo" / "0.1.0"
    folder.mkdir(parents=True)
    (folder / "agent.yaml").write_text(
        yaml.safe_dump({"agent_id": "other", "agent_name": "x", "version": "0.1.0",
                        "skills": [{"skill_id": "other.skill.a", "description": "d", "steps": [{"user": "u"}]}]})
    )
    with pytest.raises(CatalogError, match="agent_id"):
        Catalog(catalog, agents).install("demo")


@pytest.mark.parametrize("bad", ["../etc", "Demo", "a/b", ""])
def test_install_rejects_unsafe_ids(dirs, bad):
    catalog, agents = dirs
    with pytest.raises(CatalogError):
        Catalog(catalog, agents).install(bad)


def test_unknown_agent_or_version(dirs):
    catalog, agents = dirs
    _package(catalog)
    with pytest.raises(CatalogError, match="not found"):
        Catalog(catalog, agents).install("missing")
    with pytest.raises(CatalogError, match="not found"):
        Catalog(catalog, agents).install("demo", version="9.9.9")
    with pytest.raises(CatalogError, match="version"):
        Catalog(catalog, agents).install("demo", version="../x")


def test_shipped_example_package_is_valid_and_loadable(tmp_path):
    repo_catalog = Path(__file__).parents[2] / "catalog"
    agents = tmp_path / "agents"
    agents.mkdir()
    c = Catalog(repo_catalog, agents)
    assert "summarizer" in [e["agent_id"] for e in c.list()]
    c.install("summarizer")
    cfg = yaml.safe_load((agents / "summarizer.yaml").read_text())
    from core.agent_loader import GenericLLMAgent
    from core.pulsar.registry import PulsarRegistry
    agent = GenericLLMAgent(cfg, PulsarRegistry(db_path=str(tmp_path / "p.db")), "config/providers.yaml")
    assert agent.AGENT_ID == "summarizer"


def test_cli_list_and_install(dirs, monkeypatch):
    catalog, agents = dirs
    _package(catalog)
    monkeypatch.setenv("GALAXZ_CATALOG_DIR", str(catalog))
    monkeypatch.setenv("GALAXZ_AGENTS_DIR", str(agents))
    runner = CliRunner()
    out = runner.invoke(galaxz, ["catalog", "list"])
    assert out.exit_code == 0 and "demo" in out.output and "0.1.0" in out.output
    out = runner.invoke(galaxz, ["catalog", "install", "demo"])
    assert out.exit_code == 0 and "installed" in out.output and "restart" in out.output.lower()
    assert (agents / "demo.yaml").exists()
    out = runner.invoke(galaxz, ["catalog", "install", "rigel"])
    assert out.exit_code == 1
