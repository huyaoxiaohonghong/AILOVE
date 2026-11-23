from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from fastapi import Request, status

from app.core.exceptions import BusinessException
from app.core.security import decode_access_token
from app.db.redis import get_redis

logger = logging.getLogger(__name__)


class RateLimiter:
    """基于 Redis 的滑动/固定窗口限流器，Redis 离线时自动降级进程内计数。"""

    def __init__(self) -> None:
        self._mem_buckets: dict[str, tuple[float, int]] = {}

    def _prune_mem(self, now: float) -> None:
        if len(self._mem_buckets) < 512:
            return
        expired = [k for k, (exp, _) in self._mem_buckets.items() if exp <= now]
        for k in expired:
            self._mem_buckets.pop(k, None)

    async def check(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
        """返回 (allowed, remaining, retry_after_seconds)。"""
        cap = max(1, int(limit))
        win = max(1, int(window_seconds))
        rkey = f"ailove:rl:{key}"

        try:
            client = get_redis()
            count = int(await client.incr(rkey))
            if count == 1:
                await client.expire(rkey, win)
            if count > cap:
                ttl = int(await client.ttl(rkey))
                retry_after = max(1, ttl if ttl > 0 else win)
                return False, 0, retry_after
            return True, max(0, cap - count), 0
        except Exception:
            now = time.time()
            self._prune_mem(now)
            exp, cur = self._mem_buckets.get(rkey, (0.0, 0))
            if exp <= now:
                exp = now + win
                count = 1
            else:
                count = cur + 1
            self._mem_buckets[rkey] = (exp, count)
            if count > cap:
                retry_after = max(1, int(exp - now) + 1)
                return False, 0, retry_after
            return True, max(0, cap - count), 0


rate_limiter = RateLimiter()


def _extract_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(
    scope: str,
    limit: int,
    window_seconds: int = 60,
    *,
    by_user: bool = False,
) -> Callable[..., Any]:
    """FastAPI 限流依赖工厂：超限返回 HTTP 429 与明确重试秒数。"""

    async def _guard(request: Request) -> None:
        ident = ""
        if by_user:
            auth_header = request.headers.get("authorization", "")
            if auth_header.lower().startswith("bearer "):
                token = auth_header[7:].strip()
                try:
                    payload = decode_access_token(token)
                    sub = str(payload.get("sub", "")).strip()
                    utype = str(payload.get("type", "web")).strip()
                    if sub:
                        ident = f"u:{utype}:{sub}"
                except Exception:
                    pass
        if not ident:
            ident = f"ip:{_extract_ip(request)}"

        allowed, _, retry_after = await rate_limiter.check(
            f"{scope}:{ident}", limit=limit, window_seconds=window_seconds
        )
        if not allowed:
            raise BusinessException(
                f"请求过于频繁，请约 {retry_after} 秒后再试",
                code=42902,
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )

    return _guard
