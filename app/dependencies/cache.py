import redis.asyncio as aioredis

from app.config import config


class RedisClient:
    """Менеджер для роботи з Redis у FastAPI"""

    def __init__(self):
        self.redis = None

    async def init_redis(self):
        """Ініціалізація Redis-клієнта (тільки один екземпляр)"""
        if self.redis is None:
            self.redis = await aioredis.from_url(
                f"redis://{config.REDIS_HOST}:{config.REDIS_PORT}",
                password=config.REDIS_PASSWORD,
                db=0,
                decode_responses=True,
            )
        return self.redis

    async def get_redis(self):
        """Отримати підключення до Redis"""
        if self.redis is None:
            await self.init_redis()
        return self.redis

    async def close_redis(self):
        """Закриває підключення до Redis перед виходом"""
        if self.redis:
            await self.redis.close()
            self.redis = None  # Важливо очистити змінну


# 🔹 Глобальний екземпляр Redis-клієнта
redis_client = RedisClient()
