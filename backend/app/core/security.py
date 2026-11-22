from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings


def hash_password(plain_password: str) -> str:
    """使用 bcrypt 对明文密码进行单向哈希。"""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """校验明文密码与 bcrypt 哈希是否匹配。"""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(
    subject: str,
    user_type: str,
    extra: dict[str, Any] | None = None,
    expires_minutes: int | None = None,
    jti: str | None = None,
) -> tuple[str, int, str]:
    """签发带唯一会话 jti 的 JWT Access Token，返回 (token, expires_in_seconds, jti)。"""
    settings = get_settings()
    expire_mins = expires_minutes or settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    now = datetime.now(UTC)
    expire_at = now + timedelta(minutes=expire_mins)
    session_jti = jti or secrets.token_hex(16)

    payload: dict[str, Any] = {
        "sub": subject,
        "type": user_type,  # "admin" | "user" | "miniapp"
        "jti": session_jti,
        "iat": int(now.timestamp()),
        "exp": int(expire_at.timestamp()),
    }
    if extra:
        payload.update(extra)

    token = jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    return token, expire_mins * 60, session_jti


def decode_access_token(token: str) -> dict[str, Any]:
    """解析并验证 JWT Token。"""
    settings = get_settings()
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
