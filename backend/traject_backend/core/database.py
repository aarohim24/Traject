"""Async SQLAlchemy database engine and session management for the Traject backend.

Provides the async engine, session factory, and FastAPI dependency ``get_db()``
that yields a transactional ``AsyncSession`` per request.  The ``init_db()``
coroutine is called once during application startup to ensure all tables exist.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from traject_backend.core.config import settings

engine = create_async_engine(
    settings.database_url,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    echo=False,
)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an ``AsyncSession`` for use as a FastAPI dependency.

    Opens a new session, yields it to the caller, then ensures the session
    is closed in a ``finally`` block regardless of whether an exception was
    raised during the request.

    Yields:
        AsyncSession: A SQLAlchemy async database session bound to the
            shared async engine.

    Example::

        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)) -> list[Item]:
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """Create all database tables if they do not already exist.

    Imports ``Base`` lazily from ``traject_backend.models.base`` to avoid
    circular imports during application startup (models are not available
    until after the core infrastructure is imported).  If the models package
    is not yet present, the import error is silently swallowed and the
    function returns without creating any tables.

    This coroutine is intended to be called once inside the FastAPI lifespan
    context manager::

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    Raises:
        Nothing — ``ImportError`` from missing models is caught and ignored.
    """
    try:
        from traject_backend.models.base import Base  # noqa: PLC0415
    except ImportError:
        return

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
