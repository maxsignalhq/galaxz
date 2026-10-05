# Constellation (agent catalog) — Design

Date: 2026-10-04 · A local catalog; a hosted marketplace and certification stay v2+.

## Problem
Adding an agent means hand-copying YAML into `config/agents/`. There is no way to
discover, version or install shareable agents.

## Design
No new runtime contract: a package *is* the existing declarative YAML agent
(`core/agent_loader.py`), which contains prompts and no code.

- Layout: `catalog/<agent_id>/<version>/agent.yaml`, version `MAJOR.MINOR.PATCH`.
  The file may carry an optional `catalog:` block (`description`, `author`,
  `tags`) that the loader ignores. The index is derived by scanning the
  directory, so it cannot drift from the packages.
- `core/constellation/catalog.py` `Catalog(catalog_dir, agents_dir)`:
  - `list()` → one entry per agent (latest version, all versions, skills,
    `installed_version`). Invalid packages are logged and skipped.
  - `install(agent_id, version=None, force=False)` validates, then copies to
    `config/agents/<agent_id>.yaml` atomically. Identical content is a no-op; a
    different existing file needs `force`.
- Validation: `agent_id` matches the directory and `^[a-z][a-z0-9_]*$`; file
  `version` matches the directory; `agent_name`, non-empty `skills`, each with
  `skill_id` prefixed `<agent_id>.skill.`, `description`, and `steps` with a
  `user` template. `agent_id` must not be a built-in (`rigel`, `vega`,
  `andromeda`, `pulsar`, `orion`, `aether`, `quasar`), so a package cannot
  replace core agents.
- Surfaces: CLI `galaxz catalog list|install`; API `GET /catalog`,
  `POST /catalog/{agent_id}/install` (`version`, `force`); Prism page `/catalog`.
- Ships one example package, `catalog/summarizer/0.1.0`.

## Limits
- Installing writes config only. Agents load at boot, so install responds with
  `restart_required: true`.
- No signatures, checksums, remote index or uninstall; a package is trusted as
  much as any file you drop into `config/agents/`. Prompts can still steer an
  LLM, so review packages before installing.
- API install is behind the existing API key; any key holder can install.
