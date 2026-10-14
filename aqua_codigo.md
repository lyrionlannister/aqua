## __init__.py
```python
from core import *

__all__ = ["core"]
```

## app_example.py
```python
from . import Aqua, Module

@Module
class AppModule():
    pass



app = Aqua()
```

## core\__init__.py
```python
"""
Aqua Framework

Importa todo lo público de Aqua desde un solo lugar, igual que
`from fastapi import FastAPI, Depends` o `from '@nestjs/common' import
{ Controller, Injectable }` — no hace falta saber en qué submódulo vive
cada decorador.

La clase `Aqua` en sí vive en `core/application.py`; este archivo es solo
el punto de entrada público.
"""

from core.application import Aqua
from core.controller import Controller, Get, Post, Put, Delete, Patch
from core.module import Module
from core.di import Injectable, Inject, Scope
from core.dto import Dto, BaseSchema
from core.entity import (
    Entity,
    PrimaryGeneratedColumn,
    PrimaryColumn,
    Column,
    ForeignKey,
    CreateDateColumn,
    UpdateDateColumn,
    DeleteDateColumn,
    ManyToOne,
    OneToMany,
    OneToOne,
    ManyToMany,
)
from core.database import Base, Repository, InjectRepository, DataSourceOptions, DATABASE_PROVIDERS, DatabaseModule
from core.container import Container, Provider
from core.encoding import jsonable_encoder
from core.exceptions import Catch

__all__ = [
    "Aqua",
    "Controller", "Get", "Post", "Put", "Delete", "Patch",
    "Module",
    "Injectable", "Inject", "Scope",
    "Dto", "BaseSchema",
    "Entity",
    "PrimaryGeneratedColumn", "PrimaryColumn", "Column", "ForeignKey",
    "CreateDateColumn", "UpdateDateColumn", "DeleteDateColumn",
    "ManyToOne", "OneToMany", "OneToOne", "ManyToMany",
    "Base", "Repository", "InjectRepository", "DataSourceOptions", "DATABASE_PROVIDERS", "DatabaseModule",
    "Container", "Provider",
    "jsonable_encoder",
    "Catch",
]

```

## core\application.py
```python
"""
Aqua Framework - Application

Este módulo contiene la clase principal Aqua, que hereda de `Starlette`.
Aqua aporta la capa de decoradores (controllers, módulos, DI); Starlette
aporta el motor ASGI real: matching de rutas, compilación de regex una sola
vez por ruta, stack de middleware y manejo de excepciones.

Autor: lyrionlannister
Versión: 2.0.0
"""

import inspect
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.routing import Route
from uvicorn import run as uvicorn_run

from core.container import Container, Provider
from core.di import Scope
from core.router import translate_path, parse_param_types, validate_handler_signature, build_endpoint
from core.logger.logger import logger


class Aqua(Starlette):
    """
    Framework Aqua: decoradores estilo NestJS sobre el motor ASGI de Starlette.

    Attributes:
        container (Container): Contenedor de inyección de dependencias
        root_module: Módulo raíz que contiene controladores y proveedores

    Example:
        ```python
        from core import Aqua, Module

        app_module = Module(
            controllers=[UserController],
            providers=[UserService]
        )
        app = Aqua(app_module)
        app.run(app_import_string="main:app")
        ```
    """

    def __init__(self, root_module):
        """
        Args:
            root_module: Módulo decorado con @Module que contiene los
                        controllers y providers de la aplicación.
        """
        self.container = Container()
        self.root_module = root_module

        # Los exception handlers tienen que estar YA en el dict que recibe
        # Starlette.__init__, no agregados después con add_exception_handler:
        # Starlette arma (y cachea) su middleware_stack en la primera llamada
        # ASGI — que es el propio evento lifespan.startup — copiando
        # self.exception_handlers en ese momento. Nuestro _setup corre DENTRO
        # de ese lifespan, así que si registráramos ahí, siempre llegaríamos
        # tarde: el stack ya se habría armado con el dict vacío.
        exception_handlers = self._collect_exception_handlers(root_module)
        super().__init__(lifespan=self._lifespan, exception_handlers=exception_handlers)

    def _collect_exception_handlers(self, module_cls) -> dict:
        """
        Recorre el módulo (y sus imports) recolectando los handlers `@Catch(...)`.
        Es síncrono a propósito: no depende de nada async, y tiene que correr
        antes de `Starlette.__init__` (ver nota en `__init__`).
        """
        config = getattr(module_cls, "_module_config", None)
        if config is None:
            raise Exception(f"{module_cls.__name__} no está decorado con @Module")

        handlers: dict = {}
        for imported_module in config.get("imports", []):
            handlers.update(self._collect_exception_handlers(imported_module))

        for handler in config.get("exception_handlers", []):
            exc_types = getattr(handler, "_catch_types", None)
            if not exc_types:
                raise Exception(f"{handler.__name__} debe estar decorado con @Catch(...)")
            for exc_type in exc_types:
                handlers[exc_type] = handler

        return handlers

    @asynccontextmanager
    async def _lifespan(self, app):
        """
        Lifespan de Starlette: resuelve providers y registra controllers
        antes de que la app empiece a recibir requests.
        """
        await self._setup(self.root_module)
        yield

    async def _setup(self, module_cls):
        config = getattr(module_cls, "_module_config", None)
        if config is None:
            raise Exception(f"{module_cls.__name__} no está decorado con @Module")

        for imported_module in config.get("imports", []):
            await self._setup(imported_module)

        for provider in config.get("exports", []):
            await self.container.resolve(provider)
        await self._resolve_providers(config.get("providers", []))
        await self._register_controllers(config.get("controllers", []))

    async def _resolve_providers(self, providers):
        """
        Registra/resuelve los providers del módulo.

        Un `Provider` (factory) se registra siempre en el Container; si es
        singleton se resuelve ahora también, para fallar rápido en boot si
        el factory tira una excepción (ej. URL de DB inválida).

        Una clase @Injectable se resuelve ahora si es singleton. Si es
        request-scoped (por sí misma o por una dependencia), no se resuelve
        en boot — no hay request todavía.
        """
        for provider in providers:
            if isinstance(provider, Provider):
                self.container.register(provider)
                token_name = getattr(provider.token, "__name__", str(provider.token))
                if provider.scope == Scope.SINGLETON:
                    logger.debug(f"Resolviendo provider (factory): {token_name}")
                    await self.container.resolve(provider.token)
                else:
                    logger.debug(f"{token_name} es request-scoped (factory), no se resuelve en boot")
                continue

            scope = self.container.get_effective_scope(provider)
            if scope == Scope.SINGLETON:
                logger.debug(f"Resolviendo proveedor: {provider.__name__}")
                await self.container.resolve(provider)
            else:
                logger.debug(f"{provider.__name__} es request-scoped, no se resuelve en boot")

    async def _register_controllers(self, controllers):
        """
        Registra las rutas de cada controller.

        Un controller singleton (default) se resuelve una sola vez, ahora.
        Un controller request-scoped (porque él o alguna de sus dependencias
        tiene `@Injectable(scope=Scope.REQUEST)`) no se resuelve todavía —
        se resuelve de nuevo en cada request (ver `build_endpoint`).
        """
        for controller_cls in controllers:
            logger.info(f"Configurando controlador: {controller_cls.__name__}")
            scope = self.container.get_effective_scope(controller_cls)

            if scope == Scope.REQUEST:
                logger.info(f"{controller_cls.__name__} es request-scoped, se resuelve por request")
                controller_instance = None
            else:
                controller_instance = await self.container.resolve(controller_cls)

            self._register_controller_routes(controller_cls, controller_instance, scope)

    def _register_controller_routes(self, controller_cls, controller_instance, scope: Scope):
        """
        Traduce cada método decorado con @Get/@Post/etc. a un
        `starlette.routing.Route` y lo agrega al router de la app.
        """
        prefix = getattr(controller_cls, "_route_prefix", "")

        route_methods = [
            (name, method) for name, method in inspect.getmembers(
                controller_cls,
                predicate=inspect.iscoroutinefunction
            ) if hasattr(method, "_route_info")
        ]

        for name, method in route_methods:
            route_info = method._route_info
            aqua_path = prefix.rstrip("/") + route_info["path"]
            full_path = translate_path(aqua_path)

            path_param_types = parse_param_types(aqua_path)
            allow_raw_request = route_info.get("allow_raw_request", False)
            route_signature = validate_handler_signature(method, path_param_types, allow_raw_request)

            logger.info(f"Registrando ruta: {route_info['method'].upper()} {full_path} -> {controller_cls.__name__}.{name}")

            if scope == Scope.SINGLETON:
                bound_method = getattr(controller_instance, name)

                async def get_handler(request_cache, bound_method=bound_method):
                    return bound_method
            else:
                async def get_handler(request_cache, controller_cls=controller_cls, name=name):
                    instance = await self.container.resolve(controller_cls, request_cache)
                    return getattr(instance, name)

            self.router.routes.append(
                Route(
                    full_path,
                    endpoint=build_endpoint(get_handler, container=self.container, route_signature=route_signature),
                    methods=[route_info["method"]],
                )
            )

    def run(self, *, app_import_string: str | None = None, host="localhost", port=4200, reload=True, log_level="critical"):
        """
        Inicia el servidor de desarrollo usando Uvicorn.

        Args:
            app_import_string: Ruta de import de la app, ej "main:app". Obligatorio
                              si reload=True, porque Uvicorn necesita poder
                              reimportar la app en el subproceso de reload.
            host (str, optional): Dirección IP donde escuchar. Por defecto "localhost".
            port (int, optional): Puerto donde escuchar. Por defecto 4200.
            reload (bool, optional): Si habilitar auto-reload en desarrollo. Por defecto True.
            log_level (str, optional): Nivel de log de Uvicorn. Por defecto "critical".

        Example:
            ```python
            app = Aqua(AppModule)
            app.run(app_import_string="main:app", host="0.0.0.0", port=8000)
            ```
        """
        if reload:
            if not app_import_string:
                raise ValueError(
                    "reload=True requiere app_import_string (ej: app.run(app_import_string='main:app')), "
                    "Uvicorn necesita reimportar la app en el subproceso de reload."
                )
            uvicorn_run(app_import_string, host=host, port=port, reload=True, log_level=log_level)
        else:
            uvicorn_run(self, host=host, port=port, log_level=log_level)

```

## core\container\__init__.py
```python
"""
Container Package - Sistema de Inyección de Dependencias

Este paquete proporciona el sistema de inyección de dependencias del framework Aqua.
Incluye la clase Container que maneja la resolución automática de dependencias,
y Provider para registrar factories de tipos que no son clases @Injectable.

Exporta:
    Container: Clase principal para resolver dependencias
    Provider: Descriptor de factory para tipos no-@Injectable
"""

from .container import Container
from .provider import Provider

__all__ = ["Container", "Provider"]
```

## core\container\container.py
```python
"""
Container - Sistema de Inyección de Dependencias

Este módulo implementa un contenedor de inyección de dependencias para el framework Aqua.
Permite la resolución automática de dependencias usando type hints y decoradores,
con dos scopes de vida: singleton (default) y por-request. Además de clases
@Injectable, puede resolver `Provider` (factories) para tipos que no controlás.

Autor: lyrionlannister
Versión: 3.0.0
"""

import inspect

from core.di import Scope
from core.container.provider import Provider


class Container:
    """
    Contenedor de inyección de dependencias para el framework Aqua.

    Este contenedor:
    - Resuelve dependencias automáticamente usando type hints
    - Cachea singletons para toda la vida de la app
    - Resuelve clases/providers Scope.REQUEST (y cualquier cosa que dependa de
      ellos) una vez por request, usando un `request_cache` que el llamador provee
    - Soporta inyección manual usando el decorador @Inject
    - Soporta `Provider` (factory) para tipos que no son clases @Injectable

    Example:
        ```python
        container = Container()

        @Injectable
        class MyService:
            pass

        @Injectable
        class MyController:
            def __init__(self, service: MyService):
                self.service = service

        controller = await container.resolve(MyController)
        ```
    """

    def __init__(self):
        """
        Inicializa un nuevo contenedor de inyección de dependencias.
        """
        self._singletons = {}
        self._providers: dict = {}

    def register(self, provider: Provider) -> None:
        """
        Registra un `Provider` (factory) para que `provider.token` sea
        resoluble por type hint, igual que una clase @Injectable.
        """
        self._providers[provider.token] = provider

    def get_provider(self, token):
        """Devuelve el `Provider` registrado para `token`, o None si no hay."""
        return self._providers.get(token)

    def _get_spec(self, token):
        """
        Devuelve (own_scope, params, build) para `token`:
        - own_scope: Scope declarado por `token` mismo (sin mirar dependencias)
        - params: lista de (nombre, dep_token) a resolver e inyectar
        - build: callable(*deps) -> instancia (puede devolver un awaitable)
        """
        provider = self._providers.get(token)
        if provider is not None:
            sig = inspect.signature(provider.factory)
            params = []
            for name, param in sig.parameters.items():
                if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                    continue
                if param.annotation is inspect.Parameter.empty:
                    raise Exception(f"Debe anotar la dependencia '{name}' en el factory de {token}")
                params.append((name, param.annotation))
            return provider.scope, params, provider.factory

        if not getattr(token, "_injectable", False):
            raise Exception(f"{token} no está registrado como Provider ni decorado con @Injectable")

        sig = inspect.signature(token.__init__)
        overrides = getattr(token, "_inject_overrides", {})
        params = []
        for name, param in list(sig.parameters.items())[1:]:
            if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                continue
            dep_token = overrides.get(name, param.annotation)
            if dep_token is inspect.Parameter.empty:
                raise Exception(f"Debe anotar o inyectar la dependencia '{name}' en {token.__name__}")
            params.append((name, dep_token))

        own_scope = getattr(token, "_scope", Scope.SINGLETON)
        return own_scope, params, token

    async def resolve(self, token, request_cache: dict | None = None):
        """
        Resuelve `token` (clase @Injectable o token de Provider) y todas sus
        dependencias recursivamente.

        Args:
            token: Clase @Injectable, o token registrado vía `register(Provider(...))`.
            request_cache (dict, optional): Cache de vida de una sola request.
                Necesario si `token` (o alguna dependencia, directa o indirecta)
                tiene scope Scope.REQUEST.

        Returns:
            object: Instancia resuelta con todas sus dependencias inyectadas

        Raises:
            Exception: Si `token` no está registrado ni decorado con @Injectable
            Exception: Si alguna dependencia no está anotada correctamente
            Exception: Si requiere scope de request y no se proveyó `request_cache`
        """
        instance, _ = await self._resolve(token, request_cache)
        return instance

    async def _resolve(self, token, request_cache: dict | None):
        """
        Igual que `resolve`, pero además devuelve si la cadena resuelta es
        request-scoped, para que el llamador (una dependencia de más arriba)
        sepa que tampoco puede cachearse como singleton.

        Returns:
            tuple[object, bool]: (instancia, es_request_scoped)
        """
        if token in self._singletons:
            return self._singletons[token], False

        if request_cache is not None and token in request_cache:
            return request_cache[token], True

        own_scope, params, build = self._get_spec(token)
        is_request_scoped = own_scope == Scope.REQUEST

        deps = []
        for _, dep_token in params:
            dep_instance, dep_request_scoped = await self._resolve(dep_token, request_cache)
            deps.append(dep_instance)
            is_request_scoped = is_request_scoped or dep_request_scoped

        instance = build(*deps)
        if inspect.isawaitable(instance):
            instance = await instance

        if is_request_scoped:
            if request_cache is None:
                raise Exception(
                    f"{token} requiere scope de request (depende de un provider "
                    f"Scope.REQUEST) pero se intentó resolver fuera de una request"
                )
            request_cache[token] = instance
        else:
            self._singletons[token] = instance

        return instance, is_request_scoped

    def get_effective_scope(self, token) -> Scope:
        """
        Determina el scope efectivo de `token` sin instanciar nada: mira su
        scope propio y, recursivamente, el de sus dependencias. Si cualquiera
        en la cadena es Scope.REQUEST, el resultado es Scope.REQUEST (misma
        regla de propagación que `_resolve`).

        Se usa para decidir, antes de arrancar la app, si un controller se
        puede resolver una sola vez en boot o si hay que resolverlo por request.

        Args:
            token: Clase @Injectable o token de Provider a inspeccionar.

        Returns:
            Scope: Scope.REQUEST si `token` o alguna dependencia lo es, si no Scope.SINGLETON
        """
        own_scope, params, _ = self._get_spec(token)
        if own_scope == Scope.REQUEST:
            return Scope.REQUEST

        for _, dep_token in params:
            if self.get_effective_scope(dep_token) == Scope.REQUEST:
                return Scope.REQUEST

        return Scope.SINGLETON

    async def cleanup_request(self, request_cache: dict, exc: BaseException | None) -> None:
        """
        Cierra los recursos request-scoped resueltos durante una request.

        Para cada instancia en `request_cache`, si su token tiene un `Provider`
        con `on_destroy`, lo ejecuta pasándole la excepción que tiró el handler
        (o None si la request fue exitosa) — pensado para commit/rollback/close
        de cosas como un `AsyncSession`.

        Args:
            request_cache: El mismo dict que se le pasó a `resolve()` durante la request.
            exc: Excepción que tiró el handler, o None si respondió sin error.
        """
        for token, instance in request_cache.items():
            provider = self._providers.get(token)
            if provider is not None and provider.on_destroy is not None:
                await provider.on_destroy(instance, exc)

```

## core\container\provider.py
```python
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

```

## core\controller\__init__.py
```python
"""
Controller Package - Sistema de Controladores y Rutas

Este paquete proporciona decoradores para definir controladores y rutas HTTP
en el framework Aqua. Permite crear APIs REST de manera declarativa.

Exporta:
    Controller: Decorador para marcar clases como controladores
    Get: Decorador para rutas HTTP GET
    Post: Decorador para rutas HTTP POST  
    Put: Decorador para rutas HTTP PUT
    Delete: Decorador para rutas HTTP DELETE
    Patch: Decorador para rutas HTTP PATCH
"""

from .controller import Controller, Get, Post, Put, Delete, Patch

__all__ = ["Controller", "Get", "Post", "Put", "Delete", "Patch"]
```

## core\controller\controller.py
```python
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

```

## core\database\__init__.py
```python
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

```

## core\database\database_module.py
```python
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

```

## core\database\database.py
```python
"""
Motor y sesión de SQLAlchemy async para Aqua.

Define el engine, el `Base` declarativo y la clase `DeclarativeBase` que
usan los modelos. La URL se toma de `DataSourceOptions.url`, de los campos
separados (`DataSourceOptions.engine`/..) o de la variable de entorno
`DATABASE_URL` — sin ningún default implícito: un framework no debe asumir
qué base de datos querés usar.

Autor: lyrionlannister
Versión: 1.0.0
"""

import os

from sqlalchemy import MetaData
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from core.database.options import DataSourceOptions

# Sin esto, cada motor de DB nombra los constraints a su manera y las
# migraciones no pueden referenciarlos de forma estable.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _build_url(options: DataSourceOptions) -> str:
    """
    Arma la connection string a partir de los campos separados de
    `DataSourceOptions`, usando `sqlalchemy.engine.URL.create` — nunca
    f-string a mano, porque un password con `@`/`:`/`/` rompe una URL armada
    a mano y `URL.create` lo escapa correcto.

    Prioridad: `options.url` (si se dio, se usa tal cual) > campos separados
    (si se dio `engine`) > env var `DATABASE_URL`. Sin ninguno de los tres,
    error explícito — no hay fallback a una base de datos local.
    """
    if options.url:
        return options.url

    if options.engine is None:
        url = os.getenv("DATABASE_URL")
        if not url:
            raise ValueError(
                "No se configuró la base de datos: pasá `DataSourceOptions(url=...)` "
                "o `engine=...`, o definí la variable de entorno `DATABASE_URL`."
            )
        return url

    drivername = f"{options.engine}+{options.driver}" if options.driver else options.engine
    return URL.create(
        drivername=drivername,
        username=options.username,
        password=options.password,
        host=options.host,
        port=options.port,
        database=options.database,
    )


def build_engine(options: DataSourceOptions) -> AsyncEngine:
    """
    Construye el engine a partir de `DataSourceOptions`. Pensado para
    registrarse como `Provider(token=AsyncEngine, ...)` singleton — un solo
    engine (y su pool de conexiones) para toda la vida de la app.
    """
    url = _build_url(options)

    kwargs: dict = {"echo": options.echo}
    if options.pool_size is not None:
        kwargs["pool_size"] = options.pool_size
    if options.max_overflow is not None:
        kwargs["max_overflow"] = options.max_overflow

    return create_async_engine(url, **kwargs)

```

## core\database\inject_repository.py
```python
"""
InjectRepository: repository genérico para una entidad, sin escribir una
subclase de `Repository` a mano cuando solo necesitás el CRUD básico.

Usarlo directamente como type hint alcanza para que el Container lo resuelva
— no hace falta ningún mecanismo nuevo, `InjectRepository(User)` devuelve una
clase real ya decorada con `@Injectable`:

```python
@Injectable
class UserService:
    def __init__(self, repo: InjectRepository(User)):
        self.repo = repo
```

Autor: lyrionlannister
Versión: 1.0.0
"""

from typing import Type, TypeVar

from core.database.repository import Repository
from core.di import Injectable

T = TypeVar("T")

_cache: dict = {}


def InjectRepository(model_class: Type[T]) -> Type[Repository]:
    """
    Devuelve (memoizado) un `Repository` ya ligado a `model_class`, listo
    para usar como type hint en cualquier constructor `@Injectable`.

    Llamarlo dos veces con la misma entidad devuelve la MISMA clase — así el
    Container lo cachea como un solo singleton (o un solo request-scoped si
    la entidad usa `AsyncSession`), no uno distinto por cada punto de inyección.

    Args:
        model_class: La clase `@Entity` sobre la que opera el repository.

    Returns:
        type: Subclase de `Repository` con `model_class` ya seteado.
    """
    if model_class not in _cache:
        _cache[model_class] = Injectable(
            type(f"{model_class.__name__}Repository", (Repository,), {"model_class": model_class})
        )
    return _cache[model_class]

```

## core\database\options.py
```python
"""
DataSourceOptions - Configuración tipada de la conexión de SQLAlchemy.

Versión reducida del `DataSourceOptions` de TypeORM, pero separando `engine`
(el dialect: "postgresql", "mysql", "sqlite"...) de `driver` (el driver async
concreto: "asyncpg", "aiomysql", "aiosqlite"...) en vez de un solo `type` —
porque así es como SQLAlchemy realmente arma la URL (`dialect+driver://...`),
tener los dos campos separados es más fiel a cómo se conecta de verdad.

Dos campos que tiene TypeORM no están acá a propósito, no porque falten:
- `entities`: `Base.metadata` los recolecta solo — cualquier clase `@Entity`
  queda registrada por herencia, no hay que listarlas a mano.

Autor: lyrionlannister
Versión: 2.0.0
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class DataSourceOptions:
    engine: Optional[str] = None
    """Dialect de la base: "postgresql", "mysql", "sqlite", etc."""

    driver: Optional[str] = None
    """Driver async concreto: "asyncpg", "aiomysql", "aiosqlite", etc."""

    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    database: Optional[str] = None
    """Nombre de la base — o, para SQLite, la ruta del archivo."""

    url: Optional[str] = None
    """Connection string completo, ya armado. Si se da, tiene prioridad sobre
    engine/driver/host/.../database — pensado como escape hatch para casos
    que no entran en el modelo de campos separados (ej. sockets Unix)."""

    synchronize: bool = False
    """Crea las tablas automáticamente al arrancar (`Base.metadata.create_all`).
    Mismo nombre y misma advertencia que TypeORM: no usar en producción,
    usar migraciones ahí."""

    echo: bool = False
    """Loguea cada SQL que ejecuta SQLAlchemy."""

    pool_size: Optional[int] = None
    """Tamaño del pool de conexiones. No aplica a SQLite (pool nulo por defecto)."""

    max_overflow: Optional[int] = None
    """Conexiones extra permitidas por encima de `pool_size` en picos de carga."""

```

## core\database\repository.py
```python
"""Repository genérico con las operaciones CRUD comunes a todos los modelos."""

from datetime import datetime, timezone
from typing import Generic, List, Optional, Sequence, Type, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.database import Base

T = TypeVar("T", bound=Base)


class Repository(Generic[T]):
    """
    Repository genérico: recibe un `AsyncSession` (request-scoped, inyectado
    automáticamente por el Container) y opera sobre `model_class`.

    Si `model_class` tiene una columna `DeleteDateColumn()` (ver
    `core/entity/columns.py`), `get_by_id`/`get_all` excluyen automáticamente
    los registros con esa columna seteada. `delete()` siempre hace un DELETE
    real; para marcar la columna sin borrar la fila usá `soft_delete()`.

    Example:
        ```python
        @Injectable
        class UserRepository(Repository[User]):
            model_class = User
        ```
    """
    model_class: Type[T]

    def __init__(self, session: AsyncSession):
        self.session = session

    @property
    def _soft_delete_column(self) -> Optional[str]:
        return getattr(self.model_class, "__soft_delete_column__", None)

    async def add(self, instance: T) -> T:
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def add_many(self, instances: List[T]) -> Sequence[T]:
        self.session.add_all(instances)
        await self.session.flush()
        for instance in instances:
            await self.session.refresh(instance)
        return instances

    async def get_by_id(self, id: object) -> Optional[T]:
        instance = await self.session.get(self.model_class, id)
        soft_col = self._soft_delete_column
        if instance is not None and soft_col is not None and getattr(instance, soft_col) is not None:
            return None
        return instance

    async def get_all(self) -> Sequence[T]:
        stmt = select(self.model_class)
        soft_col = self._soft_delete_column
        if soft_col is not None:
            stmt = stmt.where(getattr(self.model_class, soft_col).is_(None))
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update(self, instance: T) -> T:
        merged = await self.session.merge(instance)
        await self.session.flush()
        await self.session.refresh(merged)
        return merged

    async def delete(self, instance: T) -> None:
        """DELETE real — borra la fila, haya o no columna de soft-delete."""
        attached = await self.session.merge(instance)
        await self.session.delete(attached)
        await self.session.flush()

    async def soft_delete(self, instance: T) -> T:
        """Setea la columna de soft-delete sin borrar la fila. Solo válido si `model_class` tiene `DeleteDateColumn()`."""
        soft_col = self._soft_delete_column
        if soft_col is None:
            raise Exception(f"{self.model_class.__name__} no tiene DeleteDateColumn(), usá delete()")
        attached = await self.session.merge(instance)
        setattr(attached, soft_col, datetime.now(timezone.utc))
        await self.session.flush()
        await self.session.refresh(attached)
        return attached

    async def restore(self, instance: T) -> T:
        """Deshace un soft_delete(). Solo válido si `model_class` tiene `DeleteDateColumn()`."""
        soft_col = self._soft_delete_column
        if soft_col is None:
            raise Exception(f"{self.model_class.__name__} no tiene DeleteDateColumn(), no hay nada que restaurar")
        attached = await self.session.merge(instance)
        setattr(attached, soft_col, None)
        await self.session.flush()
        await self.session.refresh(attached)
        return attached

    async def get_deleted(self) -> Sequence[T]:
        """Los registros soft-deleted (la papelera). Solo válido con `DeleteDateColumn()`."""
        soft_col = self._soft_delete_column
        if soft_col is None:
            raise Exception(f"{self.model_class.__name__} no tiene DeleteDateColumn()")
        stmt = select(self.model_class).where(getattr(self.model_class, soft_col).is_not(None))
        result = await self.session.execute(stmt)
        return result.scalars().all()

```

## core\database\session.py
```python
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

```

## core\di\__init__.py
```python
"""
DI Package - Inyección de dependencias de Aqua

Exporta:
    Injectable: Marca una clase como resoluble por el Container
    Inject: Override manual de una dependencia por nombre de parámetro
    Scope: SINGLETON (default) o REQUEST
"""

from core.di.di_decorators import Injectable, Inject, Scope

__all__ = ["Injectable", "Inject", "Scope"]

```

## core\di\di_decorators.py
```python
"""
Dependency Injection Decorators

Este módulo proporciona decoradores para el sistema de inyección de dependencias
del framework Aqua. Permite marcar clases como inyectables, configurar
inyecciones manuales de dependencias, y declarar su scope (singleton o por-request).

Autor: lyrionlannister
Versión: 2.0.0
"""

from enum import Enum


class Scope(Enum):
    """
    Scope de vida de una clase inyectable.

    SINGLETON (default): se resuelve una sola vez y se cachea para toda la
        vida de la app (igual que siempre funcionó Aqua).
    REQUEST: se resuelve una vez por cada request HTTP entrante y se descarta
        al terminar. Cualquier clase que dependa (directa o indirectamente)
        de una clase REQUEST se vuelve request-scoped también, aunque ella
        misma no lo declare — mismo comportamiento que Scope.REQUEST en NestJS.
    """
    SINGLETON = "singleton"
    REQUEST = "request"


def Injectable(cls=None, *, scope: Scope = Scope.SINGLETON):
    """
    Decorador para marcar una clase como inyectable en el contenedor de DI.

    Las clases marcadas con @Injectable pueden ser:
    - Resueltas automáticamente por el contenedor
    - Inyectadas como dependencias en otras clases
    - Cacheadas como singletons (default) o resueltas por request (scope=Scope.REQUEST)

    Args:
        cls (type, optional): Clase a marcar como inyectable. Se pasa automáticamente
                             cuando se usa como `@Injectable` sin paréntesis.
        scope (Scope, optional): Scope de vida de la clase. Por defecto Scope.SINGLETON.

    Returns:
        type: La misma clase con metadatos de inyección agregados

    Example:
        ```python
        @Injectable
        class UserService:
            def __init__(self, repo: UserRepository):
                self.repo = repo

        @Injectable
        class UserRepository:
            def __init__(self):
                pass

        @Injectable(scope=Scope.REQUEST)
        class RequestScopedThing:
            pass

        # Ambas clases pueden ser resueltas por el contenedor
        container = Container()
        service = await container.resolve(UserService)  # UserRepository se inyecta automáticamente
        ```

    Note:
        - Todas las clases que serán manejadas por el contenedor DEBEN tener este decorador
        - Sin este decorador, el contenedor lanzará una excepción al intentar resolver la clase
    """
    def wrap(target):
        target._injectable = True
        target._scope = scope
        return target

    if cls is None:
        return wrap
    return wrap(cls)


def Inject(**kwargs):
    """
    Decorador para especificar inyecciones manuales de dependencias.
    
    Permite override manual de dependencias cuando los type hints no son suficientes
    o cuando se necesita inyectar una implementación específica.
    
    Args:
        **kwargs: Mapeo de nombre_parametro=ClaseAInyectar
        
    Returns:
        function: Decorador que agrega metadatos de inyección manual a la clase
        
    Example:
        ```python
        @Injectable
        class EmailService:
            pass
            
        @Injectable  
        class SMSService:
            pass
            
        @Injectable
        @Inject(notification_service=EmailService)  # Forzar EmailService en lugar del type hint
        class UserController:
            def __init__(self, notification_service):  # Sin type hint, usa el @Inject
                self.notification_service = notification_service
                
        # O con type hint diferente:
        @Injectable
        @Inject(notification_service=SMSService)  # Override del type hint
        class AdminController:
            def __init__(self, notification_service: EmailService):  # Type hint dice EmailService
                self.notification_service = notification_service  # Pero se inyecta SMSService
        ```
        
    Note:
        - Los valores en @Inject tienen prioridad sobre los type hints
        - Útil para casos donde necesitas inyectar diferentes implementaciones de una interfaz
        - Los nombres de los parámetros deben coincidir exactamente con los del constructor
    """
    def wrapper(cls):
        cls._inject_overrides = kwargs
        return cls
    return wrapper
```

## core\dto\__init__.py
```python
"""
DTO Package - Definición de DTOs con decoradores

Exporta:
    Dto: Decorador para definir un DTO como clase plana con type hints
    BaseSchema: BaseModel compartido (alias camelCase/snake_case) que usa @Dto
"""

from core.dto.dto import Dto
from core.dto.schema_base import BaseSchema

__all__ = ["Dto", "BaseSchema"]

```

## core\dto\dto.py
```python
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

```

## core\dto\schema_base.py
```python
"""
Schema base de Pydantic para los DTO de Aqua: alias en camelCase para el
JSON (lo que manda el cliente), snake_case en Python (lo que escribís en el
handler). `populate_by_name=True` acepta ambas formas de todos modos, y
`from_attributes=True` permite construir el DTO a partir de un objeto
(ej. un modelo de SQLAlchemy) y no solo de un dict.

Autor: lyrionlannister
Versión: 1.0.0
"""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class BaseSchema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )

```

## core\encoding\__init__.py
```python
"""
Encoding Package - Serialización de respuestas para Aqua

Exporta:
    jsonable_encoder: Convierte cualquier objeto Python a algo serializable
        a JSON (fechas, UUID, Decimal, Enum, BaseModel, dataclass, modelos
        de SQLAlchemy, etc.) antes de pasarlo a `JSONResponse`.
"""

from core.encoding.encoder import jsonable_encoder

__all__ = ["jsonable_encoder"]

```

## core\encoding\encoder.py
```python
"""
jsonable_encoder - Convierte cualquier objeto Python a algo serializable
a JSON, antes de que `JSONResponse` llame a `json.dumps`.

Starlette (y por lo tanto Aqua hasta ahora) no tiene esto: su `JSONResponse`
llama `json.dumps` pelado, así que devolver un `datetime`, `UUID`, `Decimal`,
`Enum`, un modelo Pydantic, un `dataclass`, o directamente una instancia de
SQLAlchemy desde un handler tira `TypeError: Object of type X is not JSON
serializable`. Esto es el mismo problema que resolvimos a mano para los 422
de validación (con `include_context=False`) pero generalizado: la causa de
fondo no era "los 422", era que Aqua no tenía ningún encoder de respuesta.

Portado del `jsonable_encoder` de FastAPI (`fastapi/encoders.py`), misma
lógica: intenta tipos conocidos primero (BaseModel, dataclass, Enum, dict,
list/set/tuple, y una tabla de tipos comunes), y como último recurso intenta
`dict(obj)` y después `vars(obj)` para cualquier objeto desconocido.

`sqlalchemy_safe=True` (default) descarta los atributos que empiezan con
`_sa` cuando cae en el fallback de `vars(obj)` — es lo que te deja devolver
una instancia de SQLAlchemy directamente desde un handler sin que el estado
interno de SQLAlchemy (`_sa_instance_state`) rompa la serialización.

Autor: lyrionlannister
Versión: 1.0.0
"""

import dataclasses
import datetime
from collections import deque
from decimal import Decimal
from enum import Enum
from ipaddress import (
    IPv4Address,
    IPv4Interface,
    IPv4Network,
    IPv6Address,
    IPv6Interface,
    IPv6Network,
)
from pathlib import Path, PurePath
from re import Pattern
from types import GeneratorType
from typing import Any, Callable, Dict, Optional, Set, Union
from uuid import UUID

from pydantic import BaseModel
from pydantic.networks import AnyUrl, NameEmail
from pydantic.types import SecretBytes, SecretStr
from pydantic_core import PydanticUndefinedType, Url

try:
    from pydantic.color import Color
except ImportError:  # pragma: no cover
    class Color:
        pass


def _isoformat(o: Union[datetime.date, datetime.time]) -> str:
    return o.isoformat()


def _decimal_encoder(dec_value: Decimal) -> Union[int, float]:
    """Decimal sin exponente -> int, si no -> float (evita perder precisión en el roundtrip)."""
    exponent = dec_value.as_tuple().exponent
    if isinstance(exponent, int) and exponent >= 0:
        return int(dec_value)
    return float(dec_value)


ENCODERS_BY_TYPE: Dict[type, Callable[[Any], Any]] = {
    bytes: lambda o: o.decode(),
    Color: str,
    datetime.date: _isoformat,
    datetime.datetime: _isoformat,
    datetime.time: _isoformat,
    datetime.timedelta: lambda td: td.total_seconds(),
    Decimal: _decimal_encoder,
    Enum: lambda o: o.value,
    frozenset: list,
    deque: list,
    GeneratorType: list,
    IPv4Address: str,
    IPv4Interface: str,
    IPv4Network: str,
    IPv6Address: str,
    IPv6Interface: str,
    IPv6Network: str,
    NameEmail: str,
    Path: str,
    Pattern: lambda o: o.pattern,
    SecretBytes: str,
    SecretStr: str,
    set: list,
    UUID: str,
    Url: str,
    AnyUrl: str,
}


def jsonable_encoder(
    obj: Any,
    include: Optional[Set[str]] = None,
    exclude: Optional[Set[str]] = None,
    by_alias: bool = True,
    exclude_unset: bool = False,
    exclude_defaults: bool = False,
    exclude_none: bool = False,
    custom_encoder: Optional[Dict[type, Callable[[Any], Any]]] = None,
    sqlalchemy_safe: bool = True,
) -> Any:
    """
    Convierte `obj` a algo que `json.dumps` puede serializar.

    Args:
        obj: Lo que va a terminar en el body de la Response.
        include/exclude: Igual que en Pydantic, para modelos BaseModel.
        by_alias: Si los modelos Pydantic se serializan con su alias
                 (ej. camelCase de `BaseSchema`) o con el nombre del atributo.
        exclude_unset/exclude_defaults/exclude_none: Igual que `model_dump`.
        custom_encoder: Override por tipo, se chequea antes que todo lo demás.
        sqlalchemy_safe: Si al caer en `vars(obj)` (objeto desconocido) se
                        descartan los atributos `_sa*` (estado interno de
                        SQLAlchemy) — así se puede devolver una instancia de
                        modelo de SQLAlchemy directamente desde un handler.

    Returns:
        Una estructura hecha solo de dict/list/str/int/float/bool/None,
        lista para `json.dumps`.
    """
    custom_encoder = custom_encoder or {}
    if custom_encoder:
        if type(obj) in custom_encoder:
            return custom_encoder[type(obj)](obj)
        for encoder_type, encoder in custom_encoder.items():
            if isinstance(obj, encoder_type):
                return encoder(obj)

    if isinstance(obj, BaseModel):
        obj_dict = obj.model_dump(
            mode="json",
            include=include,
            exclude=exclude,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_none=exclude_none,
            exclude_defaults=exclude_defaults,
        )
        return jsonable_encoder(
            obj_dict,
            exclude_none=exclude_none,
            exclude_defaults=exclude_defaults,
            sqlalchemy_safe=sqlalchemy_safe,
        )

    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return jsonable_encoder(
            dataclasses.asdict(obj),
            include=include,
            exclude=exclude,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            custom_encoder=custom_encoder,
            sqlalchemy_safe=sqlalchemy_safe,
        )

    if isinstance(obj, Enum):
        return obj.value

    if isinstance(obj, PurePath):
        return str(obj)

    if isinstance(obj, (str, int, float, type(None))):
        return obj

    if isinstance(obj, PydanticUndefinedType):
        return None

    if isinstance(obj, dict):
        allowed_keys = set(obj.keys())
        if include is not None:
            allowed_keys &= include
        if exclude is not None:
            allowed_keys -= exclude
        encoded = {}
        for key, value in obj.items():
            if sqlalchemy_safe and isinstance(key, str) and key.startswith("_sa"):
                continue
            if value is None and exclude_none:
                continue
            if key not in allowed_keys:
                continue
            encoded[jsonable_encoder(key, by_alias=by_alias, sqlalchemy_safe=sqlalchemy_safe)] = jsonable_encoder(
                value,
                by_alias=by_alias,
                exclude_unset=exclude_unset,
                exclude_none=exclude_none,
                custom_encoder=custom_encoder,
                sqlalchemy_safe=sqlalchemy_safe,
            )
        return encoded

    if isinstance(obj, (list, set, frozenset, GeneratorType, tuple, deque)):
        return [
            jsonable_encoder(
                item,
                include=include,
                exclude=exclude,
                by_alias=by_alias,
                exclude_unset=exclude_unset,
                exclude_defaults=exclude_defaults,
                exclude_none=exclude_none,
                custom_encoder=custom_encoder,
                sqlalchemy_safe=sqlalchemy_safe,
            )
            for item in obj
        ]

    if type(obj) in ENCODERS_BY_TYPE:
        return ENCODERS_BY_TYPE[type(obj)](obj)
    for type_, encoder in ENCODERS_BY_TYPE.items():
        if isinstance(obj, type_):
            return encoder(obj)

    # Último recurso para cualquier objeto desconocido (ej. una instancia de
    # modelo de SQLAlchemy): probar dict(obj), y si no, vars(obj).
    try:
        data = dict(obj)
    except Exception:
        try:
            data = vars(obj)
        except Exception as e:
            raise ValueError(
                f"No se pudo convertir a JSON el objeto de tipo {type(obj).__name__}: {obj!r}"
            ) from e

    return jsonable_encoder(
        data,
        include=include,
        exclude=exclude,
        by_alias=by_alias,
        exclude_unset=exclude_unset,
        exclude_defaults=exclude_defaults,
        exclude_none=exclude_none,
        custom_encoder=custom_encoder,
        sqlalchemy_safe=sqlalchemy_safe,
    )

```

## core\entity\__init__.py
```python
"""
Entity Package - Modelos de SQLAlchemy definidos con decoradores

Exporta:
    Entity: Decorador de clase que define una tabla
    PrimaryGeneratedColumn, PrimaryColumn, Column: columnas
    CreateDateColumn, UpdateDateColumn, DeleteDateColumn: columnas especiales
"""

from core.entity.entity import Entity
from core.entity.columns import (
    PrimaryGeneratedColumn,
    PrimaryColumn,
    Column,
    ForeignKey,
    CreateDateColumn,
    UpdateDateColumn,
    DeleteDateColumn,
)
from core.entity.relations import ManyToOne, OneToMany, OneToOne, ManyToMany

__all__ = [
    "Entity",
    "PrimaryGeneratedColumn",
    "PrimaryColumn",
    "Column",
    "ForeignKey",
    "CreateDateColumn",
    "UpdateDateColumn",
    "DeleteDateColumn",
    "ManyToOne",
    "OneToMany",
    "OneToOne",
    "ManyToMany",
]

```

## core\entity\columns.py
```python
"""
Decoradores de columna para `@Entity`, sobre `mapped_column` de SQLAlchemy.

Cada uno devuelve un `_ColumnSpec`: todavía no es la columna real, porque
`mapped_column(...)` necesita saber el tipo Python del atributo (via
`Mapped[tipo]`) para inferir el tipo SQL, y eso recién se sabe en `@Entity`
(ver `entity.py`), leyendo el type hint de la clase. `_ColumnSpec.build()`
es quien construye la columna real, ya con el tipo en mano.

Autor: lyrionlannister
Versión: 1.0.0
"""

import typing
import uuid as uuid_module
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import ForeignKey as SAForeignKey
from sqlalchemy import String, func
from sqlalchemy.orm import MappedColumn, mapped_column


def _unwrap_optional(python_type: Any) -> Any:
    """`Optional[str]` (== `Union[str, None]`) -> `str`. Cualquier otro tipo, igual."""
    if typing.get_origin(python_type) is typing.Union:
        args = [a for a in typing.get_args(python_type) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return python_type


@dataclass
class _ColumnSpec:
    kind: str
    kwargs: dict = field(default_factory=dict)

    def build(self, python_type: type) -> MappedColumn:
        kwargs = dict(self.kwargs)
        if self.kind == "foreign_key":
            target = kwargs.pop("target")
            return mapped_column(SAForeignKey(target), **kwargs)
        length = kwargs.pop("length", None)
        if length is not None and _unwrap_optional(python_type) is str:
            return mapped_column(String(length), **kwargs)
        return mapped_column(**kwargs)


def PrimaryGeneratedColumn(*, uuid: bool = False) -> Any:
    """
    Primary key que se autogenera — nunca la asignás vos.

    Args:
        uuid: Si True, se genera un UUID4 en Python al crear la instancia.
             Si no, auto-increment entero (lo asigna la base de datos).
    """
    kwargs: dict = {"primary_key": True}
    if uuid:
        kwargs["default"] = uuid_module.uuid4
    else:
        kwargs["autoincrement"] = True
    return _ColumnSpec("primary_generated", kwargs)


def PrimaryColumn() -> Any:
    """Primary key que asignás vos a mano antes de guardar (sin autoincrement)."""
    return _ColumnSpec("primary", {"primary_key": True, "autoincrement": False})


def Column(*, nullable: bool = False, default: Optional[Any] = None, unique: bool = False, length: Optional[int] = None) -> Any:
    """
    Columna normal.

    Args:
        nullable: Si la columna acepta NULL. Por defecto False.
        default: Valor (o callable) default a nivel de aplicación.
        unique: Constraint UNIQUE.
        length: Longitud máxima — solo tiene efecto en columnas `str` (genera `String(length)`).
    """
    kwargs: dict = {"nullable": nullable, "unique": unique}
    if default is not None:
        kwargs["default"] = default
    if length is not None:
        kwargs["length"] = length
    return _ColumnSpec("column", kwargs)


def ForeignKey(target: str, *, nullable: bool = False, unique: bool = False) -> Any:
    """
    Columna de clave foránea. Se usa junto con `ManyToOne`/`OneToOne` de
    `relations.py` para la navegación entre objetos — esta columna es solo
    el valor crudo (el id), la relación es un atributo aparte.

    Args:
        target: `"tabla.columna"` a la que apunta, ej. `"parents.id"`.
        nullable: Si la relación es opcional.
        unique: Para el lado "dueño" de una relación uno-a-uno.
    """
    return _ColumnSpec("foreign_key", {"target": target, "nullable": nullable, "unique": unique})


def CreateDateColumn() -> Any:
    """
    Columna de timestamp que se llena sola al insertar. El valor lo pone la
    base de datos (`server_default=func.now()`), no Python — así es correcto
    incluso si algo inserta sin pasar por Aqua.
    """
    return _ColumnSpec("create", {"server_default": func.now()})


def UpdateDateColumn() -> Any:
    """
    Columna de timestamp que se actualiza sola en cada UPDATE. También a
    nivel de base de datos (`server_default` + `onupdate=func.now()`).
    """
    return _ColumnSpec("update", {"server_default": func.now(), "onupdate": func.now()})


def DeleteDateColumn() -> Any:
    """
    Columna de soft-delete. Nullable, empieza en NULL. `Repository` (ver
    `core/database/repository.py`) detecta esta columna en el modelo y
    filtra automáticamente `get_by_id`/`get_all`, y habilita `soft_delete()`/
    `restore()`/`get_deleted()` en vez de un DELETE real.
    """
    return _ColumnSpec("soft_delete", {"nullable": True})

```

## core\entity\entity.py
```python
"""
Decorador @Entity: define un modelo de SQLAlchemy con la misma sintaxis
declarativa que el resto de Aqua — clase plana con type hints, cada atributo
con un marcador de columna (`PrimaryGeneratedColumn()`, `Column()`, etc. de
`columns.py`), sin heredar `Base` a mano ni escribir `Mapped[...]` vos mismo.

Por debajo construye una subclase real de `Base` (`core/database/database.py`)
vía `type(...)`, igual que `@Dto` construye un `BaseModel` real vía `create_model`.

Autor: lyrionlannister
Versión: 1.0.0
"""

import re
from typing import Optional

from sqlalchemy.orm import Mapped

from core.database.database import Base
from core.entity.columns import _ColumnSpec
from core.entity.relations import _RelationshipSpec

_CAMEL_TO_SNAKE = re.compile(r"(?<!^)(?=[A-Z])")

# Dunders que SQLAlchemy sí necesita leer de la clase declarativa (constraints
# multi-columna, args del mapper). El resto de los dunders (__module__,
# __qualname__, etc.) los pone Python solo y no hay que copiarlos.
_SQLALCHEMY_DUNDERS = ("__table_args__", "__mapper_args__")


def _default_table_name(cls_name: str) -> str:
    return _CAMEL_TO_SNAKE.sub("_", cls_name).lower()


def Entity(table_name: Optional[str] = None):
    """
    Convierte una clase plana con type hints en un modelo real de SQLAlchemy.

    Example:
        ```python
        @Entity("users")
        class User:
            id: int = PrimaryGeneratedColumn()
            name: str = Column(length=150)
            email: str = Column(unique=True)
            created_at: datetime = CreateDateColumn()
            updated_at: datetime = UpdateDateColumn()
            deleted_at: datetime = DeleteDateColumn()
        ```

    Args:
        table_name: Nombre de la tabla. Si no se da, se deriva de la clase
                   (`UserPreference` -> `user_preference`).

    Returns:
        function: Decorador que devuelve una subclase real de `Base` con el
                 mismo nombre, columnas, y métodos que la clase original.

    Raises:
        Exception: Si algún atributo tipado no usa uno de los marcadores de
                  `columns.py`/`relations.py` (`PrimaryGeneratedColumn`/
                  `PrimaryColumn`/`Column`/`ForeignKey`/`CreateDateColumn`/
                  `UpdateDateColumn`/`DeleteDateColumn`/`ManyToOne`/`OneToMany`/
                  `OneToOne`/`ManyToMany`).
    """
    def decorator(cls):
        # __annotations__ crudo, no get_type_hints: una relación puede
        # referenciar una entidad todavía no definida (ej. "Parent" como
        # forward ref) y get_type_hints la intentaría resolver ya mismo.
        # SQLAlchemy resuelve esos nombres recién al configurar los mappers,
        # no necesitamos la clase real ahora.
        hints = getattr(cls, "__annotations__", {})
        namespace: dict = {"__tablename__": table_name or _default_table_name(cls.__name__)}
        annotations: dict = {}
        soft_delete_column = None

        for name, python_type in hints.items():
            spec = getattr(cls, name, None)
            if isinstance(spec, _ColumnSpec):
                annotations[name] = Mapped[python_type]
                namespace[name] = spec.build(python_type)
                if spec.kind == "soft_delete":
                    soft_delete_column = name
            elif isinstance(spec, _RelationshipSpec):
                annotations[name] = Mapped[python_type]
                namespace[name] = spec.build()
            else:
                raise Exception(
                    f"'{name}' en {cls.__name__} debe estar definido con PrimaryGeneratedColumn()/"
                    f"PrimaryColumn()/Column()/ForeignKey()/CreateDateColumn()/UpdateDateColumn()/"
                    f"DeleteDateColumn()/ManyToOne()/OneToMany()/OneToOne()/ManyToMany()"
                )

        for name, attr in vars(cls).items():
            if name in hints:
                continue
            if name.startswith("__") and name not in _SQLALCHEMY_DUNDERS:
                continue
            namespace[name] = attr

        namespace["__annotations__"] = annotations
        namespace["__soft_delete_column__"] = soft_delete_column

        return type(cls.__name__, (Base,), namespace)

    return decorator

```

## core\entity\relations.py
```python
"""
Decoradores de relación para `@Entity`, sobre `relationship()` de SQLAlchemy.

A diferencia de las columnas (`columns.py`), la clave foránea (`ForeignKey()`)
y la relación de navegación (`ManyToOne`/`OneToMany`/`OneToOne`/`ManyToMany`)
son dos atributos separados y explícitos — ver `ForeignKey` en `columns.py`
para la columna, y este módulo para la navegación entre objetos.

Autor: lyrionlannister
Versión: 1.0.0
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import relationship


@dataclass
class _RelationshipSpec:
    kind: str
    target: str
    kwargs: dict = field(default_factory=dict)

    def build(self):
        return relationship(self.target, **self.kwargs)


def ManyToOne(target: str, *, back_populates: Optional[str] = None) -> Any:
    """
    Lado "muchos" de una relación uno-a-muchos: muchas instancias de esta
    entidad apuntan a una sola `target`. Necesita una columna `ForeignKey()`
    aparte apuntando a la tabla de `target`.

    Args:
        target: Nombre de la clase `@Entity` del otro lado (ej. `"Parent"`).
        back_populates: Nombre del atributo `OneToMany()` del otro lado, para
                       que ambas direcciones se mantengan sincronizadas en memoria.
    """
    kwargs: dict = {}
    if back_populates:
        kwargs["back_populates"] = back_populates
    return _RelationshipSpec("many_to_one", target, kwargs)


def OneToMany(target: str, *, back_populates: Optional[str] = None) -> Any:
    """
    Lado "muchos" visto desde el "uno": una lista de instancias de `target`
    que apuntan a esta entidad.

    Args:
        target: Nombre de la clase `@Entity` del otro lado (ej. `"Child"`).
        back_populates: Nombre del atributo `ManyToOne()` del otro lado.
    """
    kwargs: dict = {}
    if back_populates:
        kwargs["back_populates"] = back_populates
    return _RelationshipSpec("one_to_many", target, kwargs)


def OneToOne(target: str, *, back_populates: Optional[str] = None) -> Any:
    """
    Relación uno-a-uno. El lado que declara la columna `ForeignKey()` es el
    "dueño" de la relación; el otro lado solo necesita `OneToOne()` con
    `back_populates` apuntando al primero.

    Args:
        target: Nombre de la clase `@Entity` del otro lado.
        back_populates: Nombre del atributo `OneToOne()` del otro lado.
    """
    kwargs: dict = {"uselist": False}
    if back_populates:
        kwargs["back_populates"] = back_populates
    return _RelationshipSpec("one_to_one", target, kwargs)


def ManyToMany(target: str, *, join_table: str, back_populates: Optional[str] = None) -> Any:
    """
    Relación muchos-a-muchos vía una tabla intermedia.

    Args:
        target: Nombre de la clase `@Entity` del otro lado.
        join_table: Nombre de la tabla intermedia (debe existir en
                   `Base.metadata` — definila con `sqlalchemy.Table`).
        back_populates: Nombre del atributo `ManyToMany()` del otro lado.
    """
    kwargs: dict = {"secondary": join_table}
    if back_populates:
        kwargs["back_populates"] = back_populates
    return _RelationshipSpec("many_to_many", target, kwargs)

```

## core\exceptions\__init__.py
```python
"""
Exceptions Package - Manejo de excepciones de Aqua

Exporta:
    Catch: Decorador para registrar un handler de excepciones (o status code)
"""

from core.exceptions.catch import Catch

__all__ = ["Catch"]

```

## core\exceptions\catch.py
```python
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

```

## core\logger\__init__.py
```python
from .logger import Logger, logger


__all__ = ["Logger", "logger"]
```

## core\logger\logger.py
```python
"""
Módulo de utilidades de logging para la aplicación.

Proporciona:
- MonthlyDailyRotatingFileHandler: un handler que rota logs diariamente y organiza
  los ficheros dentro de carpetas por mes (YYYY-MM).
- Logger: wrapper singleton para obtener un logger configurado con consola y archivo.

Ejemplos:
    logger = Logger.get_logger()
    logger.info("Arrancando aplicación")
"""

import os
import sys
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime

class MonthlyDailyRotatingFileHandler(TimedRotatingFileHandler):
    """
    Rotates log files daily and creates a new folder for each month.
    """
    def __init__(self, base_dir="./output-logs", when="midnight", interval=1, backupCount=30, encoding=None):
        self.base_dir = base_dir
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)
        self.current_month = None
        log_path = self._get_log_path()
        super().__init__(log_path, when=when, interval=interval, backupCount=backupCount, encoding=encoding)

    def _get_log_path(self):
        now = datetime.now()
        month_folder = os.path.join(self.base_dir, now.strftime("%Y-%m"))
        if not os.path.exists(month_folder):
            os.makedirs(month_folder, exist_ok=True)
        return os.path.join(month_folder, now.strftime("%Y-%m-%d") + ".log")

    def doRollover(self):
        """Overrides TimedRotatingFileHandler rollover to also handle monthly folder creation"""
        self.stream.close()
        self.baseFilename = self._get_log_path()
        self.stream = self._open()

class Logger:
    """
    Singleton que expone un logger configurado para la aplicación.

    Configura:
    - StreamHandler (consola) a nivel DEBUG.
    - MonthlyDailyRotatingFileHandler (archivo) a nivel DEBUG.
    - Formato: "%(asctime)s - %(levelname)s - %(message)s".

    Uso:
        logger = Logger.get_logger()
        logger.debug("mensaje")
    """
    
    _ENV = os.getenv("ENV", "development")
    assert _ENV in ["development", "production"], "ENV debe ser 'development' o 'production'"

    @classmethod
    def get_logger(cls):
        """
        Devuelve la instancia singleton del logger.

        Si aún no existe la instancia, la crea.

        Returns:
            logging.Logger: Logger configurado para la aplicación.
        """
        if not hasattr(cls, "_instance"):
            cls._instance = cls()
        return cls._instance.logger
    
    def __init__(self):
        """
        Configura el logger (stream + file handler) si aún no tiene handlers.
        """
        self.logger = logging.getLogger("aqua-logger")
        self.formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S"
        )

        if not self.logger.hasHandlers():
            
            if self._ENV == "production":
                handler = MonthlyDailyRotatingFileHandler("./logs", encoding="utf-8")
            else:
                handler = logging.StreamHandler(sys.stdout)

            handler.stream.reconfigure(encoding="utf-8")
            handler.setLevel(logging.DEBUG)
            handler.setFormatter(self.formatter)
            self.logger.setLevel(logging.DEBUG)
            self.logger.propagate = False
            self.logger.addHandler(handler)

logger = Logger.get_logger()
```

## core\module\__init__.py
```python
"""
Module Package - Sistema de Módulos

Este paquete proporciona la funcionalidad para organizar aplicaciones en módulos.
Los módulos agrupan controladores y proveedores relacionados.

Exporta:
    Module: Clase para definir módulos de la aplicación
"""

from .module import Module

__all__ = ["Module"]
```

## core\module\module.py
```python
from typing import List, Type

def Module(*, controllers=None, providers=None, imports=None, exports=None, exception_handlers=None):
    """
    Decorador para definir un módulo en Aqua.
    """
    controllers = controllers or []
    providers = providers or []
    imports = imports or []
    exports = exports or []
    exception_handlers = exception_handlers or []

    def wrapper(cls):
        cls._module_config = {
            "controllers": controllers,
            "providers": providers,
            "imports": imports,
            "exports": exports,
            "exception_handlers": exception_handlers,
        }
        return cls

    return wrapper

```

## core\router\__init__.py
```python
"""
Router Package - Sistema de Enrutamiento

Traduce la sintaxis de rutas tipadas de Aqua a rutas nativas de Starlette.
El matching, compilación de regex y conversión de tipos de path params los
hace Starlette. El body de la request siempre se tipa con un modelo Pydantic.

Exporta:
    translate_path: Traduce "<int:id>" a "{id:int}"
    parse_param_types: Extrae {nombre: tipo Python} de una ruta Aqua
    validate_handler_signature: Valida en boot que la firma del handler sea
        consistente con la ruta, y determina su parámetro de body (si tiene)
    build_endpoint: Adapta un método de controller a un endpoint de Starlette
"""

from .url_params import translate_path, parse_param_types, validate_handler_signature, build_endpoint

__all__ = ["translate_path", "parse_param_types", "validate_handler_signature", "build_endpoint"]

```

## core\router\url_params.py
```python
"""
URL Parameter System

Traduce la sintaxis de parámetros tipados de Aqua a la sintaxis nativa
de Starlette, valida que la firma del handler sea honesta respecto a esa
sintaxis (mismo tipo, no solo de adorno), y adapta los métodos de
controller al contrato `async def endpoint(request) -> Response` que
espera `starlette.routing.Route`.

Ejemplos de traducción de ruta:
    /users/<int:user_id>        -> /users/{user_id:int}
    /posts/<str:slug>           -> /posts/{slug:str}
    /articles/<float:price>     -> /articles/{price:float}
    /users/<user_id>            -> /users/{user_id:str}  (str por defecto)

El matching, la compilación del regex y la conversión de tipos de los path
params ya no viven acá: los hace Starlette una sola vez al registrar la ruta
(`starlette.routing.compile_path`, `starlette.convertors`), no en cada request.

Cada parámetro de un handler que no sea `request` ni un path param se
clasifica por tipo, igual que FastAPI:
- Tipo escalar (str/int/float/bool/UUID, con o sin default) -> query param.
- Subclase de `BaseModel` -> body (como mucho uno).
Ambos casos se validan con Pydantic: los query params vía un modelo armado
al vuelo con `create_model` (coerción laxa: "5" -> 5, "false" -> False, con
422 si no matchea), el body contra el modelo que declaró el handler.

Autor: lyrionlannister
Versión: 4.0.0
"""

import re
import inspect
import typing
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple, Type
from uuid import UUID

from pydantic import BaseModel, ValidationError, create_model
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from core.encoding import jsonable_encoder


_PARAM_PATTERN = re.compile(r'<(?:([^:>]+):)?([^>]+)>')

_TYPE_MAP = {
    "str": str,
    "int": int,
    "float": float,
    "uuid": UUID,
    "path": str,
}

_SCALAR_TYPES = (str, int, float, bool, UUID)


def _unwrap_optional(python_type: Any) -> Any:
    """`Optional[X]` (== `Union[X, None]`) -> `X`. Cualquier otro tipo, igual."""
    if typing.get_origin(python_type) is typing.Union:
        args = [a for a in typing.get_args(python_type) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return python_type


@dataclass
class RouteSignature:
    """Lo que necesita `build_endpoint` para resolver los parámetros de una request."""
    body_param: Optional[Tuple[str, Type[BaseModel]]] = None
    query_model: Optional[Type[BaseModel]] = None


def translate_path(path: str) -> str:
    """
    Convierte la sintaxis `<tipo:nombre>` de Aqua a la sintaxis `{nombre:tipo}`
    de Starlette. Los tipos soportados son los mismos que registra Starlette
    en `starlette.convertors.CONVERTOR_TYPES`: str, int, float, uuid, path.

    Args:
        path: Ruta con sintaxis Aqua, ej "/users/<int:user_id>"

    Returns:
        Ruta con sintaxis Starlette, ej "/users/{user_id:int}"
    """
    def replace(match: re.Match) -> str:
        param_type = match.group(1) or "str"
        param_name = match.group(2)
        return f"{{{param_name}:{param_type}}}"

    return _PARAM_PATTERN.sub(replace, path)


def parse_param_types(path: str) -> dict:
    """
    Extrae, de la sintaxis `<tipo:nombre>` de Aqua, qué tipo Python le
    corresponde a cada nombre de path param (str por defecto).

    Args:
        path: Ruta con sintaxis Aqua, ej "/users/<int:user_id>/posts/<slug>"

    Returns:
        dict nombre -> tipo Python, ej {"user_id": int, "slug": str}
    """
    types = {}
    for match in _PARAM_PATTERN.finditer(path):
        param_type = match.group(1) or "str"
        param_name = match.group(2)
        types[param_name] = _TYPE_MAP[param_type]
    return types


def validate_handler_signature(handler: Callable, path_param_types: dict, allow_raw_request: bool = False) -> RouteSignature:
    """
    Valida en boot que la firma de un handler sea consistente con su ruta,
    y clasifica el resto de sus parámetros en query params y (como mucho un) body.

    Reglas:
    - `request` solo se puede declarar si la ruta se registró con
      `allow_raw_request=True` (ej. `@Post("/", allow_raw_request=True)`).
      Sin ese flag, declarar `request` es una excepción en boot — el camino
      cómodo por default fuerza Pydantic, acceder al request crudo es opt-in.
    - Todo parámetro que coincida con un nombre de `path_param_types` debe
      estar anotado, y con exactamente ese tipo — si no, es una firma
      mentirosa (ej. la ruta dice `<int:id>` pero el handler puso `id: str`).
    - Cualquier otro parámetro se clasifica por tipo: escalar (str/int/float/
      bool/UUID, con o sin `Optional`) -> query param; subclase de `BaseModel`
      -> body (como mucho uno). Cualquier otra cosa es un error en boot.

    Args:
        handler: Método del controller, sin bindear (tal como vive en la clase)
        path_param_types: Lo que devuelve `parse_param_types` para esa ruta
        allow_raw_request: El flag con el que se registró la ruta (`@Get`/`@Post`/etc.)

    Returns:
        RouteSignature con el body_param (si hay) y el query_model (si hay query params)

    Raises:
        Exception: Si algún path param no está anotado o el tipo no coincide,
                  si se declara `request` sin `allow_raw_request=True`,
                  si hay más de un candidato a body, si un parámetro no está
                  anotado, o si su tipo no es ni escalar ni un `BaseModel`.
    """
    sig = inspect.signature(handler)
    params = list(sig.parameters.values())[1:]  # saltar 'self'

    body_candidates = []
    query_fields: dict = {}

    for param in params:
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue

        if param.name == "request":
            if not allow_raw_request:
                raise Exception(
                    f"{handler.__qualname__} declara 'request' pero la ruta no tiene "
                    f"allow_raw_request=True — el body se tipa con Pydantic por default, "
                    f"si de verdad necesitás el request crudo pasá allow_raw_request=True "
                    f"en el decorador (@Get/@Post/etc.)"
                )
            continue

        if param.name in path_param_types:
            expected_type = path_param_types[param.name]
            if param.annotation is inspect.Parameter.empty:
                raise Exception(
                    f"'{param.name}' en {handler.__qualname__} debe estar anotado como "
                    f"{expected_type.__name__} (la ruta lo declara así)"
                )
            if param.annotation is not expected_type:
                raise Exception(
                    f"'{param.name}' en {handler.__qualname__} está anotado como "
                    f"{getattr(param.annotation, '__name__', param.annotation)}, pero la ruta "
                    f"lo declara <{expected_type.__name__}:{param.name}>"
                )
            continue

        annotation = param.annotation
        if annotation is inspect.Parameter.empty:
            raise Exception(
                f"'{param.name}' en {handler.__qualname__} no está anotado — anotalo con un "
                f"tipo escalar (query param: str/int/float/bool/UUID) o un modelo Pydantic (body)"
            )

        resolved = _unwrap_optional(annotation)

        if isinstance(resolved, type) and issubclass(resolved, BaseModel):
            body_candidates.append((param, resolved))
        elif resolved in _SCALAR_TYPES:
            default = ... if param.default is inspect.Parameter.empty else param.default
            query_fields[param.name] = (annotation, default)
        else:
            raise Exception(
                f"'{param.name}' en {handler.__qualname__} debe ser un tipo escalar "
                f"(str/int/float/bool/UUID, query param) o un modelo Pydantic (body) — "
                f"'{annotation}' no es ninguno de los dos"
            )

    if len(body_candidates) > 1:
        names = ", ".join(p.name for p, _ in body_candidates)
        raise Exception(
            f"{handler.__qualname__} tiene más de un parámetro de body ({names}) — "
            f"combínalos en un solo modelo Pydantic"
        )

    body_param = None
    if body_candidates:
        candidate, model = body_candidates[0]
        body_param = (candidate.name, model)

    query_model = create_model(f"{handler.__qualname__}.QueryParams", **query_fields) if query_fields else None

    return RouteSignature(body_param=body_param, query_model=query_model)


def build_endpoint(get_handler: Callable, container=None, route_signature: Optional[RouteSignature] = None) -> Callable:
    """
    Construye un endpoint compatible con `starlette.routing.Route` a partir
    de un método de controller.

    `get_handler(request_cache)` es una función async que devuelve el método
    (bound) a ejecutar. Se llama una vez POR REQUEST, nunca se cachea acá:
    - Para un controller singleton, siempre devuelve el mismo bound method.
    - Para un controller request-scoped, resuelve una instancia nueva del
      controller (usando `request_cache`) en cada llamada
      (ver `Aqua._register_controller_routes`).

    Si `route_signature.body_param`/`.query_model` vienen seteados (los
    calcula `validate_handler_signature` en boot), este endpoint parsea el
    body y/o la query string y los valida con Pydantic antes de llamar al
    handler. Si no cumplen el schema, devuelve 422 con los errores de
    Pydantic sin llegar a ejecutar el handler (igual que FastAPI) — eso NO
    cuenta como excepción de servidor: el `request_cache` se limpia como si
    la request hubiese sido exitosa.

    `request_cache` vive solo durante esta request: si algo request-scoped se
    resolvió en ella (ej. un `AsyncSession`), al terminar (éxito, 422, o
    excepción real) se llama `container.cleanup_request(request_cache, exc)`
    para que cada `Provider` con `on_destroy` pueda hacer su commit/rollback/close.
    La excepción de servidor nunca se traga acá: Starlette la maneja
    (`ExceptionMiddleware`/`ServerErrorMiddleware`) después de que el cleanup corrió.

    Solo pasa `request` al handler si lo declara como parámetro; los path
    params los toma de `request.path_params`, que Starlette ya entrega
    convertidos al tipo correcto (int, float, UUID, etc.).

    Args:
        get_handler: `async def (request_cache: dict) -> Callable`
        container: `Container` de la app, para poder limpiar recursos
                  request-scoped al terminar. Si es None, no se limpia nada.
        route_signature: Resultado de `validate_handler_signature` para esta ruta.

    Returns:
        Función `async def endpoint(request) -> Response` lista para `Route`
    """
    route_signature = route_signature or RouteSignature()
    body_param = route_signature.body_param
    query_model = route_signature.query_model

    async def endpoint(request: Request) -> Response:
        request_cache: dict = {}
        exc: BaseException | None = None
        try:
            handler = await get_handler(request_cache)
            handler_params = set(inspect.signature(handler).parameters.keys())
            accepts_request = "request" in handler_params

            kwargs = {
                name: value
                for name, value in request.path_params.items()
                if name in handler_params
            }

            if query_model is not None:
                try:
                    validated_query = query_model.model_validate(dict(request.query_params))
                except ValidationError as validation_error:
                    errors = jsonable_encoder(validation_error.errors())
                    return JSONResponse(errors, status_code=422)
                for field_name in query_model.model_fields:
                    kwargs[field_name] = getattr(validated_query, field_name)

            if body_param is not None:
                name, model = body_param
                raw_body = await request.json()
                try:
                    kwargs[name] = model.model_validate(raw_body)
                except ValidationError as validation_error:
                    # jsonable_encoder sabe convertir lo que haya adentro de
                    # ctx (incluso una excepción cruda de un @field_validator
                    # con `raise ValueError(...)`) sin perder el resto del
                    # detalle — a diferencia de json.dumps pelado.
                    errors = jsonable_encoder(validation_error.errors())
                    return JSONResponse(errors, status_code=422)

            if accepts_request:
                result = await handler(request, **kwargs)
            else:
                result = await handler(**kwargs)

            if isinstance(result, Response):
                return result
            return JSONResponse(jsonable_encoder(result))
        except BaseException as e:
            exc = e
            raise
        finally:
            if container is not None and request_cache:
                await container.cleanup_request(request_cache, exc)

    return endpoint

```

## tests\__init__.py
```python
```

## tests\config\__init__.py
```python
```

## tests\container\__init__.py
```python
```

## tests\container\test_resolution.py
```python
"""
Comportamiento actual del Container: resolución por type hint, caching de
singletons, @Inject (override manual) y errores en boot por dependencias
no anotadas o no registradas.
"""

import pytest

from core.container.container import Container
from core.di import Inject, Injectable, Scope


@pytest.fixture
def container() -> Container:
    return Container()


async def test_resuelve_clase_sin_dependencias(container: Container):
    @Injectable
    class Leaf:
        pass

    instance = await container.resolve(Leaf)

    assert isinstance(instance, Leaf)


async def test_resuelve_dependencia_por_type_hint(container: Container):
    @Injectable
    class Repo:
        pass

    @Injectable
    class Service:
        def __init__(self, repo: Repo):
            self.repo = repo

    service = await container.resolve(Service)

    assert isinstance(service.repo, Repo)


async def test_singleton_se_cachea_misma_instancia(container: Container):
    @Injectable
    class Shared:
        pass

    first = await container.resolve(Shared)
    second = await container.resolve(Shared)

    assert first is second


async def test_inject_override_tiene_prioridad_sobre_type_hint(container: Container):
    @Injectable
    class EmailService:
        pass

    @Injectable
    class SmsService:
        pass

    @Injectable
    @Inject(notifier=SmsService)
    class Controller:
        def __init__(self, notifier: EmailService):
            self.notifier = notifier

    instance = await container.resolve(Controller)

    assert isinstance(instance.notifier, SmsService)


async def test_clase_no_injectable_lanza_excepcion(container: Container):
    class NotInjectable:
        pass

    with pytest.raises(Exception):
        await container.resolve(NotInjectable)


async def test_dependencia_sin_anotar_lanza_excepcion_en_boot(container: Container):
    @Injectable
    class Broken:
        def __init__(self, sin_anotar):
            self.sin_anotar = sin_anotar

    with pytest.raises(Exception):
        await container.resolve(Broken)


async def test_request_scope_sin_request_cache_lanza_excepcion(container: Container):
    @Injectable(scope=Scope.REQUEST)
    class PerRequest:
        pass

    with pytest.raises(Exception):
        await container.resolve(PerRequest)


async def test_request_scope_se_resuelve_con_request_cache(container: Container):
    @Injectable(scope=Scope.REQUEST)
    class PerRequest:
        pass

    cache: dict = {}
    first = await container.resolve(PerRequest, cache)
    second = await container.resolve(PerRequest, cache)

    assert first is second
    assert PerRequest in cache


async def test_dependiente_de_request_scope_se_propaga_a_request(container: Container):
    @Injectable(scope=Scope.REQUEST)
    class Session:
        pass

    @Injectable
    class ServiceConSession:
        def __init__(self, session: Session):
            self.session = session

    assert container.get_effective_scope(ServiceConSession) == Scope.REQUEST

    with pytest.raises(Exception):
        await container.resolve(ServiceConSession)

    cache: dict = {}
    instance = await container.resolve(ServiceConSession, cache)
    assert isinstance(instance.session, Session)

```

## tests\lifecycle\__init__.py
```python
```

## tests\module\__init__.py
```python
```

## tests\router\__init__.py
```python
```

## pyproject.toml
```
[project]
name = "aqua"
version = "0.1.0"
description = "Framework web Python con inyección de dependencias automática, parámetros URL tipados y organización modular"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.14.0",
    "sqlalchemy[asyncio]>=2.1.4",
    "starlette>=0.48.0",
    "uvicorn[standard]>=0.37.0",
]

[dependency-groups]
dev = [
    "httpx>=0.28.1",
    "pytest>=9.1.1",
    "pytest-asyncio>=1.4.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"


```

## README.md
```
# 🌊 Aqua Framework

Framework web para Python con inyección de dependencias, parámetros URL tipados y organización modular.

## Características Principales

- **Inyección de Dependencias Automática**: Las dependencias se resuelven por tipo
- **Parámetros URL Tipados**: `<int:id>`, `<str:slug>`, `<float:price>`, `<uuid:id>` con conversión automática
- **Organización Modular**: Agrupa controladores y servicios en módulos reutilizables
- **Asíncrono**: Soporte nativo para operaciones async/await
- **Decoradores Simples**: `@Injectable`, `@Controller`, `@Get`, `@Post`, etc.

## Ejemplo Básico

### Crear un Servicio

```python
from core import Injectable

@Injectable
class GreetingService:
    def get_message(self, name: str) -> str:
        return f"¡Hola {name}!"
```

### Crear un Controlador

```python
from core import Controller, Get, Injectable

@Injectable
@Controller("/api")
class WelcomeController:
    def __init__(self, greeting_service: GreetingService):
        self.greeting_service = greeting_service
    
    @Get("/welcome/<str:name>")
    async def welcome(self, name: str):
        message = self.greeting_service.get_message(name)
        return {"message": message}
    
    @Get("/users/<int:user_id>")
    async def get_user(self, user_id: int):
        return {"user_id": user_id, "type": type(user_id).__name__}
```

### Iniciar la Aplicación

```python
from core import Aqua
from core.module import Module

app_module = Module(
    controllers=[WelcomeController],
    providers=[GreetingService]
)

app = Aqua(app_module)

if __name__ == "__main__":
    app.run()
```

**Resultado:**
- `GET /api/welcome/Juan` → `{"message": "¡Hola Juan!"}`
- `GET /api/users/123` → `{"user_id": 123, "type": "int"}`

## Parámetros URL Tipados

Los parámetros de URL se validan y convierten automáticamente según su tipo:

```python
@Get("/productos/<int:product_id>")
async def get_product(self, product_id: int): 
    return {"id": product_id}

@Get("/usuarios/<str:username>")              
async def get_user(self, username: str):
    return {"username": username}

@Get("/precios/<float:price>")                
async def get_price(self, price: float):
    return {"precio": price}

@Get("/configs/<uuid:config_id>")             
async def get_config(self, config_id):
    return {"config": str(config_id)}
```

### Múltiples Parámetros

```python
@Get("/tienda/<int:store_id>/productos/<str:category>/precio/<float:max_price>")
async def search(self, store_id: int, category: str, max_price: float):
    return {
        "tienda": store_id,
        "categoria": category,
        "precio_max": max_price
    }
```

## Ejemplos

### Sistema de Biblioteca

```python
@Injectable
class BookDatabase:
    def __init__(self):
        self.books = [
            {"id": 1, "title": "El Quijote", "author": "Cervantes"},
            {"id": 2, "title": "Cien años de soledad", "author": "García Márquez"}
        ]
    
    def find_by_id(self, book_id: int):
        return next((b for b in self.books if b["id"] == book_id), None)

@Injectable
class BookService:
    def __init__(self, database: BookDatabase):
        self.db = database
    
    async def get_all(self):
        return {"books": self.db.books}
    
    async def get_details(self, book_id: int):
        book = self.db.find_by_id(book_id)
        return {"book": book} if book else {"error": "Not found"}

@Injectable
@Controller("/biblioteca")
class BookController:
    def __init__(self, service: BookService):
        self.service = service
    
    @Get("/libros")
    async def list_all(self):
        return await self.service.get_all()
    
    @Get("/libros/<int:book_id>")
    async def get_one(self, book_id: int):
        return await self.service.get_details(book_id)
```

### E-commerce Básico

```python
@Injectable
class PaymentService:
    async def process(self, amount: float, currency: str = "USD"):
        return {"transaction_id": "TX123", "status": "approved"}

@Injectable
class OrderService:
    def __init__(self, payment: PaymentService):
        self.payment = payment
    
    async def create(self, items: list, customer_email: str):
        total = sum(item["price"] for item in items)
        payment = await self.payment.process(total)
        return {
            "order_id": "ORD456",
            "items": items,
            "total": total,
            "payment": payment
        }

@Injectable
@Controller("/tienda")
class ShopController:
    def __init__(self, orders: OrderService):
        self.orders = orders
    
    @Post("/pedidos")
    async def create_order(self, request):
        data = await request.json()
        return await self.orders.create(
            items=data["items"],
            customer_email=data["customer_email"]
        )
```

## Instalación

```bash
git clone https://github.com/Innoval-Tech-SAS/aqua.git
cd aqua
uv sync
```

```bash
python main.py
```

La aplicación estará disponible en `http://localhost:4200`

## Conceptos Clave

### Decoradores

- `@Injectable` — Clase manejada por el contenedor DI
- `@Controller("/ruta")` — Define un controlador con prefijo de ruta
- `@Get()`, `@Post()` — Métodos que responden a HTTP
- `@Inject()` — Inyección explícita de dependencias (opcional)

### Inyección de Dependencias

```python
# Las dependencias se resuelven por tipo automáticamente
@Injectable
class UserController:
    def __init__(self, user_service: UserService):  # ← Aqua lo inyecta
        self.service = user_service
```

### Módulos

```python
app_module = Module(
    controllers=[UserController, ProductController],
    providers=[UserService, ProductService]
)

app = Aqua(app_module)
```

## Despliegue

```bash
python main.py
```

O con uvicorn:

```bash
pip install uvicorn
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

## Estructura del Proyecto

```
aqua/
├── core/                    # Núcleo del framework
│   ├── application.py       # Clase principal Aqua
│   ├── container/           # Contenedor DI
│   ├── controller/          # Decoradores y lógica de controladores
│   ├── database/            # Módulo de base de datos
│   ├── di/                  # Sistema de inyección de dependencias
│   ├── dto/                 # Data Transfer Objects
│   ├── entity/              # Entidades y columnas
│   ├── encoding/            # Serialización/encoding
│   ├── exceptions/          # Manejo de excepciones
│   ├── logger/              # Logger
│   ├── module/              # Definición de módulos
│   └── router/              # Enrutamiento y parámetros URL
├── main.py                  # Punto de entrada
└── pyproject.toml           # Dependencias del proyecto
```

```

