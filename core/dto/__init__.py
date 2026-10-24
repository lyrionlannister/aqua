"""
DTO Package - Definición de DTOs con decoradores

Exporta:
    Dto: Decorador para definir un DTO como clase plana con type hints
    BaseSchema: BaseModel compartido (alias camelCase/snake_case) que usa @Dto
"""

from core.dto.dto import Dto
from core.dto.schema_base import BaseSchema

__all__ = ["Dto", "BaseSchema"]
