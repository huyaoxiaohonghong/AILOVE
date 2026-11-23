from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SysRole(Base, TimestampMixin):
    """RBAC 角色与权限映射表。"""

    __tablename__ = "sys_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        index=True,
        nullable=False,
        comment="角色唯一标识: super_admin / admin / operator / user",
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="角色展示名称")
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False, comment="角色职责说明")
    permissions: Mapped[str] = mapped_column(
        Text, default="[]", nullable=False, comment="授予权限码列表 JSON"
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否为系统内置保护角色"
    )
    is_admin_portal: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否允许进入管理中台视图"
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False, comment="排序权重")
