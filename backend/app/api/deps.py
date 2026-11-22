from __future__ import annotations

from typing import Any

import jwt
from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import BusinessException
from app.core.security import decode_access_token
from app.services.session_service import session_service

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_token_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    """解析并校验 Bearer Token；对网站/管理端会话实时校验 Redis 多点会话状态（24 小时过期与撤销生效）。"""
    if credentials is None or not credentials.credentials:
        raise BusinessException(
            "未登录或登录凭证缺失",
            code=40100,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError as exc:
        raise BusinessException(
            "登录已超过 24 小时自动过期，请重新登录",
            code=40104,
            status_code=status.HTTP_401_UNAUTHORIZED,
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise BusinessException(
            "无效的登录凭证",
            code=40105,
            status_code=status.HTTP_401_UNAUTHORIZED,
        ) from exc

    # 对网站端/管理端用户实时校验 Redis 会话是否仍然活跃（支持单端退出、多点踢下线与 24h 自动过期）
    if payload.get("type") in {"admin", "user"}:
        jti = str(payload.get("jti", ""))
        session_info = await session_service.validate_and_touch_session(jti)
        if session_info is None:
            raise BusinessException(
                "当前会话已过期或已在其他终端下线，请重新登录",
                code=40106,
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        payload["_session"] = session_info

    return payload


async def get_current_web_user(
    payload: dict[str, Any] = Depends(get_current_token_payload),
) -> dict[str, Any]:
    """校验当前请求为已登录网站端用户（包含普通注册用户、管理员分配用户与管理员）。"""
    if payload.get("type") not in {"admin", "user"}:
        raise BusinessException(
            "无权访问网站端接口",
            code=40300,
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return payload


async def get_current_admin(
    payload: dict[str, Any] = Depends(get_current_token_payload),
) -> dict[str, Any]:
    """校验当前请求为后台管理员身份。"""
    if payload.get("type") != "admin" or payload.get("role") not in {"super_admin", "admin"}:
        raise BusinessException(
            "仅管理员有权访问该接口",
            code=40300,
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return payload


async def get_current_miniapp_user(
    payload: dict[str, Any] = Depends(get_current_token_payload),
) -> dict[str, Any]:
    """校验当前请求为小程序用户身份。"""
    if payload.get("type") != "miniapp":
        raise BusinessException(
            "无权访问小程序接口",
            code=40303,
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return payload
