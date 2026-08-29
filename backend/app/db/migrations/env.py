import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
from app.db.base_class import Base
# import models to populate Base.metadata
from app.models.user import User
from app.models.video import Video
from app.models.track import Track, Detection, PersonReid
from app.models.student import Student, StudentPhoto, StudentFaceSession
from app.models.face_embedding import StudentFaceEmbedding
from app.models.recognition import StudentRecognitionEvent
from app.models.camera import Camera, CameraGroup, CameraCalibration, VirtualZone
from app.models.event import Event, EventTrack
from app.models.report import Report
from app.models.notification import Notification, NotificationPreference
from app.models.bulk_import import BulkImportJob
from app.models.incident import Incident, IncidentPerson, Evidence, DetectedEvent

target_metadata = Base.metadata

from app.core.config import settings

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = settings.SQLALCHEMY_DATABASE_URI
    if "sqlite" in url:
        sync_url = url.replace("sqlite+aiosqlite://", "sqlite://")
    else:
        sync_url = url.replace("postgresql+asyncpg://", "postgresql://")
    context.configure(
        url=sync_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = settings.SQLALCHEMY_DATABASE_URI
    
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
