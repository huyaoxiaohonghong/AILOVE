from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class WechatUser(Base, TimestampMixin):
    """微信小程序用户表。"""

    __tablename__ = "wechat_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    openid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="微信 OpenID")
    unionid: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True, comment="UnionID")
    nickname: Mapped[str] = mapped_column(String(64), default="微信用户", nullable=False, comment="昵称")
    avatar_url: Mapped[str] = mapped_column(String(512), default="", nullable=False, comment="头像")
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="手机号")
    status: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False, comment="1正常 0禁用")
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="最后登录时间"
    )
