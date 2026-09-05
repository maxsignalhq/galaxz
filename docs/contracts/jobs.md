# Durable job contracts v1.0

`TaskContract` remains the agent-facing unit of work. The durable execution
layer wraps a task reference in an immutable `Job` and records each claim as a
separate immutable `ExecutionAttempt`.

## Job lifecycle

```text
queued -> running -> completed
   |         |  \-> failed
   |         |  \-> cancelled
   |         \----> queued (expired lease is reclaimed)
   \--------------> cancelled
```

Completed, failed, and cancelled jobs are terminal. Jobs include a caller-owned
idempotency key, bounded priority, retry policy, availability time, lifecycle
timestamps, and cancellation timestamps. Repository code creates a replacement
model for each state change; it never mutates a contract instance.

Each attempt records its identity, job, attempt number, worker, opaque lease
token, lease expiry, start/end timestamps, terminal outcome, and optional error
or output reference. `ended_at` and `outcome` are written together.

Both contracts carry `contract_version: "1.0"`. Breaking field or lifecycle
changes require a new contract version and a database/API migration decision.
