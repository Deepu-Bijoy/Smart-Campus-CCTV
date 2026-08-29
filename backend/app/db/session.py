import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import ARRAY
from app.core.config import settings

@compiles(ARRAY, "sqlite")
def compile_array_sqlite(element, compiler, **kw):
    return "JSON"

db_uri = settings.SQLALCHEMY_DATABASE_URI
if "sqlite" in db_uri:
    os.makedirs(settings.STORAGE_DIR, exist_ok=True)

engine = create_async_engine(
    db_uri,
    echo=False,
    future=True,
    **(dict(pool_pre_ping=True) if "sqlite" not in db_uri else {})
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)
