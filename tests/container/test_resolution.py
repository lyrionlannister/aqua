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
