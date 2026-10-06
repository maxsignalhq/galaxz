# Skill lessons (human-gated skill evolution) — Design

Date: 2026-10-05

## Problem
Orion turns feedback into fine-tuning *candidates*, but actually executing training is out
of scope, so a human correction today changes nothing about how the agent behaves next
time. Recent agent research shows agents improving by turning experience into reusable,
revisable procedures, which is a far cheaper loop than fine-tuning. Galaxz already has the
pieces: Orion holds the corrections, Nebula is durable memory that Rigel code generation
already injects into its prompt, and the finetune-candidate flow is an established
propose-then-review pattern.

## Design
Orion proposes short guidelines ("lessons") from human corrections; **a person approves each
one; only approved lessons ever reach Nebula.** Nothing changes agent behavior unattended.

1. **Source.** Orion `events` with a non-empty `human_correction` (the output was corrected by
   a person), not quarantined, not already used for a lesson. Grouped by `(skill_id, agent_id)`.
2. **Propose** (`POST /lessons/propose`, manual; there is no background job). For each group
   with at least `min_examples` (default 3) unused corrections, one LLM call is shown up to 8
   (task payload, agent output, human correction) examples, fenced as data, and returns up to
   3 imperative guidelines. Each is cleaned (whitespace collapsed, empty, over-300-character
   and duplicate ones dropped) and stored as a **pending** `LessonCandidate` with the ids of
   its evidence events. The source events are then marked used. An LLM or parse failure
   leaves them unmarked so a later call retries.
3. **Review.** `GET /lessons?status=pending`, `POST /lessons/{id}/approve` (optional edited
   `content`), `POST /lessons/{id}/reject`. Same shape as `/finetune/candidates`.
4. **Approve** writes one Nebula memory in namespace `skill:<skill_id>`, tags
   `["lesson", "agent:<agent_id>"]`. Revoke with the existing `DELETE /memory/{id}`.
5. **Use.** `Andromeda.route()` always adds up to 3 of the newest `skill:<task.skill>` memories
   to `context["memory"]` (not keyword-gated, because a generalised lesson need not share
   words with a later task). Rigel code generation already renders that list. With no lessons
   approved, routing is byte-for-byte unchanged.

`LessonCandidate` lives in `orion/core/lesson_store.py` next to `FinetuneCandidate`
(SQLite `lessons.db` beside Orion's events DB). No change to the core contracts.

## Safety
- Human gate is structural: the only Nebula write is the approve handler, which claims the
  candidate with an atomic `pending → approved` update first (a double approval cannot write
  twice) and reverts the claim if the Nebula write fails.
- Corrections and outputs are user-influenced text, so they are quoted as data in the
  proposal prompt, lessons are length-capped, and a reviewer reads every lesson before it
  can enter any later prompt.
- Lessons are plain text guidance, never code or config.

## Limits
- Only Rigel code generation consumes `context["memory"]` today, so only that skill benefits.
- Quality depends on the LLM and on corrections existing; there is no automatic measurement
  that a lesson helped (the signed scorecards can show success rate before and after).
- One lesson store per Orion database; no per-tenant scoping (same as Nebula).

## Decisions made without review
1. Manual trigger only; no scheduled proposals, so nothing spends tokens or changes behavior
   unattended.
2. Source is `human_correction` only, not plain failures: a correction states what *should*
   have happened, a failure does not.
3. Lessons go to the existing Nebula under a `skill:` namespace instead of a new store, and
   are always included (up to 3, newest first) rather than keyword-ranked.
4. `min_examples = 3`, 3 lessons per proposal, 300-character cap are starting points.
