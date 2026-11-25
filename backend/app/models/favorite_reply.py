from __future__ import annotations

from sqlalchemy import BigInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class FavoriteReply(Base, TimestampMixin):
    """用户高情商话术收藏表（跨端共享：支持帮我回消息、先别发柔化与自由对话收藏）。"""

    __tablename__ = "user_favorite_replies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_scope: Mapped[str] = mapped_column(
        String(32), index=True, nullable=False, comment="归属标识 (web:1 / miniapp:2)"
    )
    user_type: Mapped[str] = mapped_column(String(16), default="web", nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    category: Mapped[str] = mapped_column(
        String(32),
        default="reply_helper",
        nullable=False,
        comment="来源分类: reply_helper / soften / chat / custom",
    )
    scene_label: Mapped[str] = mapped_column(
        String(64), default="", nullable=False, comment="场景或标签快照"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="收藏的高情商话术正文")
    note: Mapped[str] = mapped_column(String(255), default="", nullable=False, comment="个人备注")
