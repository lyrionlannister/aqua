"""
InjectRepository: repository genérico para una entidad, sin escribir una
subclase de `Repository` a mano cuando solo necesitás el CRUD básico.

Usarlo directamente como type hint alcanza para que el Container lo resuelva
— no hace falta ningún mecanismo nuevo, `InjectRepository(User)` devuelve una
clase real ya decorada con `@Injectable`:

```python
@Injectable
class UserService:
    def __init__(self, repo: InjectRepository(User)):
        self.repo = repo
```

Autor: lyrionlannister
Versión: 1.0.0
"""

from typing import Type, TypeVar

from core.database.repository import Repository
from core.di import Injectable

T = TypeVar("T")

_cache: dict = {}


def InjectRepository(model_class: Type[T]) -> Type[Repository]:
    """
    Devuelve (memoizado) un `Repository` ya ligado a `model_class`, listo
    para usar como type hint en cualquier constructor `@Injectable`.

    Llamarlo dos veces con la misma entidad devuelve la MISMA clase — así el
    Container lo cachea como un solo singleton (o un solo request-scoped si
    la entidad usa `AsyncSession`), no uno distinto por cada punto de inyección.

    Args:
        model_class: La clase `@Entity` sobre la que opera el repository.

    Returns:
        type: Subclase de `Repository` con `model_class` ya seteado.
    """
    if model_class not in _cache:
        _cache[model_class] = Injectable(
            type(f"{model_class.__name__}Repository", (Repository,), {"model_class": model_class})
        )
    return _cache[model_class]
