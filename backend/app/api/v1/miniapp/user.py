from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_current_miniapp_user
from app.schemas.common import ok

router = APIRouter(prefix="/user", tags=["小程序-用户"])


@router.get("/profile", summary="获取当前小程序用户资料")
async def get_miniapp_profile(
    current_user: dict[str, Any] = Depends(get_current_miniapp_user),
):
    return ok(
        {
            "id": current_user.get("sub"),
            "openid": current_user.get("openid", ""),
            "nickname": current_user.get("nickname", "微信用户"),
            "avatar_url": current_user.get("avatar_url", ""),
        }
    )
