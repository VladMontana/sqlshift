"""Асинхронный клиент для автоматической маршрутизации и исполнения SQL-запросов."""

import asyncio
from typing import Any

from sqlshift.core.models import RouteDecision
from sqlshift.core.router import SQLShiftRouter

try:
    import asyncpg
    import clickhouse_connect
except ImportError as exc:
    raise ImportError(
        "Для использования SmartClient необходимо установить зависимости клиента: "
        "pip install 'sqlshift[client]'"
    ) from exc


class AsyncSQLShiftClient:
    """Умный асинхронный клиент для гибридных систем PostgreSQL (OLTP) и ClickHouse (OLAP).

    Автоматически анализирует входящие запросы в синтаксисе PostgreSQL, маршрутизирует
    их в нужную базу данных и при необходимости транспайлит диалект в ClickHouse.

    Пример использования:
        ```python
        async with AsyncSQLShiftClient(
            pg_dsn="postgresql://user:pass@localhost:5432/db",
            ch_dsn="clickhouse://localhost:8123/db",
        ) as client:
            # Транзакционный запрос уйдет в Postgres
            user = await client.fetch("SELECT * FROM users WHERE id = 1")

            # Аналитический запрос уйдет в ClickHouse с транспайлингом функций
            stats = await client.fetch(
                "SELECT date_trunc('month', created_at), count(*) FROM events GROUP BY 1"
            )
        ```
    """

    def __init__(
        self,
        pg_dsn: str,
        ch_dsn: str,
        router: SQLShiftRouter | None = None,
    ) -> None:
        """Инициализирует клиент с DSN-строками подключения к обеим базам.

        Args:
            pg_dsn: Строка подключения к PostgreSQL (например, 'postgresql://user:pass@host:5432/db').
            ch_dsn: Строка подключения к ClickHouse (например, 'clickhouse://host:8123/db').
            router: Экземпляр SQLShiftRouter. Если не указан, создается с настройками по умолчанию.
        """
        self.pg_dsn = pg_dsn
        self.ch_dsn = ch_dsn
        self._pg_pool: asyncpg.Pool | None = None
        self._ch_client: Any = None
        self.router: SQLShiftRouter = router or SQLShiftRouter()

    async def connect(self) -> None:
        """Инициализирует пулы подключений к PostgreSQL и ClickHouse."""
        if self._pg_pool is None:
            self._pg_pool = await asyncpg.create_pool(dsn=self.pg_dsn)

        if self._ch_client is None:
            self._ch_client = await asyncio.to_thread(
                clickhouse_connect.get_client,
                dsn=self.ch_dsn,
            )

    async def close(self) -> None:
        """Корректно закрывает все активные пулы и соединения с базами данных."""
        if self._pg_pool is not None:
            await self._pg_pool.close()
            self._pg_pool = None
        if self._ch_client is not None:
            await asyncio.to_thread(self._ch_client.close)
            self._ch_client = None

    async def __aenter__(self) -> "AsyncSQLShiftClient":
        """Вход в асинхронный контекстный менеджер (автоматически вызывает connect)."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Выход из асинхронного контекстного менеджера (гарантированно закрывает соединения)."""
        await self.close()

    async def fetch(self, sql: str) -> list[dict[str, Any]]:
        """Анализирует SQL-запрос, определяет базу назначения, транспайлит и возвращает строки.

        Args:
            sql: Текст SQL-запроса на диалекте PostgreSQL.

        Returns:
            list[dict[str, Any]]: Список строк результатов, где каждая строка — словарь
                с именами колонок в качестве ключей.

        Raises:
            SQLParsingError: Если передан некорректный или пустой SQL-запрос.
            TranspilationError: Если не удалось преобразовать запрос для ClickHouse.
        """
        decision: RouteDecision = self.router.route(sql)
        if decision.target == "clickhouse":
            return await self._execute_clickhouse(decision.sql)
        else:
            return await self._execute_postgres(decision.sql)

    async def _execute_postgres(self, sql: str) -> list[dict[str, Any]]:
        """Выполняет запрос в PostgreSQL через пул соединений asyncpg."""
        if self._pg_pool is None:
            await self.connect()
        assert self._pg_pool is not None
        async with self._pg_pool.acquire() as conn:
            records = await conn.fetch(sql)
            return [dict(record) for record in records]

    def _sync_ch_query(self, sql: str) -> list[dict[str, Any]]:
        """Синхронно выполняет запрос в ClickHouse и преобразует результат в словари."""
        query_result = self._ch_client.query(sql)
        columns = query_result.column_names
        return [dict(zip(columns, row)) for row in query_result.result_rows]

    async def _execute_clickhouse(self, sql: str) -> list[dict[str, Any]]:
        """Асинхронно выполняет запрос в ClickHouse в отдельном потоке (to_thread)."""
        if self._ch_client is None:
            await self.connect()
        return await asyncio.to_thread(self._sync_ch_query, sql)
