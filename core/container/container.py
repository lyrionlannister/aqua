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
