from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from redis.asyncio import Redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_redis_client: Redis | None = None

_RELEASE_LOCK_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


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


async def acquire_distributed_lock(key: str, ttl_seconds: int = 30) -> tuple[bool, str]:
    """尝试获取 Redis 分布式互斥锁（NX + EX），防止多 Worker 并发初始化冲突。

    返回 (should_proceed, lock_token)：
    - 成功抢占锁：(True, token)，结束后调用 release_distributed_lock(key, token)
    - 锁已被其他 worker 持有：(False, "")
    - Redis 不可用/异常：(True, "")，降级放行（由业务初始化幂等性兜底）
    """
    token = uuid.uuid4().hex
    try:
        client = get_redis()
        acquired = await client.set(key, token, nx=True, ex=max(1, int(ttl_seconds)))
        if acquired:
            return True, token
        return False, ""
    except Exception as exc:
        logger.debug("Redis distributed lock fallback for key=%s: %s", key, exc)
        return True, ""


async def release_distributed_lock(key: str, token: str) -> bool:
    """按 token 原子校验并释放分布式锁，防止误删其他 worker 持有的锁。"""
    if not token:
        return False
    try:
        client = get_redis()
        released = await client.eval(_RELEASE_LOCK_LUA, 1, key, token)
        return bool(released)
    except Exception as exc:
        logger.debug("Redis distributed lock release skipped for key=%s: %s", key, exc)
        return False


async def wait_for_lock_release(
    key: str,
    timeout_seconds: float = 5.0,
    poll_interval: float = 0.2,
) -> bool:
    """短暂等待持有初始化锁的其他 worker 完成，避免尚未建表就对外提供服务。"""
    deadline = time.monotonic() + max(0.1, timeout_seconds)
    try:
        client = get_redis()
        while time.monotonic() < deadline:
            if not await client.exists(key):
                return True
            await asyncio.sleep(poll_interval)
        return False
    except Exception as exc:
        logger.debug("Redis wait_for_lock_release skipped for key=%s: %s", key, exc)
        return False
