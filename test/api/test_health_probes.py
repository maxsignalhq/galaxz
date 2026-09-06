from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.andromeda.middleware.auth import ApiKeyMiddleware


def test_liveness_is_dependency_free_and_unauthenticated():
    app = FastAPI()
    app.add_middleware(ApiKeyMiddleware)

    @app.get("/live")
    def live():
        return {"status": "alive"}

    assert TestClient(app).get("/live").json() == {"status": "alive"}
