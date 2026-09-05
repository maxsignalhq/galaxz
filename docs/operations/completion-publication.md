# Durable completion and evidence publication

SCRUM-45 uses a transactional outbox for the current local SQLite backend.
Production Postgres migration (SCRUM-46) and external object storage (SCRUM-47)
must preserve these boundaries. This change does not introduce either backend.

1. Routing a task with `execution_attempt_id` returns its evidence without
   publishing artifact versions or review rows. Synchronous `/task` execution
   retains its existing immediate publication behavior.
2. `SqliteJobRepository.complete` checks the active, unexpired lease and commits
   the attempt outcome, immutable output, job status, transition and outbox row
   in one transaction. A rollback exposes none of those changes. The outbox
   references the committed job and attempt; task input and output are immutable.
   Repeating the same completion is safe; changing its evidence is rejected.
3. The worker's reconciliation cycle reads committed outbox entries and writes
   each artifact batch in a separate atomic transaction. The attempt-to-version
   mapping is persisted even when content deduplicates against an older version.
   Concurrent publishers and replay after a crash therefore select the same
   immutable versions. Readers cannot observe an uncommitted partial batch.
4. Only after content and metadata commit does publication enqueue a review.
   Its `attempt_id` identifies the committed attempt; `agent_output.artifact_versions`
   holds the exact artifact identity, version and SHA-256 hash. No review points
   at a mutable “latest” version. An existing conflicting review is an error.
5. The outbox is acknowledged after the review commit. Crashes between these
   stores replay safely. A storage error leaves the outbox pending, logs
   `completion_publication_failed`, and retries on the next worker cycle.
   Agent execution is not repeated to repair evidence publication.

Job `completed` means execution and its raw result are durable; publication into
artifact/review views is eventually consistent. During a downstream outage a
goal may be paused awaiting a review that has not been published yet. Recovery
requires a running worker and restored storage access, not resubmission.

The API and worker must use the same persistent evidence stores. Both Compose
stacks set `REVIEW_DB_PATH=/var/lib/galaxz/reviews.db` and
`ARTIFACT_DB_PATH=/var/lib/galaxz/artifacts.db` on the shared `job-data` volume.
Outside Compose, defaults remain `data/andromeda_tasks.db` for reviews and
`data/artifacts.db` for artifacts. Before upgrading an existing deployment,
preserve its old evidence databases and migrate them to these shared paths
with the services stopped; changing paths does not merge legacy per-container
databases or backfill acknowledged publication.

Inspect pending publication using
`SELECT * FROM completion_outbox WHERE published_at IS NULL` on `JOB_DB_PATH`.
Investigate repeated publication errors before retrying a goal. Do not manually
acknowledge entries with missing evidence. Drain pending publication before
downgrading schema version 2; rollback removes the outbox. Existing completed
jobs are not backfilled because the previous runtime already published their
evidence and cannot retrospectively establish this guarantee.

Artifact content currently resides in the same SQLite transaction as metadata:
an artifact-storage failure rolls back the entire batch and prevents review
publication. A future object backend must finish and verify its immutable upload
before committing available metadata; failed or partial uploads must raise and
leave this outbox pending. Orphan object cleanup belongs to SCRUM-47.

Verification: `pytest -q test/jobs/test_completion.py test/core/test_artifact_store.py`
covers commit rollback, expired leases, changed completion replay, concurrent
publication, artifact/review/ack failure, immutable deduplication and batch rollback.
Run `python test/integration/completion_publication.py` against the isolated
integration stack to verify that a real worker's review and pinned artifact
hashes are visible through HTTP and retained after API/worker recreation.
