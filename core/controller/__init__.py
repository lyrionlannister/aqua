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