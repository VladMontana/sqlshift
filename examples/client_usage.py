"""Пример использования умного асинхронного клиента (AsyncSQLShiftClient / SmartClient).

Клиент автоматически выполняет:
1. Анализ входящего запроса на синтаксисе PostgreSQL.
2. Маршрутизацию транзакционных запросов в PostgreSQL через asyncpg.
3. Маршрутизацию аналитических запросов в ClickHouse через clickhouse-connect
   (с автоматическим транспайлингом синтаксиса).
4. Корректное открытие и закрытие пулов соединений через контекстный менеджер.
"""

import asyncio
import os
import sys

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # ty: ignore[call-non-callable]
    except Exception:
        pass

from sqlshift.client import SmartClient


async def run_client_demo() -> None:
    # DSN строки подключения берутся из переменных окружения или задаются по умолчанию
    pg_dsn = os.getenv("SQLSHIFT_PG_DSN", "postgresql://postgres:postgres@localhost:5432/postgres")
    ch_dsn = os.getenv("SQLSHIFT_CH_DSN", "clickhouse://default:@localhost:8123/default")

    print("=" * 70)
    print(">>> SQLShift -- Демонстрация AsyncSQLShiftClient (SmartClient)")
    print("=" * 70)
    print(f"  PostgreSQL DSN: {pg_dsn}")
    print(f"  ClickHouse DSN: {ch_dsn}")
    print()

    # SmartClient — это удобный алиас для AsyncSQLShiftClient
    client = SmartClient(pg_dsn=pg_dsn, ch_dsn=ch_dsn)

    # 1. Показываем логику маршрутизации клиента в памяти (без подключения к сети)
    print("[*] 1. Анализ маршрутизации перед выполнением:")
    queries = [
        "SELECT id, name FROM users WHERE id = 1",
        "SELECT date_trunc('day', created_at), count(*) FROM events GROUP BY 1",
    ]

    for sql in queries:
        decision = client.router.route(sql)
        print(f"  SQL: {sql}")
        print(
            f"  -> Назначение: {decision.target.upper()} | "
            f"Сложность: {decision.estimated_complexity}"
        )
        if decision.target == "clickhouse":
            print(f"  -> Транспайлинг для CH: {decision.sql}")
        print()

    # 2. Пример выполнения запросов через контекстный менеджер
    print("[*] 2. Попытка подключения и выполнения через async with client:")
    try:
        async with client:
            print("  Успешно подключено к пулам соединений баз данных.")

            # Пример выполнения запроса в Postgres:
            # users = await client.fetch("SELECT id, name FROM users WHERE id = 1")
            # print(f"  Результат Postgres: {users}")

            # Пример выполнения запроса в ClickHouse:
            # stats = await client.fetch("SELECT count(*) FROM events")
            # print(f"  Результат ClickHouse: {stats}")

    except Exception as exc:
        print(f"  [i] Базы данных не запущены локально ({type(exc).__name__}).")
        print("     Для реального выполнения поднимите локальные контейнеры:")
        print("       docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=postgres postgres:16")
        print("       docker run -d -p 8123:8123 clickhouse/clickhouse-server:latest")

    print("\n[OK] Демонстрация работы клиента завершена!")


def main() -> None:
    asyncio.run(run_client_demo())


if __name__ == "__main__":
    main()
