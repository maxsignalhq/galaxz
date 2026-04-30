import time
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI

from agents.rigel.agent import RigelAgent
from core.pulsar.registry import PulsarRegistry

app = FastAPI()

_start_time = time.monotonic()
registry = PulsarRegistry()
RigelAgent(registry)
rigel_manifest = registry.get_agent("rigel")
skills = rigel_manifest.skills if rigel_manifest is not None else []
print(f"[rigel] ready skills_registered={len(skills)}")


@app.get("/health")
def health():
    try:
        manifest = registry.get_agent("rigel")
        registration_check = {
            "status": "ok" if manifest is not None else "error",
            "skills": len(manifest.skills) if manifest else 0,
        }
    except Exception:
        registration_check = {"status": "error", "skills": 0}

    overall = "healthy" if registration_check["status"] == "ok" else "unhealthy"
    return {
        "service": "rigel",
        "status": overall,
        "version": "1.0.0",
        "checks": {"registration": registration_check},
        "uptime_seconds": int(time.monotonic() - _start_time),
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


if __name__ == "__main__":
    uvicorn.run("services.rigel_service:app", host="0.0.0.0", port=8002, reload=False)
