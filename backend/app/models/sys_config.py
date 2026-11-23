from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SysConfig(Base, TimestampMixin):
    """动态系统参数配置表（支持热生效与分级公开）。"""

    __tablename__ = "sys_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_key: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False, comment="配置唯一键"
    )
    group_name: Mapped[str] = mapped_column(
        String(32), index=True, nullable=False, comment="配置分组: site / security / registration / ai / log"
    )
    label: Mapped[str] = mapped_column(String(64), nullable=False, comment="配置中文名称")
    value_type: Mapped[str] = mapped_column(
        String(16), default="string", nullable=False, comment="string / int / float / bool / json"
    )
    config_value: Mapped[str] = mapped_column(Text, default="", nullable=False, comment="当前生效值")
    default_value: Mapped[str] = mapped_column(Text, default="", nullable=False, comment="系统默认值")
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False, comment="参数说明")
    is_public: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否向登录前公共接口公开"
    )
    is_secret: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否为敏感参数"
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False, comment="排序权重")
    updated_by: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="最后修改管理员ID"
    )
