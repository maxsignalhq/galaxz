# Fine-tune execution — design

Date: 2026-11-07. Depends on: accounts/roles, audit logging. Status: specified, not implemented.

## Problem
Orion detects fine-tune candidates, a human approves them (`POST /finetune/candidates/{id}/approve`),
and curated examples are written to JSONL. Nothing turns an approved candidate into a trained model:
`/orion/training/run` only flushes dataset files. The learning loop stops one step short.

## Goals
- An approved candidate can be turned into a fine-tuning run on an external provider.
- Every run is human-initiated, bounded, observable and reversible.
- The resulting model id is recorded and can be used as a provider/fallback model **by explicit
  operator action**.

## Non-goals
On-box GPU/LoRA training, automatic promotion of a tuned model into routing, hyperparameter
search, training on data that has not passed Orion's quarantine/curation.

## Design
Contract first: `FinetuneRun(run_id, candidate_id, domain, provider, base_model, dataset_path,
example_count, status, provider_job_id, result_model, error, created_by, created_at, updated_at)`
with `status` in `queued | exporting | submitted | training | succeeded | failed | cancelled`.
Stored in Orion's database (Alembic migration for PostgreSQL).

Provider adapter interface: `submit(dataset_path, base_model, params) -> provider_job_id`,
`status(provider_job_id)`, `cancel(provider_job_id)`. Shipped adapters:
- `dryrun` (**default**): builds and validates the dataset and the request, uploads nothing.
- `openai_compat`: OpenAI-style `/v1/fine_tuning/jobs`; works for OpenAI and compatible hosts.

Flow: `POST /finetune/runs {candidate_id, provider, base_model, max_examples, epochs}` (permission
`finetune:run`, reviewer/admin) requires the candidate to be `approved`. A poller in the worker's
cycle hook advances runs. Before any upload the exported dataset is scanned with the existing
`scan_untrusted_content` / secret-pattern checks; a finding fails the run with `dataset_failed_scan`
and nothing leaves the platform. Only `human_verified` or confidence-gated examples from
non-quarantined events are exported, capped at `max_examples`.

Endpoints: `POST /finetune/runs`, `GET /finetune/runs`, `GET /finetune/runs/{id}`,
`POST /finetune/runs/{id}/cancel`. Provider credentials come from secret references, never from
the request.

## Safety
One active run per candidate; a global cap (`GALAXZ_FINETUNE_MAX_ACTIVE`, default 1). Submit,
complete, fail and cancel are audited with run id, provider, example count and actor (never the
dataset content). A succeeded run produces a model id only; wiring it into `config/providers.yaml`
stays a manual, reviewed change.

## Left to the builder
Dataset chat-format conversion per domain, polling interval, and how `dryrun` surfaces its report.
