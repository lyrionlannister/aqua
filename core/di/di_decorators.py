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