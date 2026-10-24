"""
Decoradores de relación para `@Entity`, sobre `relationship()` de SQLAlchemy.

A diferencia de las columnas (`columns.py`), la clave foránea (`ForeignKey()`)
y la relación de navegación (`ManyToOne`/`OneToMany`/`OneToOne`/`ManyToMany`)
son dos atributos separados y explícitos — ver `ForeignKey` en `columns.py`
para la columna, y este módulo para la navegación entre objetos.

Autor: lyrionlannister
Versión: 1.0.0
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import relationship


@dataclass
class _RelationshipSpec:
    kind: str
    target: str
    kwargs: dict = field(default_factory=dict)

    def build(self):
        return relationship(self.target, **self.kwargs)


def ManyToOne(target: str, *, back_populates: Optional[str] = None) -> Any:
    """
    Lado "muchos" de una relación uno-a-muchos: muchas instancias de esta
    entidad apuntan a una sola `target`. Necesita una columna `ForeignKey()`
    aparte apuntando a la tabla de `target`.

    Args:
        target: Nombre de la clase `@Entity` del otro lado (ej. `"Parent"`).
        back_populates: Nombre del atributo `OneToMany()` del otro lado, para
                       que ambas direcciones se mantengan sincronizadas en memoria.
    """
    kwargs: dict = {}
    if back_populates:
        kwargs["back_populates"] = back_populates
    return _RelationshipSpec("many_to_one", target, kwargs)


def OneToMany(target: str, *, back_populates: Optional[str] = None) -> Any:
    """
    Lado "muchos" visto desde el "uno": una lista de instancias de `target`
    que apuntan a esta entidad.

    Args:
        target: Nombre de la clase `@Entity` del otro lado (ej. `"Child"`).
        back_populates: Nombre del atributo `ManyToOne()` del otro lado.
    """
    kwargs: dict = {}
    if back_populates:
        kwargs["back_populates"] = back_populates
    return _RelationshipSpec("one_to_many", target, kwargs)


def OneToOne(target: str, *, back_populates: Optional[str] = None) -> Any:
    """
    Relación uno-a-uno. El lado que declara la columna `ForeignKey()` es el
    "dueño" de la relación; el otro lado solo necesita `OneToOne()` con
    `back_populates` apuntando al primero.

    Args:
        target: Nombre de la clase `@Entity` del otro lado.
        back_populates: Nombre del atributo `OneToOne()` del otro lado.
    """
    kwargs: dict = {"uselist": False}
    if back_populates:
        kwargs["back_populates"] = back_populates
    return _RelationshipSpec("one_to_one", target, kwargs)


def ManyToMany(target: str, *, join_table: str, back_populates: Optional[str] = None) -> Any:
    """
    Relación muchos-a-muchos vía una tabla intermedia.

    Args:
        target: Nombre de la clase `@Entity` del otro lado.
        join_table: Nombre de la tabla intermedia (debe existir en
                   `Base.metadata` — definila con `sqlalchemy.Table`).
        back_populates: Nombre del atributo `ManyToMany()` del otro lado.
    """
    kwargs: dict = {"secondary": join_table}
    if back_populates:
        kwargs["back_populates"] = back_populates
    return _RelationshipSpec("many_to_many", target, kwargs)
