"""Alembic environment configuration for axon-backend.

Provides both offline (generate SQL) and online (apply to DB) migration modes.
The online mode uses SQLAlchemy's async engine to support asyncpg.
"""

import asyncio
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# ---------------------------------------------------------------------------
# Alembic Config object — provides access to alembic.ini values
# ---------------------------------------------------------------------------
config = context.config

# Interpret the config file for Python logging if present.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Import the project's metadata so Alembic can detect schema changes.
# The import is deferred so that the env.py can be used before the package
# is fully installed (e.g., during the initial pip install step).
# ---------------------------------------------------------------------------
try:
    from axon_backend.models.base import Base  # noqa: E402

    target_metadata = Base.metadata
except ImportError:
    target_metadata = None  # type: ignore[assignment]


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Configures the context with just a URL and without an Engine, then
    emits DDL to a SQL script rather than executing against a live DB.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Execute migrations against an active database connection.

    Args:
        connection: An active SQLAlchemy ``Connection`` instance.
    """
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations inside a transaction."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using an async engine."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()


def process_revision_directives(
    context: Any,  # noqa: ANN401 — Alembic internals use Any
    revision: Any,  # noqa: ANN401
    directives: Any,  # noqa: ANN401
) -> None:
    """Hook called before writing a new migration file.

    Currently a no-op placeholder; can be used to prevent empty migrations
    or to customise revision IDs.

    Args:
        context: The MigrationContext.
        revision: The current revision tuple.
        directives: The list of MigrationScript directives to be written.
    """
