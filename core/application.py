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
