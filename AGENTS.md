# Repository Guidelines

## Project Structure & Module Organization
- `cli/`: Click-based command entrypoint (`python -m cli.run`).
- `agents/`: agent implementations (`vega/`, `rigel/`, `andromeda/`).
- `core/`: shared infrastructure (`contracts/`, `aether/`, `llm/`, `pulsar/`).
- `config/`: runtime configuration (`providers.yaml`).
- `test/`: single test root for all dev/QA tests and test data.
- `memory/` and `CLAUDE.md`: architecture decisions and working rules; read before major changes.

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate`: create local Python env.
- `pip install -r requirements.txt`: install dependencies.
- `python -m cli.run --help`: verify CLI loads.
- `python -m cli.run vega --input <path> --config config/providers.yaml`: run Vega pipeline.
- `docker compose up --build -d`: build and start Redis (`aether`) + app service.
- `docker compose logs -f app`: tail app logs.
- `docker compose down`: stop stack.

## Coding Style & Naming Conventions
- Python 3.11, 4-space indentation, UTF-8, one import per line.
- Use `snake_case` for functions/modules, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants.
- Prefer explicit typing (`list[str]`, `dict[str, int]`) and Pydantic models at contract boundaries.
- Keep modules focused by domain (agent logic in `agents/*`, shared contracts in `core/contracts/*`).

## Testing Guidelines
- Run the full suite from the single test root: `pytest test`.
- Add tests and test data under `test/` using `test_<feature>.py` naming.
- Minimum sanity check before PR: `python -m py_compile $(find agents cli core orion services test -name '*.py')`.
- For pipeline changes, include at least one happy-path and one failure-path test case.

## Commit & Pull Request Guidelines
- Git history is not available in this workspace snapshot; use Conventional Commits (`feat:`, `fix:`, `chore:`).
- Keep commits small and scoped to one concern.
- PRs should include:
  - change summary and motivation,
  - affected modules (e.g., `agents/vega/pipeline.py`),
  - verification steps/commands run,
  - sample CLI output or logs for behavior changes.

## Security & Configuration Tips
- Never commit real secrets in `.env`; keep `.env.example` as the template.
- Prefer service DNS inside Docker (`redis://aether:6379`) for container-to-container communication.
