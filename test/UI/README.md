# Galaxz UI Functional Tests

Functional UI tests for Prism, written from the perspective of an operator, reviewer, developer, and admin using the Galaxz workspace.

## Coverage

- Public landing page and workspace navigation.
- Dashboard review escalation visibility.
- Task UI live backend happy path with a realistic code-generation task.
- Task UI live backend contract check that fails loudly if a selected skill/API path cannot execute.
- Review Queue triage and reviewer notes.
- Dev Console agent inspection, skill tables, model override controls, and logs.
- Settings provider, fallback, and budget policy controls.

## Run

```bash
cd test/UI
npm install
npm test
```

The Playwright config starts the Prism Vite dev server from `../../prism` automatically. To test an already-running server:

```bash
PRISM_BASE_URL=http://127.0.0.1:5173 npm test
```

The `/api/task` endpoint is not mocked. These tests expect the Galaxz backend and local LLM provider to be available. If `/api/health`, task routing, the LLM, or a skill endpoint fails, the suite fails with the backend/API error surfaced in the test output.

Live task tests allow up to 180 seconds for a single `/api/task` response because local LLM analysis can be slow.
