"""
DatabaseModule: empaqueta los providers de base de datos (`session.py`) en
un módulo importable, configurado con `DataSourceOptions`.

    @Module(imports=[DatabaseModule(DataSourceOptions(synchronize=True))], ...)

Autor: lyrionlannister
Versión: 2.0.0
"""

from typing import Optional

from core.module import Module
from core.database.options import DataSourceOptions
from core.database.session import build_database_providers


def DatabaseModule(options: Optional[DataSourceOptions] = None):
    """
    Args:
        options: `DataSourceOptions` (url, synchronize, echo, pool_size,
                 max_overflow). Si es None, usa los defaults.

    Returns:
        type: Clase `@Module` lista para `imports=[DatabaseModule(...)]`.
    """
    providers = build_database_providers(options)

    @Module(providers=providers)
    class _ConfiguredDatabaseModule:
        pass

    return _ConfiguredDatabaseModule
