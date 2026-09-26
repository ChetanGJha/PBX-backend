import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.sql import text
from src.core.config import settings

logger = logging.getLogger("pbx.database")

# Create SQLAlchemy Async Engine with connection pooling
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True
)

# Create Async Session Factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI Dependency yielding an Async Database Session.
    Ensures connection is returned to pool after request processing.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as err:
            await session.rollback()
            logger.error(f"Database session error: {err}")
            raise
        finally:
            await session.close()


async def execute_query(query_str: str, params: dict = None) -> list:
    """
    Helper function for executing direct SQL queries procedurally.
    Returns list of dictionary rows.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(text(query_str), params or {})
        if result.returns_rows:
            return [dict(row._mapping) for row in result.fetchall()]
        await session.commit()
        return []


async def execute_query_one(query_str: str, params: dict = None) -> dict:
    """
    Helper function for executing single row SQL queries procedurally.
    Returns a dictionary row or None.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(text(query_str), params or {})
        if result.returns_rows:
            row = result.fetchone()
            await session.commit()
            return dict(row._mapping) if row else None
        await session.commit()
        return None


async def execute_transaction(func):
    """
    Executes an async callback inside an isolated database transaction.
    """
    async with AsyncSessionLocal() as session:
        try:
            result = await func(session)
            await session.commit()
            return result
        except Exception as err:
            await session.rollback()
            logger.error(f"Transaction failed: {err}")
            raise

