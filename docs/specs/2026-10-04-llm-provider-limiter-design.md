# LLM Provider Limiter — Design

Date: 2026-10-04 · Status: approved in chat, implementing

## Problem

`call_llm()` (`core/llm/provider.py`) is synchronous and called from nine sites
(Vega stages and retries, Rigel, agent loader, Andromeda service). Nothing bounds
how many calls run at once, so concurrent goals and API requests can overwhelm a
single provider — most acutely the default local Ollama model — and show up as
timeouts. Each call also creates its own throwaway `ThreadPoolExecutor`.

Scope is deliberately limited to a concurrency cap. Priority, fairness and
per-agent quotas are out of scope.

## Design

- New `core/llm/limiter.py`: `ProviderLimiter`, one bounded semaphore and one
  executor per provider key (`provider/model@base_url`), created lazily.
  `submit(key, max_concurrent, queue_timeout_s, fn, **kwargs)` blocks for a slot,
  runs `fn` on that key's executor and returns the future. Exceeding the queue
  wait raises `LLMQueueTimeout(RuntimeError)`.
- The slot is released by a done-callback on the future, not when the caller
  stops waiting. A call that times out client-side keeps occupying the provider,
  so it keeps its slot until its worker actually finishes.
- `call_llm()` submits through a module-level limiter. Signature, return value
  and the `RuntimeError("LLM call failed: ...")` convention are unchanged, so no
  caller changes.
- Config: `LLM_MAX_CONCURRENT` env var, falling back to `llm.max_concurrent` in
  `config/providers.yaml` (env wins, so no placeholder is needed in the yaml). Unset → 1 for `ollama`, 4 otherwise. Values < 1
  or non-integer raise `ValueError` in `load_provider_config`.
  `LLM_QUEUE_TIMEOUT_SECONDS` (default 120) bounds the queue wait, separate from
  the existing `LITELLM_TIMEOUT_SECONDS` call timeout.
- Contention is logged at debug level when a call waits more than 1s.

No contract changes: this is internal plumbing.

## Known limits

The cap is per process. With `--profile distributed-agents`, Vega and Rigel each
enforce their own cap, so total provider load is the sum. A Redis-backed limiter
can replace `ProviderLimiter` behind the same `submit` interface later.

## Testing

`test/core/test_llm_limiter.py`, `litellm.completion` mocked: peak concurrency
never exceeds the cap; queue timeout raises `LLMQueueTimeout`; slot released
after an exception; timed-out call keeps its slot until the worker finishes;
different keys do not block each other; config defaults, env override and
rejection of invalid values. Full existing suite must stay green.

## Out of scope

Priorities, per-agent quotas, parallel DAG execution in `GoalRunner`,
context snapshot/resume, Redis-backed global limiting.
