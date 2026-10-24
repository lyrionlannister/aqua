"""
Database Package - SQLAlchemy async para Aqua

Exporta:
    Base: DeclarativeBase que deben heredar los modelos
    Repository: Repository genérico con CRUD común
    InjectRepository: Repository genérico para una entidad, sin subclase manual
    DataSourceOptions: Configuración tipada (url, synchronize, echo, pool_size, max_overflow)
    DATABASE_PROVIDERS: Providers (engine/session_factory/session) con la config default
    DatabaseModule: Los mismos providers, configurados y empaquetados para `imports=[DatabaseModule(...)]`
"""

from core.database.database import Base
from core.database.repository import Repository
from core.database.inject_repository import InjectRepository
from core.database.options import DataSourceOptions
from core.database.session import DATABASE_PROVIDERS
from core.database.database_module import DatabaseModule

__all__ = [
    "Base", "Repository", "InjectRepository",
    "DataSourceOptions", "DATABASE_PROVIDERS", "DatabaseModule",
]
