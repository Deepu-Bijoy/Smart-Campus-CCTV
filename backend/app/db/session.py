import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import ARRAY
from sqlalchemy.dialects.postgresql import UUID
from app.core.config import settings

@compiles(ARRAY, "sqlite")
def compile_array_sqlite(element, compiler, **kw):
    return "JSON"

@compiles(UUID, "sqlite")
def compile_uuid_sqlite(element, compiler, **kw):
    return "CHAR(36)"

db_uri = settings.SQLALCHEMY_DATABASE_URI
if "sqlite" in db_uri:
    os.makedirs(settings.STORAGE_DIR, exist_ok=True)

engine = create_async_engine(
    db_uri,
    echo=False,
    future=True,
    **(dict(pool_pre_ping=True) if "sqlite" not in db_uri else {})
)

if "sqlite" in db_uri:
    from sqlalchemy import event
    import sqlite3

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

