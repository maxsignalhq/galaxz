# Galaxz Production Phases

Galaxz is moving from a working prototype to a production-ready, self-hosted
team product. The live roadmap is maintained in the Jira `SCRUM` project:

- [SCRUM board](https://galaxz.atlassian.net/jira/software/projects/SCRUM/boards/1)
- [SCRUM-8: overall production-readiness initiative](https://galaxz.atlassian.net/browse/SCRUM-8)

Jira is the source of truth for current status, ownership, blockers, acceptance
criteria, and delivery order. This document records the stable phase structure
so that a future Codex, Claude, or human contributor can find the correct
starting point without treating a documentation snapshot as live status.

## Phase structure

| Phase | Outcome | Initiative | Epics | Sprint plans |
|-------|---------|------------|-------|--------------|
| 1. Production foundation | Reproducible baseline, durable jobs, and durable goal execution | [SCRUM-8](https://galaxz.atlassian.net/browse/SCRUM-8) | [SCRUM-6](https://galaxz.atlassian.net/browse/SCRUM-6), [SCRUM-7](https://galaxz.atlassian.net/browse/SCRUM-7), [SCRUM-5](https://galaxz.atlassian.net/browse/SCRUM-5) | SCRUM-31 → SCRUM-30 → SCRUM-29 |
| 2. Trusted team product | Postgres and artifact storage, GitHub workflow, sandboxing, approvals, identity, and operations | [SCRUM-35](https://galaxz.atlassian.net/browse/SCRUM-35) | SCRUM-32, SCRUM-37, SCRUM-36, SCRUM-38, SCRUM-40, SCRUM-43 | SCRUM-105 → SCRUM-103 → SCRUM-104 → SCRUM-110 |
| 3. Quality and pilot | Objective evaluation, confidence calibration, security gates, onboarding, and design-partner validation | [SCRUM-39](https://galaxz.atlassian.net/browse/SCRUM-39) | SCRUM-42, SCRUM-41 | SCRUM-107 → SCRUM-106 |
| 4. Hosted scale | Tenant isolation, horizontal scale, hosted operations, enterprise controls, and billing | [SCRUM-34](https://galaxz.atlassian.net/browse/SCRUM-34) | SCRUM-44, SCRUM-33 | SCRUM-108 → SCRUM-109 |

## Delivery sequence

```text
SCRUM-31 → SCRUM-30 → SCRUM-29 → SCRUM-105 → SCRUM-103 →
SCRUM-104 → SCRUM-110 → SCRUM-107 → SCRUM-106 → SCRUM-108 →
SCRUM-109
```

**Current starting point (recorded 2026-09-01):** begin with
[SCRUM-31](https://galaxz.atlassian.net/browse/SCRUM-31). Its initial scope is
SCRUM-9 through SCRUM-13 plus SCRUM-18, SCRUM-17, and SCRUM-15. Check Jira
before acting because completion status may have changed since this note was
written.

## Continuation protocol for coding agents

1. Read `CLAUDE.md`, `AGENTS.md`, and this document before changing code.
2. Query Jira for unfinished production work. Start with the earliest unfinished,
   unblocked sprint-plan issue in the sequence above; do not infer order from Jira
   issue numbers. A useful JQL query is
   `project = SCRUM AND labels = production-readiness AND statusCategory != Done`.
3. Open that sprint plan, its epic, and the candidate story. Read the full
   acceptance criteria, links, and blockers before selecting work.
4. Confirm whether the requested behavior is already implemented in the current
   repository. If it is complete, verify it and update Jira rather than duplicating it.
5. Implement one Jira story at a time. Preserve contract boundaries, add the
   required happy- and failure-path tests, and run the checks named in the story.
6. Record verification evidence and any newly discovered blocker on the Jira
   issue before moving it forward. Keep Jira status authoritative; do not mark
   roadmap progress only in this document.
7. Do not begin Phase 4 merely because earlier work is inconvenient. Phase 4 is
   labeled `future-scope` and is blocked on the Phase 3 pilot go/no-go decision.

## Jira conventions

Because this Jira project does not expose native Initiative or sprint creation
through the current connector, initiatives are represented by labeled
coordination tasks and planned increments by sprint-plan tasks plus
`planned-sprint-N` labels.
