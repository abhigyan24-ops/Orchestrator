import os
import pytest
import pytest_asyncio
import asyncpg
from typing import AsyncGenerator
from dotenv import load_dotenv

from db.connection import init_pool, close_pool, get_pool, apply_schema, apply_seed

# Load environment variables for testing
load_dotenv()


@pytest_asyncio.fixture(autouse=True)
async def db_pool() -> AsyncGenerator[asyncpg.Pool, None]:
    """Initialize the connection pool with the TEST_DATABASE_URL for the test session."""
    test_db_url = os.environ.get("TEST_DATABASE_URL")
    if not test_db_url:
        pytest.skip("TEST_DATABASE_URL environment variable is not set.")
    
    # Ensure encryption key is set for tests
    if not os.environ.get("ENCRYPTION_KEY"):
        from cryptography.fernet import Fernet
        os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()

    pool = await init_pool(test_db_url)
    
    # Initialize the schema in the test database once per session
    async with pool.acquire() as conn:
        # Drop everything first in case it's dirty from a previous aborted test
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        await apply_schema(conn)
        await apply_seed(conn)

    yield pool
    
    await close_pool()


@pytest_asyncio.fixture
async def db_conn(db_pool: asyncpg.Pool) -> AsyncGenerator[asyncpg.Connection, None]:
    """Provide a database connection wrapped in a transaction that rolls back after the test."""
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            yield conn
        finally:
            await tr.rollback()
