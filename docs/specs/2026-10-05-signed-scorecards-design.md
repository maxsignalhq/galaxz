# Signed Orion scorecards — Design

Date: 2026-10-05

## Problem
Orion records the real outcome of every task per agent and skill (success, partial, fail,
confidence, human verification, latency). That is the one thing a marketplace of agents
cannot fake, but today it is only visible to the operator through `/orion/analytics`. An
agent author or consumer has no way to hand a third party *verifiable* evidence of how an
agent performs. `core/platform.py::certify_agent` is only a boolean checklist, and Pulsar's
`avg_confidence` is a self-declared number.

## Design
A scorecard is a small statement computed from Orion's `events` table and signed with an
Ed25519 key held by the operator, so anyone with the public key can verify it offline.

```
payload  = canonical JSON bytes of:
  { "version": "1.0", "issuer": <GALAXZ_SCORECARD_ISSUER, default "galaxz">,
    "subject": {"agent_id", "skill_id"}, "issued_at",
    "window": {"from", "to", "days"},
    "metrics": {"tasks", "success_rate", "success_rate_ci95": [lo, hi], "partial_rate",
                "fail_rate", "avg_confidence", "human_verified_rate",
                "latency_ms_p50", "latency_ms_p95"},
    "sample": {"min_tasks": 20, "sufficient": <tasks >= 20>} }
envelope = { "payload": base64url(payload), "scorecard": <payload parsed, convenience only>,
             "signature": {"alg": "Ed25519", "kid", "value": base64url(sig over payload bytes)} }
```

- The signature covers the exact `payload` bytes, so verification needs no canonicalization
  rules in other languages. Verifiers must trust `payload`, never the `scorecard` mirror
  (`verify_envelope` also checks the mirror matches).
- `kid` is the first 16 hex chars of SHA-256 over the raw public key.
- Success rate comes with a Wilson 95% interval and `sample.sufficient`, so a 3-task agent
  cannot present "100% success" as if it meant the same as 3,000 tasks.
- Quarantined events are excluded. Metrics use the last `days` (default 30, 1-365).
- Scorecards are grouped by `(agent_id, skill_id)`; skills with no events have none.

**Off by default:** signing needs a key. `GALAXZ_SCORECARD_KEY_PATH` (PEM file) or
`GALAXZ_SCORECARD_KEY` (inline PEM). Without one, the endpoints return 503.

API (behind the normal `GALAXZ_API_KEY` auth, so a scorecard is shared by forwarding the
signed envelope): `GET /scorecards?days=`, `GET /scorecards/{skill_id}?days=`,
`GET /scorecards/key` (public key and `kid`).
CLI: `galaxz scorecard keygen [--out PATH]`, `galaxz scorecard verify FILE --public-key B64`.

No new contract, no new dependency (`cryptography` is already required).

## Limits
- It proves "this operator attests to these Orion numbers", not that the numbers are good:
  anyone can run their own Galaxz. Value comes from the issuer's reputation, like a TLS cert.
- Metrics reflect Orion's events, which are only as honest as the feedback that produced
  them; `human_verified_rate` shows how much was checked by a person.
- No revocation, key rotation or transparency log; rotate by issuing a new key and `kid`.
- Not yet embedded in Agent Cards or the catalog; the envelope is portable on its own.

## Decisions made without review
1. Ed25519 via `cryptography` and a detached-payload envelope instead of JWS/JWT, to avoid
   canonicalization pitfalls (float formatting) when verified by non-Python clients.
2. Scorecards are signed on request, not stored.
3. Endpoints stay behind the API key (not public) to match every other Orion endpoint.
4. `min_tasks = 20` and a 30-day default window are arbitrary starting points.
