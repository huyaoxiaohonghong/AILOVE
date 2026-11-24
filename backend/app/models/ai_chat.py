from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class AIConversation(Base, TimestampMixin):
    """AI 对话会话表。"""

    __tablename__ = "ai_conversations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="会话ID")
    user_type: Mapped[str] = mapped_column(
        String(16), default="miniapp", nullable=False, comment="admin / miniapp"
    )
    user_id: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False, comment="用户ID")
    title: Mapped[str] = mapped_column(String(128), default="新对话", nullable=False, comment="标题")
    model_name: Mapped[str] = mapped_column(String(64), default="", nullable=False, comment="模型名")
    persona_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True, comment="绑定的智能体ID"
    )
    persona_name: Mapped[str] = mapped_column(
        String(64), default="", nullable=False, comment="绑定的智能体名称快照"
    )
    is_pinned: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否置顶会话"
    )

    messages: Mapped[list[AIMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
    )


class AIMessage(Base, TimestampMixin):
    """AI 对话消息记录表。"""

    __tablename__ = "ai_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ai_conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, comment="system/user/assistant")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="消息内容")
    token_usage: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="Token消耗")

    conversation: Mapped[AIConversation] = relationship(back_populates="messages")
