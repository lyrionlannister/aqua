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
