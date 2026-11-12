#!/usr/bin/env python3
"""Скрипт верификации гибридного стенда PostgreSQL + ClickHouse (Milestone 3 / R6).

Выполняет:
1. Проверку готовности обоих контейнеров (PostgreSQL 16 и ClickHouse 24.3).
2. Сценарий 1: Простой OLTP-запрос к `orders` (маршрутизируется в PostgreSQL).
3. Сценарий 2: Аналитический GROUP BY к `orders` (маршрутизируется в ClickHouse).
   Выполняет исходный SQL в PostgreSQL и транслированный SQL в ClickHouse,
   построчно сравнивает результаты и подтверждает численную эквивалентность!
4. Сценарий 3: Аналитический запрос с таблицей `returns` (остается в PostgreSQL,
   так как `returns` отсутствует в каталоге ClickHouse).
"""

import asyncio
import sys
import time
from decimal import Decimal
from typing import Any

import asyncpg
import clickhouse_connect

from sqlshift.core.catalog import TableCatalog
from sqlshift.core.router import SQLShiftRouter

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        reconfig = getattr(stream, "reconfigure", None)
        if callable(reconfig):
            try:
                reconfig(encoding="utf-8", errors="replace")
            except Exception:
                pass

PG_DSN = "postgresql://postgres:postgres@localhost:5432/postgres"
CH_HOST = "localhost"
CH_PORT = 8123
CH_USER = "default"
CH_PASSWORD = ""
CH_DATABASE = "default"


async def wait_for_postgres(timeout: int = 40) -> asyncpg.Connection:
    """Ожидает доступности PostgreSQL."""
    start = time.time()
    last_err: Exception | None = None
    while time.time() - start < timeout:
        try:
            conn = await asyncpg.connect(PG_DSN)
            # Проверим наличие таблиц orders и returns
            check_sql = (
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_name IN ('orders', 'returns')"
            )
            val = await conn.fetchval(check_sql)
            if val == 2:
                return conn
            await conn.close()
        except Exception as e:
            last_err = e
        await asyncio.sleep(1.0)
    raise TimeoutError(f"PostgreSQL не ответил за {timeout}с. Последняя ошибка: {last_err}")


async def wait_for_clickhouse(timeout: int = 40) -> Any:
    """Ожидает доступности ClickHouse."""
    start = time.time()
    last_err: Exception | None = None
    while time.time() - start < timeout:
        try:
            client = clickhouse_connect.get_client(
                host=CH_HOST,
                port=CH_PORT,
                username=CH_USER,
                password=CH_PASSWORD,
                database=CH_DATABASE,
            )
            check_sql = (
                "SELECT count() FROM system.tables WHERE name = 'orders' AND database = 'default'"
            )
            res = client.command(check_sql)
            if int(str(res)) >= 1:
                return client
            client.close()
        except Exception as e:
            last_err = e
        await asyncio.sleep(1.0)
    raise TimeoutError(f"ClickHouse не ответил за {timeout}с. Последняя ошибка: {last_err}")


def format_row(row: dict[str, Any]) -> str:
    parts = []
    for k, v in row.items():
        if isinstance(v, Decimal):
            parts.append(f"{k}={v:.2f}")
        else:
            parts.append(f"{k}={v}")
    return ", ".join(parts)


async def main() -> int:
    print("=" * 70)
    print(" SQLShift Stand Verification (PostgreSQL 16 & ClickHouse 24.3)")
    print("=" * 70)

    # 1. Ожидание готовности контейнеров
    print("\n[1/4] Проверка готовности баз данных...")
    try:
        pg_conn = await wait_for_postgres()
        print("  [OK] PostgreSQL готов (порт 5432, таблицы 'orders' и 'returns' созданы)")
    except Exception as e:
        print(f"  [FAIL] Ошибка подключения к PostgreSQL: {e}")
        return 1

    try:
        ch_client = await wait_for_clickhouse()
        print("  [OK] ClickHouse готов (порт 8123, таблица 'orders' создана)")
    except Exception as e:
        print(f"  [FAIL] Ошибка подключения к ClickHouse: {e}")
        await pg_conn.close()
        return 1

    # 2. Инициализация каталога и роутера
    catalog = TableCatalog(
        allowed_tables=["orders", "public.orders"],
        postgres_only_tables=["returns", "public.returns"],
    )
    router = SQLShiftRouter(catalog=catalog)

    try:
        # Сценарий 1: Простой OLTP-запрос к orders
        print("\n[2/4] Сценарий 1: OLTP SELECT по первичному ключу")
        query_s1 = "SELECT id, customer_id, amount, status FROM orders WHERE id = 1"
        print(f"  SQL: {query_s1}")
        dec_s1 = router.route(query_s1)
        print(f"  Решение: target={dec_s1.target}, analytical={dec_s1.is_analytical}")
        print(f"  Причина: {dec_s1.reason}")
        assert dec_s1.target == "postgresql", f"Ожидался postgresql, получено {dec_s1.target}"
        assert not dec_s1.is_analytical, "Запрос не должен быть классифицирован как аналитический"

        pg_row_s1 = await pg_conn.fetchrow(dec_s1.sql)
        assert pg_row_s1 is not None, "Заказ с id=1 не найден!"
        row_dict_s1 = dict(pg_row_s1)
        print(f"  Результат из PostgreSQL: {format_row(row_dict_s1)}")
        assert row_dict_s1["id"] == 1
        assert Decimal(str(row_dict_s1["amount"])) == Decimal("150.00")
        print("  [OK] Сценарий 1 успешно пройден!")

        # Сценарий 2: Аналитический GROUP BY к orders (Кросс-БД верификация)
        print("\n[3/4] Сценарий 2: Аналитический отчет GROUP BY по orders")
        query_s2 = (
            "SELECT status, count(*) AS total_orders, sum(amount) AS total_revenue "
            "FROM orders GROUP BY status ORDER BY status"
        )
        print(f"  Исходный SQL: {query_s2}")
        dec_s2 = router.route(query_s2)
        print(f"  Решение: target={dec_s2.target}, analytical={dec_s2.is_analytical}")
        print(f"  Причина: {dec_s2.reason}")
        print(f"  Транслированный SQL (ClickHouse): {dec_s2.sql}")
        assert dec_s2.target == "clickhouse", f"Ожидался clickhouse, получено {dec_s2.target}"
        assert dec_s2.is_analytical, "Запрос должен быть аналитическим"

        # Исполняем исходный запрос в PostgreSQL
        pg_records_s2 = await pg_conn.fetch(query_s2)
        pg_rows_s2 = [dict(r) for r in pg_records_s2]

        # Исполняем транслированный запрос в ClickHouse
        ch_res_s2 = ch_client.query(dec_s2.sql)
        ch_cols = [c.lower() for c in ch_res_s2.column_names]
        ch_rows_s2 = [dict(zip(ch_cols, r, strict=False)) for r in ch_res_s2.result_rows]

        print("\n  Сравнение результатов выполнения:")
        header_str = (
            f"  {'Status':<14} | {'Postgres Orders':<16} | "
            f"{'ClickHouse Orders':<18} | {'Revenue (PG)':<14} | {'Revenue (CH)':<14}"
        )
        print(header_str)
        print("  " + "-" * 85)

        assert len(pg_rows_s2) == len(ch_rows_s2), (
            f"Несовпадение числа строк: PG={len(pg_rows_s2)}, CH={len(ch_rows_s2)}"
        )

        total_pg_revenue = Decimal("0.00")
        total_ch_revenue = Decimal("0.00")

        for pg_r, ch_r in zip(pg_rows_s2, ch_rows_s2, strict=True):
            status = str(pg_r["status"])
            assert status == str(ch_r["status"]), (
                f"Статусы не совпадают: {status} vs {ch_r['status']}"
            )

            pg_orders = int(pg_r["total_orders"])
            ch_orders = int(ch_r["total_orders"])
            assert pg_orders == ch_orders, (
                f"Число заказов не совпадает для {status}: {pg_orders} vs {ch_orders}"
            )

            pg_rev = Decimal(str(pg_r["total_revenue"]))
            ch_rev = Decimal(str(ch_r["total_revenue"]))
            total_pg_revenue += pg_rev
            total_ch_revenue += ch_rev
            assert abs(pg_rev - ch_rev) < Decimal("0.001"), (
                f"Выручка не совпадает для {status}: PG={pg_rev} vs CH={ch_rev}"
            )

            row_line = (
                f"  {status:<14} | {pg_orders:<16} | {ch_orders:<18} | "
                f"{pg_rev:<14.2f} | {ch_rev:<14.2f}"
            )
            print(row_line)

        assert total_pg_revenue == Decimal("2300.00"), f"Сумма PG={total_pg_revenue} != 2300.00"
        assert total_ch_revenue == Decimal("2300.00"), f"Сумма CH={total_ch_revenue} != 2300.00"
        print("  " + "-" * 85)
        print(f"  ИТОГО: 10 заказов, точная сумма выручки: {total_pg_revenue:.2f}")
        print("  [OK] Сценарий 2: Построчная и численная эквивалентность доказана на 100%!")

        # Сценарий 3: Аналитический запрос с таблицей returns (отказ допуска)
        print("\n[4/4] Сценарий 3: Аналитический запрос с таблицей returns")
        query_s3 = (
            "SELECT o.status, count(*) AS total_orders, sum(r.refund_amount) AS total_refunded "
            "FROM orders AS o "
            "JOIN returns AS r ON o.id = r.order_id "
            "GROUP BY o.status "
            "ORDER BY o.status"
        )
        print(f"  SQL: {query_s3}")
        dec_s3 = router.route(query_s3)
        print(f"  Решение: target={dec_s3.target}, analytical={dec_s3.is_analytical}")
        print(f"  Причина: {dec_s3.reason}")
        print(f"  Код причины: {dec_s3.reason_code}")
        print(f"  Физические таблицы: {dec_s3.physical_tables}")

        assert dec_s3.target == "postgresql", f"Ожидался postgresql, получено {dec_s3.target}"
        assert dec_s3.is_analytical, (
            "Запрос аналитический, но должен остаться в PostgreSQL из-за каталога"
        )
        assert dec_s3.reason_code in ("TABLE_PG_PINNED", "TABLE_NOT_IN_CATALOG"), (
            f"Неожиданный reason_code: {dec_s3.reason_code}"
        )
        assert "returns" in dec_s3.physical_tables
        assert "orders" in dec_s3.physical_tables

        pg_records_s3 = await pg_conn.fetch(dec_s3.sql)
        pg_rows_s3 = [dict(r) for r in pg_records_s3]
        total_refunded = Decimal("0.00")
        for r in pg_rows_s3:
            st = r["status"]
            cnt = r["total_orders"]
            ref = Decimal(str(r["total_refunded"]))
            total_refunded += ref
            print(f"  Статус={st}: заказов с возвратом={cnt}, возврат={ref:.2f}")
        assert total_refunded == Decimal("720.00"), f"Сумма возвратов {total_refunded} != 720.00"
        print(f"  Итого возвратов: {total_refunded:.2f} (точно совпадает с ожидаемым сидом)")
        print("  [OK] Сценарий 3 успешно пройден!")

    finally:
        await pg_conn.close()
        ch_client.close()

    print("\n" + "=" * 70)
    print(" ВСЕ 3 СЦЕНАРИЯ СТЕНДА УСПЕШНО ВЕРИФИЦИРОВАНЫ (100% SUCCESS)!")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
