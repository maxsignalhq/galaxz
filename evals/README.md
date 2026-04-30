# Galaxz Evals

This folder holds a deterministic end-to-end eval harness for Galaxz.

Contents:
- `datasets/industry_scenarios.json`: finance, health, hospitality, and retail scenarios grounded in common industry data standards.
- `run_evals.py`: executes the eval suites and writes execution reports.
- `report/`: review notes and generated run reports.

Run:

```bash
.venv/bin/python evals/run_evals.py
```

The harness is intentionally deterministic:
- no live LLM calls,
- no live Redis dependency,
- no external APIs,
- no mutation of project source files outside `evals/report`.

