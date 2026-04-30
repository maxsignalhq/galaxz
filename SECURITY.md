# Security

## Scope

Galaxz v1 is designed for **local and single-user deployment** — running on a developer's machine, a private homelab, or a trusted internal network where all callers are assumed to be the operator.

No authentication, authorization, or multi-tenancy is implemented in v1. This is an **explicit design decision**, not an oversight. Keeping the trust model flat in v1 reduces operational complexity, avoids premature abstraction around access control, and lets contributors focus on the core orchestration and learning-loop machinery. The v2 roadmap below describes the planned auth layer.

## Trust Boundary

| Layer | v1 Status | Notes |
|---|---|---|
| Task endpoint (`POST /task`) | Unauthenticated | Internal / localhost only |
| Review queue API (`/review/queue/*`) | Unauthenticated | Internal / localhost only |
| Fine-tune candidates API (`/finetune/candidates/*`) | Unauthenticated | Internal / localhost only |
| Pulsar registry | Unauthenticated | Internal only |
| Operator dashboard / UI | No login | Single-user, local deploy |
| API keys | None | Not in v1 |

All service ports (8001 andromeda, 8002 rigel, 8003 pulsar, 8080 vega) must be bound to `localhost` or a private network interface. The default `docker-compose.yml` binds to `0.0.0.0` for local dev convenience — change this before placing any service on a shared host.

## Production Guidance

For production or multi-user deployments, place a reverse proxy in front of Andromeda's HTTP interface before exposing any endpoint outside a private network. Recommended patterns:

- **nginx + mTLS** — issue client certificates to each authorised caller; nginx terminates TLS and forwards to Andromeda on localhost
- **API gateway** (Kong, Traefik, AWS API GW) — handle auth, rate-limiting, and TLS termination at the gateway; Galaxz services see only trusted internal traffic
- **Tailscale / WireGuard** — restrict access to the Galaxz host to authenticated peers on a private overlay network without changing the application layer

Do not expose any Galaxz service port directly to the public internet in v1. There is no brute-force protection, no rate limiting, and no input sanitisation beyond what FastAPI provides.

## v2 Auth Roadmap

The following access-control features are planned for v2 and will be designed as a coherent layer rather than bolted onto individual services. **Planned:** API key authentication on the task endpoint, with keys scoped to specific skills or agent classes. **Planned:** Workspace isolation per tenant so that multiple teams can share a Galaxz deployment without visibility into each other's task logs, review queues, or training datasets. **Planned:** Role-based access control on the review queue — a `reviewer` role can accept or reject candidates, while an `admin` role can manage routing weights and fine-tune queue approvals. **Not planned for open source core:** OAuth, OIDC, or SSO integration — these belong in a hosted or enterprise tier and are out of scope for the community edition.

## Reporting Security Issues

**Non-sensitive bugs** (e.g. a missing input validation, an unhandled error that leaks a stack trace) — open a [GitHub Issue](https://github.com/galaxz-ai/galaxz/issues) with the label `security` and a description of the behaviour. No embargo required for issues that require local access to exploit.

**Sensitive disclosures** (e.g. a vulnerability that could affect users who have followed the production guidance above and placed Galaxz behind a proxy, or an issue in a dependency that has a CVE) — please email **security@galaxz.ai** with a description of the issue, reproduction steps, and any suggested mitigations. We aim to acknowledge within 48 hours and to ship a patch or mitigation within 14 days. We will credit reporters in the release notes unless you request anonymity.

We do not currently operate a bug bounty programme.
