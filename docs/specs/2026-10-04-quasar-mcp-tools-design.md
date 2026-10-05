# Quasar (MCP tool manager) — Design

Date: 2026-10-04

## Problem
Galaxz agents cannot use external tools. MCP is the common way to expose them,
but there is no MCP client, and any integration must still honor the contracts:
every tool call is a routed `TaskContract`, every output carries a confidence.

## Design
No new contract. Each MCP tool becomes a normal Pulsar skill on one agent:

- `config/mcp.yaml` lists servers (`name`, `command`, optional `env`,
  `timeout_s`, `allowed_origins`). The shipped file has `servers: []`, so
  default behavior is unchanged.
- `core/quasar/client.py` `McpStdioClient`: minimal synchronous MCP client over
  stdio (newline-delimited JSON-RPC): `initialize` handshake, `tools/list`
  (with pagination), `tools/call`, per-request timeout, restart-and-re-handshake
  if the server process died. No new dependency (the official SDK is async and
  Andromeda's agent interface is synchronous).
- `core/quasar/agent.py` `QuasarAgent` (`AGENT_ID="quasar"`): at startup lists
  each server's tools and registers one `SkillManifest` whose skills are
  `quasar.<server>.<tool>` (`input_schema` = the tool's `inputSchema`,
  `allowed_origins` = the server's). A server that fails to start or list is
  logged and skipped; with no tools, no manifest is registered.
- `run(skill_id, payload, context)` calls the tool with `payload` as arguments.
  Result: `summary` = joined text content, `result` = the raw MCP content,
  `confidence` = 1.0 on success and 0.0 when the tool reports `isError`. Because
  confidence is only ever 1.0 or 0.0, Andromeda's retry rule (retry only when
  confidence >= 0.60 and below threshold) never silently re-runs a
  side-effecting tool. Transport errors raise and become a `failed` task.
- `boot()` loads `config/mcp.yaml` and adds the agent to Andromeda's agents.
- Access control reuses `allowed_origins` (see the access-control spec), so a
  filesystem or shell server can be limited to e.g. `goal:*`.

## Limits
- stdio transport only; no HTTP/SSE, OAuth, resources or prompts.
- Tools are discovered at boot; adding a tool needs a restart.
- Tool arguments are not validated against `inputSchema` (the server does).
- Server processes run with Galaxz's privileges. Only list servers you trust;
  an execution sandbox for them is out of scope.
- Confidence is a binary success signal, not a quality estimate.
