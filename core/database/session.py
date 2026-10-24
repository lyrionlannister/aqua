"""
Providers de sesión de SQLAlchemy para el Container de Aqua.

Encadena tres providers:
    AsyncEngine (singleton)
        -> async_sessionmaker (singleton)
            -> AsyncSession (request-scoped)

Cualquier repository/service que reciba un `AsyncSession` en su constructor
queda automáticamente request-scoped por propagación (ver `Container._resolve`),
sin tener que declarar `@Injectable(scope=Scope.REQUEST)` a mano.

Al terminar la request, `destroy_session` hace commit si no hubo excepción,
rollback si la hubo, y siempre cierra la sesión — mismo criterio que
cualquier patrón de "unit of work por request".

Autor: lyrionlannister
Versión: 2.0.0
"""

from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from core.container.provider import Provider
from core.di import Scope
from core.database.database import Base, build_engine
from core.database.options import DataSourceOptions


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(bind=engine, expire_on_commit=False)


def create_session(session_factory: async_sessionmaker) -> AsyncSession:
    return session_factory()


async def destroy_session(session: AsyncSession, exc: Optional[BaseException]) -> None:
    try:
        if exc is None:
            await session.commit()
        else:
            await session.rollback()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


class _SynchronizeToken:
    """Nadie inyecta esto — su único propósito es que el Container lo resuelva
    una vez en boot (singleton) y dispare `_synchronize` como efecto de lado."""


async def _synchronize(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def build_database_providers(options: Optional[DataSourceOptions] = None) -> List[Provider]:
    """
    Construye la lista de providers de base de datos a partir de `DataSourceOptions`.

    Args:
        options: Configuración tipada (url, synchronize, echo, pool_size,
                max_overflow). Si es None, usa los defaults de `DataSourceOptions`.

    Returns:
        list[Provider]: lista para `Module(providers=[*lista, ...])`, o usala
        a través de `DatabaseModule(options)` (`database_module.py`).
    """
    options = options or DataSourceOptions()

    def _create_engine() -> AsyncEngine:
        return build_engine(options)

    providers = [
        Provider(token=AsyncEngine, factory=_create_engine, scope=Scope.SINGLETON),
        Provider(token=async_sessionmaker, factory=create_session_factory, scope=Scope.SINGLETON),
        Provider(
            token=AsyncSession,
            factory=create_session,
            scope=Scope.REQUEST,
            on_destroy=destroy_session,
        ),
    ]

    if options.synchronize:
        providers.append(Provider(token=_SynchronizeToken, factory=_synchronize, scope=Scope.SINGLETON))

    return providers


DATABASE_PROVIDERS = build_database_providers()
"""Providers con la configuración default — lista para `Module(providers=[*DATABASE_PROVIDERS, ...])`
cuando no necesitás tocar ninguna opción. Para configurar, usá `DatabaseModule(options)`."""
