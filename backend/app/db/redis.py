from __future__ import annotations

import json
import logging
from typing import Any

from redis.asyncio import Redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_redis_client: Redis | None = None


def init_redis() -> Redis:
    """初始化异步 Redis 客户端连接池。"""
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = Redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _redis_client


def get_redis() -> Redis:
    """获取全局异步 Redis 客户端实例。"""
    return init_redis()


async def check_redis_health() -> tuple[bool, str]:
    """检测 Redis 连通性。"""
    try:
        client = get_redis()
        pong = await client.ping()
        return bool(pong), "connected" if pong else "unexpected_ping_response"
    except Exception as exc:
        logger.warning("Redis health check failed: %s", exc)
        return False, f"disconnected ({type(exc).__name__})"


async def close_redis() -> None:
    """应用关闭时释放 Redis 连接。"""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


async def cache_set_json(key: str, value: Any, ttl_seconds: int = 3600) -> bool:
    """安全写入 JSON 缓存，Redis 不可用时降级返回 False。"""
    try:
        client = get_redis()
        await client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl_seconds)
        return True
    except Exception as exc:
        logger.debug("Redis set failed for key=%s: %s", key, exc)
        return False


async def cache_get_json(key: str) -> Any | None:
    """安全读取 JSON 缓存，Redis 不可用或不存在时返回 None。"""
    try:
        client = get_redis()
        raw = await client.get(key)
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.debug("Redis get failed for key=%s: %s", key, exc)
        return None


async def cache_delete(key: str) -> bool:
    """安全删除缓存键。"""
    try:
        client = get_redis()
        await client.delete(key)
        return True
    except Exception as exc:
        logger.debug("Redis delete failed for key=%s: %s", key, exc)
        return False


async def cache_get_del_json(key: str) -> Any | None:
    """原子读取并删除 JSON 缓存（用于一次性验证码票据消费），返回 None 表示不存在或 Redis 不可用。"""
    try:
        client = get_redis()
        raw = await client.getdel(key)
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.debug("Redis getdel failed for key=%s: %s", key, exc)
        return None
