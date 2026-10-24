"""
Encoding Package - Serialización de respuestas para Aqua

Exporta:
    jsonable_encoder: Convierte cualquier objeto Python a algo serializable
        a JSON (fechas, UUID, Decimal, Enum, BaseModel, dataclass, modelos
        de SQLAlchemy, etc.) antes de pasarlo a `JSONResponse`.
"""

from core.encoding.encoder import jsonable_encoder

__all__ = ["jsonable_encoder"]
