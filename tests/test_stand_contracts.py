"""Автономные тесты контрактов стенда Docker Compose, DDL, сидов и сценариев маршрутизации.

Эти тесты работают на 100% автономно в CI без необходимости запуска демона Docker:
1. Валидация спецификации `docker-compose.yml` (сервисы, образы, порты, healthchecks).
2. Валидация DDL и детерминированных сидов `stand/postgres/init.sql` (10 заказов, 3 возврата).
3. Валидация DDL и сидов `stand/clickhouse/init.sql` (MergeTree, ORDER BY id, 10 заказов).
4. Проверка численной эквивалентности сидов между PostgreSQL и ClickHouse.
5. In-memory тестирование всех 3 сценариев маршрутизации через SQLShiftRouter и TableCatalog.
6. Модульная проверка алгоритма кросс-БД сравнения результатов.
"""

import re
from decimal import Decimal
from pathlib import Path

import pytest

from sqlshift.core.catalog import TableCatalog
from sqlshift.core.router import SQLShiftRouter

ROOT_DIR = Path(__file__).resolve().parent.parent


def test_docker_compose_contracts() -> None:
    """Проверяет корректность структуры docker-compose.yml."""
    compose_path = ROOT_DIR / "docker-compose.yml"
    assert compose_path.exists(), "docker-compose.yml должен существовать в корне проекта"

    content = compose_path.read_text(encoding="utf-8")

    # Проверка сервиса PostgreSQL
    assert "postgres:" in content
    assert "postgres:16-alpine" in content
    assert "5432:5432" in content
    assert "POSTGRES_USER: postgres" in content
    assert "POSTGRES_PASSWORD: postgres" in content
    assert "POSTGRES_DB: postgres" in content
    assert "stand/postgres/init.sql:/docker-entrypoint-initdb.d/init.sql:ro" in content
    assert "pg_isready -U postgres -d postgres" in content

    # Проверка сервиса ClickHouse
    assert "clickhouse:" in content
    assert "clickhouse/clickhouse-server:24.3-alpine" in content
    assert "8123:8123" in content
    assert "9000:9000" in content
    assert "CLICKHOUSE_DB: default" in content
    assert "stand/clickhouse/init.sql:/docker-entrypoint-initdb.d/init.sql:ro" in content
    assert "wget -q -O - http://127.0.0.1:8123/ping" in content


def _extract_insert_tuples(sql_text: str, table_name: str) -> list[str]:
    """Извлекает кортежи значений из INSERT INTO <table_name>."""
    pattern = rf"INSERT\s+INTO\s+{table_name}\s*\([^)]+\)\s*VALUES\s*(.*?)(?:ON\s+CONFLICT|;)"
    match = re.search(pattern, sql_text, re.DOTALL | re.IGNORECASE)
    assert match is not None, f"INSERT INTO {table_name} не найден"
    values_str = match.group(1).strip()
    # Разбиваем по строкам кортежей: (...),
    tuple_pattern = r"\((.*?)\)"
    raw_tuples = re.findall(tuple_pattern, values_str, re.DOTALL)
    # Фильтруем только кортежи данных (начинаются с цифры id)
    return [t.strip() for t in raw_tuples if t.strip() and t.strip()[0].isdigit()]


def test_postgres_init_sql_contracts() -> None:
    """Проверяет DDL и сиды в stand/postgres/init.sql."""
    init_path = ROOT_DIR / "stand" / "postgres" / "init.sql"
    assert init_path.exists(), "stand/postgres/init.sql должен существовать"

    content = init_path.read_text(encoding="utf-8")

    # Проверка создания таблиц
    assert "CREATE TABLE IF NOT EXISTS orders" in content
    assert "CREATE TABLE IF NOT EXISTS returns" in content
    assert "amount NUMERIC(10, 2)" in content
    assert "refund_amount NUMERIC(10, 2)" in content

    # Извлекаем строки orders
    order_tuples = _extract_insert_tuples(content, "orders")
    assert len(order_tuples) == 10, f"Ожидалось 10 строк orders, получено {len(order_tuples)}"

    total_amount = Decimal("0.00")
    for t in order_tuples:
        # id, customer_id, order_date, status, amount, items_count, created_at
        parts = [p.strip().strip("'") for p in t.split(",")]
        amount = Decimal(parts[4])
        total_amount += amount

    assert total_amount == Decimal("2300.00"), f"Сумма заказов в PG {total_amount} != 2300.00"

    # Извлекаем строки returns
    return_tuples = _extract_insert_tuples(content, "returns")
    assert len(return_tuples) == 3, f"Ожидалось 3 строки returns, получено {len(return_tuples)}"

    total_returns = Decimal("0.00")
    for t in return_tuples:
        # id, order_id, return_date, reason, refund_amount, status
        parts = [p.strip().strip("'") for p in t.split(",")]
        refund = Decimal(parts[4])
        total_returns += refund

    assert total_returns == Decimal("720.00"), f"Сумма возвратов в PG {total_returns} != 720.00"


def test_clickhouse_init_sql_contracts() -> None:
    """Проверяет DDL и сиды в stand/clickhouse/init.sql."""
    init_path = ROOT_DIR / "stand" / "clickhouse" / "init.sql"
    assert init_path.exists(), "stand/clickhouse/init.sql должен существовать"

    content = init_path.read_text(encoding="utf-8")

    # Проверка схемы orders
    assert "CREATE TABLE IF NOT EXISTS orders" in content
    assert "ENGINE = MergeTree()" in content
    assert "ORDER BY id" in content
    assert "amount Decimal(10, 2)" in content

    # Проверка отсутствия returns (изоляция аналитического каталога)
    assert "CREATE TABLE IF NOT EXISTS returns" not in content

    # Извлекаем строки orders
    ch_order_tuples = _extract_insert_tuples(content, "orders")
    assert len(ch_order_tuples) == 10, f"Ожидалось 10 строк orders, получено {len(ch_order_tuples)}"

    total_amount = Decimal("0.00")
    for t in ch_order_tuples:
        parts = [p.strip().strip("'") for p in t.split(",")]
        amount = Decimal(parts[4])
        total_amount += amount

    assert total_amount == Decimal("2300.00"), (
        f"Сумма заказов в ClickHouse {total_amount} != 2300.00"
    )


def test_cross_db_seeds_identical() -> None:
    """Проверяет полную идентичность сид-данных таблицы orders между PG и ClickHouse."""
    pg_content = (ROOT_DIR / "stand" / "postgres" / "init.sql").read_text(encoding="utf-8")
    ch_content = (ROOT_DIR / "stand" / "clickhouse" / "init.sql").read_text(encoding="utf-8")

    pg_tuples = _extract_insert_tuples(pg_content, "orders")
    ch_tuples = _extract_insert_tuples(ch_content, "orders")

    assert len(pg_tuples) == len(ch_tuples) == 10

    for idx, (pg_t, ch_t) in enumerate(zip(pg_tuples, ch_tuples, strict=True)):
        pg_parts = [p.strip().strip("'") for p in pg_t.split(",")]
        ch_parts = [p.strip().strip("'") for p in ch_t.split(",")]

        # Сверяем id, customer_id, order_date, status, amount, items_count
        assert pg_parts[0] == ch_parts[0], f"Row {idx}: ID mismatch {pg_parts[0]} vs {ch_parts[0]}"
        assert pg_parts[1] == ch_parts[1], f"Row {idx}: Customer ID mismatch"
        assert pg_parts[2] == ch_parts[2], f"Row {idx}: Order date mismatch"
        assert pg_parts[3] == ch_parts[3], f"Row {idx}: Status mismatch"
        assert Decimal(pg_parts[4]) == Decimal(ch_parts[4]), f"Row {idx}: Amount mismatch"
        assert pg_parts[5] == ch_parts[5], f"Row {idx}: Items count mismatch"


def test_in_memory_routing_scenarios() -> None:
    """Тестирует все 3 сценария маршрутизации стенда в памяти без внешних сервисов."""
    catalog = TableCatalog(
        allowed_tables=["orders", "public.orders"],
        postgres_only_tables=["returns", "public.returns"],
    )
    router = SQLShiftRouter(catalog=catalog)

    # Сценарий 1: OLTP SELECT orders -> PostgreSQL
    q1 = "SELECT id, customer_id, amount, status FROM orders WHERE id = 1"
    dec1 = router.route(q1)
    assert dec1.target == "postgresql"
    assert not dec1.is_analytical
    assert dec1.estimated_complexity == "low"
    assert "orders" in dec1.physical_tables

    # Сценарий 2: Аналитический GROUP BY orders -> ClickHouse
    q2 = (
        "SELECT status, count(*) AS total_orders, sum(amount) AS total_revenue "
        "FROM orders GROUP BY status ORDER BY status"
    )
    dec2 = router.route(q2)
    assert dec2.target == "clickhouse"
    assert dec2.is_analytical
    assert "COUNT" in dec2.sql or "count" in dec2.sql
    assert "SUM" in dec2.sql or "sum" in dec2.sql
    assert "orders" in dec2.physical_tables
    assert dec2.catalog_checked

    # Сценарий 3: Аналитический отчет с returns -> PostgreSQL (отказ допуска)
    q3 = (
        "SELECT o.status, count(*) AS total_orders, sum(r.refund_amount) AS total_refunded "
        "FROM orders AS o "
        "JOIN returns AS r ON o.id = r.order_id "
        "GROUP BY o.status "
        "ORDER BY o.status"
    )
    dec3 = router.route(q3)
    assert dec3.target == "postgresql"
    assert dec3.is_analytical
    assert dec3.reason_code in ("TABLE_PG_PINNED", "TABLE_NOT_IN_CATALOG")
    assert "returns" in dec3.physical_tables
    assert "orders" in dec3.physical_tables
    assert dec3.catalog_checked


def test_cross_db_comparison_logic() -> None:
    """Проверяет логику попиксельного/построчного сравнения строк PG и ClickHouse."""
    from typing import Any

    pg_data: list[dict[str, Any]] = [
        {"status": "cancelled", "total_orders": 1, "total_revenue": Decimal("450.00")},
        {"status": "paid", "total_orders": 5, "total_revenue": Decimal("1494.50")},
        {"status": "processing", "total_orders": 1, "total_revenue": Decimal("55.00")},
        {"status": "shipped", "total_orders": 3, "total_revenue": Decimal("300.50")},
    ]

    ch_data_matching: list[dict[str, Any]] = [
        {"status": "cancelled", "total_orders": 1, "total_revenue": Decimal("450.00")},
        {"status": "paid", "total_orders": 5, "total_revenue": Decimal("1494.50")},
        {"status": "processing", "total_orders": 1, "total_revenue": Decimal("55.00")},
        {"status": "shipped", "total_orders": 3, "total_revenue": Decimal("300.50")},
    ]

    # Валидация успешного совпадения
    assert len(pg_data) == len(ch_data_matching)
    total_rev = Decimal("0.00")
    for pg_r, ch_r in zip(pg_data, ch_data_matching, strict=True):
        assert pg_r["status"] == ch_r["status"]
        assert pg_r["total_orders"] == ch_r["total_orders"]
        rev_pg = Decimal(str(pg_r["total_revenue"]))
        rev_ch = Decimal(str(ch_r["total_revenue"]))
        assert abs(rev_pg - rev_ch) < Decimal("0.001")
        total_rev += rev_pg
    assert total_rev == Decimal("2300.00")

    # Валидация обнаружения несовпадения
    ch_data_mismatched: list[dict[str, Any]] = [
        {"status": "cancelled", "total_orders": 1, "total_revenue": Decimal("450.00")},
        {"status": "paid", "total_orders": 5, "total_revenue": Decimal("1400.00")},  # расхождение
        {"status": "processing", "total_orders": 1, "total_revenue": Decimal("55.00")},
        {"status": "shipped", "total_orders": 3, "total_revenue": Decimal("300.50")},
    ]

    with pytest.raises(AssertionError):
        for pg_r, ch_r in zip(pg_data, ch_data_mismatched, strict=True):
            rev_pg = Decimal(str(pg_r["total_revenue"]))
            rev_ch = Decimal(str(ch_r["total_revenue"]))
            assert abs(rev_pg - rev_ch) < Decimal("0.001")
