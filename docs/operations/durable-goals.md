# Durable goal operations

Goal plans are persisted before execution. The API then asks the durable goal
coordinator to enqueue every eligible dependency-free planned task. No goal
execution depends on an API-owned daemon thread.

The worker runs coordinator reconciliation before each claim cycle. It maps
completed jobs back to planned tasks, persists results, blocks only descendants
of failed branches, and enqueues newly ready work. Stable goal/task idempotency
keys make repeated reconciliation after API or worker restarts safe.

`GOAL_CONCURRENCY` limits running jobs per goal (default 4), while
`GLOBAL_JOB_CONCURRENCY` limits all observed running jobs (default 32). Fan-out
branches can run concurrently; fan-in tasks wait for every dependency.

Authenticated operator endpoints are `pause`, `resume`, `cancel`, and task
`rerun` beneath `/goals/{goal_id}`. Pause stops new enqueue while active jobs
finish. Cancel propagates to queued and running descendants. Rerun creates a
new job while retaining prior history. Control events retain actor, timestamp,
reason, and affected task IDs.

`GET /goals/{goal_id}` returns branch rollups, immutable resolved payloads, job
IDs, attempts, transitions, active leases, failure reasons, and control events.
Prism renders this persisted timeline and recovers it after browser refresh.
