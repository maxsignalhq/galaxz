from uuid import UUID

from test.api.test_goals_api import AUTH, client  # noqa: F401  (fixture re-export)


def test_post_goal_accepts_token_budget(client):
    r = client.post("/goals", json={"objective": "x", "token_budget": 5000}, headers=AUTH)
    assert r.status_code == 202
    goal = r.json()["goal"]
    assert goal["token_budget"] == 5000
    assert goal["tokens_used"] == 0


def test_post_goal_rejects_non_positive_budget(client):
    r = client.post("/goals", json={"objective": "x", "token_budget": 0}, headers=AUTH)
    assert r.status_code == 422


def test_resume_can_raise_the_budget(client):
    created = client.post(
        "/goals", json={"objective": "x", "token_budget": 10}, headers=AUTH
    ).json()["goal"]
    gid = created["goal_id"]
    client._andromeda.goal_store.pause_with_reason(UUID(gid), "token_budget", None)
    r = client.post(f"/goals/{gid}/resume", json={"token_budget": 9999}, headers=AUTH)
    assert r.status_code == 202
    assert r.json()["goal"]["token_budget"] == 9999


def test_resume_rejects_non_positive_budget(client):
    gid = client.post("/goals", json={"objective": "x"}, headers=AUTH).json()["goal"]["goal_id"]
    client._andromeda.goal_store.pause_with_reason(UUID(gid), "token_budget", None)
    r = client.post(f"/goals/{gid}/resume", json={"token_budget": 0}, headers=AUTH)
    assert r.status_code == 422
