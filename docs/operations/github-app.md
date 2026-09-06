# GitHub App integration

Galaxz supports GitHub App authentication for repository selection, pull
requests, checks, and signed webhooks. Configure `GALAXZ_GITHUB_APP_ID` and
`GALAXZ_GITHUB_APP_PRIVATE_KEY`; set `GALAXZ_GITHUB_INSTALLATION_ID` for the
default installation, or pass `installation_id` to PR/check requests.

The App should request only these permissions:

| Permission | Access | Use |
| --- | --- | --- |
| Metadata | Read | List and identify repositories |
| Contents | Write | Publish approved generated changes |
| Checks | Write | Publish execution outcomes |
| Pull requests | Write | Create and update review requests |

Installation access tokens are exchanged on demand, cached only in process
memory until shortly before expiry, and never written to the database or logs.
GitHub 401/403 responses are surfaced as an unavailable or revoked
installation. Private keys and webhook secrets must be supplied through the
deployment secret manager, not committed to the repository.
