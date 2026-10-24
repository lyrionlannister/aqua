"""
Decorador @Dto: define un DTO con la misma sintaxis que el resto del
framework — decorás una clase plana con type hints, no heredás de nada.

Por debajo construye un modelo Pydantic real (con `pydantic.create_model`),
basado en `BaseSchema` (alias camelCase/snake_case, ver `schema_base.py`),
así que todo lo que ya sabe hacer Pydantic funciona igual:
- Validación por type hint y `Field(...)` para constraints (tipo class-validator)
- `@field_validator`/`@model_validator` para reglas custom con mensaje propio
  (el `raise ValueError("mensaje")` que tires ahí es lo que Pydantic devuelve
  en el 422 — así se "pasan los mensajes de error" para que los reciba Pydantic)

Autor: lyrionlannister
Versión: 2.0.0
"""

from typing import get_type_hints

from pydantic import create_model

from core.dto.schema_base import BaseSchema


def Dto(cls):
    """
    Convierte una clase plana con type hints en un modelo Pydantic real.

    Example:
        ```python
        @Dto
        class CreateUserDto:
            user_name: str
            age: int = 0

            @field_validator("age")
            @classmethod
            def age_no_negativa(cls, v):
                if v < 0:
                    raise ValueError("la edad no puede ser negativa")
                return v

        # equivalente a:
        class CreateUserDto(BaseSchema):
            user_name: str
            age: int = 0

            @field_validator("age")
            @classmethod
            def age_no_negativa(cls, v):
                if v < 0:
                    raise ValueError("la edad no puede ser negativa")
                return v

        # acepta tanto {"userName": "Ada"} (alias camelCase, lo que manda
        # un front típico) como {"user_name": "Ada"} (populate_by_name=True)
        ```

    Args:
        cls (type): Clase plana con atributos tipados (y opcionalmente
                   valores default, `Field(...)`, y métodos decorados con
                   `@field_validator`/`@model_validator` de Pydantic).

    Returns:
        type: Un nuevo modelo Pydantic (subclase de `BaseSchema`) con los
             mismos campos, validators y métodos que `cls`.
    """
    hints = get_type_hints(cls, include_extras=True)
    fields = {
        name: (type_, getattr(cls, name, ...))
        for name, type_ in hints.items()
    }

    validators = {}
    namespace = {}
    for name, attr in vars(cls).items():
        if name in hints or name.startswith("__"):
            continue
        if hasattr(attr, "decorator_info"):
            # Decorado con @field_validator/@model_validator/etc. — Pydantic
            # lo reconoce por este atributo, se lo pasamos vía __validators__.
            validators[name] = attr
        else:
            # Método normal (helper, property, etc.) — se conserva tal cual.
            namespace[name] = attr

    return create_model(
        cls.__name__,
        __base__=BaseSchema,
        __validators__=validators or None,
        __namespace__=namespace or None,
        **fields,
    )
