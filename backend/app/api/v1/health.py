from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from app.core.config import get_settings
from app.db.mysql import check_mysql_health
from app.db.redis import check_redis_health
from app.schemas.common import ok
from app.services.ai_config_service import resolve_runtime_config

router = APIRouter(tags=["系统健康"])


@router.get("/health", summary="系统与依赖健康检查")
async def health_check():
    settings = get_settings()
    mysql_ok, mysql_status = await check_mysql_health()
    redis_ok, redis_status = await check_redis_health()
    ai_cfg = await resolve_runtime_config()

    return ok(
        {
            "status": "ok" if (mysql_ok and redis_ok) else "degraded",
            "app": settings.APP_NAME,
            "env": settings.APP_ENV,
            "timestamp": datetime.now(UTC).isoformat(),
            "services": {
                "mysql": {"healthy": mysql_ok, "status": mysql_status},
                "redis": {"healthy": redis_ok, "status": redis_status},
                "langchain": {
                    "configured": ai_cfg.is_configured,
                    "provider": ai_cfg.provider,
                    "protocol": ai_cfg.protocol,
                    "model": ai_cfg.model_name,
                    "base_url": ai_cfg.base_url,
                    "config_name": ai_cfg.name,
                    "last_test_status": ai_cfg.last_test_status,
                    "last_test_latency_ms": ai_cfg.last_test_latency_ms,
                },
                "wechat": {
                    "configured": settings.is_wechat_configured,
                },
            },
        }
    )
