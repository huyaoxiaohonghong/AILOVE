from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AIPersona(Base, TimestampMixin):
    """AI 智能体 / Prompt 预设模板表。"""

    __tablename__ = "ai_personas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False, comment="智能体唯一编码"
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="智能体名称")
    avatar_emoji: Mapped[str] = mapped_column(
        String(16), default="🤖", nullable=False, comment="头像图标 Emoji"
    )
    category: Mapped[str] = mapped_column(
        String(32),
        index=True,
        default="general",
        nullable=False,
        comment="分类: general/writing/coding/translate/analysis",
    )
    description: Mapped[str] = mapped_column(
        String(255), default="", nullable=False, comment="一句话简介"
    )
    system_prompt: Mapped[str] = mapped_column(
        Text, nullable=False, comment="角色系统提示词"
    )
    starter_prompts_json: Mapped[str] = mapped_column(
        Text, default="[]", nullable=False, comment="开场白示例提示词 JSON 数组"
    )
    temperature: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="覆盖采样温度(为空则继承默认模型)"
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否系统预置智能体"
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, index=True, nullable=False, comment="是否启用"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, default=100, nullable=False, comment="排序(越小越靠前)"
    )
    usage_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="累计使用次数"
    )
