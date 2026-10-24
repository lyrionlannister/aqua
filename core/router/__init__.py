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
