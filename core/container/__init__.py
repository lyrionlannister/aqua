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