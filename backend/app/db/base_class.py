from typing import Any
from sqlalchemy.orm import DeclarativeBase, declared_attr
import re

import sqlalchemy
import sqlalchemy.types
import sqlalchemy.dialects.postgresql
from app.core.config import SqliteCompatibleArray, SqliteCompatibleUUID

sqlalchemy.ARRAY = SqliteCompatibleArray
sqlalchemy.types.ARRAY = SqliteCompatibleArray
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
