# Skill Access Control — Design

Date: 2026-10-04

## Problem
Any caller can route a task to any registered skill. Per-agent auth is deferred
to v2 (ADR-001), but agents have no way to declare who may use a skill.

## Design
- `SkillDefinition.allowed_origins: list[str] | None` (contract change).
  `None` = open (all existing manifests unchanged); a list holds `fnmatch`
  patterns matched against `TaskContract.origin` (e.g. `ops`, `goal:*`);
  `[]` denies every origin. `SkillDefinition.permits(origin)` implements it.
- `PulsarRegistry.get_agents_for_skill(skill_id, origin=None)` returns only agents
  whose skill permits `origin`; `origin=None` keeps the old unfiltered behavior.
- `AndromedaState.origin` carries `task.origin` into the graph; the weighted
  skill-match node filters by it. If agents offer the skill but none permit the
  origin, the result is `status="no_agent_found"`,
  `failure_reason="origin_not_allowed"`. Reusing `no_agent_found` means the
  goal runner, coordinator and graph already treat it as a hard failure.
- Persistence needs no migration: manifests are stored as JSON.

## Limits
Origin is a caller-supplied string, so this is policy, not authentication; it
becomes enforceable once per-agent/user auth exists (v2). The unused
`nodes.make_skill_match_node` is not updated.
