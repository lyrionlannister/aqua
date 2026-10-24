"""
Decorador @Entity: define un modelo de SQLAlchemy con la misma sintaxis
declarativa que el resto de Aqua — clase plana con type hints, cada atributo
con un marcador de columna (`PrimaryGeneratedColumn()`, `Column()`, etc. de
`columns.py`), sin heredar `Base` a mano ni escribir `Mapped[...]` vos mismo.

Por debajo construye una subclase real de `Base` (`core/database/database.py`)
vía `type(...)`, igual que `@Dto` construye un `BaseModel` real vía `create_model`.

Autor: lyrionlannister
Versión: 1.0.0
"""

import re
from typing import Optional

from sqlalchemy.orm import Mapped

from core.database.database import Base
from core.entity.columns import _ColumnSpec
from core.entity.relations import _RelationshipSpec

_CAMEL_TO_SNAKE = re.compile(r"(?<!^)(?=[A-Z])")

# Dunders que SQLAlchemy sí necesita leer de la clase declarativa (constraints
# multi-columna, args del mapper). El resto de los dunders (__module__,
# __qualname__, etc.) los pone Python solo y no hay que copiarlos.
_SQLALCHEMY_DUNDERS = ("__table_args__", "__mapper_args__")


def _default_table_name(cls_name: str) -> str:
    return _CAMEL_TO_SNAKE.sub("_", cls_name).lower()


def Entity(table_name: Optional[str] = None):
    """
    Convierte una clase plana con type hints en un modelo real de SQLAlchemy.

    Example:
        ```python
        @Entity("users")
        class User:
            id: int = PrimaryGeneratedColumn()
            name: str = Column(length=150)
            email: str = Column(unique=True)
            created_at: datetime = CreateDateColumn()
            updated_at: datetime = UpdateDateColumn()
            deleted_at: datetime = DeleteDateColumn()
        ```

    Args:
        table_name: Nombre de la tabla. Si no se da, se deriva de la clase
                   (`UserPreference` -> `user_preference`).

    Returns:
        function: Decorador que devuelve una subclase real de `Base` con el
                 mismo nombre, columnas, y métodos que la clase original.

    Raises:
        Exception: Si algún atributo tipado no usa uno de los marcadores de
                  `columns.py`/`relations.py` (`PrimaryGeneratedColumn`/
                  `PrimaryColumn`/`Column`/`ForeignKey`/`CreateDateColumn`/
                  `UpdateDateColumn`/`DeleteDateColumn`/`ManyToOne`/`OneToMany`/
                  `OneToOne`/`ManyToMany`).
    """
    def decorator(cls):
        # __annotations__ crudo, no get_type_hints: una relación puede
        # referenciar una entidad todavía no definida (ej. "Parent" como
        # forward ref) y get_type_hints la intentaría resolver ya mismo.
        # SQLAlchemy resuelve esos nombres recién al configurar los mappers,
        # no necesitamos la clase real ahora.
        hints = getattr(cls, "__annotations__", {})
        namespace: dict = {"__tablename__": table_name or _default_table_name(cls.__name__)}
        annotations: dict = {}
        soft_delete_column = None

        for name, python_type in hints.items():
            spec = getattr(cls, name, None)
            if isinstance(spec, _ColumnSpec):
                annotations[name] = Mapped[python_type]
                namespace[name] = spec.build(python_type)
                if spec.kind == "soft_delete":
                    soft_delete_column = name
            elif isinstance(spec, _RelationshipSpec):
                annotations[name] = Mapped[python_type]
                namespace[name] = spec.build()
            else:
                raise Exception(
                    f"'{name}' en {cls.__name__} debe estar definido con PrimaryGeneratedColumn()/"
                    f"PrimaryColumn()/Column()/ForeignKey()/CreateDateColumn()/UpdateDateColumn()/"
                    f"DeleteDateColumn()/ManyToOne()/OneToMany()/OneToOne()/ManyToMany()"
                )

        for name, attr in vars(cls).items():
            if name in hints:
                continue
            if name.startswith("__") and name not in _SQLALCHEMY_DUNDERS:
                continue
            namespace[name] = attr

        namespace["__annotations__"] = annotations
        namespace["__soft_delete_column__"] = soft_delete_column

        return type(cls.__name__, (Base,), namespace)

    return decorator
