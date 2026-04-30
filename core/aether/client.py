import json
import os

from pydantic import BaseModel
from redis import Redis

STREAM_KEY = "galaxz:tasks"


class AetherClient:
    def __init__(self, redis_url: str):
        self.redis = Redis.from_url(redis_url)

    def publish(self, message: BaseModel) -> None:
        self.redis.xadd(STREAM_KEY, {"data": message.model_dump_json()})

    def publish_event(self, stream: str, payload: dict) -> None:
        self.redis.xadd(stream, {"data": json.dumps(payload)})

    def close(self) -> None:
        self.redis.close()


def get_aether_client() -> AetherClient:
    redis_url = os.environ.get("REDIS_URL", "redis://aether:6379")
    return AetherClient(redis_url)
