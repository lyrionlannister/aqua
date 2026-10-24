"""
Schema base de Pydantic para los DTO de Aqua: alias en camelCase para el
JSON (lo que manda el cliente), snake_case en Python (lo que escribís en el
handler). `populate_by_name=True` acepta ambas formas de todos modos, y
`from_attributes=True` permite construir el DTO a partir de un objeto
(ej. un modelo de SQLAlchemy) y no solo de un dict.

Autor: lyrionlannister
Versión: 1.0.0
"""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class BaseSchema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )
