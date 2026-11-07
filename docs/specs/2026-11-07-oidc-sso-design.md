# OIDC single sign-on — design

Date: 2026-11-07. Depends on: accounts/roles, audit logging. Status: specified, not implemented.

## Problem
Operators of Prism share an API key. Organizations that already run an identity provider want to
sign in with it, and want membership and role to follow their directory.

## Goals
- Sign in to Prism with any standards-compliant OpenID Connect provider.
- A signed-in browser session resolves to a `user` principal with that user's role.
- Roles can be derived from IdP group claims.

## Non-goals
SAML, SCIM, multiple simultaneous IdPs per organization, social login, MFA enforcement (the IdP's job),
machine-to-machine OAuth (API tokens cover that).

## Design
Authorization Code flow with PKCE. Configuration (env, secrets via secret references where the
secret store is available): `GALAXZ_OIDC_ISSUER`, `GALAXZ_OIDC_CLIENT_ID`, `GALAXZ_OIDC_CLIENT_SECRET`,
`GALAXZ_OIDC_REDIRECT_URI`, optional `GALAXZ_OIDC_GROUP_ROLE_MAP` (JSON, group -> role).
Discovery from `/.well-known/openid-configuration`; ID token signature checked against the
provider's JWKS (PyJWT with `cryptography`); `iss`, `aud`, `exp`, `nonce` and `state` validated.

Endpoints (exempt from API-key auth, rate-limited): `GET /auth/login`, `GET /auth/callback`,
`POST /auth/logout`, `GET /auth/me`. A successful callback creates a server-side session (random id,
stored hashed, 8-hour expiry) delivered as an `HttpOnly; Secure; SameSite=Lax` cookie. The auth
middleware accepts either that cookie or a bearer token and produces the same `Principal`.
State-changing browser requests also require a CSRF header derived from the session.

User mapping: match on `(issuer, sub)`; first sign-in links by verified email to an existing user.
Just-in-time provisioning is **off by default**: an unknown identity is refused and the attempt is
audited. When enabled it creates a `viewer` unless the group map grants more.

## Security notes
No tokens in URLs after the callback; the callback validates and then redirects without query
parameters. Failed logins and logouts write `auth.login.failed` / `auth.logout` audit events.
The cookie is never accepted for the A2A or webhook routes.

## Left to the builder
Prism login screen, session cleanup job, and JWKS caching duration.
