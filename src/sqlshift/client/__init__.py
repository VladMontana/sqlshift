"""Client execution layer (asyncpg + clickhouse-connect)."""

from sqlshift.client.async_client import AsyncSQLShiftClient

SmartClient = AsyncSQLShiftClient

__all__ = ["AsyncSQLShiftClient", "SmartClient"]
