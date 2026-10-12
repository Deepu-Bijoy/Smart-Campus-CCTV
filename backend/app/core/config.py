from typing import List, Union
from pydantic import BeforeValidator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Annotated
import json

import sqlalchemy
import sqlalchemy.types
from sqlalchemy.types import TypeDecorator, JSON, ARRAY

class SqliteCompatibleArray(TypeDecorator):
    impl = ARRAY
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(JSON())
        else:
            return dialect.type_descriptor(self.impl_instance)

    def process_bind_param(self, value, dialect):
        return value

    def process_result_value(self, value, dialect):
        return value

sqlalchemy.ARRAY = SqliteCompatibleArray
sqlalchemy.types.ARRAY = SqliteCompatibleArray

import uuid as _python_uuid
from sqlalchemy.types import CHAR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
import sqlalchemy.dialects.postgresql

class SqliteCompatibleUUID(TypeDecorator):
    impl = PG_UUID
    cache_ok = True

    def __init__(self, as_uuid=True, *args, **kwargs):
        self.as_uuid = as_uuid
        super().__init__(as_uuid=as_uuid, *args, **kwargs)

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(CHAR(36))
        else:
            return dialect.type_descriptor(PG_UUID(as_uuid=self.as_uuid))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect is None or getattr(dialect, "name", None) == "sqlite":
            if isinstance(value, _python_uuid.UUID):
                return str(value)
            try:
                return str(_python_uuid.UUID(str(value)))
            except (ValueError, AttributeError):
                return str(value)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, _python_uuid.UUID):
            return value
        try:
            return _python_uuid.UUID(str(value))
        except (ValueError, AttributeError):
            return value

sqlalchemy.dialects.postgresql.UUID = SqliteCompatibleUUID
sqlalchemy.types.UUID = SqliteCompatibleUUID


def parse_cors_origins(v: Union[str, List[str]]) -> List[str]:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",")]
    elif isinstance(v, (list, str)):
        return json.loads(v) if isinstance(v, str) else v
    raise ValueError(v)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_ignore_empty=True, extra="ignore"
    )

    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "AI-Powered Smart CCTV Investigation System"
    
    # Security / Auth
    LEGACY_DEFAULT_SECRET: str = "SUPER_SECRET_REPLACE_THIS_IN_PRODUCTION"
    SECRET_KEY: str = Field(default="7f9b8c2d1e0a4f5b6c7d8e9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # 60 minutes
    ALGORITHM: str = "HS256"

    # CORS
    BACKEND_CORS_ORIGINS: Annotated[
        List[str], BeforeValidator(parse_cors_origins)
    ] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # Databases
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "cctv_investigation"
    
    DB_FALLBACK_SQLITE_VAL: bool = Field(default=True, validation_alias="DB_FALLBACK_SQLITE")
    QDRANT_IN_MEMORY_VAL: bool = Field(default=False, validation_alias="QDRANT_IN_MEMORY")
    CELERY_ALWAYS_EAGER_VAL: bool = Field(default=False, validation_alias="CELERY_ALWAYS_EAGER")
    
    @property
    def DB_FALLBACK_SQLITE(self) -> bool:
        return self.DB_FALLBACK_SQLITE_VAL or not self._postgres_available

    @property
    def _postgres_available(self) -> bool:
        if self.DB_FALLBACK_SQLITE_VAL:
            return False
        if not hasattr(self, "_cached_postgres_available"):
            import socket
            try:
                socket.getaddrinfo(self.POSTGRES_SERVER, self.POSTGRES_PORT)
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.2)
                s.connect((self.POSTGRES_SERVER, self.POSTGRES_PORT))
                s.close()
                self._cached_postgres_available = True
            except Exception:
                self._cached_postgres_available = False
        return self._cached_postgres_available

    @property
    def _redis_available(self) -> bool:
        if self.CELERY_ALWAYS_EAGER_VAL:
            return False
        import time
        now = time.time()
        if hasattr(self, "_last_redis_check") and (now - self._last_redis_check < 5.0):
            return getattr(self, "_cached_redis_available", False)
        
        self._last_redis_check = now
        import socket
        try:
            socket.getaddrinfo(self.REDIS_HOST, self.REDIS_PORT)
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            s.connect((self.REDIS_HOST, self.REDIS_PORT))
            s.close()
            self._cached_redis_available = True
        except Exception:
            self._cached_redis_available = False
        return self._cached_redis_available

    @property
    def _qdrant_available(self) -> bool:
        if self.QDRANT_IN_MEMORY_VAL:
            return False
        if not hasattr(self, "_cached_qdrant_available"):
            import socket
            try:
                socket.getaddrinfo(self.QDRANT_HOST, self.QDRANT_PORT)
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.2)
                s.connect((self.QDRANT_HOST, self.QDRANT_PORT))
                s.close()
                self._cached_qdrant_available = True
            except Exception:
                self._cached_qdrant_available = False
        return self._cached_qdrant_available

    @property
    def STORAGE_DIR(self) -> str:
        import os
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        return os.path.join(backend_dir, "storage")

    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        import os
        test_uri = os.getenv("TEST_DATABASE_URI")
        if test_uri:
            return test_uri
        if self.DB_FALLBACK_SQLITE:
            db_path = os.path.join(self.STORAGE_DIR, "cctv.db").replace("\\", "/")
            return f"sqlite+aiosqlite:///{db_path}"
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    # Vector DB
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_API_KEY: str = ""

    @property
    def QDRANT_IN_MEMORY(self) -> bool:
        return self.QDRANT_IN_MEMORY_VAL or not self._qdrant_available

    # Redis / Celery
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    
    @property
    def CELERY_ALWAYS_EAGER(self) -> bool:
        import os
        if os.getenv("TESTING") == "True" or os.getenv("CELERY_ALWAYS_EAGER", "").lower() == "true":
            return True
        return self.CELERY_ALWAYS_EAGER_VAL or not self._redis_available
    
    @property
    def CELERY_BROKER_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"
        
    @property
    def CELERY_RESULT_BACKEND(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"
    
    # Face Identification Thresholds
    RECOGNITION_HIGH_THRESHOLD: float = 0.75
    RECOGNITION_MEDIUM_THRESHOLD: float = 0.60
    
    # Upload Limits (500 MiB = 524,288,000 bytes)
    MAX_UPLOAD_SIZE_BYTES: int = 524_288_000
    
    # Logging
    LOG_LEVEL: str = "INFO"

settings = Settings()
