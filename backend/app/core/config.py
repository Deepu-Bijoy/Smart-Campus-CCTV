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
    SECRET_KEY: str = Field(default="SUPER_SECRET_REPLACE_THIS_IN_PRODUCTION")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
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
        if not hasattr(self, "_cached_redis_available"):
            import socket
            try:
                socket.getaddrinfo(self.REDIS_HOST, self.REDIS_PORT)
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.2)
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
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        import os
        test_uri = os.getenv("TEST_DATABASE_URI")
        if test_uri:
            return test_uri
        if self.DB_FALLBACK_SQLITE:
            return "sqlite+aiosqlite:///./storage/cctv.db"
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
        return self.CELERY_ALWAYS_EAGER_VAL or not self._redis_available
    
    @property
    def CELERY_BROKER_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"
        
    @property
    def CELERY_RESULT_BACKEND(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    # Storage
    STORAGE_DIR: str = "storage"
    
    # Face Identification Thresholds
    RECOGNITION_HIGH_THRESHOLD: float = 0.75
    RECOGNITION_MEDIUM_THRESHOLD: float = 0.60
    
    # Logging
    LOG_LEVEL: str = "INFO"

settings = Settings()
