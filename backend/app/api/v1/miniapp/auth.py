from __future__ import annotations

from fastapi import APIRouter

from app.schemas.auth import WxLoginRequest
from app.schemas.common import ok
from app.services.auth_service import login_wechat_user

router = APIRouter(prefix="/auth", tags=["小程序-认证"])


@router.post("/wx-login", summary="微信小程序一键登录 (code 换取 token)")
async def miniapp_wx_login(req: WxLoginRequest):
    result = await login_wechat_user(req)
    return ok(result.model_dump())
