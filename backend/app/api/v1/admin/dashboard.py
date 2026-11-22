from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import get_current_admin
from app.core.config import get_settings
from app.db.mysql import check_mysql_health, get_session_factory
from app.db.redis import check_redis_health
from app.models.ai_chat import AIConversation, AIMessage
from app.models.user import User
from app.models.wechat_user import WechatUser
from app.schemas.common import ok
from app.services.ai_config_service import resolve_runtime_config
from app.services.session_service import session_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard", tags=["管理端-仪表盘"])


@router.get("/overview", summary="控制台核心概览数据")
async def dashboard_overview(_current_admin: dict[str, Any] = Depends(get_current_admin)):
    settings = get_settings()
    mysql_ok, mysql_status = await check_mysql_health()
    redis_ok, redis_status = await check_redis_health()
    active_sessions = await session_service.count_total_active_sessions()
    ai_cfg = await resolve_runtime_config()

    stats = {
        "platform_user_count": 1,
        "email_registered_count": 0,
        "admin_assigned_count": 0,
        "active_session_count": active_sessions,
        "wechat_user_count": 0,
        "admin_user_count": 1,
        "ai_conversation_count": 0,
        "ai_message_count": 0,
        "db_connected": mysql_ok,
    }

    if mysql_ok:
        try:
            factory = get_session_factory()
            async with factory() as session:
                stats["platform_user_count"] = (
                    await session.scalar(select(func.count(User.id))) or 0
                )
                stats["email_registered_count"] = (
                    await session.scalar(
                        select(func.count(User.id)).where(User.register_source == "email_register")
                    )
                    or 0
                )
                stats["admin_assigned_count"] = (
                    await session.scalar(
                        select(func.count(User.id)).where(User.register_source == "admin_assigned")
                    )
                    or 0
                )
                stats["admin_user_count"] = (
                    await session.scalar(
                        select(func.count(User.id)).where(User.role.in_(["super_admin", "admin"]))
                    )
                    or 0
                )
                stats["wechat_user_count"] = (
                    await session.scalar(select(func.count(WechatUser.id))) or 0
                )
                stats["ai_conversation_count"] = (
                    await session.scalar(select(func.count(AIConversation.id))) or 0
                )
                stats["ai_message_count"] = (
                    await session.scalar(select(func.count(AIMessage.id))) or 0
                )
        except SQLAlchemyError as exc:
            logger.warning("Dashboard stats query failed: %s", exc)
            stats["db_connected"] = False

    return ok(
        {
            "stats": stats,
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
