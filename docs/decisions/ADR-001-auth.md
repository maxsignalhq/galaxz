# ADR-001: Authentication Boundary for v1

## Status
Accepted

## Context
Galaxz v1 is an open-source tool intended for local and self-hosted 
deployment. The platform is stateful — tasks are queued, humans review 
them, and FeedbackEvents flow into Orion. An unauthenticated public 
deployment would be an open relay with write access to the review queue.

## Decision
v1 ships with single static API key authentication on all Andromeda 
HTTP endpoints. The key is set via GALAXZ_API_KEY environment variable. 
Multi-tenancy, JWT, OAuth, and workspace isolation are explicitly out 
of scope for v1.

## Consequences
- Any request to Andromeda without a valid key returns 401
- Key is set in .env, excluded from version control via .gitignore
- Contributors must not build conflicting auth approaches in v1
- Full auth system (JWT, workspaces, tenant isolation) is a v2 milestone

## Out of scope until v2
- Multi-tenancy
- User accounts and roles
- OAuth / SSO
- Per-agent authentication
- Audit logging
- Fine-tune execution — approval workflow only, no training runs in v1
