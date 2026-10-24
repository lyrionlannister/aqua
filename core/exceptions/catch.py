"""
@Catch: registra una función como handler para una o más excepciones (o
status codes), equivalente a `@app.exception_handler()` de FastAPI.

Por debajo se resuelve a `Starlette.add_exception_handler` — Aqua hereda el
stack de middleware de Starlette (`ServerErrorMiddleware`/`ExceptionMiddleware`),
así que registrar un handler acá es decirle a ESE stack qué hacer con una
excepción puntual en vez de dejarla caer al 500 genérico.

Autor: lyrionlannister
Versión: 1.0.0
"""

from typing import Callable, Type, Union


def Catch(*exception_types: Union[int, Type[Exception]]):
    """
    Decora una función `async def handler(request, exc) -> Response` para
    que maneje una o más excepciones (o status codes) en vez del 500
    genérico.

    Example:
        ```python
        class UserNotFoundError(Exception):
            pass

        @Catch(UserNotFoundError)
        async def handle_user_not_found(request: Request, exc: UserNotFoundError) -> Response:
            return JSONResponse({"error": str(exc)}, status_code=404)

        @Module(exception_handlers=[handle_user_not_found], ...)
        class AppModule:
            pass
        ```

    Args:
        *exception_types: Una o más clases de excepción, o status codes
                          (int) — ej. `@Catch(500)` para el catch-all.

    Returns:
        function: Decorador que marca la función con los tipos que atrapa.
    """
    def decorator(func: Callable) -> Callable:
        func._catch_types = exception_types
        return func
    return decorator
