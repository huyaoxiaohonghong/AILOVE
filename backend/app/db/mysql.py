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


async def ensure_tables() -> None:
    """确保 ORM 定义的数据表在 MySQL 中存在（幂等创建缺失表）。"""
    from app.models import Base  # noqa: PLC0415

    engine = init_mysql()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_mysql() -> None:
    """应用关闭时释放数据库连接池。"""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
