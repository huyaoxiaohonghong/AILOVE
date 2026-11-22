from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class WechatUserItem(BaseModel):
    id: int
    openid: str
    nickname: str
    avatar_url: str = ""
    phone: str | None = None
    status: int = 1
    last_login_at: datetime | None = None
    created_at: datetime | None = None


class WechatUserStatusUpdate(BaseModel):
    status: int = Field(..., ge=0, le=1, description="1正常 0禁用")
