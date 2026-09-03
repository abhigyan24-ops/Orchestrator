"""
Database connection pool using asyncpg (PostgreSQL only).

Reads DATABASE_URL from environment. Provides an async context manager
for acquiring connections from a shared pool.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import asyncpg

_pool: asyncpg.Pool | None = None


async def init_pool(dsn: str | None = None, **kwargs) -> asyncpg.Pool:
    """Create the global connection pool.

    Args:
        dsn: PostgreSQL connection string. Falls back to DATABASE_URL env var.
        **kwargs: Extra keyword arguments forwarded to asyncpg.create_pool().
    """
    global _pool
    if _pool is not None:
        return _pool

    database_url = dsn or os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL environment variable is required. "
            "Example: postgresql://orchestrator:orchestrator@localhost:5432/orchestrator"
        )

    _pool = await asyncpg.create_pool(
        database_url,
        min_size=kwargs.pop("min_size", 2),
        max_size=kwargs.pop("max_size", 10),
        **kwargs,
    )
    return _pool


async def close_pool() -> None:
    """Gracefully close the global connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def get_pool() -> asyncpg.Pool:
    """Return the existing pool, initialising it if necessary."""
    if _pool is None:
        await init_pool()
    return _pool  # type: ignore[return-value]


@asynccontextmanager
async def get_connection() -> AsyncIterator[asyncpg.Connection]:
    """Acquire a connection from the pool as an async context manager.

    Usage::

        async with get_connection() as conn:
            row = await conn.fetchrow("SELECT 1")
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def apply_schema(conn: asyncpg.Connection | None = None) -> None:
    """Read db/schema.sql and execute it against the given connection.

    If no connection is provided, one is acquired from the pool.
    """
    schema_path = Path(__file__).parent / "schema.sql"
    ddl = schema_path.read_text(encoding="utf-8")

    if conn is not None:
        await conn.execute(ddl)
    else:
        async with get_connection() as c:
            await c.execute(ddl)


async def apply_seed(conn: asyncpg.Connection | None = None) -> None:
    """Read db/seed_data.sql and execute it against the given connection."""
    seed_path = Path(__file__).parent / "seed_data.sql"
    sql = seed_path.read_text(encoding="utf-8")

    if conn is not None:
        await conn.execute(sql)
    else:
        async with get_connection() as c:
            await c.execute(sql)
