CREATE TABLE IF NOT EXISTS finetune_candidates (
    candidate_id   TEXT    PRIMARY KEY,
    agent_id       TEXT    NOT NULL,
    example_count  INTEGER NOT NULL,
    quality_avg    REAL    NOT NULL,
    emitted_at     TEXT    NOT NULL,
    status         TEXT    NOT NULL DEFAULT 'pending',
    reviewed_at    TEXT,
    reviewed_by    TEXT,
    reviewer_note  TEXT
);
