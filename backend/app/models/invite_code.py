from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class InviteCode(Base, TimestampMixin):
    """小圈子内测邀请码表（限次/限时控制注册与微信小程序准入）。"""

    __tablename__ = "invite_codes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, nullable=False, comment="邀请码（全大写）"
    )
    note: Mapped[str] = mapped_column(String(128), default="", nullable=False, comment="用途/对象备注")
    max_uses: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False, comment="最大可用次数，0 表示不限次"
    )
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="已核销次数")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="过期时间")
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="创建管理员 ID")
