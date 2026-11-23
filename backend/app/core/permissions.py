from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionDef:
    code: str
    group: str
    group_label: str
    label: str
    description: str


PERMISSION_DEFS: tuple[PermissionDef, ...] = (
    PermissionDef(
        code="dashboard:view",
        group="dashboard",
        group_label="核心概览",
        label="查看系统控制台",
        description="查看后台概览统计指标、活跃会话与基础设施健康状态",
    ),
    PermissionDef(
        code="account:view",
        group="account",
        group_label="平台账号与分配",
        label="查看平台账号列表",
        description="查询平台用户账号、邮箱可信评分及实时在线设备数",
    ),
    PermissionDef(
        code="account:create",
        group="account",
        group_label="平台账号与分配",
        label="分配创建新账号",
        description="由管理员后台分配创建账号（支持特权内部邮箱分配）",
    ),
    PermissionDef(
        code="account:manage",
        group="account",
        group_label="平台账号与分配",
        label="账号风控与角色变更",
        description="启用/禁用账号、重置密码、强制踢下线以及调整账号角色",
    ),
    PermissionDef(
        code="miniapp_user:view",
        group="miniapp_user",
        group_label="小程序用户",
        label="查看小程序用户",
        description="分页查看微信小程序授权用户与登录记录",
    ),
    PermissionDef(
        code="miniapp_user:manage",
        group="miniapp_user",
        group_label="小程序用户",
        label="管理小程序用户",
        description="启用或禁用微信小程序端用户状态",
    ),
    PermissionDef(
        code="ai:chat",
        group="ai",
        group_label="智能与模型中心",
        label="使用 AI 对话工作台",
        description="调用 AI 同步/流式多轮对话与调试台能力",
    ),
    PermissionDef(
        code="ai:config:view",
        group="ai",
        group_label="智能与模型中心",
        label="查看 AI 模型配置",
        description="查看模型提供商注册表、模型配置列表与测试延迟结果",
    ),
    PermissionDef(
        code="ai:config:manage",
        group="ai",
        group_label="智能与模型中心",
        label="管理 AI 模型配置",
        description="新增/编辑/删除模型配置、设置默认模型及连通性测试",
    ),
    PermissionDef(
        code="system:config:view",
        group="system",
        group_label="系统配置中心",
        label="查看系统动态配置",
        description="查看站点信息、登录安全策略、注册风控、AI 与日志配置",
    ),
    PermissionDef(
        code="system:config:manage",
        group="system",
        group_label="系统配置中心",
        label="修改系统动态配置",
        description="保存并热更新系统参数配置或重置分组默认值",
    ),
    PermissionDef(
        code="log:audit:view",
        group="log",
        group_label="日志与安全审计",
        label="查看审计与登录日志",
        description="查看操作审计流水、越权告警及全站登录安全日志",
    ),
    PermissionDef(
        code="log:audit:manage",
        group="log",
        group_label="日志与安全审计",
        label="清理过期审计日志",
        description="按保留策略手动清理历史操作审计日志与登录日志",
    ),
    PermissionDef(
        code="rbac:role:view",
        group="rbac",
        group_label="角色与权限 (RBAC)",
        label="查看角色与权限矩阵",
        description="查看系统内置角色与自定义角色的权限点分配",
    ),
    PermissionDef(
        code="rbac:role:manage",
        group="rbac",
        group_label="角色与权限 (RBAC)",
        label="管理角色与权限",
        description="新增、编辑或删除自定义角色并调整角色权限集合",
    ),
)

ALL_PERMISSION_CODES: frozenset[str] = frozenset(p.code for p in PERMISSION_DEFS)


def build_permission_groups() -> list[dict]:
    """构建按模块分组的权限点树，供前端权限勾选矩阵直接渲染。"""
    groups_map: dict[str, dict] = {}
    for p in PERMISSION_DEFS:
        if p.group not in groups_map:
            groups_map[p.group] = {
                "group": p.group,
                "label": p.group_label,
                "items": [],
            }
        groups_map[p.group]["items"].append(
            {
                "code": p.code,
                "label": p.label,
                "description": p.description,
            }
        )
    return list(groups_map.values())


PERMISSION_GROUPS: list[dict] = build_permission_groups()


def has_permission(granted: list[str] | set[str], required: str) -> bool:
    """判断已授予权限集合是否满足目标权限码（支持 `*` 超级通配符）。"""
    if not required:
        return True
    if "*" in granted:
        return True
    return required in granted
