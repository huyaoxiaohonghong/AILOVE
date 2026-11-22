from __future__ import annotations

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class LoginLog(Base, TimestampMixin):
    """用户登录安全审计日志表。"""

    __tablename__ = "login_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True, comment="用户ID")
    account: Mapped[str] = mapped_column(String(191), nullable=False, comment="登录使用的账号/邮箱")
    ip: Mapped[str] = mapped_column(String(64), default="", nullable=False, comment="客户端IP")
    device_label: Mapped[str] = mapped_column(
        String(128), default="", nullable=False, comment="解析后的终端/浏览器描述"
    )
    user_agent: Mapped[str] = mapped_column(String(512), default="", nullable=False, comment="原始UA")
    status: Mapped[str] = mapped_column(
        String(16), default="success", nullable=False, comment="success / failed"
    )
    fail_reason: Mapped[str] = mapped_column(
        String(255), default="", nullable=False, comment="失败原因"
    )
