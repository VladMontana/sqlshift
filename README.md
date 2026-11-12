<p align="center">
  <img src="assets/logo.jpg" alt="SQLShift Logo" width="680" style="max-width: 100%; border-radius: 12px;">
</p>
<p align="center">
  <em>Интеллектуальный SQL-маршрутизатор и AST-транспайлер для гибридных систем PostgreSQL & ClickHouse</em>
</p>
<p align="center">
  <a href="https://github.com/VladMontana/sqlshift"><img src="https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-blue?logo=python&logoColor=white" alt="Python Version"></a>
  <a href="https://github.com/VladMontana/sqlshift"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License"></a>
  <a href="https://github.com/VladMontana/sqlshift"><img src="https://img.shields.io/badge/Type_Checked-mypy-blueviolet?logo=python" alt="MyPy"></a>
  <a href="https://github.com/VladMontana/sqlshift"><img src="https://img.shields.io/badge/Linted-ruff-orange?logo=ruff" alt="Ruff"></a>
  <a href="https://github.com/VladMontana/sqlshift"><img src="https://img.shields.io/badge/Tests-188%20passed-brightgreen" alt="Tests"></a>
</p>

---

**SQLShift** — это современная, высокопроизводительная библиотека и HTTP-шлюз на Python для автоматической маршрутизации и транспайлинга SQL-запросов между транзакционными базами данных (**PostgreSQL**) и аналитическими колоночными хранилищами (**ClickHouse**).

Библиотека анализирует синтаксическое дерево (AST) каждого SQL-запроса в оперативной памяти, извлекает физические таблицы с учетом областей видимости (Scope), проверяет политику допуска по каталогу таблиц, мгновенно определяет характер нагрузки (OLTP vs OLAP), оценивает сложность и при необходимости транспайлит диалект PostgreSQL в нативный диалект ClickHouse.

---

## ⚡ Ключевые возможности

* 🏎️ **Zero-Overhead Routing**: Анализ AST через `sqlglot` в оперативной памяти со средней задержкой **< 0.3–0.8 мс** (пропускная способность **> 1 200–4 000 запросов/сек** на ядро).
* 📋 **Каталог таблиц и политика допуска (TableCatalog)**:
  * **Двойной режим (Dual Mode)**: режим без каталога (`catalog=None`) сохраняет чистую синтаксическую эвристику (100% обратная совместимость); режим с каталогом (`catalog=TableCatalog(...)`) проверяет реальную доступность таблиц в ClickHouse.
  * **Строгая защита**: пустой настроенный каталог запрещает направление в ClickHouse; таблицы, закрепленные за PostgreSQL (`postgres_only_tables`), имеют безусловный приоритет запрета.
  * **Умная нормализация**: автоматическое разрешение квалифицированных (`public.orders`) и неквалифицированных (`orders`) имен, поддержка схем и регистра.
* 🔍 **AST Scope Extraction**:
  * Изоляция физических таблиц через механизм областей видимости SQLGlot (`traverse_scope`).
  * Полное исключение CTE (`WITH ...`), табличных псевдонимов (aliases), производных подзапросов в `FROM` и генераторов (`generate_series`).
  * Безопасное обнаружение модифицирующих CTE (`WITH del AS (DELETE ...)`) и блокировок (`FOR UPDATE`).
* 🎯 **Двухэтапная маршрутизация и структурированные объяснения**:
  * Четкое разделение этапа классификации (DML, DDL/TCL, OLTP vs OLAP) и этапа допуска в ClickHouse.
  * Полноценный аудит-трейл: машиночитаемый `reason_code` (`ANALYTICAL_CLICKHOUSE`, `TABLE_NOT_IN_CATALOG`, `TABLE_PG_PINNED`, `DML_OPERATION`, `NON_ANALYTICAL_QUERY`, `NO_PHYSICAL_TABLES`), список извлеченных `physical_tables` и признак `catalog_checked`.
* 🔄 **Автоматический транспайлинг**: Преобразование конструкций PostgreSQL (функции дат `date_trunc`, типы данных, диалектные особенности) в нативный диалект ClickHouse.
* 📊 **Интерактивный HTML-дашборд аудита**: Генерация автономного отчета с карточками метрик, поиском, фильтрами и side-by-side инспектором запросов.
* 🔌 **Library-First архитектура**: Ядро библиотеки работает автономно и без базы данных. Драйверы (`asyncpg`, `clickhouse-connect`) и сервер (`fastapi`) подключаются опционально через `extras`.
* 🛠️ **CLI и HTTP Gateway**: Консольная утилита с поддержкой опций каталога (`--allowed-tables`, `--pg-only-tables`) и готовый Sidecar API сервер для полиглотных систем.

---

## 🏛️ Архитектура системы

```text
                           ┌──────────────────────────┐
                           │   Клиентское приложение   │
                           │  (Python, Go, Node.js)   │
                           └────────────┬─────────────┘
                                        │  SQL (PostgreSQL dialect)
                                        ▼
                       ┌───────────────────────────────────┐
                       │             SQLShift              │
                       │ ┌───────────────────────────────┐ │
                       │ │  AST Analyzer & Scope (sqlglot│ │  0.25 - 0.8 ms
                       │ │  - Извлечение физ. таблиц     │ │
                       │ │  - Исключение CTE & aliases   │ │
                       │ └───────────────┬───────────────┘ │
                       │                 ▼                 │
                       │ ┌───────────────────────────────┐ │
                       │ │  TableCatalog Admission Check │ │  O(1) in-memory
                       │ │  - Режим без каталога (None)  │ │
                       │ │  - Режим с каталогом (Policy) │ │
                       │ └───────────────┬───────────────┘ │
                       │                 ▼                 │
                       │ ┌───────────────────────────────┐ │
                       │ │  PG -> CH Transpiler          │ │
                       │ └───────────────────────────────┘ │
                       └────────────┬─────────────────┬────┘
                                    │                 │
                 Транзакционный     │                 │   Аналитический
                 (исходный SQL)     │                 │   (транспайленный SQL)
                                    ▼                 ▼
                         ┌──────────────────┐ ┌──────────────────┐
                         │    PostgreSQL    │ │    ClickHouse    │
                         │      (OLTP)      │ │      (OLAP)      │
                         └──────────────────┘ └──────────────────┘
```

---

## 📦 Установка

```bash
# 1. Минимальный SDK (только in-memory роутер и транспайлер)
pip install sqlshift

# 2. С поддержкой прямого исполнения запросов в БД (asyncpg + clickhouse-connect)
pip install "sqlshift[client]"

# 3. С поддержкой запуска REST HTTP Gateway (FastAPI + Uvicorn)
pip install "sqlshift[server]"

# 4. Полная установка со всеми компонентами
pip install "sqlshift[all]"
```

---

## 🚀 Быстрый старт

### 1. Маршрутизация с каталогом таблиц (In-Memory)

```python
from sqlshift import SQLRouter, TableCatalog

# Настраиваем каталог: orders доступна в ClickHouse, returns только в PostgreSQL
catalog = TableCatalog(
    allowed_tables=["orders", "public.events"],
    postgres_only_tables=["returns"],
    default_schema="public",
)

router = SQLRouter(catalog=catalog)

# 1. Запрос к orders -> Направляется в ClickHouse с транспайлингом
res1 = router.route(
    "SELECT date_trunc('month', created_at), count(*) FROM orders GROUP BY 1"
)
print(res1.target)  # 'clickhouse'
print(res1.reason_code)  # 'ANALYTICAL_CLICKHOUSE'
print(res1.physical_tables)  # ['orders']
print(res1.sql)  # 'SELECT dateTrunc('month', created_at), COUNT(*) ...'

# 2. Аналитический запрос, использующий returns -> Оставляется в PostgreSQL
res2 = router.route(
    "SELECT r.reason, count(*) FROM returns r GROUP BY 1"
)
print(res2.target)  # 'postgresql'
print(res2.reason_code)  # 'TABLE_PG_PINNED'
print(res2.reason)  # "Таблица 'returns' закреплена за PostgreSQL. Выбрана PostgreSQL."

# 3. Транзакционная операция (DML) -> Всегда в PostgreSQL
res3 = router.route("UPDATE orders SET status = 'shipped' WHERE id = 42")
print(res3.target)  # 'postgresql'
print(res3.reason_code)  # 'DML_OPERATION'
```

---

### 2. Режим без каталога (Обратная совместимость)

Если каталог не передан (`catalog=None`), маршрутизатор работает в режиме эвристического анализа, транспайля любые аналитические конструкции:

```python
legacy_router = SQLRouter()  # catalog=None по умолчанию
decision = legacy_router.route("SELECT count(*) FROM custom_table")
print(decision.target)  # 'clickhouse'
print(decision.catalog_checked)  # False
```

---

### 3. Автоматическое исполнение через `AsyncSQLShiftClient`

```python
import asyncio
from sqlshift import TableCatalog
from sqlshift.client import AsyncSQLShiftClient


async def main():
    catalog = TableCatalog(allowed_tables=["orders"])
    async with AsyncSQLShiftClient(
        pg_dsn="postgresql://user:pass@localhost:5432/mydb",
        ch_dsn="clickhouse://localhost:8123/default",
        catalog=catalog,
    ) as client:
        # Точечный SELECT идет в PostgreSQL:
        user = await client.fetch("SELECT * FROM orders WHERE id = 42")

        # Агрегация идет в ClickHouse:
        stats = await client.fetch(
            "SELECT status, sum(amount) FROM orders GROUP BY status"
        )


asyncio.run(main())
```

---

## ⚙️ Настройка каталога таблиц (TableCatalog)

Класс `TableCatalog` (или псевдоним `TableAdmissionPolicy`) предоставляет гибкую декларативную настройку:

```python
from sqlshift.core.catalog import TableCatalog, TableReference

catalog = TableCatalog(
    # Список таблиц, реплицированных и доступных для аналитики в ClickHouse
    allowed_tables=[
        "orders",               # неквалифицированное имя
        "public.order_items",   # имя с указанием схемы
        ("analytics", "events") # кортеж (schema, table)
    ],
    # Таблицы, которые строго запрещено направлять в ClickHouse
    postgres_only_tables=["returns", "users", "sensitive_audit"],
    # Схема по умолчанию для автоматической взаимной нормализации (default: "public")
    default_schema="public",
    # Учет регистра идентификаторов (default: False)
    case_sensitive=False,
)
```

**Правила работы каталога**:
1. **Приоритет запрета**: Если таблица указана в `postgres_only_tables`, она **никогда** не попадет в ClickHouse, даже если присутствует в `allowed_tables` (`reason_code: TABLE_PG_PINNED`).
2. **Двусторонняя нормализация схемы**: При `default_schema="public"` запись `orders` эквивалентна `public.orders`. Запрос к `public.orders` будет разрешен, если указано `orders`, и наоборот.
3. **Пустой каталог**: `TableCatalog(allowed_tables=[])` явно запрещает допуск всех таблиц в ClickHouse (`reason_code: TABLE_NOT_IN_CATALOG`), сохраняя все аналитические запросы в PostgreSQL.

---

## 🛠️ Команды стенда, тестов и бенчмарка

### 1. Запуск и верификация Docker Compose стенда

Проект включает готовый демонстрационный стенд с **PostgreSQL 16** и **ClickHouse 24.3** (таблицы `orders` и `returns` с детерминированными данными):

```bash
# Запуск контейнеров и выполнение верификации 3 сценариев с проверкой числового паритета:
docker compose up -d && uv run python stand/verify_stand.py
```

### 2. Автономное тестирование стенда (без запуска Docker)

Проверка DDL, контрактов данных, целостности сумм и решений маршрутизатора в памяти:

```bash
uv run pytest tests/test_stand_contracts.py -v
```

### 3. Полный набор тестов проекта

```bash
# Запуск 188 тестов:
uv run pytest

# Статическая типизация (35 файлов):
uv run mypy src tests stand benchmarks

# Проверка линтером Ruff:
uv run ruff check .
```

### 4. Запуск воспроизводимого бенчмарка

Скрипт проводит микро-бенчмаркинг по 16 000 измерений на `perf_counter_ns` с прогревом:

```bash
uv run python benchmarks/run_benchmark.py
```

---

## 📊 Результаты бенчмарка производительности

Измерения проведены на **16 000 итерациях** (8 типов запросов × 2 режима × 1 000 замеров) с изоляцией ввода-вывода и наносекундным разрешением таймера:

* **Окружение**: AMD64 (12 logical cores), Windows 10, Python 3.13.5 (CPython), SQLGlot 30.18.0.

| Query ID | Описание запроса | Без каталога (p50, мкс) | С каталогом (p50, мкс) | Накладные расходы (Δ) | Оверхед (%) | С каталогом (p95, мкс) |
|---|---|---|---|---|---|---|
| `Q1_OLTP_LOOKUP` | OLTP поиск по первичному ключу | 257.7 | 261.7 | +4.0 мкс | +1.6% | 445.3 мкс |
| `Q2_OLTP_FILTER` | OLTP фильтрация нескольких полей | 311.4 | 312.6 | +1.2 мкс | +0.4% | 389.0 мкс |
| `Q3_OLAP_GROUP_BY` | OLAP группировка GROUP BY + AGG | 417.7 | 430.1 | +12.3 мкс | +3.0% | 627.6 мкс |
| `Q4_OLAP_WINDOW` | Аналитическая оконная функция | 374.5 | 384.4 | +9.9 мкс | +2.6% | 506.3 мкс |
| `Q5_MULTI_JOIN` | Соединение 3 таблиц (Multi-JOIN) | 786.6 | 801.3 | +14.7 мкс | +1.9% | 1001.7 мкс |
| `Q6_CTE_AGG` | Изоляция Scope CTE + агрегация | 585.4 | 591.6 | +6.2 мкс | +1.1% | 830.3 мкс |
| `Q7_DASHBOARD_COMPLEX` | Сложный дашборд (CTE + LAG + date_trunc) | 772.3 | 774.2 | +1.9 мкс | +0.2% | 1020.6 мкс |
| `Q8_SCALAR_NO_TABLES` | Скалярные выражения без таблиц | 204.4 | 205.5 | +1.1 мкс | +0.5% | 273.8 мкс |

**Выводы**:
1. Дополнительные накладные расходы на анализ областей видимости AST и проверку допуска по каталогу составляют всего **от +1.1 до +14.7 мкс** (+0.2% – +3.0%).
2. Все запросы выполняют полный цикл синтаксического анализа и проверки каталога быстрее **1.0 мс** на 95-м перцентиле (p95), с медианой от **0.20 до 0.80 мс**, что с запасом укладывается в норматив SLA < 1.5 мс.

---

## 💻 Консольный интерфейс (CLI)

Консольная утилита `sqlshift` поддерживает указание таблиц каталога:

```bash
# Маршрутизация с проверкой каталога
sqlshift route "SELECT status, count(*) FROM orders GROUP BY status" --allowed-tables orders,order_items

# Маршрутизация с фиксацией таблицы за PostgreSQL
sqlshift route "SELECT reason, count(*) FROM returns GROUP BY reason" --allowed-tables orders --pg-only-tables returns

# Пакетный аудит и генерация HTML-отчета
sqlshift audit queries.sql --allowed-tables orders --output report.html --open

# Запуск Sidecar HTTP шлюза
sqlshift serve --host 0.0.0.0 --port 8000
```

---

## 🧠 Логика маршрутизации и коды причин

| Категория | Синтаксические признаки | Допуск каталога | Целевая СУБД | Код причины (`reason_code`) |
|---|---|---|---|---|
| **DML / Модификация** | `INSERT`, `UPDATE`, `DELETE`, модифицирующие CTE | Не требуется | **PostgreSQL** 🐘 | `DML_OPERATION` |
| **DDL / TCL** | `CREATE`, `DROP`, `ALTER`, `BEGIN`, `COMMIT` | Не требуется | **PostgreSQL** 🐘 | `DDL_TCL_COMMAND` |
| **Точечное чтение** | Чтение по ключу (`WHERE id = ?`), `LIMIT 1` | Не требуется | **PostgreSQL** 🐘 | `NON_ANALYTICAL_QUERY` |
| **Аналитика без таблиц** | `SELECT 1 GROUP BY 1` | Нет физ. таблиц | **PostgreSQL** 🐘 | `NO_PHYSICAL_TABLES` |
| **Аналитика (разрешено)** | `GROUP BY`, `SUM/AVG`, Window, Heavy JOIN | Все таблицы в `allowed` | **ClickHouse** 📦 | `ANALYTICAL_CLICKHOUSE` |
| **Аналитика (нет в каталоге)**| `GROUP BY`, Window, JOIN | Таблица не в `allowed` | **PostgreSQL** 🐘 | `TABLE_NOT_IN_CATALOG` |
| **Аналитика (запрещено)** | `GROUP BY`, Window, JOIN | Таблица в `pg_only` | **PostgreSQL** 🐘 | `TABLE_PG_PINNED` |

---

## 📄 Лицензия

Проект распространяется под открытой лицензией [MIT](LICENSE).
