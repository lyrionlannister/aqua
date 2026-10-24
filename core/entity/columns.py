"""
Decoradores de columna para `@Entity`, sobre `mapped_column` de SQLAlchemy.

Cada uno devuelve un `_ColumnSpec`: todavía no es la columna real, porque
`mapped_column(...)` necesita saber el tipo Python del atributo (via
`Mapped[tipo]`) para inferir el tipo SQL, y eso recién se sabe en `@Entity`
(ver `entity.py`), leyendo el type hint de la clase. `_ColumnSpec.build()`
es quien construye la columna real, ya con el tipo en mano.

Autor: lyrionlannister
Versión: 1.0.0
"""

import typing
import uuid as uuid_module
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import ForeignKey as SAForeignKey
from sqlalchemy import String, func
from sqlalchemy.orm import MappedColumn, mapped_column


def _unwrap_optional(python_type: Any) -> Any:
    """`Optional[str]` (== `Union[str, None]`) -> `str`. Cualquier otro tipo, igual."""
    if typing.get_origin(python_type) is typing.Union:
        args = [a for a in typing.get_args(python_type) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return python_type


@dataclass
class _ColumnSpec:
    kind: str
    kwargs: dict = field(default_factory=dict)

    def build(self, python_type: type) -> MappedColumn:
        kwargs = dict(self.kwargs)
        if self.kind == "foreign_key":
            target = kwargs.pop("target")
            return mapped_column(SAForeignKey(target), **kwargs)
        length = kwargs.pop("length", None)
        if length is not None and _unwrap_optional(python_type) is str:
            return mapped_column(String(length), **kwargs)
        return mapped_column(**kwargs)


def PrimaryGeneratedColumn(*, uuid: bool = False) -> Any:
    """
    Primary key que se autogenera — nunca la asignás vos.

    Args:
        uuid: Si True, se genera un UUID4 en Python al crear la instancia.
             Si no, auto-increment entero (lo asigna la base de datos).
    """
    kwargs: dict = {"primary_key": True}
    if uuid:
        kwargs["default"] = uuid_module.uuid4
    else:
        kwargs["autoincrement"] = True
    return _ColumnSpec("primary_generated", kwargs)


def PrimaryColumn() -> Any:
    """Primary key que asignás vos a mano antes de guardar (sin autoincrement)."""
    return _ColumnSpec("primary", {"primary_key": True, "autoincrement": False})


def Column(*, nullable: bool = False, default: Optional[Any] = None, unique: bool = False, length: Optional[int] = None) -> Any:
    """
    Columna normal.

    Args:
        nullable: Si la columna acepta NULL. Por defecto False.
        default: Valor (o callable) default a nivel de aplicación.
        unique: Constraint UNIQUE.
        length: Longitud máxima — solo tiene efecto en columnas `str` (genera `String(length)`).
    """
    kwargs: dict = {"nullable": nullable, "unique": unique}
    if default is not None:
        kwargs["default"] = default
    if length is not None:
        kwargs["length"] = length
    return _ColumnSpec("column", kwargs)


def ForeignKey(target: str, *, nullable: bool = False, unique: bool = False) -> Any:
    """
    Columna de clave foránea. Se usa junto con `ManyToOne`/`OneToOne` de
    `relations.py` para la navegación entre objetos — esta columna es solo
    el valor crudo (el id), la relación es un atributo aparte.

    Args:
        target: `"tabla.columna"` a la que apunta, ej. `"parents.id"`.
        nullable: Si la relación es opcional.
        unique: Para el lado "dueño" de una relación uno-a-uno.
    """
    return _ColumnSpec("foreign_key", {"target": target, "nullable": nullable, "unique": unique})


def CreateDateColumn() -> Any:
    """
    Columna de timestamp que se llena sola al insertar. El valor lo pone la
    base de datos (`server_default=func.now()`), no Python — así es correcto
    incluso si algo inserta sin pasar por Aqua.
    """
    return _ColumnSpec("create", {"server_default": func.now()})


def UpdateDateColumn() -> Any:
    """
    Columna de timestamp que se actualiza sola en cada UPDATE. También a
    nivel de base de datos (`server_default` + `onupdate=func.now()`).
    """
    return _ColumnSpec("update", {"server_default": func.now(), "onupdate": func.now()})


def DeleteDateColumn() -> Any:
    """
    Columna de soft-delete. Nullable, empieza en NULL. `Repository` (ver
    `core/database/repository.py`) detecta esta columna en el modelo y
    filtra automáticamente `get_by_id`/`get_all`, y habilita `soft_delete()`/
    `restore()`/`get_deleted()` en vez de un DELETE real.
    """
    return _ColumnSpec("soft_delete", {"nullable": True})
