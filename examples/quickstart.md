# Five-minute workflow

1. Copy `.env.example` to `.env` and configure the readiness checks.
2. Run `python -m cli.run --help` to confirm the CLI is available.
3. Run a Vega goal against the sample repository path configured during setup.
4. Inspect the goal outcome and usage report, then export the pilot evidence.

The workflow keeps organization and repository context attached to each goal and never prints secret values.
