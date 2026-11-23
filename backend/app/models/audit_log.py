from __future__ import annotations

from sqlalchemy import BigInteger, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AuditLog(Base, TimestampMixin):
    """系统操作与安全审计日志表。"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False, comment="链路请求ID")
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, index=True, nullable=True, comment="操作人用户ID"
    )
    username: Mapped[str] = mapped_column(
        String(128), default="anonymous", nullable=False, comment="操作人标识"
    )
    role: Mapped[str] = mapped_column(String(32), default="anonymous", nullable=False, comment="操作人角色")
    module: Mapped[str] = mapped_column(String(32), index=True, nullable=False, comment="业务模块")
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False, comment="操作语义描述")
    method: Mapped[str] = mapped_column(String(10), nullable=False, comment="HTTP 方法")
    path: Mapped[str] = mapped_column(String(255), index=True, nullable=False, comment="请求路径")
    status_code: Mapped[int] = mapped_column(Integer, index=True, nullable=False, comment="HTTP 状态码")
    result: Mapped[str] = mapped_column(
        String(16), index=True, default="success", nullable=False, comment="success / denied / error"
    )
    ip: Mapped[str] = mapped_column(String(64), default="", nullable=False, comment="客户端IP")
    device_label: Mapped[str] = mapped_column(
        String(128), default="", nullable=False, comment="设备与浏览器描述"
    )
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="耗时(ms)")
    request_summary: Mapped[str] = mapped_column(
        Text, default="", nullable=False, comment="脱敏后的请求摘要 JSON"
    )
    error_message: Mapped[str] = mapped_column(
        String(255), default="", nullable=False, comment="错误或拦截摘要"
    )
