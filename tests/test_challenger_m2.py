"""Empirical Adversarial Verification Suite for Milestone 2: CLI & Client.

Tests:
1. CLI invocation via Typer CliRunner and subprocess for all required and edge scenarios:
   a) no catalog -> clickhouse
   b) catalog allowed -> clickhouse
   c) catalog unallowed -> postgresql (TABLE_NOT_IN_CATALOG)
   d) catalog pinned -> postgresql (TABLE_PG_PINNED)
   e) table structure, reason code, physical tables output verification
   f) adversarial stress: syntax errors, multi-statement injection, empty inputs,
      whitespace in flags, CTE name shadowing, DML, zero physical tables.
2. AsyncSQLShiftClient initialization, catalog propagation, router precedence,
   and mock query routing for all cases.
3. Zero unhandled exceptions verification across all surfaces.
"""

import asyncio
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from sqlshift.cli.main import app
from sqlshift.client import AsyncSQLShiftClient
from sqlshift.core.catalog import TableCatalog
from sqlshift.core.router import SQLShiftRouter
from sqlshift.utils.exception import SQLParsingError, SQLShiftError

runner = CliRunner()


# ============================================================================
# 1. CLI Stress Tests (CliRunner + Subprocess)
# ============================================================================


def test_cli_route_case_a_no_catalog() -> None:
    """Case a: no catalog -> clickhouse."""
    sql = "SELECT count(*) FROM orders GROUP BY status"
    result = runner.invoke(app, ["route", sql])
    assert result.exit_code == 0, f"Exit code {result.exit_code} != 0. Output:\n{result.stdout}"
    assert "ClickHouse (OLAP)" in result.stdout
    assert "Reason Code: ANALYTICAL_CLICKHOUSE" in result.stdout
    assert "Physical Tables: orders" in result.stdout


def test_cli_route_case_b_catalog_allowed() -> None:
    """Case b: catalog allowed -> clickhouse."""
    sql = "SELECT count(*) FROM orders GROUP BY status"
    result = runner.invoke(app, ["route", sql, "--allowed-tables", "orders"])
    assert result.exit_code == 0, f"Exit code {result.exit_code} != 0. Output:\n{result.stdout}"
    assert "ClickHouse (OLAP)" in result.stdout
    assert "Reason Code: ANALYTICAL_CLICKHOUSE" in result.stdout
    assert "Physical Tables: orders" in result.stdout


def test_cli_route_case_c_catalog_missing() -> None:
    """Case c: catalog missing orders -> postgresql."""
    sql = "SELECT count(*) FROM orders GROUP BY status"
    result = runner.invoke(app, ["route", sql, "--allowed-tables", "returns"])
    assert result.exit_code == 0, f"Exit code {result.exit_code} != 0. Output:\n{result.stdout}"
    assert "PostgreSQL (OLTP)" in result.stdout
    assert "Reason Code: TABLE_NOT_IN_CATALOG" in result.stdout
    assert "Physical Tables: orders" in result.stdout


def test_cli_route_case_d_catalog_pinned() -> None:
    """Case d: catalog pinned -> postgresql."""
    sql = "SELECT count(*) FROM orders GROUP BY status"
    result = runner.invoke(
        app,
        ["route", sql, "--allowed-tables", "orders", "--pg-only-tables", "orders"],
    )
    assert result.exit_code == 0, f"Exit code {result.exit_code} != 0. Output:\n{result.stdout}"
    assert "PostgreSQL (OLTP)" in result.stdout
    assert "Reason Code: TABLE_PG_PINNED" in result.stdout
    assert "Physical Tables: orders" in result.stdout


def test_cli_route_subprocess_execution() -> None:
    """Test actual CLI subprocess execution via `uv run sqlshift route`."""
    cmd = [
        "uv",
        "run",
        "sqlshift",
        "route",
        "SELECT count(*) FROM orders GROUP BY status",
        "--allowed-tables",
        "orders",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, f"Subprocess failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    assert "ClickHouse" in proc.stdout
    assert "ANALYTICAL_CLICKHOUSE" in proc.stdout
    assert "orders" in proc.stdout


def test_cli_adversarial_whitespace_and_commas() -> None:
    """Adversarial: whitespace and trailing commas in table lists."""
    sql = "SELECT count(*) FROM orders GROUP BY status"
    result = runner.invoke(
        app,
        ["route", sql, "--allowed-tables", "  orders , , items,  "],
    )
    assert result.exit_code == 0
    assert "ClickHouse (OLAP)" in result.stdout
    assert "ANALYTICAL_CLICKHOUSE" in result.stdout


def test_cli_adversarial_empty_catalog_flag() -> None:
    """Adversarial: empty --allowed-tables flag blocks ClickHouse."""
    sql = "SELECT count(*) FROM orders GROUP BY status"
    result = runner.invoke(app, ["route", sql, "--allowed-tables", ""])
    assert result.exit_code == 0
    assert "PostgreSQL (OLTP)" in result.stdout
    assert "TABLE_NOT_IN_CATALOG" in result.stdout


def test_cli_adversarial_multi_statement() -> None:
    """Adversarial: multi-statement SQL must fail cleanly with code 1 and no crash."""
    sql = "SELECT count(*) FROM orders; DROP TABLE orders;"
    result = runner.invoke(app, ["route", sql])
    assert result.exit_code == 1
    assert "PARSING ERROR" in result.stdout.upper()
    assert "Traceback" not in result.stdout


def test_cli_adversarial_syntax_error() -> None:
    """Adversarial: syntax error must fail cleanly with code 1 and no crash."""
    sql = "SELECT FROM WHERE"
    result = runner.invoke(app, ["route", sql])
    assert result.exit_code == 1
    assert "PARSING ERROR" in result.stdout.upper()
    assert "Traceback" not in result.stdout


def test_cli_adversarial_empty_sql() -> None:
    """Adversarial: empty or whitespace SQL must fail cleanly with code 1 and no crash."""
    result = runner.invoke(app, ["route", "   \n\t  "])
    assert result.exit_code == 1
    assert "PARSING ERROR" in result.stdout.upper()
    assert "Traceback" not in result.stdout


def test_cli_adversarial_cte_shadowing() -> None:
    """Adversarial: CTE name must not be listed as a physical table."""
    sql = (
        "WITH orders AS (SELECT 1 AS x), "
        "     summary AS (SELECT count(*) FROM raw_orders GROUP BY status) "
        "SELECT * FROM summary"
    )
    result = runner.invoke(app, ["route", sql, "--allowed-tables", "raw_orders"])
    assert result.exit_code == 0
    assert "ClickHouse (OLAP)" in result.stdout
    assert "ANALYTICAL_CLICKHOUSE" in result.stdout
    assert "Physical Tables: raw_orders" in result.stdout


def test_cli_adversarial_zero_physical_tables() -> None:
    """Adversarial: analytical query without physical tables stays in Postgres."""
    sql = "SELECT 1, count(*) GROUP BY 1"
    result = runner.invoke(app, ["route", sql, "--allowed-tables", "orders"])
    assert result.exit_code == 0
    assert "PostgreSQL (OLTP)" in result.stdout
    assert "NO_PHYSICAL_TABLES" in result.stdout
    assert "Physical Tables: (none)" in result.stdout


def test_cli_adversarial_dml_routing() -> None:
    """Adversarial: DML UPDATE stays in Postgres even with allowed tables."""
    sql = "UPDATE orders SET status = 'shipped' WHERE id = 1"
    result = runner.invoke(app, ["route", sql, "--allowed-tables", "orders"])
    assert result.exit_code == 0
    assert "PostgreSQL (OLTP)" in result.stdout
    assert "DML_OPERATION" in result.stdout
    assert "Physical Tables: orders" in result.stdout


def test_cli_adversarial_unicode_cyrillic() -> None:
    """Adversarial: unicode strings and comments are handled without decoding errors."""
    sql = "SELECT count(*) FROM orders WHERE status = 'доставлен' /* проверка */ GROUP BY status"
    result = runner.invoke(app, ["route", sql, "--allowed-tables", "orders"])
    assert result.exit_code == 0
    assert "ClickHouse (OLAP)" in result.stdout
    assert "ANALYTICAL_CLICKHOUSE" in result.stdout


# ============================================================================
# 2. AsyncSQLShiftClient Stress Tests
# ============================================================================


def _route_helper(client: AsyncSQLShiftClient, sql: str):
    """Call client.route(sql) if available, or client.router.route(sql)."""
    if hasattr(client, "route"):
        return client.route(sql)
    return client.router.route(sql)


def test_client_init_no_catalog() -> None:
    """Client initialized without catalog has router.catalog == None."""
    client = AsyncSQLShiftClient("postgresql://localhost/db", "clickhouse://localhost/db")
    assert client.router.catalog is None
    decision = _route_helper(client, "SELECT count(*) FROM orders GROUP BY status")
    assert decision.target == "clickhouse"
    assert decision.reason_code == "ANALYTICAL_CLICKHOUSE"
    assert decision.physical_tables == ["orders"]
    assert not decision.catalog_checked


def test_client_init_with_catalog_allowed() -> None:
    """Client with catalog admitting table routes to ClickHouse."""
    catalog = TableCatalog(allowed_tables=["orders"])
    client = AsyncSQLShiftClient(
        "postgresql://localhost/db",
        "clickhouse://localhost/db",
        catalog=catalog,
    )
    assert client.router.catalog is catalog
    decision = _route_helper(client, "SELECT count(*) FROM orders GROUP BY status")
    assert decision.target == "clickhouse"
    assert decision.reason_code == "ANALYTICAL_CLICKHOUSE"
    assert decision.catalog_checked


def test_client_init_with_catalog_unallowed() -> None:
    """Client with catalog missing table routes to PostgreSQL."""
    catalog = TableCatalog(allowed_tables=["returns"])
    client = AsyncSQLShiftClient(
        "postgresql://localhost/db",
        "clickhouse://localhost/db",
        catalog=catalog,
    )
    assert client.router.catalog is catalog
    decision = _route_helper(client, "SELECT count(*) FROM orders GROUP BY status")
    assert decision.target == "postgresql"
    assert decision.reason_code == "TABLE_NOT_IN_CATALOG"
    assert decision.catalog_checked


def test_client_init_with_catalog_pinned() -> None:
    """Client with catalog pinning table routes to PostgreSQL."""
    catalog = TableCatalog(allowed_tables=["orders"], postgres_only_tables=["orders"])
    client = AsyncSQLShiftClient(
        "postgresql://localhost/db",
        "clickhouse://localhost/db",
        catalog=catalog,
    )
    assert client.router.catalog is catalog
    decision = _route_helper(client, "SELECT count(*) FROM orders GROUP BY status")
    assert decision.target == "postgresql"
    assert decision.reason_code == "TABLE_PG_PINNED"
    assert decision.catalog_checked


def test_client_init_router_precedence() -> None:
    """Explicit router argument overrides catalog argument."""
    cat1 = TableCatalog(allowed_tables=["orders"])
    cat2 = TableCatalog(allowed_tables=["returns"])
    custom_router = SQLShiftRouter(catalog=cat1)

    client = AsyncSQLShiftClient(
        "postgresql://localhost/db",
        "clickhouse://localhost/db",
        router=custom_router,
        catalog=cat2,
    )
    assert client.router is custom_router
    assert client.router.catalog is cat1


def test_client_empty_catalog_blocks_clickhouse() -> None:
    """Empty catalog strictly prevents any query from reaching ClickHouse."""
    catalog = TableCatalog(allowed_tables=[])
    client = AsyncSQLShiftClient(
        "postgresql://localhost/db",
        "clickhouse://localhost/db",
        catalog=catalog,
    )
    decision = _route_helper(client, "SELECT count(*) FROM orders GROUP BY status")
    assert decision.target == "postgresql"
    assert decision.reason_code == "TABLE_NOT_IN_CATALOG"


def test_client_exception_safety_multi_statement() -> None:
    """Client routing multi-statement query raises SQLShiftError cleanly."""
    client = AsyncSQLShiftClient("postgresql://localhost/db", "clickhouse://localhost/db")
    with pytest.raises(SQLShiftError) as exc_info:
        _route_helper(client, "SELECT 1; DROP TABLE orders;")
    assert isinstance(exc_info.value, SQLParsingError)
    assert "несколько" in str(exc_info.value).lower()


def test_client_exception_safety_empty_query() -> None:
    """Client routing empty query raises SQLShiftError cleanly."""
    client = AsyncSQLShiftClient("postgresql://localhost/db", "clickhouse://localhost/db")
    with pytest.raises(SQLShiftError) as exc_info:
        _route_helper(client, "")
    assert isinstance(exc_info.value, SQLParsingError)
    assert "пустым" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_client_fetch_mock_routing_matrix() -> None:
    """Empirically test async client.fetch() routing across all 4 admission conditions."""
    patch_pg = patch("sqlshift.client.async_client.asyncpg.create_pool", new_callable=AsyncMock)
    patch_ch = patch("sqlshift.client.async_client.clickhouse_connect.get_client")

    with patch_pg as mock_pg_factory, patch_ch as mock_ch_factory:
        mock_pg_pool = MagicMock()
        mock_pg_pool.close = AsyncMock()
        mock_pg_conn = AsyncMock()
        mock_pg_conn.fetch.return_value = [{"result": "from_pg"}]
        mock_acquire = MagicMock()
        mock_acquire.__aenter__ = AsyncMock(return_value=mock_pg_conn)
        mock_acquire.__aexit__ = AsyncMock(return_value=None)
        mock_pg_pool.acquire.return_value = mock_acquire
        mock_pg_factory.return_value = mock_pg_pool

        mock_ch_client = MagicMock()
        mock_ch_client.close = MagicMock()
        mock_ch_res = MagicMock()
        mock_ch_res.column_names = ["result"]
        mock_ch_res.result_rows = [("from_ch",)]
        mock_ch_client.query.return_value = mock_ch_res
        mock_ch_factory.return_value = mock_ch_client

        # 1. No catalog -> ClickHouse
        client_no_cat = AsyncSQLShiftClient("pg://localhost", "ch://localhost")
        res1 = await client_no_cat.fetch("SELECT count(*) FROM orders GROUP BY status")
        assert res1 == [{"result": "from_ch"}]
        assert mock_ch_client.query.call_count == 1
        assert mock_pg_conn.fetch.call_count == 0

        # Reset counts
        mock_ch_client.query.reset_mock()
        mock_pg_conn.fetch.reset_mock()

        # 2. Allowed table -> ClickHouse
        cat_allowed = TableCatalog(allowed_tables=["orders"])
        client_allowed = AsyncSQLShiftClient(
            "pg://localhost", "ch://localhost", catalog=cat_allowed
        )
        res2 = await client_allowed.fetch("SELECT count(*) FROM orders GROUP BY status")
        assert res2 == [{"result": "from_ch"}]
        assert mock_ch_client.query.call_count == 1
        assert mock_pg_conn.fetch.call_count == 0

        # Reset counts
        mock_ch_client.query.reset_mock()
        mock_pg_conn.fetch.reset_mock()

        # 3. Unallowed table -> PostgreSQL
        cat_unallowed = TableCatalog(allowed_tables=["returns"])
        client_unallowed = AsyncSQLShiftClient(
            "pg://localhost", "ch://localhost", catalog=cat_unallowed
        )
        res3 = await client_unallowed.fetch("SELECT count(*) FROM orders GROUP BY status")
        assert res3 == [{"result": "from_pg"}]
        assert mock_pg_conn.fetch.call_count == 1
        assert mock_ch_client.query.call_count == 0

        # Reset counts
        mock_ch_client.query.reset_mock()
        mock_pg_conn.fetch.reset_mock()

        # 4. Pinned table -> PostgreSQL
        cat_pinned = TableCatalog(allowed_tables=["orders"], postgres_only_tables=["orders"])
        client_pinned = AsyncSQLShiftClient("pg://localhost", "ch://localhost", catalog=cat_pinned)
        res4 = await client_pinned.fetch("SELECT count(*) FROM orders GROUP BY status")
        assert res4 == [{"result": "from_pg"}]
        assert mock_pg_conn.fetch.call_count == 1
        assert mock_ch_client.query.call_count == 0

        # Cleanup
        await client_no_cat.close()
        await client_allowed.close()
        await client_unallowed.close()
        await client_pinned.close()


# ============================================================================
# Main runner for standalone execution: `uv run python tests/test_challenger_m2.py`
# ============================================================================


def main() -> int:
    print("=" * 70)
    print("SQLShift Milestone 2 Adversarial Stress Verification Suite")
    print("=" * 70)

    sync_tests = [
        ("test_cli_route_case_a_no_catalog", test_cli_route_case_a_no_catalog),
        ("test_cli_route_case_b_catalog_allowed", test_cli_route_case_b_catalog_allowed),
        ("test_cli_route_case_c_catalog_missing", test_cli_route_case_c_catalog_missing),
        ("test_cli_route_case_d_catalog_pinned", test_cli_route_case_d_catalog_pinned),
        ("test_cli_route_subprocess_execution", test_cli_route_subprocess_execution),
        ("test_cli_adversarial_whitespace_and_commas", test_cli_adversarial_whitespace_and_commas),
        ("test_cli_adversarial_empty_catalog_flag", test_cli_adversarial_empty_catalog_flag),
        ("test_cli_adversarial_multi_statement", test_cli_adversarial_multi_statement),
        ("test_cli_adversarial_syntax_error", test_cli_adversarial_syntax_error),
        ("test_cli_adversarial_empty_sql", test_cli_adversarial_empty_sql),
        ("test_cli_adversarial_cte_shadowing", test_cli_adversarial_cte_shadowing),
        ("test_cli_adversarial_zero_physical_tables", test_cli_adversarial_zero_physical_tables),
        ("test_cli_adversarial_dml_routing", test_cli_adversarial_dml_routing),
        ("test_cli_adversarial_unicode_cyrillic", test_cli_adversarial_unicode_cyrillic),
        ("test_client_init_no_catalog", test_client_init_no_catalog),
        ("test_client_init_with_catalog_allowed", test_client_init_with_catalog_allowed),
        ("test_client_init_with_catalog_unallowed", test_client_init_with_catalog_unallowed),
        ("test_client_init_with_catalog_pinned", test_client_init_with_catalog_pinned),
        ("test_client_init_router_precedence", test_client_init_router_precedence),
        (
            "test_client_empty_catalog_blocks_clickhouse",
            test_client_empty_catalog_blocks_clickhouse,
        ),
        (
            "test_client_exception_safety_multi_statement",
            test_client_exception_safety_multi_statement,
        ),
        ("test_client_exception_safety_empty_query", test_client_exception_safety_empty_query),
    ]

    passed = 0
    failed = 0

    for name, fn in sync_tests:
        try:
            fn()
            print(f"[PASS] {name}")
            passed += 1
        except Exception as e:
            print(f"[FAIL] {name}: {e}")
            failed += 1

    # Run async test
    try:
        asyncio.run(test_client_fetch_mock_routing_matrix())
        print("[PASS] test_client_fetch_mock_routing_matrix")
        passed += 1
    except Exception as e:
        print(f"[FAIL] test_client_fetch_mock_routing_matrix: {e}")
        failed += 1

    print("=" * 70)
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed} tests.")
    print("=" * 70)

    if failed > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
