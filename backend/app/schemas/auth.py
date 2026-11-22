from __future__ import annotations

from pydantic import BaseModel, Field


class EmailCheckRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254, description="待检测的邮箱地址")


class EmailRegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254, description="正规公共邮箱地址")
    password: str = Field(..., min_length=8, max_length=128, description="登录密码（至少8位且含字母与数字）")
    nickname: str | None = Field(default=None, max_length=64, description="用户昵称（可选）")
    captcha_token: str = Field(..., min_length=16, max_length=128, description="滑动验证通过后的一次性票据")


class AccountLoginRequest(BaseModel):
    account: str = Field(..., min_length=2, max_length=254, description="邮箱或管理员用户名")
    password: str = Field(..., min_length=6, max_length=128, description="登录密码")
    captcha_token: str = Field(..., min_length=16, max_length=128, description="滑动验证通过后的一次性票据")


class AdminLoginRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=254, description="管理员用户名或邮箱")
    password: str = Field(..., min_length=6, max_length=128, description="登录密码")
    captcha_token: str = Field(..., min_length=16, max_length=128, description="滑动验证通过后的一次性票据")


class UserProfile(BaseModel):
    id: int
    username: str | None = None
    email: str
    nickname: str
    role: str
    register_source: str = "email_register"
    email_provider: str = ""
    email_trust_score: int = 100
    auth_mode: str = "mysql"


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    session_id: str = ""
    expires_at: str = ""
    user: UserProfile


class UpdateProfileRequest(BaseModel):
    nickname: str = Field(..., min_length=1, max_length=64, description="新的用户昵称")


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=6, max_length=128, description="当前密码")
    new_password: str = Field(
        ..., min_length=8, max_length=128, description="新密码（至少8位且含字母与数字）"
    )
    logout_other_devices: bool = Field(
        default=True, description="修改密码后是否自动下线其他在线设备"
    )


class WxLoginRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=128, description="wx.login 获取的临时登录凭证")
    nickname: str | None = Field(default=None, max_length=64, description="用户昵称（可选）")
    avatar_url: str | None = Field(default=None, max_length=512, description="用户头像（可选）")


class MiniappUserProfile(BaseModel):
    id: int
    openid: str
    nickname: str
    avatar_url: str
    phone: str | None = None
    status: int = 1


class WxLoginResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: MiniappUserProfile
    is_mock_wx: bool = False
