"""
database.py — Async SQLAlchemy engine, session, and Base
"""
from collections.abc import AsyncGenerator
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse, urlunparse

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from config import settings


def _build_engine() -> AsyncEngine:
    """Build async engine. Handles Neon SSL and URL-encoded DB names."""
    raw_url = settings.DATABASE_URL
    connect_args: dict = {}

    parsed = urlparse(raw_url)
    query_params = parse_qs(parsed.query)

    if bool({"ssl", "sslmode"} & set(query_params.keys())) or "neon.tech" in raw_url:
        connect_args["ssl"] = "require"

    clean_url = urlunparse(parsed._replace(query="", path=unquote(parsed.path)))

    return create_async_engine(
        clean_url,
        echo=settings.DEBUG,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        connect_args=connect_args,
    )


engine: AsyncEngine = _build_engine()

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    """All ORM models inherit from this."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, Any]:
    """FastAPI dependency — one DB session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def get_db_context():
    """
    Plain async context manager for background tasks (e.g. APScheduler jobs).
    Use as:  async with get_db_context() as db:
    Unlike get_db(), this does NOT need FastAPI's DI system.
    """
    return AsyncSessionLocal()


async def create_tables() -> None:
    """Create all DB tables on startup. Safe to run repeatedly."""
    import models  # noqa: F401 — registers all models with Base.metadata
    from utils.logger import logger
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("[OK] Database tables created / verified")
    except Exception as e:
        logger.error(f"[FAIL] DB table creation failed: {e}")
        raise


async def ensure_pg_invite_enum_values() -> None:
    """
    Ensure the 'WALKIN' label exists in the PostgreSQL 'invitetype' enum.
    Databases created before the WALKIN invite type was added will fail
    with 'invalid input value for enum invitetype' when approving walk-ins.
    """
    url = (settings.DATABASE_URL or "").lower()
    if "postgresql" not in url and "postgres" not in url:
        return
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    from utils.logger import logger

    try:
        async with engine.connect() as conn:
            ddl = text("ALTER TYPE invitetype ADD VALUE IF NOT EXISTS 'WALKIN'")
            try:
                await conn.execute(ddl)
                await conn.commit()
                logger.info("[OK] PostgreSQL invitetype enum has value 'WALKIN'")
            except ProgrammingError as e:
                await conn.rollback()
                msg = str(e.orig if hasattr(e, "orig") else e).lower()
                if "already exists" not in msg and "duplicate" not in msg:
                    logger.warning(f"[WARN] ALTER TYPE invitetype ADD VALUE 'WALKIN': {e}")
    except Exception as e:
        logger.warning(f"[WARN] Could not extend PostgreSQL invite enum: {e}")


async def ensure_pg_userrole_enum_values() -> None:
    """
    PostgreSQL deployments created before RESIDENTIAL_GUARD existed may fail
    public registration with 'invalid input value for enum'. Add the label if missing.
    """
    url = (settings.DATABASE_URL or "").lower()
    if "postgresql" not in url and "postgres" not in url:
        return
    import re
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    from utils.logger import logger

    ident_re = re.compile(r"^[a-z_][a-z0-9_]*$", re.I)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT DISTINCT n.nspname AS sch, t.typname AS typ
                    FROM pg_type t
                    JOIN pg_enum e ON t.oid = e.enumtypid
                    JOIN pg_namespace n ON n.oid = t.typnamespace
                    WHERE e.enumlabel = 'ORGANIZER'
                    """
                )
            )
            rows = result.fetchall()
            for sch, typ in rows:
                if not ident_re.match(sch) or not ident_re.match(typ):
                    continue
                ddl = text(f'ALTER TYPE "{sch}"."{typ}" ADD VALUE \'RESIDENTIAL_GUARD\'')
                try:
                    await conn.execute(ddl)
                    await conn.commit()
                except ProgrammingError as e:
                    await conn.rollback()
                    msg = str(e.orig if hasattr(e, "orig") else e).lower()
                    if "already exists" not in msg and "duplicate" not in msg:
                        logger.warning(f"[WARN] ALTER TYPE {sch}.{typ} ADD VALUE: {e}")
        logger.info("[OK] PostgreSQL user role enum verified (RESIDENTIAL_GUARD)")
    except Exception as e:
        logger.warning(f"[WARN] Could not extend PostgreSQL role enum: {e}")
