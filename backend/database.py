"""Database engine and session management with async SQLAlchemy."""

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text
from backend.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """Dependency for FastAPI routes."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Initialize database: create pgvector extension and all tables."""
    from backend.models import Base

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_sha256 VARCHAR(64)"))
        await conn.execute(text("ALTER TABLE structured_data ADD COLUMN IF NOT EXISTS source_sha256 VARCHAR(64)"))
        # create_all does not add columns to existing installations.
        await conn.execute(text("ALTER TABLE structured_data ADD COLUMN IF NOT EXISTS source_page INTEGER"))
        await conn.execute(text("ALTER TABLE structured_data ADD COLUMN IF NOT EXISTS unit VARCHAR(100)"))
        await conn.execute(text("ALTER TABLE structured_data ADD COLUMN IF NOT EXISTS source_provider VARCHAR(40)"))
        await conn.execute(text("ALTER TABLE structured_data ADD COLUMN IF NOT EXISTS quality_status VARCHAR(40)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_structured_data_source_page ON structured_data (document_id, source_page)"))
    print("[OK] Database initialized with pgvector extension")
