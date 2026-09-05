#!/usr/bin/env bash
set -euo pipefail

repository_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$repository_root"

python_bin="${PYTHON_BIN:-python3}"
venv_path="${GALAXZ_BASELINE_VENV:-.venv}"
compose_file="docker-compose.integration.yml"
created_env="false"

cleanup() {
  docker compose -f "$compose_file" down --volumes >/dev/null 2>&1 || true
  if [[ "$created_env" == "true" ]]; then
    rm -f .env
  fi
}
trap cleanup EXIT

if [[ ! -f .env ]]; then
  cp .env.example .env
  created_env="true"
fi

docker compose config --quiet

"$python_bin" -m venv "$venv_path"
"$venv_path/bin/python" -m pip install -r requirements.txt
"$venv_path/bin/python" -m pip install --no-deps .
"$venv_path/bin/galaxz" --help
"$venv_path/bin/galaxz" vega --help
"$venv_path/bin/python" -m compileall -q agents cli core orion services test
"$venv_path/bin/python" -m pytest -q test

npm --prefix prism ci
npm --prefix prism run typecheck
npm --prefix prism run build

docker compose -f "$compose_file" config --quiet
docker compose -f "$compose_file" up --build --wait
curl --fail --show-error http://127.0.0.1:18001/health
curl --fail --show-error http://127.0.0.1:18001/status
curl --fail --show-error http://127.0.0.1:18003/health
curl --fail --show-error http://127.0.0.1:15173/api/health
docker compose -f "$compose_file" exec -T galaxz galaxz route \
  --skill rigel.skill.code_generation \
  --payload '{"spec":"Return a deterministic integration smoke function."}'
"$venv_path/bin/python" test/integration/smoke_task.py
"$venv_path/bin/python" test/integration/crash_recovery.py
"$venv_path/bin/python" test/integration/completion_publication.py

echo "Galaxz production baseline verified."
