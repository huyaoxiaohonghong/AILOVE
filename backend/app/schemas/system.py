from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class RoleCreateRequest(BaseModel):
    code: str = Field(
        ...,
        min_length=2,
        max_length=32,
        pattern=r"^[a-z][a-z0-9_]{1,31}$",
        description="角色唯一编码（小写字母开头，含字母/数字/下划线）",
    )
    name: str = Field(..., min_length=1, max_length=64, description="角色展示名称")
    description: str = Field(default="", max_length=255, description="职责说明")
    permissions: list[str] = Field(default_factory=list, description="授予的权限码列表")
    is_admin_portal: bool = Field(default=True, description="是否允许登录管理后台工作台")
    is_enabled: bool = Field(default=True, description="是否启用")
    sort_order: int = Field(default=100, ge=0, le=9999)


class RoleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=255)
    permissions: list[str] | None = None
    is_admin_portal: bool | None = None
    is_enabled: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=9999)


class AccountRoleUpdate(BaseModel):
    role: str = Field(..., min_length=2, max_length=32, description="目标角色编码")


class SysConfigBatchUpdateRequest(BaseModel):
    items: dict[str, Any] = Field(
        ...,
        min_length=1,
        description="待更新的配置键值对 {config_key: value}",
    )


class SysConfigResetRequest(BaseModel):
    group_name: str | None = Field(
        default=None,
        description="指定重置的分组名（留空重置全部系统配置）",
    )


class SmtpTestRequest(BaseModel):
    to_email: str = Field(..., min_length=5, max_length=254, description="测试收件邮箱地址")


class AlertWebhookTestRequest(BaseModel):
    message: str = Field(default="", max_length=200, description="可选的自定义测试告警文案")


class AuditLogCleanupRequest(BaseModel):
    retention_days: int | None = Field(
        default=None,
        ge=1,
        le=3650,
        description="保留最近 N 天日志（留空按系统配置 log.retention_days 执行）",
    )
    target: Literal["audit", "login", "all"] = Field(
        default="all",
        description="清理范围: audit / login / all",
    )


class AuditLogItem(BaseModel):
    id: int
    request_id: str
    user_id: int | None = None
    username: str
    role: str
    module: str
    action: str
    method: str
    path: str
    status_code: int
    result: str
    ip: str
    device_label: str
    duration_ms: int
    request_summary: str
    error_message: str
    created_at: datetime | None = None
