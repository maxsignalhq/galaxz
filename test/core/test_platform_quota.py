from core.platform import enforce_quota

def test_quota_is_bounded():
    assert enforce_quota(10, 10)["allowed"] is False
    assert enforce_quota(2, 10)["remaining"] == 8
