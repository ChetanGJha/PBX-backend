import logging
import redis.asyncio as aioredis
from src.core.config import settings

logger = logging.getLogger("pbx.redis")

redis_client: aioredis.Redis = None


async def init_redis():
    global redis_client
    try:
        redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True
        )
        await redis_client.ping()
        logger.info("Redis client connected successfully.")
    except Exception as err:
        logger.warning(f"Failed to connect to Redis: {err}. Proceeding without active Redis cache.")


async def close_redis():
    global redis_client
    if redis_client:
        await redis_client.close()
        logger.info("Redis connection closed.")


def get_redis() -> aioredis.Redis:
    return redis_client
