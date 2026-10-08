from typing import Any
from sqlalchemy.orm import DeclarativeBase, declared_attr
import re

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
        if dialect.name == "sqlite":
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, _python_uuid.UUID):
            return value
        return _python_uuid.UUID(str(value))

sqlalchemy.dialects.postgresql.UUID = SqliteCompatibleUUID
sqlalchemy.types.UUID = SqliteCompatibleUUID


class Base(DeclarativeBase):
    id: Any
    __name__: str

    # Generate __tablename__ automatically
    @declared_attr.directive
    def __tablename__(cls) -> str:
        name = cls.__name__
        # Convert CamelCase to snake_case and append 's'
        snake = re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()
        if snake.endswith('y'):
            return snake[:-1] + 'ies'
        elif snake.endswith('s'):
            return snake
        return snake + 's'
