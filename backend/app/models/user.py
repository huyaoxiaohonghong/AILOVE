from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    """平台统一用户表（支持邮箱自主注册、管理员分配创建与系统管理员）。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True, comment="登录用户名（管理员或可选别名）"
    )
    email: Mapped[str] = mapped_column(
        String(191), unique=True, nullable=False, comment="规范化后的邮箱地址"
    )
    canonical_email: Mapped[str] = mapped_column(
        String(191), unique=True, nullable=False, comment="去别名归一化邮箱（防同邮箱多注册）"
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="bcrypt 密码哈希")
    nickname: Mapped[str] = mapped_column(String(64), default="", nullable=False, comment="用户昵称")
    role: Mapped[str] = mapped_column(
        String(32), default="user", nullable=False, comment="角色: super_admin / admin / user"
    )
    register_source: Mapped[str] = mapped_column(
        String(32),
        default="email_register",
        nullable=False,
        comment="来源: email_register / admin_assigned / system_bootstrap",
    )
    email_provider: Mapped[str] = mapped_column(
        String(64), default="", nullable=False, comment="识别出的邮箱服务商"
    )
    email_trust_score: Mapped[int] = mapped_column(
        Integer, default=100, nullable=False, comment="注册时邮箱可信度评分 (0-100)"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="分配创建该用户的管理员ID"
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="最后登录时间"
    )
