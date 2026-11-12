# SQLShift Docker Compose Stand (R6)

Гибридный демонстрационный стенд с двумя базами данных: **PostgreSQL 16** (OLTP) и **ClickHouse 24.3** (OLAP).

## Схема данных и сценарий магазина

- **`orders`**: присутствует в обеих СУБД. Содержит 10 детерминированных записей с точной суммой заказов `2300.00`.
- **`returns`**: присутствует **только в PostgreSQL**. Содержит 3 детерминированные записи с точной суммой возвратов `720.00`.

Каталог маршрутизации SQLShift настраивается следующим образом:
- Разрешенные таблицы в ClickHouse: `orders` (и `public.orders`).
- Таблицы, закрепленные за PostgreSQL (или отсутствующие в каталоге ClickHouse): `returns`.

## Быстрый старт

### 1. Запуск контейнеров

```bash
docker compose up -d
```

Контейнеры снабжены автоматическими проверками готовности (`healthcheck`):
- PostgreSQL: `pg_isready -U postgres -d postgres` (порт 5432)
- ClickHouse: HTTP ping на `http://127.0.0.1:8123/ping` (порты 8123, 9000)

### 2. Верификация стенда и проверка сценариев маршрутизации

Скрипт автоматически дожидается готовности контейнеров, выполняет 3 сценария маршрутизации и сверяет результаты:

```bash
uv run python stand/verify_stand.py
```

#### Демонстрируемые сценарии:
1. **Сценарий 1 (OLTP-чтение по ключу)**:
   ```sql
   SELECT id, customer_id, amount, status FROM orders WHERE id = 1
   ```
   *Маршрутизируется в PostgreSQL (простой транзакционный SELECT).*

2. **Сценарий 2 (Аналитический GROUP BY по orders)**:
   ```sql
   SELECT status, count(*) AS total_orders, sum(amount) AS total_revenue
   FROM orders
   GROUP BY status
   ORDER BY status
   ```
   *Маршрутизируется в ClickHouse. Скрипт выполняет исходный SQL в PostgreSQL и транслированный SQL в ClickHouse, сравнивает построчно и валидирует численную эквивалентность!*

3. **Сценарий 3 (Аналитический запрос с таблицей returns)**:
   ```sql
   SELECT o.status, count(*) AS total_orders, sum(r.refund_amount) AS total_refunded
   FROM orders AS o
   JOIN returns AS r ON o.id = r.order_id
   GROUP BY o.status
   ORDER BY o.status
   ```
   *Остается в PostgreSQL, поскольку таблица `returns` отсутствует в каталоге ClickHouse.*

### 3. Автономные тесты без Docker (CI/Offline)

Контракты DDL, сидов и сценариев маршрутизации полностью покрыты автономными unit-тестами, которые запускаются без Docker:

```bash
uv run pytest tests/test_stand_contracts.py -v
```

### 4. Остановка стенда

```bash
docker compose down -v
```
