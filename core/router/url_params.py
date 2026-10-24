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
