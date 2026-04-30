from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


DEFAULT_EXECUTION_IMAGE = "galaxz:latest"


class ExecutionResult(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    outcome: Literal["pass", "fail", "timeout", "error"]
    duration_ms: int = Field(ge=0)


class ExecutionSandboxUnavailable(RuntimeError):
    pass


def execute_generated_output(
    skill_id: str,
    payload: dict,
    result: dict,
    timeout_s: int = 30,
    image: str = DEFAULT_EXECUTION_IMAGE,
) -> ExecutionResult | None:
    files = _build_execution_files(skill_id, payload, result)
    if files is None:
        return None

    start = time.monotonic()
    container_name = f"rigel-exec-{uuid4().hex[:12]}"

    try:
        with tempfile.TemporaryDirectory(prefix="rigel-exec-") as temp_dir:
            workspace = Path(temp_dir)
            os.chmod(workspace, 0o755)
            for filename, content in files.items():
                path = workspace / filename
                path.write_text(content, encoding="utf-8")
                os.chmod(path, 0o644)

            command = _docker_run_command(
                workspace=workspace,
                image=image,
                container_name=container_name,
            )
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
    except subprocess.TimeoutExpired as exc:
        _cleanup_container(container_name)
        return ExecutionResult(
            exit_code=-1,
            stdout=_coerce_output(exc.stdout),
            stderr=_coerce_output(exc.stderr),
            outcome="timeout",
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    except (FileNotFoundError, PermissionError) as exc:
        raise ExecutionSandboxUnavailable(str(exc)) from exc
    except OSError as exc:
        raise ExecutionSandboxUnavailable(str(exc)) from exc
    except Exception as exc:
        return ExecutionResult(
            exit_code=-1,
            stdout="",
            stderr=str(exc),
            outcome="error",
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    stderr = completed.stderr or ""
    if completed.returncode == 125 or _docker_unavailable(stderr):
        raise ExecutionSandboxUnavailable(stderr or "docker run failed")

    return ExecutionResult(
        exit_code=completed.returncode,
        stdout=completed.stdout or "",
        stderr=stderr,
        outcome="pass" if completed.returncode == 0 else "fail",
        duration_ms=int((time.monotonic() - start) * 1000),
    )


def _build_execution_files(skill_id: str, payload: dict, result: dict) -> dict[str, str] | None:
    if skill_id == "rigel.skill.code_generation":
        code = result.get("code")
        tests = payload.get("tests") or payload.get("test_code")
        language = result.get("language", payload.get("language", "python"))
        if language != "python" or not code or not tests:
            return None
        return {
            "generated_module.py": code,
            "test_generated.py": "from generated_module import *\n\n" + tests,
            "runner.py": _runner_source("test_generated.py"),
        }

    if skill_id == "rigel.skill.test_writing":
        code = payload.get("code")
        tests = result.get("tests")
        if not code or not tests:
            return None
        return {
            "source_module.py": code,
            "test_generated.py": "from source_module import *\n\n" + tests,
            "runner.py": _runner_source("test_generated.py"),
        }

    return None


def _docker_run_command(
    workspace: Path,
    image: str,
    container_name: str,
) -> list[str]:
    workspace_path = str(workspace.resolve())
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "64",
        "--memory",
        "256m",
        "--cpus",
        "0.5",
        "--user",
        "65534:65534",
        "--mount",
        f"type=bind,src={workspace_path},dst=/workspace",
        "--workdir",
        "/workspace",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        image,
        "python",
        "runner.py",
    ]


def _cleanup_container(container_name: str) -> None:
    try:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        pass


def _coerce_output(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _docker_unavailable(stderr: str) -> bool:
    lowered = stderr.lower()
    markers = (
        "cannot connect to the docker daemon",
        "error during connect",
        "permission denied while trying to connect to the docker api",
        "is the docker daemon running",
        "docker.sock",
    )
    return any(marker in lowered for marker in markers)


def _runner_source(test_filename: str) -> str:
    return textwrap.dedent(
        f"""
        import asyncio
        import importlib.util
        import inspect
        import pathlib
        import sys
        import traceback

        ROOT = pathlib.Path(__file__).resolve().parent
        TEST_PATH = ROOT / {test_filename!r}

        def _load_module(name, path):
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"Unable to load module {{name}} from {{path}}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            return module

        try:
            module = _load_module("test_generated", TEST_PATH)
            tests = []
            for name, value in vars(module).items():
                if name.startswith("test_") and callable(value):
                    tests.append((name, value))

            if not tests:
                print("no tests discovered", file=sys.stderr)
                sys.exit(1)

            for name, test_fn in tests:
                result = test_fn()
                if inspect.isawaitable(result):
                    asyncio.run(result)
                print(f"PASS {{name}}")

            sys.exit(0)
        except AssertionError:
            traceback.print_exc()
            sys.exit(1)
        except Exception:
            traceback.print_exc()
            sys.exit(1)
        """
    ).strip() + "\n"
