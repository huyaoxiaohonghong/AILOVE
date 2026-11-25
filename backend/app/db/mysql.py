from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_mysql() -> AsyncEngine:
    """初始化 SQLAlchemy 异步引擎与 Session 工厂。"""
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.mysql_dsn,
            echo=False,
            pool_pre_ping=True,
            pool_size=settings.MYSQL_POOL_SIZE,
            max_overflow=settings.MYSQL_MAX_OVERFLOW,
            pool_recycle=1800,
            connect_args={"connect_timeout": 3},
        )
        _session_factory = async_sessionmaker(
            bind=_engine,
            class_=AsyncSession,
            autoflush=False,
            expire_on_commit=False,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        init_mysql()
    assert _session_factory is not None
    return _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：获取异步数据库 Session。"""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def check_mysql_health() -> tuple[bool, str]:
    """检测 MySQL 连接是否可用，返回 (是否健康, 状态描述)。"""
    try:
        engine = init_mysql()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True, "connected"
    except Exception as exc:
        logger.warning("MySQL health check failed: %s", exc)
        return False, f"disconnected ({type(exc).__name__})"


_AI_CONVERSATIONS_EXTRA_COLUMNS: tuple[tuple[str, str], ...] = (
    ("persona_id", "BIGINT NULL COMMENT '绑定的智能体ID'"),
    ("persona_name", "VARCHAR(64) NOT NULL DEFAULT '' COMMENT '绑定的智能体名称快照'"),
    ("is_pinned", "TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否置顶会话'"),
)


async def _ensure_incremental_columns() -> None:
    """为历史存量表幂等补齐新增列（弥补 create_all 不修改已有表的局限）。"""
    engine = init_mysql()
    async with engine.begin() as conn:
        rows = await conn.execute(
            text(
                "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ai_conversations'"
            )
        )
        existing = {str(r[0]).lower() for r in rows.fetchall()}
        if existing:
            for col_name, ddl in _AI_CONVERSATIONS_EXTRA_COLUMNS:
                if col_name not in existing:
                    await conn.execute(
                        text(f"ALTER TABLE `ai_conversations` ADD COLUMN `{col_name}` {ddl}")
                    )
                    logger.info("Schema upgrade: added column ai_conversations.%s", col_name)

        wx_rows = await conn.execute(
            text(
                "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'wechat_users'"
            )
        )
        wx_cols = {str(r[0]).lower() for r in wx_rows.fetchall()}
        if wx_cols and "invite_verified" not in wx_cols:
            await conn.execute(
                text(
                    "ALTER TABLE `wechat_users` ADD COLUMN `invite_verified` "
                    "TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否已通过小圈子邀请码验证'"
                )
            )
            # 仅在首次升级补列时将存量老用户标记为已验证，避免升级后锁死既有用户
            await conn.execute(text("UPDATE `wechat_users` SET `invite_verified` = 1"))
            logger.info("Schema upgrade: added column wechat_users.invite_verified")


async def ensure_tables() -> None:
    """确保 ORM 定义的数据表与增量字段在 MySQL 中就绪（幂等执行）。"""
    from app.models import Base  # noqa: PLC0415

    engine = init_mysql()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _ensure_incremental_columns()


async def dispose_mysql() -> None:
    """应用关闭时释放数据库连接池。"""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
