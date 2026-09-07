import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "--env-file", "/dev/null", "-p", "galaxz-integration",
           "-f", "docker-compose.integration.yml"]


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker Compose CLI unavailable")
def test_integration_configuration_has_no_development_state():
    result = subprocess.run([*COMPOSE, "config", "--format", "json"], cwd=ROOT,
                            capture_output=True, text=True, check=True)
    config = json.loads(result.stdout)
    assert config["name"] == "galaxz-integration"
    assert config["volumes"]["job-data"]["name"] == "galaxz-integration_job-data"
    for service in config["services"].values():
        assert not service.get("env_file")
        for mount in service.get("volumes", []):
            if mount["type"] == "bind":
                assert mount.get("read_only") is True
                assert Path(mount["source"]).is_relative_to(ROOT / "test/integration")
    assert config["services"]["galaxz"]["environment"]["GALAXZ_API_KEY"] == ""


def test_baseline_failure_before_start_does_not_run_cleanup(tmp_path):
    log = tmp_path / "docker.log"
    docker = tmp_path / "docker"
    docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$REVIEW_DOCKER_LOG"\n')
    docker.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}",
           "PYTHON_BIN": "/usr/bin/false", "REVIEW_DOCKER_LOG": str(log)}
    result = subprocess.run(["bash", "scripts/verify_production_baseline.sh"],
                            cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    calls = log.read_text()
    assert "-p galaxz-integration" in calls
    assert "down" not in calls
    assert "docker-compose.yml" not in calls
