# Nebula (agent memory) — Design

Date: 2026-10-04 · Idea borrowed from AIOS's memory manager.

## Problem
Agents are stateless between tasks. Orion learns offline from feedback, but
nothing lets a human or agent leave durable notes that later tasks can use.

## Design
- Contract `MemoryEntry` (`core/contracts/contracts.py`): `memory_id`,
  `namespace`, `content`, `tags`, `source_task_id`, `created_at`.
- `core/nebula/store.py` `NebulaStore` (SQLite, `NEBULA_DB_PATH`, default
  `data/nebula.db`): `remember`, `recall(namespaces, query, limit)`, `list`,
  `forget`. Recall is keyword-overlap scoring (content + tags) with recency
  tiebreak; with no query it returns the most recent. No embeddings (YAGNI).
- Andromeda owns a `NebulaStore`. `route()` recalls from `[task.origin, "global"]`
  using the payload's text as the query and puts the result in
  `context["memory"]` (list of `{memory_id, namespace, content, tags}`, up to 5).
  Nothing is injected when there are no matches, so existing behavior is unchanged.
- Rigel: `run()` forwards `context["memory"]` into the payload and
  `code_generation` adds a "Relevant memory" block to the prompt. Other skills
  ignore it for now.
- API (behind the existing API-key middleware): `POST /memory`,
  `GET /memory?namespace=&q=&limit=`, `DELETE /memory/{memory_id}`.

## Limits
- Memory is written explicitly (API); tasks do not auto-remember results.
  Durable-worker attempts finish in `core/jobs/completion.py`, which is out of
  scope here.
- No tenant/organization scoping: namespaces are the only isolation, so do not
  put tenant secrets in shared namespaces. Revisit with multi-tenancy.
- Only Rigel code generation consumes memory.
