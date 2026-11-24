from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_v1_router
from app.core.audit_middleware import AuditMiddleware
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.db.mysql import check_mysql_health, dispose_mysql, ensure_tables, init_mysql
from app.db.redis import (
    acquire_distributed_lock,
    check_redis_health,
    close_redis,
    init_redis,
    release_distributed_lock,
    wait_for_lock_release,
)
from app.services.ai_config_service import ensure_default_ai_config
from app.services.ai_persona_service import ensure_default_personas
from app.services.auth_service import ensure_default_admin
from app.services.rbac_service import ensure_default_roles
from app.services.sys_config_service import ensure_default_sys_configs

settings = get_settings()
setup_logging(debug=settings.APP_DEBUG)
logger = logging.getLogger(__name__)

_INSECURE_SECRET_MARKERS = ("dev-only", "change-this", "please-change")
_BOOTSTRAP_LOCK_KEY = "ailove:bootstrap:lock"


def _audit_security_settings() -> None:
    """非开发环境下检测弱默认密钥/默认管理员口令，及时告警避免带默认凭据上线。"""
    if settings.is_development:
        return
    secret = settings.JWT_SECRET_KEY
    if len(secret) < 32 or any(marker in secret for marker in _INSECURE_SECRET_MARKERS):
        logger.warning(
            "[SECURITY] JWT_SECRET_KEY 仍为默认值或长度不足 32 位，请立即在 .env 中替换为高强度随机密钥！"
        )
    if settings.DEFAULT_ADMIN_PASSWORD == "Admin123456":
        logger.warning(
            "[SECURITY] DEFAULT_ADMIN_PASSWORD 仍为初始值，若管理员尚未修改密码请尽快登录后台修改！"
        )
    if settings.ALLOW_DEV_FALLBACK_AUTH:
        logger.warning("[SECURITY] 非开发环境不建议开启 ALLOW_DEV_FALLBACK_AUTH，请设置为 false。")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """应用生命周期管理：启动时初始化并探测 MySQL/Redis，退出时安全释放连接池。"""
    logger.info("Starting %s (env=%s)", settings.APP_NAME, settings.APP_ENV)
    _audit_security_settings()
    init_mysql()
    init_redis()

    mysql_ok, mysql_status = await check_mysql_health()
    redis_ok, redis_status = await check_redis_health()
    logger.info("Startup check -> MySQL: %s | Redis: %s", mysql_status, redis_status)

    if mysql_ok:
        if redis_ok:
            should_bootstrap, lock_token = await acquire_distributed_lock(
                _BOOTSTRAP_LOCK_KEY, ttl_seconds=30
            )
        else:
            should_bootstrap, lock_token = True, ""

        if should_bootstrap:
            try:
                await ensure_tables()
                await ensure_default_roles()
                await ensure_default_sys_configs()
                await ensure_default_admin()
                await ensure_default_ai_config()
                await ensure_default_personas()
            finally:
                if lock_token:
                    await release_distributed_lock(_BOOTSTRAP_LOCK_KEY, lock_token)
        else:
            logger.info(
                "Startup bootstrap lock held by another worker, waiting for completion..."
            )
            await wait_for_lock_release(_BOOTSTRAP_LOCK_KEY, timeout_seconds=5.0)
    else:
        logger.warning(
            "MySQL 未连接，服务已以降级模式启动；可执行 `docker compose up -d` 启动本地 MySQL/Redis。"
        )

    yield

    await close_redis()
    await dispose_mysql()
    logger.info("Shutdown complete.")


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(
        title=cfg.APP_NAME,
        description="AILOVE 网站管理端 + 微信小程序统一后端服务 (FastAPI + MySQL + Redis + LangChain)",
        version="0.1.0",
        docs_url="/docs" if cfg.APP_DEBUG else None,
        redoc_url="/redoc" if cfg.APP_DEBUG else None,
        openapi_url="/openapi.json" if cfg.APP_DEBUG else None,
        lifespan=lifespan,
    )

    app.add_middleware(AuditMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_v1_router, prefix=cfg.API_V1_PREFIX)

    @app.get("/", tags=["基础"])
    async def root():
        return {
            "name": cfg.APP_NAME,
            "env": cfg.APP_ENV,
            "docs": "/docs" if cfg.APP_DEBUG else None,
            "health": f"{cfg.API_V1_PREFIX}/health",
        }

    return app


app = create_app()
