# 🌊 Aqua Framework

Framework web para Python con inyección de dependencias, parámetros URL tipados y organización modular.

## Características Principales

- **Inyección de Dependencias Automática**: Las dependencias se resuelven por tipo
- **Parámetros URL Tipados**: `<int:id>`, `<str:slug>`, `<float:price>`, `<uuid:id>` con conversión automática
- **Organización Modular**: Agrupa controladores y servicios en módulos reutilizables
- **Asíncrono**: Soporte nativo para operaciones async/await
- **Decoradores Simples**: `@Injectable`, `@Controller`, `@Get`, `@Post`, etc.

## Ejemplo Básico

### Crear un Servicio

```python
from core import Injectable

@Injectable
class GreetingService:
    def get_message(self, name: str) -> str:
        return f"¡Hola {name}!"
```

### Crear un Controlador

```python
from core import Controller, Get, Injectable

@Injectable
@Controller("/api")
class WelcomeController:
    def __init__(self, greeting_service: GreetingService):
        self.greeting_service = greeting_service
    
    @Get("/welcome/<str:name>")
    async def welcome(self, name: str):
        message = self.greeting_service.get_message(name)
        return {"message": message}
    
    @Get("/users/<int:user_id>")
    async def get_user(self, user_id: int):
        return {"user_id": user_id, "type": type(user_id).__name__}
```

### Iniciar la Aplicación

```python
from core import Aqua
from core.module import Module

app_module = Module(
    controllers=[WelcomeController],
    providers=[GreetingService]
)

app = Aqua(app_module)

if __name__ == "__main__":
    app.run()
```

**Resultado:**
- `GET /api/welcome/Juan` → `{"message": "¡Hola Juan!"}`
- `GET /api/users/123` → `{"user_id": 123, "type": "int"}`

## Parámetros URL Tipados

Los parámetros de URL se validan y convierten automáticamente según su tipo:

```python
@Get("/productos/<int:product_id>")
async def get_product(self, product_id: int): 
    return {"id": product_id}

@Get("/usuarios/<str:username>")              
async def get_user(self, username: str):
    return {"username": username}

@Get("/precios/<float:price>")                
async def get_price(self, price: float):
    return {"precio": price}

@Get("/configs/<uuid:config_id>")             
async def get_config(self, config_id):
    return {"config": str(config_id)}
```

### Múltiples Parámetros

```python
@Get("/tienda/<int:store_id>/productos/<str:category>/precio/<float:max_price>")
async def search(self, store_id: int, category: str, max_price: float):
    return {
        "tienda": store_id,
        "categoria": category,
        "precio_max": max_price
    }
```

## Ejemplos

### Sistema de Biblioteca

```python
@Injectable
class BookDatabase:
    def __init__(self):
        self.books = [
            {"id": 1, "title": "El Quijote", "author": "Cervantes"},
            {"id": 2, "title": "Cien años de soledad", "author": "García Márquez"}
        ]
    
    def find_by_id(self, book_id: int):
        return next((b for b in self.books if b["id"] == book_id), None)

@Injectable
class BookService:
    def __init__(self, database: BookDatabase):
        self.db = database
    
    async def get_all(self):
        return {"books": self.db.books}
    
    async def get_details(self, book_id: int):
        book = self.db.find_by_id(book_id)
        return {"book": book} if book else {"error": "Not found"}

@Injectable
@Controller("/biblioteca")
class BookController:
    def __init__(self, service: BookService):
        self.service = service
    
    @Get("/libros")
    async def list_all(self):
        return await self.service.get_all()
    
    @Get("/libros/<int:book_id>")
    async def get_one(self, book_id: int):
        return await self.service.get_details(book_id)
```

### E-commerce Básico

```python
@Injectable
class PaymentService:
    async def process(self, amount: float, currency: str = "USD"):
        return {"transaction_id": "TX123", "status": "approved"}

@Injectable
class OrderService:
    def __init__(self, payment: PaymentService):
        self.payment = payment
    
    async def create(self, items: list, customer_email: str):
        total = sum(item["price"] for item in items)
        payment = await self.payment.process(total)
        return {
            "order_id": "ORD456",
            "items": items,
            "total": total,
            "payment": payment
        }

@Injectable
@Controller("/tienda")
class ShopController:
    def __init__(self, orders: OrderService):
        self.orders = orders
    
    @Post("/pedidos")
    async def create_order(self, request):
        data = await request.json()
        return await self.orders.create(
            items=data["items"],
            customer_email=data["customer_email"]
        )
```

## Instalación

```bash
git clone https://github.com/Innoval-Tech-SAS/aqua.git
cd aqua
uv sync
```

```bash
python main.py
```

La aplicación estará disponible en `http://localhost:4200`

## Conceptos Clave

### Decoradores

- `@Injectable` — Clase manejada por el contenedor DI
- `@Controller("/ruta")` — Define un controlador con prefijo de ruta
- `@Get()`, `@Post()` — Métodos que responden a HTTP
- `@Inject()` — Inyección explícita de dependencias (opcional)

### Inyección de Dependencias

```python
# Las dependencias se resuelven por tipo automáticamente
@Injectable
class UserController:
    def __init__(self, user_service: UserService):  # ← Aqua lo inyecta
        self.service = user_service
```

### Módulos

```python
app_module = Module(
    controllers=[UserController, ProductController],
    providers=[UserService, ProductService]
)

app = Aqua(app_module)
```

## Despliegue

```bash
python main.py
```

O con uvicorn:

```bash
pip install uvicorn
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

## Estructura del Proyecto

```
aqua/
├── core/                    # Núcleo del framework
│   ├── application.py       # Clase principal Aqua
│   ├── container/           # Contenedor DI
│   ├── controller/          # Decoradores y lógica de controladores
│   ├── database/            # Módulo de base de datos
│   ├── di/                  # Sistema de inyección de dependencias
│   ├── dto/                 # Data Transfer Objects
│   ├── entity/              # Entidades y columnas
│   ├── encoding/            # Serialización/encoding
│   ├── exceptions/          # Manejo de excepciones
│   ├── logger/              # Logger
│   ├── module/              # Definición de módulos
│   └── router/              # Enrutamiento y parámetros URL
├── main.py                  # Punto de entrada
└── pyproject.toml           # Dependencias del proyecto
```
