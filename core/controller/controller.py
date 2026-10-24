"""
Controller Decorators - Sistema de Enrutamiento

Este módulo proporciona decoradores para definir controladores y rutas HTTP
en el framework Aqua. Sigue un patrón similar a frameworks como NestJS o FastAPI.

Autor: lyrionlannister
Versión: 2.0.0
"""
def Controller(prefix: str = ""):
    """
    Decorador para marcar una clase como controlador y definir un prefijo de ruta.

    Args:
        prefix (str, optional): Prefijo que se agregará a todas las rutas del controlador.
                               Por defecto "". Ejemplo: "/api/v1"

    Returns:
        function: Decorador que modifica la clase agregando metadatos de ruta.

    Example:
        ```python
        @Controller("/users")
        class UserController:
            @Get("/")
            async def list_users(self, request):
                return {"users": []}

        # Resultará en la ruta: GET /users/
        ```

    Note:
        El prefijo se combina con las rutas individuales definidas en los métodos.
        Si el prefijo es "/api" y el método tiene ruta "/users", la ruta final será "/api/users".
    """
    def decorator(cls):
        cls._route_prefix = prefix
        return cls
    return decorator


def _route(method: str, path: str, allow_raw_request: bool):
    def decorator(func):
        setattr(func, "_route_info", {
            "method": method,
            "path": path,
            "allow_raw_request": allow_raw_request,
        })
        return func
    return decorator


def Get(path: str, allow_raw_request: bool = False):
    """
    Decorador para definir una ruta HTTP GET.

    Args:
        path (str): Ruta relativa para este endpoint. Ejemplo: "/", "/users", "/users/<int:id>"
        allow_raw_request (bool, optional): Si el handler puede declarar `request`
            y acceder al objeto crudo (ej. `await request.json()`). Por defecto
            False — el body SIEMPRE se tipa con un modelo Pydantic; declarar
            `request` sin este flag tira una excepción en boot.

    Returns:
        function: Decorador que agrega metadatos de ruta al método.

    Example:
        ```python
        @Get("/users")
        async def get_users(self):
            return {"users": []}
        ```
    """
    return _route("GET", path, allow_raw_request)


def Post(path: str, allow_raw_request: bool = False):
    """
    Decorador para definir una ruta HTTP POST.

    Args:
        path (str): Ruta relativa para este endpoint.
        allow_raw_request (bool, optional): Ver `Get`. Por defecto False.

    Returns:
        function: Decorador que agrega metadatos de ruta al método.

    Example:
        ```python
        @Post("/users")
        async def create_user(self, body: CreateUserDto):
            # body ya viene parseado y validado por Pydantic
            return {"created": True}
        ```
    """
    return _route("POST", path, allow_raw_request)


def Put(path: str, allow_raw_request: bool = False):
    """
    Decorador para definir una ruta HTTP PUT.

    Args:
        path (str): Ruta relativa para este endpoint.
        allow_raw_request (bool, optional): Ver `Get`. Por defecto False.

    Returns:
        function: Decorador que agrega metadatos de ruta al método.

    Example:
        ```python
        @Put("/users/<int:user_id>")
        async def update_user(self, user_id: int, body: UpdateUserDto):
            return {"updated": True}
        ```
    """
    return _route("PUT", path, allow_raw_request)


def Delete(path: str, allow_raw_request: bool = False):
    """
    Decorador para definir una ruta HTTP DELETE.

    Args:
        path (str): Ruta relativa para este endpoint.
        allow_raw_request (bool, optional): Ver `Get`. Por defecto False.

    Returns:
        function: Decorador que agrega metadatos de ruta al método.

    Example:
        ```python
        @Delete("/users/<int:user_id>")
        async def delete_user(self, user_id: int):
            return {"deleted": True}
        ```
    """
    return _route("DELETE", path, allow_raw_request)


def Patch(path: str, allow_raw_request: bool = False):
    """
    Decorador para definir una ruta HTTP PATCH.

    Args:
        path (str): Ruta relativa para este endpoint.
        allow_raw_request (bool, optional): Ver `Get`. Por defecto False.

    Returns:
        function: Decorador que agrega metadatos de ruta al método.

    Example:
        ```python
        @Patch("/users/<int:user_id>")
        async def patch_user(self, user_id: int, body: PatchUserDto):
            return {"patched": True}
        ```
    """
    return _route("PATCH", path, allow_raw_request)
