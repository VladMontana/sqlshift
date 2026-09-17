"""Модульные тесты для AsyncSQLShiftClient с использованием моков (без реальных БД)."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sqlshift.client import AsyncSQLShiftClient, SmartClient


@pytest.fixture
def mock_db_drivers():
    """Фикстура мока драйверов asyncpg и clickhouse_connect."""
    patch_pg = patch(
        "sqlshift.client.async_client.asyncpg.create_pool", new_callable=AsyncMock
    )
    patch_ch = patch(
        "sqlshift.client.async_client.clickhouse_connect.get_client"
    )
    with patch_pg as mock_pg_pool_factory, patch_ch as mock_ch_client_factory:
        # Настраиваем mock asyncpg
        mock_pg_pool = MagicMock()
        mock_pg_pool.close = AsyncMock()
        mock_pg_conn = AsyncMock()
        mock_pg_conn.fetch.return_value = [{"id": 42, "email": "user@example.com"}]

        # pool.acquire() возвращает асинхронный контекстный менеджер
        mock_acquire_ctx = MagicMock()
        mock_acquire_ctx.__aenter__ = AsyncMock(return_value=mock_pg_conn)
        mock_acquire_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_pg_pool.acquire.return_value = mock_acquire_ctx

        mock_pg_pool_factory.return_value = mock_pg_pool

        # Настраиваем mock clickhouse_connect
        mock_ch_client = MagicMock()
        mock_ch_result = MagicMock()
        mock_ch_result.column_names = ["month", "total"]
        mock_ch_result.result_rows = [("2026-01-01", 1500)]
        mock_ch_client.query.return_value = mock_ch_result
        mock_ch_client_factory.return_value = mock_ch_client

        yield {
            "mock_pg_pool_factory": mock_pg_pool_factory,
            "mock_pg_pool": mock_pg_pool,
            "mock_pg_conn": mock_pg_conn,
            "mock_ch_client_factory": mock_ch_client_factory,
            "mock_ch_client": mock_ch_client,
        }


@pytest.mark.asyncio
async def test_client_routes_oltp_to_postgres(mock_db_drivers: dict[str, Any]) -> None:
    """Проверяет, что транзакционный запрос исполняется через asyncpg в Postgres."""
    client = AsyncSQLShiftClient(
        pg_dsn="postgresql://postgres:secret@localhost:5432/testdb",
        ch_dsn="clickhouse://localhost:8123/testdb",
    )

    async with client:
        rows = await client.fetch("SELECT id, email FROM users WHERE id = 42")

    assert rows == [{"id": 42, "email": "user@example.com"}]
    # Проверяем, что запрос ушел в Postgres
    mock_db_drivers["mock_pg_conn"].fetch.assert_awaited_once_with(
        "SELECT id, email FROM users WHERE id = 42"
    )
    # И НЕ ушел в ClickHouse
    mock_db_drivers["mock_ch_client"].query.assert_not_called()


@pytest.mark.asyncio
async def test_client_routes_olap_to_clickhouse(mock_db_drivers: dict[str, Any]) -> None:
    """Проверяет, что аналитический запрос транспайлится и уходит в ClickHouse."""
    client = SmartClient(
        pg_dsn="postgresql://postgres:secret@localhost:5432/testdb",
        ch_dsn="clickhouse://localhost:8123/testdb",
    )

    async with client:
        sql = "SELECT date_trunc('month', created_at), sum(amount) FROM payments GROUP BY 1"
        rows = await client.fetch(sql)

    assert rows == [{"month": "2026-01-01", "total": 1500}]
    # Проверяем, что запрос ушел в ClickHouse с транспайленным диалектом
    mock_db_drivers["mock_ch_client"].query.assert_called_once()
    called_sql = mock_db_drivers["mock_ch_client"].query.call_args[0][0]
    assert "dateTrunc" in called_sql or "toStartOfMonth" in called_sql
    # И НЕ ушел в Postgres
    mock_db_drivers["mock_pg_conn"].fetch.assert_not_called()


@pytest.mark.asyncio
async def test_client_context_manager_lifecycle(mock_db_drivers: dict[str, Any]) -> None:
    """Проверяет жизненный цикл соединений (connect / close) в контекстном менеджере."""
    client = AsyncSQLShiftClient(
        pg_dsn="postgresql://localhost:5432/testdb",
        ch_dsn="clickhouse://localhost:8123/testdb",
    )

    async with client:
        assert client._pg_pool is not None
        assert client._ch_client is not None

    # После выхода из контекста пулы должны быть закрыты и сброшены в None
    assert client._pg_pool is None
    assert client._ch_client is None
    mock_db_drivers["mock_pg_pool"].close.assert_awaited_once()
    mock_db_drivers["mock_ch_client"].close.assert_called_once()
