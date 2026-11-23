from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AIUsageLog(Base):
    """AI 对话调用明细与 Token 用量流水表。"""

    __tablename__ = "ai_usage_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_scope: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False, comment="调用者标识: web:1 / miniapp:2"
    )
    user_type: Mapped[str] = mapped_column(
        String(16), default="web", nullable=False, comment="用户端类型: web / miniapp"
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, default=0, index=True, nullable=False, comment="用户 ID"
    )
    username: Mapped[str] = mapped_column(
        String(64), default="", nullable=False, comment="用户名快照"
    )
    session_id: Mapped[str] = mapped_column(
        String(128), index=True, default="", nullable=False, comment="会话 ID"
    )
    persona_id: Mapped[int | None] = mapped_column(
        BigInteger, index=True, nullable=True, comment="使用的智能体 ID"
    )
    persona_name: Mapped[str] = mapped_column(
        String(64), default="", nullable=False, comment="智能体名称快照"
    )
    provider: Mapped[str] = mapped_column(
        String(32), default="deepseek", nullable=False, comment="模型提供商"
    )
    model_name: Mapped[str] = mapped_column(
        String(64), index=True, default="", nullable=False, comment="模型名称"
    )
    prompt_tokens: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="输入 Token 数"
    )
    completion_tokens: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="输出 Token 数"
    )
    total_tokens: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="总 Token 数"
    )
    latency_ms: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="端到端响应耗时(毫秒)"
    )
    is_stream: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否流式调用"
    )
    is_mock: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否 Mock 兜底"
    )
    status: Mapped[str] = mapped_column(
        String(16), index=True, default="success", nullable=False, comment="调用状态: success / failed"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True, nullable=False, comment="调用时间"
    )
