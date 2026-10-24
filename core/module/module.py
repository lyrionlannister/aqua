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
