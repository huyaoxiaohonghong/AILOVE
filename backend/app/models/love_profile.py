from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class UserLoveProfile(Base, TimestampMixin):
    """用户恋爱状态与情感背景记忆卡（按 owner_scope 严格隔离，可选自动注入 AI 对话上下文）。"""

    __tablename__ = "user_love_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_scope: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False, comment="归属作用域: web:1 / miniapp:2"
    )
    user_type: Mapped[str] = mapped_column(
        String(16), default="web", nullable=False, comment="web / miniapp"
    )
    user_id: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False, comment="用户ID")
    relationship_stage: Mapped[str] = mapped_column(
        String(32), default="", nullable=False, comment="当前情感阶段编码"
    )
    partner_nickname: Mapped[str] = mapped_column(
        String(32), default="", nullable=False, comment="对方称呼/昵称"
    )
    partner_traits_json: Mapped[str] = mapped_column(
        Text, default="[]", nullable=False, comment="对方性格与依恋标签 JSON"
    )
    my_traits_json: Mapped[str] = mapped_column(
        Text, default="[]", nullable=False, comment="自我沟通特点标签 JSON"
    )
    relationship_goal: Mapped[str] = mapped_column(
        String(160), default="", nullable=False, comment="当前核心情感诉求/目标"
    )
    communication_taboos: Mapped[str] = mapped_column(
        String(300), default="", nullable=False, comment="沟通雷区与注意事项"
    )
    background_notes: Mapped[str] = mapped_column(
        Text, default="", nullable=False, comment="补充情感背景摘要"
    )
    auto_inject: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="对话时是否自动注入上下文"
    )
