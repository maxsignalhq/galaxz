import time
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI

from core.pulsar.registry import PulsarRegistry, storage_backend_summary

app = FastAPI()

_start_time = time.monotonic()
registry = PulsarRegistry()
storage = storage_backend_summary()
print(f"[pulsar] storage backend={storage['backend']} registry={storage}")
print(f"[pulsar] ready agents_registered={len(registry.list_agents())}")


@app.get("/health")
def health():
    try:
        agents = registry.list_agents()
        registry_check = {"status": "ok", "agent_count": len(agents)}
    except Exception:
        registry_check = {"status": "error", "agent_count": 0}

    overall = "healthy" if registry_check["status"] == "ok" else "degraded"
    return {
        "service": "pulsar",
        "status": overall,
        "version": "1.0.0",
        "checks": {"registry": registry_check},
        "uptime_seconds": int(time.monotonic() - _start_time),
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


if __name__ == "__main__":
    uvicorn.run("services.pulsar_service:app", host="0.0.0.0", port=8003, reload=False)
