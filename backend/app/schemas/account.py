from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AccountItem(BaseModel):
    id: int
    username: str | None = None
    email: str
    canonical_email: str
    nickname: str
    role: str
    register_source: str
    email_provider: str = ""
    email_trust_score: int = 100
    is_active: bool = True
    online_sessions: int = 0
    created_by: int | None = None
    last_login_at: datetime | None = None
    created_at: datetime | None = None


class AdminCreateAccountRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254, description="用户邮箱")
    password: str = Field(..., min_length=8, max_length=128, description="初始密码（至少8位且含字母与数字）")
    nickname: str = Field(..., min_length=1, max_length=64, description="用户昵称")
    username: str | None = Field(default=None, max_length=64, description="可选登录用户名")
    role: Literal["user", "admin"] = Field(default="user", description="分配角色: user / admin")
    allow_non_mainstream_email: bool = Field(
        default=False,
        description="管理员特权：是否允许为内部成员分配非常规/域名邮箱",
    )


class AccountStatusUpdate(BaseModel):
    is_active: bool = Field(..., description="true 启用 / false 禁用")


class AccountResetPasswordRequest(BaseModel):
    new_password: str = Field(
        ..., min_length=8, max_length=128, description="新密码（至少8位且含字母与数字）"
    )
