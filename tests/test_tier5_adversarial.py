"""Tier 5 Adversarial Test Suite for SQLShift.

Stress-tests edge cases, deep nestings, schema casings, extreme query scales,
and documents empirical vulnerabilities in comment handling and modifying CTE scoping.
"""

import time

import pytest
from fastapi.testclient import TestClient

from sqlshift.client.async_client import AsyncSQLShiftClient
from sqlshift.core.catalog import TableCatalog, extract_physical_tables
from sqlshift.core.parser import parse_sql
from sqlshift.core.router import SQLShiftRouter
from sqlshift.server.app import create_app
from sqlshift.utils.exception import SQLParsingError


def test_t5_deep_nested_cte_3_levels() -> None:
    cat = TableCatalog(allowed_tables=["orders", "users"])
    router = SQLShiftRouter(catalog=cat)
    sql = """
    WITH
      c1 AS (SELECT id, amount, user_id FROM orders WHERE amount > 100),
      c2 AS (SELECT c1.id, c1.amount, u.name FROM c1 JOIN users u ON c1.user_id = u.id),
      c3 AS (SELECT name, sum(amount) as s FROM c2 GROUP BY name)
    SELECT * FROM c3 WHERE s > 500;
    """
    decision = router.route(sql)
    assert decision.target == "clickhouse"
    assert decision.reason_code == "ANALYTICAL_CLICKHOUSE"
    assert sorted(decision.physical_tables) == ["orders", "users"]


def test_t5_deep_nested_cte_5_levels() -> None:
    cat = TableCatalog(allowed_tables=["orders", "users", "items"])
    router = SQLShiftRouter(catalog=cat)
    sql = """
    WITH
      c1 AS (SELECT id, amount, user_id FROM orders),
      c2 AS (SELECT user_id, sum(amount) as total FROM c1 GROUP BY user_id),
      c3 AS (SELECT c2.user_id, c2.total, u.name FROM c2 JOIN users u ON c2.user_id = u.id),
      c4 AS (SELECT c3.name, c3.total, i.price FROM c3 JOIN items i ON c3.user_id = i.id),
      c5 AS (SELECT name, avg(price) as avg_p FROM c4 GROUP BY name)
    SELECT * FROM c5;
    """
    decision = router.route(sql)
    assert decision.target == "clickhouse"
    assert sorted(decision.physical_tables) == ["items", "orders", "users"]


def test_t5_recursive_cte_self_reference() -> None:
    cat = TableCatalog(allowed_tables=["users"])
    router = SQLShiftRouter(catalog=cat)
    sql = """
    WITH RECURSIVE subordinates AS (
        SELECT id, manager_id FROM users WHERE manager_id IS NULL
        UNION ALL
        SELECT u.id, u.manager_id FROM users u JOIN subordinates s ON u.manager_id = s.id
    )
    SELECT count(*) FROM subordinates;
    """
    decision = router.route(sql)
    assert decision.target == "clickhouse"
    assert decision.physical_tables == ["users"]


def test_t5_cte_shadowing_physical_table() -> None:
    cat = TableCatalog(allowed_tables=["orders", "raw_users"])
    router = SQLShiftRouter(catalog=cat)
    sql = """
    WITH orders AS (SELECT id, name FROM raw_users)
    SELECT count(*) FROM orders;
    """
    decision = router.route(sql)
    assert decision.target == "clickhouse"
    assert decision.physical_tables == ["raw_users"]


def test_t5_nested_subquery_cte_shadowing_outer_cte() -> None:
    cat = TableCatalog(allowed_tables=["backup_users", "raw_users"])
    router = SQLShiftRouter(catalog=cat)
    sql = """
    WITH users AS (SELECT * FROM raw_users)
    SELECT count(*) FROM (
        WITH users AS (SELECT * FROM backup_users)
        SELECT * FROM users
    ) sub JOIN users ON sub.id = users.id;
    """
    decision = router.route(sql)
    assert decision.target == "clickhouse"
    assert sorted(decision.physical_tables) == ["backup_users", "raw_users"]


def test_t5_derived_table_alias_matches_physical_table() -> None:
    cat = TableCatalog(allowed_tables=["orders", "users"])
    router = SQLShiftRouter(catalog=cat)
    sql = "SELECT count(*) FROM users AS orders JOIN orders ON users.id = orders.id;"
    decision = router.route(sql)
    assert decision.target == "clickhouse"
    assert sorted(decision.physical_tables) == ["orders", "users"]


def test_t5_cte_name_conflicts_with_schema_qualified_table() -> None:
    cat = TableCatalog(allowed_tables=["orders", "raw_users"])
    router = SQLShiftRouter(catalog=cat)
    sql = """
    WITH orders AS (SELECT * FROM raw_users)
    SELECT count(*) FROM orders JOIN public.orders ON orders.id = public.orders.id;
    """
    decision = router.route(sql)
    assert decision.target == "clickhouse"
    assert sorted(decision.physical_tables) == ["public.orders", "raw_users"]


def test_t5_quoted_schema_case_insensitive() -> None:
    cat = TableCatalog(allowed_tables=["orders"], case_sensitive=False)
    router = SQLShiftRouter(catalog=cat)
    # 1. "public"."orders" в нижнем регистре разрешен в ClickHouse
    d_admitted = router.route('SELECT count(*) FROM "public"."orders";')
    assert d_admitted.target == "clickhouse"
    assert d_admitted.reason_code == "ANALYTICAL_CLICKHOUSE"

    # 2. "Public"."Orders" с заглавными в кавычках отличается от orders -> в PostgreSQL
    d_rejected = router.route('SELECT count(*) FROM "Public"."Orders";')
    assert d_rejected.target == "postgresql"
    assert d_rejected.reason_code == "TABLE_NOT_IN_CATALOG"


def test_t5_table_name_with_space_in_quotes() -> None:
    cat = TableCatalog(allowed_tables=["order items"])
    router = SQLShiftRouter(catalog=cat)
    decision = router.route('SELECT count(*) FROM "order items";')
    assert decision.target == "clickhouse"
    assert decision.reason_code == "ANALYTICAL_CLICKHOUSE"


def test_t5_case_sensitive_catalog_strict_rejection() -> None:
    cat = TableCatalog(allowed_tables=["orders"], case_sensitive=True)
    router = SQLShiftRouter(catalog=cat)
    decision = router.route('SELECT count(*) FROM "Orders";')
    assert decision.target == "postgresql"
    assert decision.reason_code == "TABLE_NOT_IN_CATALOG"


def test_t5_stress_50_joins() -> None:
    all_tables = ["orders"] + [f"t{i}" for i in range(50)]
    cat = TableCatalog(allowed_tables=all_tables)
    router = SQLShiftRouter(catalog=cat)
    joins = " ".join(f"JOIN t{i} ON orders.id = t{i}.id" for i in range(50))
    sql = f"SELECT count(*) FROM orders {joins};"
    t0 = time.perf_counter()
    decision = router.route(sql)
    dt = time.perf_counter() - t0
    assert decision.target == "clickhouse"
    assert len(decision.physical_tables) == 51
    assert dt < 0.5


def test_t5_stress_50_chained_ctes() -> None:
    cat = TableCatalog(allowed_tables=["orders"])
    router = SQLShiftRouter(catalog=cat)
    ctes_list = [
        "c0 AS (SELECT id, amount FROM orders)"
        if i == 0
        else f"c{i} AS (SELECT id, amount FROM c{i-1})"
        for i in range(50)
    ]
    sql = f"WITH {', '.join(ctes_list)} SELECT count(*), sum(amount) FROM c49;"
    t0 = time.perf_counter()
    decision = router.route(sql)
    dt = time.perf_counter() - t0
    assert decision.target == "clickhouse"
    assert decision.physical_tables == ["orders"]
    assert dt < 0.5


def test_t5_stress_1000_in_items() -> None:
    cat = TableCatalog(allowed_tables=["orders"])
    router = SQLShiftRouter(catalog=cat)
    in_items = ", ".join(str(i) for i in range(1000))
    sql = f"SELECT count(*) FROM orders WHERE id IN ({in_items});"
    t0 = time.perf_counter()
    decision = router.route(sql)
    dt = time.perf_counter() - t0
    assert decision.target == "clickhouse"
    assert dt < 0.5


def test_t5_stress_20_level_nested_subqueries() -> None:
    cat = TableCatalog(allowed_tables=["orders"])
    router = SQLShiftRouter(catalog=cat)
    nested = "orders"
    for i in range(20):
        nested = f"(SELECT * FROM {nested} AS s_{i})"
    sql = f"SELECT count(*) FROM {nested} AS final;"
    t0 = time.perf_counter()
    decision = router.route(sql)
    dt = time.perf_counter() - t0
    assert decision.target == "clickhouse"
    assert decision.physical_tables == ["orders"]
    assert dt < 0.5


def test_t5_weird_spacing_crlf_and_tabs() -> None:
    cat = TableCatalog(allowed_tables=["orders"])
    router = SQLShiftRouter(catalog=cat)
    sql = "SELECT\r\n\tcount(*)\r\nFROM\r\n\torders\r\nWHERE\r\n\tstatus = 'ok';"
    decision = router.route(sql)
    assert decision.target == "clickhouse"
    assert decision.physical_tables == ["orders"]


def test_t5_semicolon_inside_string_literal() -> None:
    cat = TableCatalog(allowed_tables=["orders"])
    router = SQLShiftRouter(catalog=cat)
    sql = "SELECT count(*), 'hello; world; SELECT * FROM users;' AS col FROM orders;"
    decision = router.route(sql)
    assert decision.target == "clickhouse"
    assert decision.physical_tables == ["orders"]


def test_t5_comments_only_rejected() -> None:
    with pytest.raises(SQLParsingError):
        parse_sql("-- just a comment\n/* block comment */")


def test_t5_trailing_comment_with_semicolon() -> None:
    cat = TableCatalog(allowed_tables=["orders"])
    router = SQLShiftRouter(catalog=cat)
    sql = "SELECT count(*) FROM orders WHERE id = 1; -- ; DROP TABLE orders;"
    decision = router.route(sql)
    assert decision.target == "clickhouse"
    assert decision.physical_tables == ["orders"]


def test_t5_server_api_route_empty_sql_422() -> None:
    app = create_app()
    client = TestClient(app)
    res = client.post("/v1/route", json={"sql": ""})
    assert res.status_code == 422


def test_t5_server_api_route_multistatement_400() -> None:
    app = create_app()
    client = TestClient(app)
    res = client.post("/v1/route", json={"sql": "SELECT 1; DROP TABLE orders;"})
    assert res.status_code == 400
    assert res.json().get("error") == "SQLParsingError"


def test_t5_server_api_query_no_db_503() -> None:
    app = create_app()
    client = TestClient(app)
    res = client.post("/v1/query", json={"sql": "SELECT 1;"})
    assert res.status_code == 503


@pytest.mark.asyncio
async def test_t5_async_client_lifecycle_close_unopened() -> None:
    client = AsyncSQLShiftClient(
        pg_dsn="postgresql://localhost:5432/db",
        ch_dsn="clickhouse://localhost:8123/db",
    )
    await client.close()


# -----------------------------------------------------------------------------
# Empirical Vulnerability Proofs (Disprove / Request Changes)
# -----------------------------------------------------------------------------

def test_t5_vulnerability_comment_leak_on_table_name() -> None:
    cat = TableCatalog(allowed_tables=["orders"])
    router = SQLShiftRouter(catalog=cat)
    sql = "SELECT count(*) FROM orders -- check\nWHERE status = 'ok';"
    tree = parse_sql(sql)
    tables = extract_physical_tables(tree)
    # Correct behavior: table is ['orders'] without inline comment text
    assert tables == ["orders"], f"Comment leaked into physical table name: {tables}"
    decision = router.route(sql)
    assert decision.target == "clickhouse"
    assert decision.reason_code == "ANALYTICAL_CLICKHOUSE"


def test_t5_vulnerability_modifying_cte_masked_by_outer_read_only_cte() -> None:
    router = SQLShiftRouter()
    sql = """
    WITH valid_cte AS (SELECT 1 AS x)
    SELECT * FROM (
        WITH modifying_cte AS (DELETE FROM orders WHERE id = 1 RETURNING id)
        SELECT * FROM modifying_cte
    ) sub;
    """
    decision = router.route(sql)
    # Correct behavior: Any query containing DELETE must route to PostgreSQL with DML_OPERATION
    assert decision.target == "postgresql"
    assert decision.reason_code == "DML_OPERATION"


def test_t5_top_level_package_exports() -> None:
    """Verifies that all primary abstractions are cleanly exported from root sqlshift package."""
    import sqlshift

    assert hasattr(sqlshift, "TableCatalog")
    assert hasattr(sqlshift, "TableAdmissionPolicy")
    assert hasattr(sqlshift, "TableReference")
    assert hasattr(sqlshift, "extract_physical_tables")
    assert sqlshift.TableAdmissionPolicy is sqlshift.TableCatalog
    assert "TableCatalog" in sqlshift.__all__
    assert "TableAdmissionPolicy" in sqlshift.__all__
    assert "TableReference" in sqlshift.__all__
    assert "extract_physical_tables" in sqlshift.__all__
