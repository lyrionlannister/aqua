"""
Motor y sesión de SQLAlchemy async para Aqua.

Define el engine, el `Base` declarativo y la clase `DeclarativeBase` que
usan los modelos. La URL se toma de `DataSourceOptions.url`, de los campos
separados (`DataSourceOptions.engine`/..) o de la variable de entorno
`DATABASE_URL` — sin ningún default implícito: un framework no debe asumir
qué base de datos querés usar.

Autor: lyrionlannister
Versión: 1.0.0
"""

import os

from sqlalchemy import MetaData
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from core.database.options import DataSourceOptions

# Sin esto, cada motor de DB nombra los constraints a su manera y las
# migraciones no pueden referenciarlos de forma estable.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _build_url(options: DataSourceOptions) -> str:
    """
    Arma la connection string a partir de los campos separados de
    `DataSourceOptions`, usando `sqlalchemy.engine.URL.create` — nunca
    f-string a mano, porque un password con `@`/`:`/`/` rompe una URL armada
    a mano y `URL.create` lo escapa correcto.

    Prioridad: `options.url` (si se dio, se usa tal cual) > campos separados
    (si se dio `engine`) > env var `DATABASE_URL`. Sin ninguno de los tres,
    error explícito — no hay fallback a una base de datos local.
    """
    if options.url:
        return options.url

    if options.engine is None:
        url = os.getenv("DATABASE_URL")
        if not url:
            raise ValueError(
                "No se configuró la base de datos: pasá `DataSourceOptions(url=...)` "
                "o `engine=...`, o definí la variable de entorno `DATABASE_URL`."
            )
        return url

    drivername = f"{options.engine}+{options.driver}" if options.driver else options.engine
    return URL.create(
        drivername=drivername,
        username=options.username,
        password=options.password,
        host=options.host,
        port=options.port,
        database=options.database,
    )


def build_engine(options: DataSourceOptions) -> AsyncEngine:
    """
    Construye el engine a partir de `DataSourceOptions`. Pensado para
    registrarse como `Provider(token=AsyncEngine, ...)` singleton — un solo
    engine (y su pool de conexiones) para toda la vida de la app.
    """
    url = _build_url(options)

    kwargs: dict = {"echo": options.echo}
    if options.pool_size is not None:
        kwargs["pool_size"] = options.pool_size
    if options.max_overflow is not None:
        kwargs["max_overflow"] = options.max_overflow

    return create_async_engine(url, **kwargs)
