from core.github import WebhookStore


def test_pull_request_webhook_reconciliation_is_idempotent(tmp_path):
    store = WebhookStore(tmp_path / "webhooks.db")
    payload = {"action": "closed", "pull_request": {"number": 12, "merged": True}}
    result = store.reconcile("delivery-1", "pull_request", payload)
    assert result["state"] == "merged"
    duplicate = store.reconcile("delivery-1", "pull_request", payload)
    assert duplicate == {"duplicate": True, "delivery_id": "delivery-1"}


def test_non_pull_request_delivery_is_recorded_without_state(tmp_path):
    store = WebhookStore(tmp_path / "webhooks.db")
    assert store.reconcile("delivery-2", "push", {"deleted": True})["ignored"] is True
