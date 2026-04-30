# Project Review

## Findings

1. High: `test/api/test_andromeda_api.py` is stale against the current FastAPI service. The tests still expect `/health` to return registry details, while `services/andromeda_service.py` now returns a fixed service health payload. The tests also call protected write endpoints without bearer auth, while `ApiKeyMiddleware` enforces `GALAXZ_API_KEY` when configured. Current focused run: `3 failed`.
2. Medium: `agents/andromeda/orchestrator.py` accepts `TaskContract.confidence_threshold` but routing decisions still use hard-coded `0.65` and `0.40` thresholds. The contract carries a threshold that the router does not honor.
3. Medium: `core/contracts/contracts.py` no longer matches the constitutional task envelope documented in `CLAUDE.md`. The code now uses `origin`, `skill`, and `confidence_threshold`; the project constitution still describes `type`, `context`, `priority`, and `origin_agent`. That drift increases integration risk for future agents.

## Resolved Since Prior Review

1. `OrionService.ingest()` now writes accepted examples under `config.dataset_path` and rejected examples under a configured sibling `quarantine/` directory. The eval harness now asserts that legacy hard-coded `orion_datasets/` output is not produced.

## Coverage Gaps In Existing Tests

1. The deterministic eval harness now covers the cross-system feedback handshake, but normal pytest coverage still focuses on isolated units and has drifted for the API surface.
2. The eval harness now covers Click CLI behavior, but repository pytest coverage still does not.
3. Heuristic behavior exists, but the repo mostly skips Redis-backed end-to-end execution in normal local runs.

## Eval Design Response

The eval harness adds deterministic end-to-end coverage for:
- contracts and registry behavior,
- Vega pipeline across finance, health, hospitality, and retail scenarios,
- Rigel skills and execution calibration,
- Andromeda routing for Vega, Rigel, and no-match cases,
- CLI and API entrypoints, including bearer auth, status, review queue, and fine-tune queue flows,
- Orion ingest, extraction, heuristic emission, and cross-system feedback compatibility.

Latest eval result: `8 passed`, `0 failed`.
