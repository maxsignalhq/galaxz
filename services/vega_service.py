import time
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI

from agents.vega.agent import VegaAgent
from core.pulsar.registry import PulsarRegistry

app = FastAPI()

_start_time = time.monotonic()
registry = PulsarRegistry()
vega = VegaAgent(registry)
vega.start()
print("[vega] ready")


@app.get("/health")
def health():
    try:
        manifest = registry.get_agent("vega")
        registration_check = {
            "status": "ok" if manifest is not None else "error",
            "skills": len(manifest.skills) if manifest else 0,
        }
    except Exception:
        registration_check = {"status": "error", "skills": 0}

    overall = "healthy" if registration_check["status"] == "ok" else "unhealthy"
    return {
        "service": "vega",
        "status": overall,
        "version": "1.0.0",
        "checks": {"registration": registration_check},
        "uptime_seconds": int(time.monotonic() - _start_time),
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


if __name__ == "__main__":
    uvicorn.run("services.vega_service:app", host="0.0.0.0", port=8080, reload=False)
