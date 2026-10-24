"""
jsonable_encoder - Convierte cualquier objeto Python a algo serializable
a JSON, antes de que `JSONResponse` llame a `json.dumps`.

Starlette (y por lo tanto Aqua hasta ahora) no tiene esto: su `JSONResponse`
llama `json.dumps` pelado, así que devolver un `datetime`, `UUID`, `Decimal`,
`Enum`, un modelo Pydantic, un `dataclass`, o directamente una instancia de
SQLAlchemy desde un handler tira `TypeError: Object of type X is not JSON
serializable`. Esto es el mismo problema que resolvimos a mano para los 422
de validación (con `include_context=False`) pero generalizado: la causa de
fondo no era "los 422", era que Aqua no tenía ningún encoder de respuesta.

Portado del `jsonable_encoder` de FastAPI (`fastapi/encoders.py`), misma
lógica: intenta tipos conocidos primero (BaseModel, dataclass, Enum, dict,
list/set/tuple, y una tabla de tipos comunes), y como último recurso intenta
`dict(obj)` y después `vars(obj)` para cualquier objeto desconocido.

`sqlalchemy_safe=True` (default) descarta los atributos que empiezan con
`_sa` cuando cae en el fallback de `vars(obj)` — es lo que te deja devolver
una instancia de SQLAlchemy directamente desde un handler sin que el estado
interno de SQLAlchemy (`_sa_instance_state`) rompa la serialización.

Autor: lyrionlannister
Versión: 1.0.0
"""

import dataclasses
import datetime
from collections import deque
from decimal import Decimal
from enum import Enum
from ipaddress import (
    IPv4Address,
    IPv4Interface,
    IPv4Network,
    IPv6Address,
    IPv6Interface,
    IPv6Network,
)
from pathlib import Path, PurePath
from re import Pattern
from types import GeneratorType
from typing import Any, Callable, Dict, Optional, Set, Union
from uuid import UUID

from pydantic import BaseModel
from pydantic.networks import AnyUrl, NameEmail
from pydantic.types import SecretBytes, SecretStr
from pydantic_core import PydanticUndefinedType, Url

try:
    from pydantic.color import Color
except ImportError:  # pragma: no cover
    class Color:
        pass


def _isoformat(o: Union[datetime.date, datetime.time]) -> str:
    return o.isoformat()


def _decimal_encoder(dec_value: Decimal) -> Union[int, float]:
    """Decimal sin exponente -> int, si no -> float (evita perder precisión en el roundtrip)."""
    exponent = dec_value.as_tuple().exponent
    if isinstance(exponent, int) and exponent >= 0:
        return int(dec_value)
    return float(dec_value)


ENCODERS_BY_TYPE: Dict[type, Callable[[Any], Any]] = {
    bytes: lambda o: o.decode(),
    Color: str,
    datetime.date: _isoformat,
    datetime.datetime: _isoformat,
    datetime.time: _isoformat,
    datetime.timedelta: lambda td: td.total_seconds(),
    Decimal: _decimal_encoder,
    Enum: lambda o: o.value,
    frozenset: list,
    deque: list,
    GeneratorType: list,
    IPv4Address: str,
    IPv4Interface: str,
    IPv4Network: str,
    IPv6Address: str,
    IPv6Interface: str,
    IPv6Network: str,
    NameEmail: str,
    Path: str,
    Pattern: lambda o: o.pattern,
    SecretBytes: str,
    SecretStr: str,
    set: list,
    UUID: str,
    Url: str,
    AnyUrl: str,
}


def jsonable_encoder(
    obj: Any,
    include: Optional[Set[str]] = None,
    exclude: Optional[Set[str]] = None,
    by_alias: bool = True,
    exclude_unset: bool = False,
    exclude_defaults: bool = False,
    exclude_none: bool = False,
    custom_encoder: Optional[Dict[type, Callable[[Any], Any]]] = None,
    sqlalchemy_safe: bool = True,
) -> Any:
    """
    Convierte `obj` a algo que `json.dumps` puede serializar.

    Args:
        obj: Lo que va a terminar en el body de la Response.
        include/exclude: Igual que en Pydantic, para modelos BaseModel.
        by_alias: Si los modelos Pydantic se serializan con su alias
                 (ej. camelCase de `BaseSchema`) o con el nombre del atributo.
        exclude_unset/exclude_defaults/exclude_none: Igual que `model_dump`.
        custom_encoder: Override por tipo, se chequea antes que todo lo demás.
        sqlalchemy_safe: Si al caer en `vars(obj)` (objeto desconocido) se
                        descartan los atributos `_sa*` (estado interno de
                        SQLAlchemy) — así se puede devolver una instancia de
                        modelo de SQLAlchemy directamente desde un handler.

    Returns:
        Una estructura hecha solo de dict/list/str/int/float/bool/None,
        lista para `json.dumps`.
    """
    custom_encoder = custom_encoder or {}
    if custom_encoder:
        if type(obj) in custom_encoder:
            return custom_encoder[type(obj)](obj)
        for encoder_type, encoder in custom_encoder.items():
            if isinstance(obj, encoder_type):
                return encoder(obj)

    if isinstance(obj, BaseModel):
        obj_dict = obj.model_dump(
            mode="json",
            include=include,
            exclude=exclude,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_none=exclude_none,
            exclude_defaults=exclude_defaults,
        )
        return jsonable_encoder(
            obj_dict,
            exclude_none=exclude_none,
            exclude_defaults=exclude_defaults,
            sqlalchemy_safe=sqlalchemy_safe,
        )

    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return jsonable_encoder(
            dataclasses.asdict(obj),
            include=include,
            exclude=exclude,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            custom_encoder=custom_encoder,
            sqlalchemy_safe=sqlalchemy_safe,
        )

    if isinstance(obj, Enum):
        return obj.value

    if isinstance(obj, PurePath):
        return str(obj)

    if isinstance(obj, (str, int, float, type(None))):
        return obj

    if isinstance(obj, PydanticUndefinedType):
        return None

    if isinstance(obj, dict):
        allowed_keys = set(obj.keys())
        if include is not None:
            allowed_keys &= include
        if exclude is not None:
            allowed_keys -= exclude
        encoded = {}
        for key, value in obj.items():
            if sqlalchemy_safe and isinstance(key, str) and key.startswith("_sa"):
                continue
            if value is None and exclude_none:
                continue
            if key not in allowed_keys:
                continue
            encoded[jsonable_encoder(key, by_alias=by_alias, sqlalchemy_safe=sqlalchemy_safe)] = jsonable_encoder(
                value,
                by_alias=by_alias,
                exclude_unset=exclude_unset,
                exclude_none=exclude_none,
                custom_encoder=custom_encoder,
                sqlalchemy_safe=sqlalchemy_safe,
            )
        return encoded

    if isinstance(obj, (list, set, frozenset, GeneratorType, tuple, deque)):
        return [
            jsonable_encoder(
                item,
                include=include,
                exclude=exclude,
                by_alias=by_alias,
                exclude_unset=exclude_unset,
                exclude_defaults=exclude_defaults,
                exclude_none=exclude_none,
                custom_encoder=custom_encoder,
                sqlalchemy_safe=sqlalchemy_safe,
            )
            for item in obj
        ]

    if type(obj) in ENCODERS_BY_TYPE:
        return ENCODERS_BY_TYPE[type(obj)](obj)
    for type_, encoder in ENCODERS_BY_TYPE.items():
        if isinstance(obj, type_):
            return encoder(obj)

    # Último recurso para cualquier objeto desconocido (ej. una instancia de
    # modelo de SQLAlchemy): probar dict(obj), y si no, vars(obj).
    try:
        data = dict(obj)
    except Exception:
        try:
            data = vars(obj)
        except Exception as e:
            raise ValueError(
                f"No se pudo convertir a JSON el objeto de tipo {type(obj).__name__}: {obj!r}"
            ) from e

    return jsonable_encoder(
        data,
        include=include,
        exclude=exclude,
        by_alias=by_alias,
        exclude_unset=exclude_unset,
        exclude_defaults=exclude_defaults,
        exclude_none=exclude_none,
        custom_encoder=custom_encoder,
        sqlalchemy_safe=sqlalchemy_safe,
    )
