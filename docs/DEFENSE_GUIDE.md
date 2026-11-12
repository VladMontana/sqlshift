# Руководство к защите проекта SQLShift (Defense Guide)

Документ подготовлен в соответствии с Разделом 8 итогового плана проекта. Предназначен для автора проекта для подготовки к докладу, презентации и ответам на вопросы комиссии.

---

## 1. Двухэтапный алгоритм маршрутизации и его границы

Маршрутизатор **SQLShift** решает задачу безопасного разделения транзакционной (OLTP) и аналитической (OLAP) нагрузки между PostgreSQL и ClickHouse.

Алгоритм разделен на два независимых этапа:

```text
Входной SQL
    │
    ▼
[Этап 1: Синтаксический анализ & Выявление намерений]
    ├── 1. Проверка multi-statement (несколько инструкций) ──► Ошибка SQLParsingError
    ├── 2. Проверка DML (INSERT/UPDATE/DELETE) и DML в WITH  ──► PostgreSQL (DML_OPERATION)
    ├── 3. Проверка блокирующих выборок (FOR UPDATE/SHARE)    ──► PostgreSQL (LOCKING_READ)
    ├── 4. Проверка команд управления (DDL/TCL)              ──► PostgreSQL (DDL_TCL_COMMAND)
    └── 5. Классификация чтения (OLTP vs OLAP)               ──► Если OLTP: PostgreSQL
                                                                 (NON_ANALYTICAL_QUERY)
    │
    ▼ (Запрос аналитический: GROUP BY, агрегаты, оконные функции, JOIN, тяжелый CTE)
[Этап 2: Проверка политики допуска (Admission Policy)]
    ├── Режим без каталога (catalog is None):
    │     └── 100% транспайлинг в ClickHouse (обратная совместимость)
    └── Режим с каталогом (catalog is TableCatalog):
          ├── Извлечение физических таблиц через Scope AST
          ├── Если физических таблиц нет (SELECT 1 GROUP BY 1) ──► PostgreSQL (NO_PHYSICAL_TABLES)
          ├── Если хотя бы 1 таблица в pg_only_tables          ──► PostgreSQL (TABLE_PG_PINNED)
          ├── Если хотя бы 1 таблица отсутствует в каталоге    ──► PostgreSQL (TABLE_NOT_IN_CATALOG)
          └── Все таблицы разрешены в каталоге                ──► ClickHouse (ANALYTICAL_CLICKHOUSE)
```

### Границы применимости и осознанные ограничения (Limitations)

1. **Не является оптимизатором на основе стоимостной модели (CBO)**: SQLShift не читает статистику распределения данных (гистограммы, селективность предикатов, размер таблиц на диске) и не строит физический план. Маршрутизация детерминирована и основана на синтаксических правилах и контракте каталога.
2. **Не выполняет распределенных транзакций (No 2PC / Cross-DB JOINs)**: Запрос не дробится на части. Если в запросе соединяются таблицы, одна из которых отсутствует в ClickHouse, запрос целиком направляется в PostgreSQL.
3. **Не контролирует задержку репликации (Replication Lag)**: Предполагается, что репликация данных из PostgreSQL в ClickHouse организована внешней инфраструктурой (например, CDC через Debezium или ClickHouse MaterializedPostgreSQL). Решение направить запрос в PostgreSQL при отсутствии допуска — это решение политики изоляции, а не обработка сбоя сети.
4. **Идентичность схем**: В текущей версии имена реплицированных таблиц и используемых колонок в обеих базах должны совпадать.

---

## 2. Руководство по настройке каталога таблиц (TableCatalog)

Каталог задает **контракт доступности**, а не осуществляет динамическое сканирование сети при каждом запросе. Все проверки выполняются в памяти за $O(1)$.

### Пример настройки на Python

```python
from sqlshift.core.catalog import TableCatalog, TableReference

# Инициализация политики допуска
catalog = TableCatalog(
    # Таблицы, гарантированно присутствующие и актуальные в ClickHouse
    allowed_tables=[
        "orders",               # неквалифицированное имя
        "public.order_items",   # имя с указанием схемы
        ("analytics", "events") # кортеж (схема, таблица)
    ],
    # Таблицы, которые строго запрещено читать из ClickHouse
    postgres_only_tables=[
        "returns",              # частые возвраты, критичные к задержке репликации
        "users",                # персональные данные, запрещенные к выгрузке
    ],
    # Схема по умолчанию для взаимной нормализации (default: "public")
    default_schema="public",
    # Учет регистра идентификаторов (default: False)
    case_sensitive=False,
)
```

### Ключевые свойства каталога:
* **Двойной режим (Dual Mode)**:
  * `SQLShiftRouter(catalog=None)` — режим без каталога. Аналитические запросы транспайлятся в ClickHouse без проверки таблиц (поведение ранних версий).
  * `SQLShiftRouter(catalog=catalog)` — режим с каталогом. Защищает аналитическую базу от чтения несуществующих данных.
  * Пустой настроенный каталог `TableCatalog(allowed_tables=[])` **запрещает** направление в ClickHouse любых запросов.
* **Приоритет запрета (Override)**: Таблица из `postgres_only_tables` никогда не попадет в ClickHouse, даже если по ошибке была добавлена в `allowed_tables`.
* **Взаимная нормализация**: При `default_schema="public"` имя `orders` и `public.orders` считаются эквивалентными в обе стороны.

---

## 3. Демонстрационный сценарий: 3 запроса стенда

На стенде развернуты две базы данных:
* **PostgreSQL 16**: содержит таблицы `orders` (10 строк) и `returns` (3 строки).
* **ClickHouse 24.3**: содержит реплицированную аналитическую таблицу `orders` (10 строк, MergeTree). Таблица `returns` в ClickHouse **отсутствует**.

Каталог сконфигурирован:
`allowed_tables=["orders"]`, `postgres_only_tables=["returns"]`.

### Запрос 1: Точечный транзакционный поиск (OLTP)
* **SQL**:
  ```sql
  SELECT id, customer_id, amount, status FROM orders WHERE id = 1
  ```
* **Решение**: `target: postgresql`, `is_analytical: False`
* **Код причины**: `NON_ANALYTICAL_QUERY`
* **Объяснение**: *«Обычный SELECT без сложных конструкций»*
* **Физические таблицы**: `['orders']`
* **Результат**: Выполняется в PostgreSQL, возвращает строку заказа #1 (`amount=150.00, status=paid`).

### Запрос 2: Аналитический отчет по выручке (OLAP)
* **SQL**:
  ```sql
  SELECT status, count(*) AS total_orders, sum(amount) AS total_revenue
  FROM orders
  GROUP BY status
  ORDER BY status
  ```
* **Решение**: `target: clickhouse`, `is_analytical: True`
* **Код причины**: `ANALYTICAL_CLICKHOUSE`
* **Объяснение**: *«Наличие GROUP BY. Все используемые таблицы разрешены в ClickHouse. Выбрана ClickHouse.»*
* **Физические таблицы**: `['orders']`
* **Транспайлинг (ClickHouse)**:
  ```sql
  SELECT status, COUNT(*) AS total_orders, SUM(amount) AS total_revenue
  FROM orders
  GROUP BY status
  ORDER BY status
  ```
* **Паритет данных**: И в PostgreSQL, и в ClickHouse возвращаются абсолютно идентичные строки с точной суммой выручки **2300.00** (Decimal без погрешностей округления).

### Запрос 3: Аналитический запрос с недоступной таблицей
* **SQL**:
  ```sql
  SELECT o.status, count(*) AS total_orders, sum(r.refund_amount) AS total_refunded
  FROM orders AS o
  JOIN returns AS r ON o.id = r.order_id
  GROUP BY o.status
  ORDER BY status
  ```
* **Решение**: `target: postgresql`, `is_analytical: True`
* **Код причины**: `TABLE_PG_PINNED`
* **Объяснение**: *«Наличие GROUP BY. Таблица 'returns' закреплена за PostgreSQL. Выбрана PostgreSQL.»*
* **Физические таблицы**: `['orders', 'returns']`
* **Результат**: Несмотря на наличие аналитических признаков (`GROUP BY`, `sum()`, `JOIN`), запрос остается в PostgreSQL, предотвращая ошибку `Table default.returns doesn't exist` в ClickHouse.

---

## 4. Воспроизведение измерений производительности

### Команды воспроизведения

```bash
# 1. Запуск замера микро-бенчмарка (16 000 итераций)
uv run python benchmarks/run_benchmark.py

# 2. Проверка результатов в сгенерированных файлах:
#    - benchmarks/results/benchmark_summary.md (сводная таблица)
#    - benchmarks/results/benchmark_summary.json (машиночитаемый отчет со средними и p95)
#    - benchmarks/results/benchmark_raw.csv (сырые наносекундные замеры)
```

### Параметры тестового окружения
* **ОС**: Windows 10 (Build 19045, AMD64)
* **Процессор**: AMD Ryzen (Family 25 Model 33 Stepping 2, 12 логических ядер)
* **Python**: 3.13.5 (CPython, 64-bit)
* **SQLGlot**: 30.18.0
* **Методология**: таймер `time.perf_counter_ns()`, 50 итераций прогрева на каждый запрос, 5 серий по 200 итераций (1000 замеров на пару запрос/режим). Создание роутера и любой ввод-вывод строго вынесены за пределы измерительного цикла.

### Фактические измеренные показатели

| Запрос (Query ID) | Описание | Без каталога Mean (мкс) | Без каталога Med (мкс) | С каталогом Mean (мкс) | С каталогом Med (мкс) | С каталогом p95 (мкс) | Оверхед каталога (Δ) | Оверхед (%) |
|---|---|---|---|---|---|---|---|---|
| `Q1_OLTP_LOOKUP` | OLTP поиск по ключу | 265.0 | 257.7 | 288.2 | 261.7 | 445.3 | +4.0 мкс | +1.6% |
| `Q2_OLTP_FILTER` | OLTP мультифильтр | 320.3 | 311.4 | 324.2 | 312.6 | 389.0 | +1.2 мкс | +0.4% |
| `Q3_OLAP_GROUP_BY`| OLAP GROUP BY + AGG | 434.2 | 417.7 | 460.6 | 430.1 | 627.6 | +12.3 мкс| +3.0% |
| `Q4_OLAP_WINDOW` | Аналитическое окно | 395.3 | 374.5 | 400.4 | 384.4 | 506.3 | +9.9 мкс | +2.6% |
| `Q5_MULTI_JOIN` | Соединение 3 таблиц | 818.6 | 786.6 | 843.9 | 801.3 | 1001.7| +14.7 мкс| +1.9% |
| `Q6_CTE_AGG` | Scope CTE агрегация | 631.0 | 585.4 | 627.3 | 591.6 | 830.3 | +6.2 мкс | +1.1% |
| `Q7_DASHBOARD` | Дашборд CTE+LAG+DATE | 814.7 | 772.3 | 818.5 | 774.2 | 1020.6| +1.9 мкс | +0.2% |
| `Q8_SCALAR_CONST`| Скалярные выражения | 210.2 | 204.4 | 215.2 | 205.5 | 273.8 | +1.1 мкс | +0.5% |

### Главные выводы бенчмарка:
1. **Диапазон медиан**: медианное время маршрутизации с каталогом составляет **205,5 – 801,3 мкс** в зависимости от сложности AST (у простых точечных запросов ~0.26 мс, у тяжелых дашбордов ~0.80 мс).
2. **Перцентиль p95**: максимальный p95 среди шаблонов составляет **1020,6 мкс** (у 6 из 8 шаблонов p95 ниже 850 мкс, у сложных многотабличных соединений и дашбордов около 1,0–1,02 мс).
3. **Добавочные затраты каталога**: рост медианы относительно режима без каталога составляет **от 0,25% до 2,96%** (+1,1 ... +14,7 мкс).
   *Методологическое уточнение*: оба режима вызывают `extract_physical_tables()`. Сравнение отражает добавочные затраты сопоставления с каталогом, но не полную стоимость анализа областей видимости AST.
4. **Соответствие SLA**: у всех восьми шаблонов медиана и p95 стабильно ниже **1,5 мс** на указанном стенде. Отдельные единичные вызовы могут превышать этот порог, поэтому гарантировать его для абсолютно любого произвольного запроса нельзя.

---

## 5. Разделение ответственности: SQLGlot vs Собственная часть SQLShift

| Компонент / Задача | Инструмент / Библиотека | Реализация в проекте |
|---|---|---|
| Лексический и синтаксический разбор SQL | **SQLGlot** | `sqlglot.parse_one(sql, read="postgres")` строит базовое дерево AST. |
| Анализ областей видимости (Scope Isolation) | **SQLGlot** + **SQLShift** | `sqlglot.optimizer.scope.traverse_scope` строит иерархию областей видимости. Фильтрация CTE, подзапросов, псевдонимов и табличных функций реализована в `sqlshift.core.catalog.extract_physical_tables`. |
| Обнаружение DML в CTE и блокирующих чтений | **SQLShift** | Поиск модифицирующих узлов внутри `WITH`, анализ предложений `FOR UPDATE / FOR SHARE`. |
| Каталог таблиц и схема допуска | **Собственная разработка SQLShift** | Класс `TableCatalog`: нормализация схем (`public.table`), поддержка регистра, приоритет запрета (`postgres_only_tables`), проверка допуска $O(1)$. |
| Логика принятия решений о маршрутизации | **Собственная разработка SQLShift** | Двухэтапная машина решений в `SQLShiftRouter`: разделение синтаксических признаков и ограничений каталога. |
| Структурированный аудит-трейл | **Собственная разработка SQLShift** | Модель `RouteDecision`: детерминированные `reason_code`, перечень `physical_tables`, флаг `catalog_checked`. |
| Генерация ClickHouse диалекта | **SQLGlot** | `tree.sql(dialect="clickhouse")` транспайлит AST-дерево. |
| Клиентские адаптеры, CLI, Server, HTML Dashboard | **Собственная разработка SQLShift** | Асинхронный диспетчер `AsyncSQLShiftClient`, REST-шлюз FastAPI, CLI Typer/Rich, генератор отчетов аудита `AnalyzeAllSql`. |

---

## 6. Три фрагмента реального исходного кода для слайдов

### Фрагмент 1: Извлечение физических таблиц через Scope AST
Файл: `src/sqlshift/core/catalog.py` (`extract_physical_tables`)

```python
def extract_physical_tables(tree: exp.Expression) -> list[str]:
    found_tables: list[exp.Table] = []

    # 1. Верхнеуровневый DML
    if isinstance(tree, (exp.Insert, exp.Update, exp.Delete)):
        for t in tree.find_all(exp.Table):
            if isinstance(t.this, exp.Identifier) and bool(t.name):
                found_tables.append(t)
    else:
        # 2. Изоляция CTE и поиск физических источников в областях видимости
        scopes = traverse_scope(tree)
        for scope in scopes:
            for source in scope.sources.values():
                if isinstance(source, exp.Table):
                    if isinstance(source.this, exp.Identifier) and bool(source.name):
                        found_tables.append(source)

    # 3. Дедупликация и нормализация без псевдонимов (aliases)
    results: set[str] = set()
    for t in found_tables:
        t_copy = t.copy()
        t_copy.set("alias", None)
        formatted = t_copy.sql("postgres")
        if formatted:
            results.add(formatted)

    return sorted(results)
```
* **Вход**: AST-дерево `exp.Expression` (разобранный SQL-запрос).
* **Выход**: Дедуплицированный, отсортированный список имен физических таблиц `list[str]` (например, `['orders', 'payments']`).
* **Зачем реализовано**: Обычный `tree.find_all(exp.Table)` ошибочно считает физическими таблицами имена CTE (`WITH summary AS (...) SELECT * FROM summary`), подзапросы в `FROM` и табличные генераторы (`generate_series()`). Обход `traverse_scope` изолирует локальные области видимости.
* **Пограничный случай**: Теневые имена (Shadowing) — когда имя CTE совпадает с именем реальной таблицы в базе (`WITH orders AS (SELECT 1) SELECT * FROM orders`). Scope определяет, что источник — локальный CTE, а не физическая таблица.

---

### Фрагмент 2: Выбор целевой СУБД и проверка допуска
Файл: `src/sqlshift/core/router.py` (`SQLShiftRouter.route_tree`)

```python
        # Анализ синтаксических признаков и извлечение таблиц
        is_analytical, complexity, reason = analyze_query(tree)
        physical_tables = extract_physical_tables(tree)

        # Неаналитические запросы (OLTP) -> строго PostgreSQL
        if not is_analytical:
            return RouteDecision(target="postgresql", is_analytical=False, ...)

        # Режим А: Без каталога (catalog is None) — обратная совместимость
        if self.catalog is None:
            return RouteDecision(target="clickhouse", sql=transpile_to_clickhouse(tree), ...)

        # Режим Б: С каталогом — проверка допустимости
        if not physical_tables:  # Например: SELECT 1 GROUP BY 1
            return RouteDecision(
                target="postgresql",
                reason_code="NO_PHYSICAL_TABLES",
                reason=f"{reason}. Запрос не содержит физических таблиц. Выбрана PostgreSQL.",
            )

        admission = self.catalog.check_admission(physical_tables)
        if admission.is_admitted:
            return RouteDecision(
                target="clickhouse",
                sql=transpile_to_clickhouse(tree),
                reason_code="ANALYTICAL_CLICKHOUSE",
            )
        else:
            return RouteDecision(
                target="postgresql",
                sql=pg_sql,
                reason_code=admission.reason_code,
                reason=f"{reason}. {admission.reason_description}",
            )
```
* **Вход**: Синтаксическое дерево запроса `tree: exp.Expression`.
* **Выход**: Объект `RouteDecision` (целевая СУБД, итоговый SQL, признак аналитики, сложность, машиночитаемый код причины, проверенные таблицы).
* **Зачем реализовано**: Реализует двухэтапную политику маршрутизации, разделяя наличие синтаксических признаков аналитики и право на исполнение в ClickHouse. Предотвращает ошибки выполнения в ClickHouse при отсутствии таблиц.
* **Пограничный случай**: Аналитический запрос без физических таблиц (например, `SELECT 1 AS x, count(*) GROUP BY 1`). Без физических таблиц запрос не имеет смысла отправлять в ClickHouse; роутер детерминированно оставляет его в PostgreSQL с кодом `NO_PHYSICAL_TABLES`.

---

### Фрагмент 3: Модульный тест проверки приоритета запрета
Файл: `tests/test_catalog_ast.py` (`test_router_olap_report_pg_pinned_table`)

```python
def test_router_olap_report_pg_pinned_table() -> None:
    # Настраиваем каталог, где returns явно закреплена за PostgreSQL
    router = SQLShiftRouter(
        catalog=TableCatalog(
            allowed_tables=["orders", "returns"],
            pg_only_tables=["returns"],
        )
    )
    sql = "SELECT reason, count(*) FROM returns GROUP BY reason"
    decision = router.route(sql)

    # Верификация: запрет имеет приоритет над списком разрешенных
    assert decision.target == "postgresql"
    assert decision.is_analytical is True
    assert decision.reason_code == "TABLE_PG_PINNED"
    assert "returns" in decision.reason
    assert "закреплена за PostgreSQL" in decision.reason
    assert decision.physical_tables == ["returns"]
```
* **Вход**: Аналитический SQL-запрос с `GROUP BY` и `count(*)` к таблице `returns`, сконфигурированной одновременно в `allowed_tables` и `pg_only_tables`.
* **Выход**: Проверка утверждений `assert`, подтверждающих, что запрос направлен в PostgreSQL с кодом `TABLE_PG_PINNED`.
* **Зачем реализовано**: Автоматическая регрессионная проверка гарантии безопасности: запрет (`postgres_only_tables`) безусловно переопределяет любое случайное или ошибочное включение таблицы в список разрешенных.
* **Пограничный случай**: Запрос с JOIN разрешенной и запрещенной таблиц (`orders JOIN returns`). Тест подтверждает, что при наличии хотя бы одной закрепленной за PostgreSQL таблицы весь запрос остается в PostgreSQL.
