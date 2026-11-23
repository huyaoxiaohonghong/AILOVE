from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import require_permissions
from app.core.permissions import PERMISSION_GROUPS
from app.schemas.common import ok
from app.schemas.system import RoleCreateRequest, RoleUpdateRequest
from app.services import rbac_service

router = APIRouter(prefix="/rbac", tags=["管理端-RBAC 角色与权限中心"])


@router.get("/permissions", summary="获取系统全部细粒度权限点树")
async def get_permission_tree(
    _current_admin: dict[str, Any] = Depends(require_permissions("rbac:role:view")),
):
    return ok({"groups": PERMISSION_GROUPS})


@router.get("/roles", summary="获取角色列表（含绑定账号数量与权限矩阵）")
async def list_rbac_roles(
    only_enabled: bool = Query(default=False),
    _current_admin: dict[str, Any] = Depends(require_permissions("rbac:role:view")),
):
    items = await rbac_service.list_roles(only_enabled=only_enabled)
    return ok({"items": items})


@router.post("/roles", summary="新建自定义 RBAC 角色")
async def create_rbac_role(
    req: RoleCreateRequest,
    _current_admin: dict[str, Any] = Depends(require_permissions("rbac:role:manage")),
):
    created = await rbac_service.create_role(req)
    return ok(created, message=f"角色「{created['name']}」创建成功")


@router.put("/roles/{role_id}", summary="更新角色名称与权限集合（立即生效）")
async def update_rbac_role(
    role_id: int,
    req: RoleUpdateRequest,
    _current_admin: dict[str, Any] = Depends(require_permissions("rbac:role:manage")),
):
    updated = await rbac_service.update_role(role_id, req)
    return ok(updated, message=f"角色「{updated['name']}」权限已保存并热生效")


@router.delete("/roles/{role_id}", summary="删除未被占用的自定义角色")
async def delete_rbac_role(
    role_id: int,
    _current_admin: dict[str, Any] = Depends(require_permissions("rbac:role:manage")),
):
    await rbac_service.delete_role(role_id)
    return ok({"id": role_id, "deleted": True}, message="自定义角色已删除")
