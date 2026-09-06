import hashlib
import hmac
import json

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from agents.andromeda.middleware.auth import ApiKeyMiddleware
from core.secrets import SecretScope, SecretStore, redact_secrets
from cryptography.fernet import Fernet


def test_missing_and_wrong_api_credentials_are_denied(monkeypatch):
    monkeypatch.setenv("GALAXZ_API_KEY", "expected")
    app = FastAPI()
    app.add_middleware(ApiKeyMiddleware)

    @app.get("/protected")
    def protected():
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/protected").status_code == 401
    assert client.get("/protected", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/protected", headers={"Authorization": "Bearer expected"}).json() == {"ok": True}


def test_webhook_signature_rejects_tampering_without_api_key(monkeypatch):
    monkeypatch.setenv("GALAXZ_API_KEY", "api-key")
    monkeypatch.setenv("GALAXZ_GITHUB_WEBHOOK_SECRET", "webhook-secret")
    app = FastAPI()
    app.add_middleware(ApiKeyMiddleware)

    @app.post("/github/webhook")
    async def webhook(request: Request):
        body = await request.body()
        expected = "sha256=" + hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(request.headers.get("X-Hub-Signature-256", ""), expected):
            return {"error": "invalid signature"}
        return {"ok": True}

    body = json.dumps({"action": "opened"}).encode()
    signature = "sha256=" + hmac.new(b"wrong", body, hashlib.sha256).hexdigest()
    response = TestClient(app).post("/github/webhook", content=body, headers={"X-Hub-Signature-256": signature})
    assert response.json() == {"error": "invalid signature"}


def test_secret_scope_confusion_and_logging_are_blocked(tmp_path):
    store = SecretStore(tmp_path / "secrets.db", type("Provider", (), {"key": lambda self: Fernet.generate_key()})())
    scope = SecretScope("org-a", "repo-a", "task-a", "deny-all")
    reference = store.put("forbidden-token-value", scope)
    assert "forbidden-token-value" not in json.dumps(reference)
    assert redact_secrets("failure forbidden-token-value", [store.resolve(reference["secret_id"], scope)]) == "failure [REDACTED]"
