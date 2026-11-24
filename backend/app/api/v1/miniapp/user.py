from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import get_current_miniapp_user
from app.core.exceptions import BusinessException
from app.db.mysql import get_session_factory
from app.models.wechat_user import WechatUser
from app.schemas.auth import MiniappProfileUpdateRequest
from app.schemas.common import ok

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/user", tags=["小程序-用户"])

# MySQL 离线时的小程序资料内存缓存（仅本地开发调试）
_mem_miniapp_profiles: dict[str, dict[str, Any]] = {}


def _fallback_profile(current_user: dict[str, Any]) -> dict[str, Any]:
    openid = str(current_user.get("openid", ""))
    cached = _mem_miniapp_profiles.get(openid)
    if cached:
        return dict(cached)
    raw_sub = str(current_user.get("sub", "0"))
    return {
        "id": int(raw_sub) if raw_sub.isdigit() else 0,
        "openid": openid,
        "nickname": str(current_user.get("nickname") or "微信用户"),
        "avatar_url": str(current_user.get("avatar_url") or ""),
        "status": 1,
    }


@router.get("/profile", summary="获取当前小程序用户最新资料")
async def get_miniapp_profile(
    current_user: dict[str, Any] = Depends(get_current_miniapp_user),
):
    openid = str(current_user.get("openid", ""))
    try:
        factory = get_session_factory()
        async with factory() as session:
            user = (
                await session.execute(select(WechatUser).where(WechatUser.openid == openid))
            ).scalar_one_or_none()
            if user is not None:
                return ok(
                    {
                        "id": user.id,
                        "openid": user.openid,
                        "nickname": user.nickname or "微信用户",
                        "avatar_url": user.avatar_url or "",
                        "phone": user.phone,
                        "status": user.status,
                    }
                )
    except (SQLAlchemyError, OSError) as exc:
        logger.debug("Miniapp profile DB read fallback: %s", exc)
    return ok(_fallback_profile(current_user))


@router.patch("/profile", summary="更新当前小程序用户昵称或头像")
async def update_miniapp_profile(
    req: MiniappProfileUpdateRequest,
    current_user: dict[str, Any] = Depends(get_current_miniapp_user),
):
    if req.nickname is None and req.avatar_url is None:
        raise BusinessException(
            "请提供需要更新的昵称或头像",
            code=40062,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    openid = str(current_user.get("openid", ""))
    clean_nick = req.nickname.strip()[:64] if req.nickname is not None else None
    clean_avatar = req.avatar_url.strip()[:512] if req.avatar_url is not None else None

    try:
        factory = get_session_factory()
        async with factory() as session:
            user = (
                await session.execute(select(WechatUser).where(WechatUser.openid == openid))
            ).scalar_one_or_none()
            if user is not None:
                if clean_nick is not None:
                    user.nickname = clean_nick or "微信用户"
                if clean_avatar is not None:
                    user.avatar_url = clean_avatar
                await session.commit()
                return ok(
                    {
                        "id": user.id,
                        "openid": user.openid,
                        "nickname": user.nickname,
                        "avatar_url": user.avatar_url or "",
                        "phone": user.phone,
                        "status": user.status,
                    },
                    message="个人资料已更新",
                )
    except (SQLAlchemyError, OSError) as exc:
        logger.debug("Miniapp profile DB write fallback: %s", exc)

    prof = _fallback_profile(current_user)
    if clean_nick is not None:
        prof["nickname"] = clean_nick or "微信用户"
    if clean_avatar is not None:
        prof["avatar_url"] = clean_avatar
    if openid:
        _mem_miniapp_profiles[openid] = prof
    return ok(prof, message="个人资料已更新")
