from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.db.mysql import get_session_factory
from app.db.redis import get_redis
from app.models.login_log import LoginLog

logger = logging.getLogger(__name__)

# Redis / MySQL 离线时的本地开发降级存储（仅无外部中间件的本地开发/单元测试生效）
_mem_sessions: dict[str, tuple[float, dict[str, Any]]] = {}
_mem_user_sessions: dict[int, set[str]] = {}
_mem_fail_counts: dict[str, tuple[float, int]] = {}
_mem_locks: dict[str, float] = {}
_mem_login_logs: list[dict[str, Any]] = []


def parse_device_label(user_agent: str) -> str:
    """将 User-Agent 解析为人类可读的操作系统 + 浏览器标签。"""
    ua = (user_agent or "").strip()
    if not ua:
        return "未知设备"
    ua_l = ua.lower()

    if "iphone" in ua_l:
        os_name = "iPhone"
    elif "ipad" in ua_l:
        os_name = "iPad"
    elif "android" in ua_l:
        os_name = "Android"
    elif "mac os x" in ua_l or "macintosh" in ua_l:
        os_name = "macOS"
    elif "windows" in ua_l:
        os_name = "Windows"
    elif "linux" in ua_l:
        os_name = "Linux"
    else:
        os_name = "其他系统"

    if "micromessenger" in ua_l:
        browser = "微信内置浏览器"
    elif "edg/" in ua_l:
        browser = "Edge"
    elif "chrome/" in ua_l or "crios/" in ua_l:
        browser = "Chrome"
    elif "firefox/" in ua_l:
        browser = "Firefox"
    elif "safari/" in ua_l and "chrome/" not in ua_l:
        browser = "Safari"
    elif "python" in ua_l or "httpx" in ua_l or "curl" in ua_l:
        return "API 客户端"
    else:
        browser = "浏览器"

    return f"{os_name} · {browser}"


def _iso_from_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()


class SessionService:
    """基于 Redis 的多点登录会话管理服务（支持 24 小时自动过期、并发设备上限与即时踢下线）。"""

    def _session_key(self, jti: str) -> str:
        return f"ailove:session:{jti}"

    def _user_set_key(self, user_id: int) -> str:
        return f"ailove:user:sessions:{user_id}"

    def _prune_mem(self) -> None:
        now = time.time()
        expired = [k for k, (exp, _) in _mem_sessions.items() if exp <= now]
        for jti in expired:
            _, data = _mem_sessions.pop(jti)
            uid = int(data.get("user_id", 0))
            if uid in _mem_user_sessions:
                _mem_user_sessions[uid].discard(jti)

    async def _get_session_raw(self, jti: str) -> dict[str, Any] | None:
        try:
            client = get_redis()
            raw = await client.get(self._session_key(jti))
            if raw:
                return json.loads(raw)
            return None
        except Exception:
            self._prune_mem()
            item = _mem_sessions.get(jti)
            return dict(item[1]) if item else None

    async def _put_session_raw(self, jti: str, data: dict[str, Any], ttl_seconds: int) -> None:
        ttl = max(1, int(ttl_seconds))
        try:
            client = get_redis()
            await client.set(
                self._session_key(jti),
                json.dumps(data, ensure_ascii=False),
                ex=ttl,
            )
            uid = int(data["user_id"])
            set_key = self._user_set_key(uid)
            await client.sadd(set_key, jti)
            await client.expire(set_key, ttl + 3600)
        except Exception:
            self._prune_mem()
            _mem_sessions[jti] = (time.time() + ttl, dict(data))
            uid = int(data["user_id"])
            _mem_user_sessions.setdefault(uid, set()).add(jti)

    async def _del_session_raw(self, user_id: int, jti: str) -> None:
        try:
            client = get_redis()
            await client.delete(self._session_key(jti))
            await client.srem(self._user_set_key(user_id), jti)
        except Exception:
            _mem_sessions.pop(jti, None)
            if user_id in _mem_user_sessions:
                _mem_user_sessions[user_id].discard(jti)

    async def create_session(
        self,
        *,
        user_id: int,
        jti: str,
        role: str,
        ip: str = "",
        user_agent: str = "",
        ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        """创建新的设备会话；超出多点登录设备上限时自动按 FIFO 淘汰最早登录的会话。"""
        from app.services import sys_config_service

        settings = get_settings()
        if ttl_seconds is not None:
            ttl = ttl_seconds
        else:
            ttl_hours = await sys_config_service.get_int(
                "security.session_ttl_hours",
                default=max(1, settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES // 60),
            )
            ttl = ttl_hours * 3600
        max_sessions = max(
            1,
            await sys_config_service.get_int(
                "security.max_sessions_per_user", default=settings.MAX_SESSIONS_PER_USER
            ),
        )

        existing = await self.list_user_sessions(user_id)
        if len(existing) >= max_sessions:
            # 按登录时间从旧到新排序，淘汰多余的最早会话
            existing_sorted = sorted(existing, key=lambda s: float(s.get("login_at_ts", 0)))
            evict_count = len(existing_sorted) - max_sessions + 1
            for old in existing_sorted[:evict_count]:
                await self._del_session_raw(user_id, str(old["session_id"]))
                logger.info(
                    "Evicted oldest session %s for user_id=%s (limit=%s)",
                    old["session_id"][:8],
                    user_id,
                    max_sessions,
                )

        now = time.time()
        expires_at_ts = now + ttl
        record = {
            "session_id": jti,
            "user_id": user_id,
            "role": role,
            "ip": ip or "unknown",
            "device_label": parse_device_label(user_agent),
            "user_agent": (user_agent or "")[:256],
            "login_at_ts": now,
            "last_active_ts": now,
            "expires_at_ts": expires_at_ts,
            "login_at": _iso_from_ts(now),
            "last_active_at": _iso_from_ts(now),
            "expires_at": _iso_from_ts(expires_at_ts),
        }
        await self._put_session_raw(jti, record, ttl)
        return record

    async def validate_and_touch_session(self, jti: str) -> dict[str, Any] | None:
        """校验会话是否仍有效（未 24 小时过期且未被撤销），并节流刷新最后活跃时间（不延长 24 小时硬过期）。"""
        if not jti:
            return None
        record = await self._get_session_raw(jti)
        if record is None:
            return None

        now = time.time()
        expires_at_ts = float(record.get("expires_at_ts", 0))
        if expires_at_ts <= now:
            await self._del_session_raw(int(record.get("user_id", 0)), jti)
            return None

        # 每 60 秒节流刷新一次 last_active_at，同时严格保持剩余 TTL 不变（24小时硬过期）
        last_active_ts = float(record.get("last_active_ts", 0))
        if now - last_active_ts >= 60:
            record["last_active_ts"] = now
            record["last_active_at"] = _iso_from_ts(now)
            remaining = max(1, int(expires_at_ts - now))
            await self._put_session_raw(jti, record, remaining)

        return record

    async def list_user_sessions(
        self, user_id: int, current_jti: str = ""
    ) -> list[dict[str, Any]]:
        """列出用户当前所有在线会话，并自动清理已 24 小时自然过期的会话索引。"""
        jtis: set[str] = set()
        using_redis = False
        try:
            client = get_redis()
            members = await client.smembers(self._user_set_key(user_id))
            jtis = set(members)
            using_redis = True
        except Exception:
            self._prune_mem()
            jtis = set(_mem_user_sessions.get(user_id, set()))

        now = time.time()
        active: list[dict[str, Any]] = []
        stale: list[str] = []

        for jti in jtis:
            record = await self._get_session_raw(jti)
            if record is None or float(record.get("expires_at_ts", 0)) <= now:
                stale.append(jti)
                continue
            remaining = max(0, int(float(record["expires_at_ts"]) - now))
            active.append(
                {
                    "session_id": record["session_id"],
                    "ip": record.get("ip", ""),
                    "device_label": record.get("device_label", "未知设备"),
                    "login_at": record.get("login_at", ""),
                    "last_active_at": record.get("last_active_at", ""),
                    "expires_at": record.get("expires_at", ""),
                    "login_at_ts": record.get("login_at_ts", 0),
                    "remaining_seconds": remaining,
                    "is_current": record["session_id"] == current_jti,
                }
            )

        if stale:
            if using_redis:
                try:
                    await get_redis().srem(self._user_set_key(user_id), *stale)
                except Exception:
                    pass
            else:
                for s_jti in stale:
                    _mem_user_sessions.get(user_id, set()).discard(s_jti)

        active.sort(key=lambda s: (not s["is_current"], -float(s.get("login_at_ts", 0))))
        return active

    async def count_user_sessions(self, user_id: int) -> int:
        return len(await self.list_user_sessions(user_id))

    async def count_total_active_sessions(self) -> int:
        try:
            client = get_redis()
            count = 0
            async for _ in client.scan_iter(match="ailove:session:*", count=200):
                count += 1
            return count
        except Exception:
            self._prune_mem()
            return len(_mem_sessions)

    async def revoke_session(self, user_id: int, jti: str) -> bool:
        """撤销指定用户的单个设备会话。"""
        record = await self._get_session_raw(jti)
        if record is None:
            await self._del_session_raw(user_id, jti)
            return False
        if int(record.get("user_id", -1)) != user_id:
            return False
        await self._del_session_raw(user_id, jti)
        return True

    async def revoke_other_sessions(self, user_id: int, keep_jti: str) -> int:
        """下线除当前设备外的全部其他在线终端。"""
        sessions = await self.list_user_sessions(user_id, current_jti=keep_jti)
        revoked = 0
        for s in sessions:
            if s["session_id"] != keep_jti:
                await self._del_session_raw(user_id, s["session_id"])
                revoked += 1
        return revoked

    async def revoke_all_sessions(self, user_id: int) -> int:
        """强制下线指定用户的全部设备（管理员踢下线 / 禁用账号 / 重置密码时触发）。"""
        sessions = await self.list_user_sessions(user_id)
        for s in sessions:
            await self._del_session_raw(user_id, s["session_id"])
        return len(sessions)


class LoginRateLimiter:
    """登录防爆破锁定器：同一账号连续密码错误达到阈值后自动临时锁定。"""

    def _fail_key(self, account_key: str) -> str:
        return f"ailove:auth:fail:{account_key}"

    def _lock_key(self, account_key: str) -> str:
        return f"ailove:auth:lock:{account_key}"

    async def check_locked(self, account_key: str) -> tuple[bool, int]:
        key = account_key.strip().lower()
        try:
            client = get_redis()
            ttl = await client.ttl(self._lock_key(key))
            if ttl and ttl > 0:
                return True, int(ttl)
            return False, 0
        except Exception:
            now = time.time()
            exp = _mem_locks.get(key, 0.0)
            if exp > now:
                return True, max(1, int(exp - now))
            _mem_locks.pop(key, None)
            return False, 0

    async def record_failure(self, account_key: str) -> tuple[int, bool, int]:
        """记录一次密码错误，返回 (当前失败次数, 是否刚触发锁定, 剩余可尝试次数)。"""
        from app.services import sys_config_service

        settings = get_settings()
        max_fails = max(
            1,
            await sys_config_service.get_int(
                "security.login_max_fail_attempts", default=settings.LOGIN_MAX_FAIL_ATTEMPTS
            ),
        )
        lock_minutes = max(
            1,
            await sys_config_service.get_int(
                "security.login_lock_minutes", default=settings.LOGIN_LOCK_MINUTES
            ),
        )
        lock_seconds = max(60, lock_minutes * 60)
        key = account_key.strip().lower()

        try:
            client = get_redis()
            fkey = self._fail_key(key)
            count = int(await client.incr(fkey))
            if count == 1:
                await client.expire(fkey, lock_seconds)
            if count >= max_fails:
                await client.set(self._lock_key(key), "1", ex=lock_seconds)
                await client.delete(fkey)
                return count, True, 0
            return count, False, max(0, max_fails - count)
        except Exception:
            now = time.time()
            exp, cur = _mem_fail_counts.get(key, (0.0, 0))
            count = (cur + 1) if exp > now else 1
            if count >= max_fails:
                _mem_locks[key] = now + lock_seconds
                _mem_fail_counts.pop(key, None)
                return count, True, 0
            _mem_fail_counts[key] = (now + lock_seconds, count)
            return count, False, max(0, max_fails - count)

    async def clear_failures(self, account_key: str) -> None:
        key = account_key.strip().lower()
        try:
            client = get_redis()
            await client.delete(self._fail_key(key), self._lock_key(key))
        except Exception:
            _mem_fail_counts.pop(key, None)
            _mem_locks.pop(key, None)


async def record_login_log(
    *,
    user_id: int | None,
    account: str,
    ip: str,
    user_agent: str,
    status: str,
    fail_reason: str = "",
) -> None:
    """记录登录安全审计日志（MySQL 持久化，无库开发模式自动降级内存）。"""
    device_label = parse_device_label(user_agent)
    ua_short = (user_agent or "")[:500]
    try:
        factory = get_session_factory()
        async with factory() as session:
            session.add(
                LoginLog(
                    user_id=user_id,
                    account=account[:191],
                    ip=(ip or "")[:64],
                    device_label=device_label[:128],
                    user_agent=ua_short,
                    status=status,
                    fail_reason=fail_reason[:255],
                )
            )
            await session.commit()
    except (SQLAlchemyError, OSError) as exc:
        logger.debug("Login log DB write skipped: %s", exc)
        _mem_login_logs.insert(
            0,
            {
                "id": len(_mem_login_logs) + 1,
                "user_id": user_id,
                "account": account[:191],
                "ip": ip or "",
                "device_label": device_label,
                "status": status,
                "fail_reason": fail_reason,
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
        del _mem_login_logs[100:]


async def list_user_login_logs(user_id: int, limit: int = 20) -> list[dict[str, Any]]:
    """查询指定用户的近期登录安全审计日志。"""
    try:
        factory = get_session_factory()
        async with factory() as session:
            stmt = (
                select(LoginLog)
                .where(LoginLog.user_id == user_id)
                .order_by(LoginLog.id.desc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [
                {
                    "id": row.id,
                    "account": row.account,
                    "ip": row.ip,
                    "device_label": row.device_label,
                    "status": row.status,
                    "fail_reason": row.fail_reason,
                    "created_at": row.created_at.isoformat() if row.created_at else "",
                }
                for row in rows
            ]
    except (SQLAlchemyError, OSError):
        return [item for item in _mem_login_logs if item.get("user_id") == user_id][:limit]


session_service = SessionService()
login_rate_limiter = LoginRateLimiter()
