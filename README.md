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
  <a href="https://github.com/VladMontana/sqlshift"><img src="https://img.shields.io/badge/Tests-43%20passed-brightgreen" alt="Tests"></a>
</p>

---

**SQLShift** — это современная, высокопроизводительная библиотека и HTTP-шлюз на Python для автоматической маршрутизации и транспайлинга SQL-запросов между транзакционными базами данных (**PostgreSQL**) и аналитическими колоночными хранилищами (**ClickHouse**).

Библиотека анализирует синтаксическое дерево (AST) каждого SQL-запроса в оперативной памяти, мгновенно определяет характер нагрузки (OLTP vs OLAP), оценивает сложность и при необходимости на лету транспайлит диалект PostgreSQL в синтаксис ClickHouse.

---

## ⚡ Ключевые преимущества

* 🏎️ **Zero-Overhead Routing**: Анализ AST через `sqlglot` в оперативной памяти со средней задержкой **< 0.25 мс** (пропускная способность **> 3 500 запросов/сек** на ядро).
* 🎯 **Умное разделение нагрузки**:
  * **OLTP (PostgreSQL)**: точечные выборки по первичным ключам, простые фильтры и любые DML-операции (`INSERT`, `UPDATE`, `DELETE`).
  * **OLAP (ClickHouse)**: агрегации (`COUNT`, `SUM`, `AVG`), группировки (`GROUP BY`), оконные функции, CTE-цепочки и многотабличные соединения (`JOIN`).
* 🔄 **Автоматический транспайлинг**: Преобразование конструкций PostgreSQL (функции дат `date_trunc`, типы данных, диалектные особенности) в нативный диалект ClickHouse.
* 📊 **Интерактивный HTML-дашборд аудита**: Генерация автономного, красивого dark-theme отчета с карточками метрик, поиском, фильтрами и side-by-side инспектором запросов.
* 🔌 **Library-First архитектура**: Ядро библиотеки работает автономно и без базы данных. Драйверы (`asyncpg`, `clickhouse-connect`) и сервер (`fastapi`) подключаются опционально через `extras`.
* 🛠️ **Богатый CLI**: Встроенные команды для отладки маршрутизации, проведения стресс-тестов производительности и генерации отчетов в терминале.
* 🌐 **Полиглотность (HTTP Gateway)**: Готовый Sidecar API сервер для прозрачной интеграции с сервисами на **Go**, **Java**, **Node.js** или **Rust**.

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
                      │ │  AST Analyzer (sqlglot)       │ │  < 0.3 ms
                      │ │  - OLTP / OLAP эвристики      │ │
                      │ │  - Оценка сложности (L/M/H)   │ │
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

Выберите вариант установки в зависимости от ваших задач:

```bash
# 1. Минимальный SDK (только in-memory роутер и транспайлер, без лишних зависимостей)
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

### 1. In-Memory маршрутизация в Python (Без подключения к БД)

Для использования парсера и транспайлера не требуются базы данных или запущенные сервисы:

```python
from sqlshift import SQLRouter

router = SQLRouter()

# Аналитический запрос с группировкой и усечением даты
query = "SELECT date_trunc('month', created_at), count(*) FROM events GROUP BY 1"

decision = router.route(query)

print(f"Целевая БД:   {decision.target}")               # 'clickhouse'
print(f"Аналитика:    {decision.is_analytical}")        # True
print(f"Сложность:    {decision.estimated_complexity}") # 'high'
print(f"Причина:      {decision.reason}")               # 'Обнаружены агрегатные функции...'
print(f"Итоговый SQL: {decision.sql}")                  # 'SELECT dateTrunc('month', created_at), COUNT(*) ...'
```

---

### 2. Пакетный аудит и генерация HTML-дашборда

Если у вас есть файл со списком SQL-запросов (например, из логов продакшена), `sqlshift` проведет глубокий аудит и сформирует интерактивный dark-theme отчет:

```python
from sqlshift import AnalyzeAllSql

# Загружаем пачку запросов из .sql файла
analyzer = AnalyzeAllSql.from_file("examples/queries.sql")

# Получаем сводную статистику
summary = analyzer.analyze()
print(f"Всего запросов: {summary.total_queries}")
print(f"PostgreSQL: {summary.postgres_count} | ClickHouse: {summary.clickhouse_count}")
print(f"Обнаруженные узкие места: {summary.bottleneck_detected}")

# Экспортируем автономный интерактивный HTML-дашборд
analyzer.to_html(output_path="audit_report.html", title="Аудит рабочей нагрузки")
```

> **Что внутри HTML-отчета:**
> - Карточки распределения нагрузки и сложности запросов.
> - Список архитектурных узких мест (*Heavy JOINs*, *CTE chains*, *Window functions*).
> - Живой поиск и фильтрация таблицы запросов.
> - **Side-by-side инспектор**: сравнение исходного запроса PostgreSQL и сгенерированного ClickHouse SQL с кнопками копирования.

---

### 3. Автоматическое исполнение через `AsyncSQLShiftClient`

При установленном `sqlshift[client]` библиотека берет на себя подключение к обеим базам и диспетчеризацию:

```python
import asyncio
from sqlshift.client import AsyncSQLShiftClient

async def main():
    async with AsyncSQLShiftClient(
        pg_dsn="postgresql://user:pass@localhost:5432/mydb",
        ch_dsn="clickhouse://localhost:8123/default",
    ) as client:
        # Запрос автоматически отправится в нужную БД:
        # 1. Точечный SELECT пойдет в PostgreSQL:
        user = await client.fetch("SELECT * FROM users WHERE id = 42")

        # 2. Тяжелая аналитика транспайлится и исполнится в ClickHouse:
        stats = await client.fetch(
            "SELECT date_trunc('day', paid_at), sum(amount) FROM payments GROUP BY 1"
        )

asyncio.run(main())
```

---

## 💻 Консольный интерфейс (CLI)

`sqlshift` поставляется с удобной консольной утилитой на базе `Typer` и `Rich`:

### Анализ единичного запроса
```bash
sqlshift route "SELECT date_trunc('month', paid_at), sum(amount) FROM payments GROUP BY 1"
```

### Пакетный аудит и экспорт HTML с открытием в браузере
```bash
sqlshift audit queries.sql --output report.html --open
```

### Стресс-тест скорости маршрутизации
```bash
sqlshift benchmark -n 5000
```
```text
  ✓ Benchmark completed successfully
  • Total queries: 25,000
  • Total time:    6.852 s
  • Latency:       0.274 ms / query (274.1 µs)
  • Throughput:    3,648 queries/sec (RPS)
```

### Запуск HTTP Gateway сервера
```bash
sqlshift serve --host 0.0.0.0 --port 8000
```

---

## 🌐 Интеграция с Go и другими языками (Sidecar Pattern)

Сервер `sqlshift serve` предоставляет легковесный REST API. Запустив его рядом с вашим микросервисом (в Kubernetes Pod или Docker Compose), вы можете вызывать роутинг из любого языка программирования:

```go
// Пример отправки запроса на маршрутизацию из Go:
resp, err := http.Post(
    "http://127.0.0.1:8000/v1/route",
    "application/json",
    strings.NewReader(`{"sql": "SELECT date_trunc('month', ts), count(*) FROM events GROUP BY 1"}`),
)
// Ответ:
// {
//   "target": "clickhouse",
//   "sql": "SELECT dateTrunc('month', ts), count(*) FROM events GROUP BY 1",
//   "is_analytical": true,
//   "estimated_complexity": "high"
// }
```

Интерактивная документация Swagger UI доступна по адресу: `http://127.0.0.1:8000/docs`.

---

## 🧠 Логика маршрутизации (Эвристики)

| Тип операции | Признаки AST-дерева | Целевая СУБД | Пример |
|---|---|---|---|
| **DML операции** | `INSERT`, `UPDATE`, `DELETE`, `MERGE` | **PostgreSQL** 🐘 | `INSERT INTO logs VALUES (...)` |
| **Точечное чтение** | Чтение по ключу (`WHERE id = ?`), `LIMIT 1` без агрегатов | **PostgreSQL** 🐘 | `SELECT email FROM users WHERE id = 1` |
| **Агрегации** | `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`, `ARRAY_AGG` | **ClickHouse** 📦 | `SELECT count(*) FROM page_views` |
| **Группировки** | `GROUP BY`, `HAVING`, `CUBE`, `ROLLUP` | **ClickHouse** 📦 | `SELECT status, count(*) GROUP BY 1` |
| **Оконные функции** | `OVER (PARTITION BY ... ORDER BY ...)` | **ClickHouse** 📦 | `SELECT ROW_NUMBER() OVER (...)` |
| **Сложные выборки** | 2 и более `JOIN`, цепочки `WITH ... AS` (CTE) | **ClickHouse** 📦 | `WITH t AS (...) SELECT * FROM t JOIN ...` |

---

## 🛠️ Разработка и тестирование

Проект использует современный менеджер пакетов [uv](https://github.com/astral-sh/uv):

```bash
# Клонирование и установка зависимостей
git clone https://github.com/VladMontana/sqlshift.git
cd sqlshift
uv sync --all-extras

# Запуск полного набора модульных тестов
uv run pytest

# Проверка линтером и форматированием
uv run ruff check .

# Проверка строгой статической типизации
uv run mypy src
```

---

## 📄 Лицензия

Проект распространяется под открытой лицензией [MIT](LICENSE).
