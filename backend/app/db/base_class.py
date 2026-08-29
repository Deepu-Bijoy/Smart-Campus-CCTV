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
