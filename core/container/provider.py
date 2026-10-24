"""
Provider - Registro de dependencias que no son clases @Injectable

Permite registrar en el Container cómo construir un tipo que no controlás
(ej. `AsyncSession` de SQLAlchemy) sin necesidad de decorarlo con @Injectable.

Autor: lyrionlannister
Versión: 1.0.0
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from core.di import Scope


@dataclass
class Provider:
    """
    Describe cómo construir una instancia de `token` cuando algo la pide
    por type hint.

    Attributes:
        token: El tipo que se usa en los type hints para pedir esta dependencia
              (ej. `AsyncSession`). Es la clave con la que se registra en el Container.
        factory: Callable (sync o async) que construye la instancia. Sus parámetros
                se resuelven igual que un constructor `@Injectable`: por type hint,
                recursivamente contra el Container.
        scope: Scope.SINGLETON (default) o Scope.REQUEST.
        on_destroy: Callback opcional `async def (instance, exc) -> None` que se
                   ejecuta al terminar la request si `scope=Scope.REQUEST`. `exc` es
                   la excepción que tiró el handler, o None si la request fue exitosa.
                   Pensado para commit/rollback/close de recursos como un AsyncSession.

    Example:
        ```python
        def create_engine() -> AsyncEngine:
            return create_async_engine(DATABASE_URL)

        def create_session(engine: AsyncEngine) -> AsyncSession:
            return async_sessionmaker(bind=engine)()

        async def destroy_session(session: AsyncSession, exc) -> None:
            await (session.rollback() if exc else session.commit())
            await session.close()

        Module(providers=[
            Provider(token=AsyncEngine, factory=create_engine),
            Provider(token=AsyncSession, factory=create_session, scope=Scope.REQUEST, on_destroy=destroy_session),
        ])
        ```
    """
    token: Any
    factory: Callable
    scope: Scope = Scope.SINGLETON
    on_destroy: Optional[Callable[[Any, Optional[BaseException]], Awaitable[None]]] = None
