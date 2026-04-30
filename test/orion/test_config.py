from orion.config import OrionConfig


def test_redis_url_uses_shared_redis_url(monkeypatch):
    monkeypatch.delenv("ORION_REDIS_URL", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://aether:6379")

    config = OrionConfig(_env_file=None)

    assert config.redis_url == "redis://aether:6379"


def test_orion_redis_url_overrides_shared_redis_url(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://aether:6379")
    monkeypatch.setenv("ORION_REDIS_URL", "redis://orion-redis:6379")

    config = OrionConfig(_env_file=None)

    assert config.redis_url == "redis://orion-redis:6379"


def test_redis_url_can_still_be_passed_by_field_name():
    config = OrionConfig(redis_url="redis://explicit:6379", _env_file=None)

    assert config.redis_url == "redis://explicit:6379"
