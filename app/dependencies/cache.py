import redis.asyncio as aioredis

from app.config import config

redis_client = aioredis.from_url(
    f"redis://{config.REDIS_HOST}:{config.REDIS_PORT}",
    password=config.REDIS_PASSWORD,
    decode_responses=True,
)


async def get_redis():
    return redis_client
