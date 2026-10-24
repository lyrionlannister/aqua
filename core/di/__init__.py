"""
DI Package - Inyección de dependencias de Aqua

Exporta:
    Injectable: Marca una clase como resoluble por el Container
    Inject: Override manual de una dependencia por nombre de parámetro
    Scope: SINGLETON (default) o REQUEST
"""

from core.di.di_decorators import Injectable, Inject, Scope

__all__ = ["Injectable", "Inject", "Scope"]
