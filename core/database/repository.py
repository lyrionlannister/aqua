"""Repository genérico con las operaciones CRUD comunes a todos los modelos."""

from datetime import datetime, timezone
from typing import Generic, List, Optional, Sequence, Type, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.database import Base

T = TypeVar("T", bound=Base)


class Repository(Generic[T]):
    """
    Repository genérico: recibe un `AsyncSession` (request-scoped, inyectado
    automáticamente por el Container) y opera sobre `model_class`.

    Si `model_class` tiene una columna `DeleteDateColumn()` (ver
    `core/entity/columns.py`), `get_by_id`/`get_all` excluyen automáticamente
    los registros con esa columna seteada. `delete()` siempre hace un DELETE
    real; para marcar la columna sin borrar la fila usá `soft_delete()`.

    Example:
        ```python
        @Injectable
        class UserRepository(Repository[User]):
            model_class = User
        ```
    """
    model_class: Type[T]

    def __init__(self, session: AsyncSession):
        self.session = session

    @property
    def _soft_delete_column(self) -> Optional[str]:
        return getattr(self.model_class, "__soft_delete_column__", None)

    async def add(self, instance: T) -> T:
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def add_many(self, instances: List[T]) -> Sequence[T]:
        self.session.add_all(instances)
        await self.session.flush()
        for instance in instances:
            await self.session.refresh(instance)
        return instances

    async def get_by_id(self, id: object) -> Optional[T]:
        instance = await self.session.get(self.model_class, id)
        soft_col = self._soft_delete_column
        if instance is not None and soft_col is not None and getattr(instance, soft_col) is not None:
            return None
        return instance

    async def get_all(self) -> Sequence[T]:
        stmt = select(self.model_class)
        soft_col = self._soft_delete_column
        if soft_col is not None:
            stmt = stmt.where(getattr(self.model_class, soft_col).is_(None))
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update(self, instance: T) -> T:
        merged = await self.session.merge(instance)
        await self.session.flush()
        await self.session.refresh(merged)
        return merged

    async def delete(self, instance: T) -> None:
        """DELETE real — borra la fila, haya o no columna de soft-delete."""
        attached = await self.session.merge(instance)
        await self.session.delete(attached)
        await self.session.flush()

    async def soft_delete(self, instance: T) -> T:
        """Setea la columna de soft-delete sin borrar la fila. Solo válido si `model_class` tiene `DeleteDateColumn()`."""
        soft_col = self._soft_delete_column
        if soft_col is None:
            raise Exception(f"{self.model_class.__name__} no tiene DeleteDateColumn(), usá delete()")
        attached = await self.session.merge(instance)
        setattr(attached, soft_col, datetime.now(timezone.utc))
        await self.session.flush()
        await self.session.refresh(attached)
        return attached

    async def restore(self, instance: T) -> T:
        """Deshace un soft_delete(). Solo válido si `model_class` tiene `DeleteDateColumn()`."""
        soft_col = self._soft_delete_column
        if soft_col is None:
            raise Exception(f"{self.model_class.__name__} no tiene DeleteDateColumn(), no hay nada que restaurar")
        attached = await self.session.merge(instance)
        setattr(attached, soft_col, None)
        await self.session.flush()
        await self.session.refresh(attached)
        return attached

    async def get_deleted(self) -> Sequence[T]:
        """Los registros soft-deleted (la papelera). Solo válido con `DeleteDateColumn()`."""
        soft_col = self._soft_delete_column
        if soft_col is None:
            raise Exception(f"{self.model_class.__name__} no tiene DeleteDateColumn()")
        stmt = select(self.model_class).where(getattr(self.model_class, soft_col).is_not(None))
        result = await self.session.execute(stmt)
        return result.scalars().all()
