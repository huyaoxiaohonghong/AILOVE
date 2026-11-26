from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class MascotProfile(Base, TimestampMixin):
    """看板娘「恋恋」专属情感状态与羁绊档案（PAD 情感向量 + 亲密等级 + 心情打卡趋势）。"""

    __tablename__ = "mascot_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_scope: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False, comment="归属作用域: web:1 / miniapp:2"
    )
    user_type: Mapped[str] = mapped_column(
        String(16), default="web", nullable=False, comment="web / miniapp"
    )
    user_id: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False, comment="用户ID")
    valence: Mapped[float] = mapped_column(
        Float, default=0.25, nullable=False, comment="PAD 愉悦度 [-1.0, 1.0]"
    )
    arousal: Mapped[float] = mapped_column(
        Float, default=0.35, nullable=False, comment="PAD 唤醒度 [0.0, 1.0]"
    )
    affinity: Mapped[float] = mapped_column(
        Float, default=12.0, nullable=False, comment="亲密羁绊值 [0.0, 100.0]"
    )
    interaction_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="累计互动次数"
    )
    pet_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="累计摸头/贴贴次数"
    )
    mood_checkin_date: Mapped[str] = mapped_column(
        String(16), default="", nullable=False, comment="最近一次心情打卡日期 YYYY-MM-DD"
    )
    mood_checkin_score: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="最近一次心情分 1~5"
    )
    mood_history_json: Mapped[str] = mapped_column(
        Text, default="[]", nullable=False, comment="近 14 天心情打卡记录 JSON"
    )
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="最近活跃时间 (UTC naive)"
    )


class MascotMemory(Base, TimestampMixin):
    """恋恋情景事件记忆（结合艾宾浩斯遗忘/强化衰减曲线动态召回）。"""

    __tablename__ = "mascot_memories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_scope: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False, comment="归属作用域: web:1 / miniapp:2"
    )
    category: Mapped[str] = mapped_column(
        String(24), default="event", nullable=False, comment="event/preference/emotion/milestone/taboo"
    )
    summary: Mapped[str] = mapped_column(
        String(160), default="", nullable=False, comment="提炼后的简洁情景记忆"
    )
    keywords_json: Mapped[str] = mapped_column(
        Text, default="[]", nullable=False, comment="关键词列表 JSON"
    )
    importance: Mapped[float] = mapped_column(
        Float, default=2.5, nullable=False, comment="重要度权重 [1.0, 5.0]"
    )
    valence: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False, comment="情绪效价 [-1.0, 1.0]"
    )
    recall_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="累计召回强化次数"
    )
    last_recalled_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="最近召回时间 (UTC naive)"
    )
