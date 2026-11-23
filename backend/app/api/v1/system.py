from __future__ import annotations

from fastapi import APIRouter

from app.schemas.common import ok
from app.services import sys_config_service

router = APIRouter(prefix="/system", tags=["公共-系统运行配置"])


@router.get("/public-config", summary="获取登录前公共站点与风控策略配置（热生效）")
async def get_public_system_config():
    return ok(await sys_config_service.get_public_configs())
