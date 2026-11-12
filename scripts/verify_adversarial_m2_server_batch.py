"""Adversarial stress testing and empirical verification suite for Milestone 2:
FastAPI Server (/v1/route) and BatchAnalyzer (AnalyzeAllSql).

Run via:
    uv run python scripts/verify_adversarial_m2_server_batch.py
"""

import asyncio
import sys
import time
import traceback

import httpx
from fastapi.testclient import TestClient

from sqlshift.core.batch_analyzer import AnalyzeAllSql
from sqlshift.core.catalog import TableCatalog
from sqlshift.core.models import BatchAuditSummary
from sqlshift.server import create_app
from sqlshift.server.config import ServerSettings


class VerificationFailure(Exception):
    """Raised when an empirical assertion fails."""


def log_step(name: str) -> None:
    print(f"\n{'=' * 70}\n>>> RUNNING: {name}\n{'=' * 70}")


def log_pass(msg: str) -> None:
    print(f"  [PASS] {msg}")


# ---------------------------------------------------------------------------
# SECTION 1: FastAPI Server (/v1/route) Verification
# ---------------------------------------------------------------------------


def test_server_no_catalog_routes_analytical_to_clickhouse() -> None:
    log_step("1.1 FastAPI Server: No Catalog -> Routes Analytical to ClickHouse")
    app = create_app()
    client = TestClient(app)

    # 1. Analytical query with aggregation and grouping
    sql_olap = "SELECT status, count(*), sum(amount) FROM orders GROUP BY status"
    resp = client.post("/v1/route", json={"sql": sql_olap})
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()

    assert data["target"] == "clickhouse", f"Expected clickhouse, got {data['target']}"
    assert data["is_analytical"] is True
    assert data["catalog_checked"] is False
    assert data["reason_code"] == "ANALYTICAL_CLICKHOUSE"
    assert "orders" in data["physical_tables"]
    log_pass("Analytical query routed to ClickHouse without catalog check")

    # 2. Transactional query (OLTP)
    sql_oltp = "SELECT id, name FROM users WHERE id = 42"
    resp = client.post("/v1/route", json={"sql": sql_oltp})
    assert resp.status_code == 200
    data = resp.json()

    assert data["target"] == "postgresql"
    assert data["is_analytical"] is False
    assert data["catalog_checked"] is False
    assert data["reason_code"] == "NON_ANALYTICAL_QUERY"
    log_pass("OLTP query correctly routed to PostgreSQL")


def test_server_with_catalog_orders_admission() -> None:
    log_step("1.2 FastAPI Server: TableCatalog(allowed_tables=['orders']) Admission")
    catalog = TableCatalog(
        allowed_tables=["orders"],
        pg_only_tables=["returns"],
    )
    app = create_app(catalog=catalog)
    client = TestClient(app)

    # Case A: orders table (allowed) -> ClickHouse
    sql_orders = "SELECT status, count(*) FROM orders GROUP BY status"
    resp = client.post("/v1/route", json={"sql": sql_orders})
    assert resp.status_code == 200
    d = resp.json()
    assert d["target"] == "clickhouse"
    assert d["catalog_checked"] is True
    assert d["reason_code"] == "ANALYTICAL_CLICKHOUSE"
    assert d["physical_tables"] == ["orders"]
    log_pass("Allowed table 'orders' routed to ClickHouse with catalog_checked=True")

    # Case B: users table (not in catalog) -> PostgreSQL
    sql_users = "SELECT role, count(*) FROM users GROUP BY role"
    resp = client.post("/v1/route", json={"sql": sql_users})
    assert resp.status_code == 200
    d = resp.json()
    assert d["target"] == "postgresql"
    assert d["catalog_checked"] is True
    assert d["reason_code"] == "TABLE_NOT_IN_CATALOG"
    assert d["physical_tables"] == ["users"]
    assert "users" in d["reason"]
    log_pass("Uncataloged table 'users' routed to PostgreSQL with TABLE_NOT_IN_CATALOG")

    # Case C: returns table (pg-only pinned) -> PostgreSQL
    sql_returns = "SELECT reason, count(*) FROM returns GROUP BY reason"
    resp = client.post("/v1/route", json={"sql": sql_returns})
    assert resp.status_code == 200
    d = resp.json()
    assert d["target"] == "postgresql"
    assert d["catalog_checked"] is True
    assert d["reason_code"] == "TABLE_PG_PINNED"
    assert d["physical_tables"] == ["returns"]
    assert "returns" in d["reason"]
    log_pass("Pinned table 'returns' routed to PostgreSQL with TABLE_PG_PINNED")

    # Case D: JOIN allowed table with unallowed table -> PostgreSQL
    sql_join = (
        "SELECT o.status, u.role, count(*) "
        "FROM orders o JOIN users u ON o.user_id = u.id "
        "GROUP BY o.status, u.role"
    )
    resp = client.post("/v1/route", json={"sql": sql_join})
    assert resp.status_code == 200
    d = resp.json()
    assert d["target"] == "postgresql"
    assert d["catalog_checked"] is True
    assert d["reason_code"] == "TABLE_NOT_IN_CATALOG"
    assert sorted(d["physical_tables"]) == ["orders", "users"]
    log_pass("JOIN of allowed and uncataloged table routed to PostgreSQL")


def test_server_full_response_body_schema() -> None:
    log_step("1.3 FastAPI Server: Full Response Body Schema Completeness")
    catalog = TableCatalog(allowed_tables=["orders"])
    app = create_app(catalog=catalog)
    client = TestClient(app)

    expected_keys = {
        "target",
        "sql",
        "is_analytical",
        "estimated_complexity",
        "reason",
        "reason_code",
        "physical_tables",
        "catalog_checked",
    }

    # Test with analytical query
    query = "SELECT status, count(*) FROM orders GROUP BY status"
    resp = client.post("/v1/route", json={"sql": query})
    assert resp.status_code == 200
    body = resp.json()

    missing_keys = expected_keys - set(body.keys())
    assert not missing_keys, f"Response missing keys: {missing_keys}"

    # Verify types
    assert body["target"] in ("postgresql", "clickhouse"), f"Invalid target: {body['target']}"
    assert isinstance(body["sql"], str) and len(body["sql"]) > 0
    assert isinstance(body["is_analytical"], bool)
    assert body["estimated_complexity"] in ("low", "medium", "high")
    assert isinstance(body["reason"], str) and len(body["reason"]) > 0
    assert isinstance(body["reason_code"], str) and len(body["reason_code"]) > 0
    assert isinstance(body["physical_tables"], list)
    assert isinstance(body["catalog_checked"], bool)
    log_pass(f"All 8 schema fields present with valid types: {list(body.keys())}")


def test_server_settings_configuration() -> None:
    log_step("1.4 FastAPI Server: ServerSettings Configuration Path")
    settings = ServerSettings(
        allowed_tables=["orders", "events"],
        postgres_only_tables=["sensitive_data"],
    )
    app = create_app(settings=settings)
    client = TestClient(app)

    # Allowed table 'events'
    resp = client.post("/v1/route", json={"sql": "SELECT count(*) FROM events GROUP BY type"})
    assert resp.status_code == 200
    assert resp.json()["target"] == "clickhouse"
    assert resp.json()["catalog_checked"] is True

    # Pinned table 'sensitive_data'
    resp = client.post(
        "/v1/route",
        json={"sql": "SELECT count(*) FROM sensitive_data GROUP BY cat"},
    )
    assert resp.status_code == 200
    assert resp.json()["target"] == "postgresql"
    assert resp.json()["reason_code"] == "TABLE_PG_PINNED"
    log_pass("ServerSettings configuration instantiates and enforces TableCatalog correctly")


def test_server_httpx_async_client() -> None:
    log_step("1.5 FastAPI Server: AsyncClient (httpx.AsyncClient) Testing")

    async def _async_runner() -> None:
        catalog = TableCatalog(allowed_tables=["orders"], pg_only_tables=["returns"])
        app = create_app(catalog=catalog)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. Allowed table
            r1 = await client.post(
                "/v1/route",
                json={"sql": "SELECT status, count(*) FROM orders GROUP BY status"},
            )
            assert r1.status_code == 200
            assert r1.json()["target"] == "clickhouse"
            assert r1.json()["catalog_checked"] is True
            assert r1.json()["reason_code"] == "ANALYTICAL_CLICKHOUSE"

            # 2. Pinned table
            r2 = await client.post(
                "/v1/route",
                json={"sql": "SELECT reason, count(*) FROM returns GROUP BY reason"},
            )
            assert r2.status_code == 200
            assert r2.json()["target"] == "postgresql"
            assert r2.json()["reason_code"] == "TABLE_PG_PINNED"

            # 3. Uncataloged table
            r3 = await client.post(
                "/v1/route",
                json={"sql": "SELECT id, count(*) FROM invoices GROUP BY id"},
            )
            assert r3.status_code == 200
            assert r3.json()["target"] == "postgresql"
            assert r3.json()["reason_code"] == "TABLE_NOT_IN_CATALOG"

    asyncio.run(_async_runner())
    log_pass("httpx.AsyncClient successfully executed and verified async route requests")


def test_server_adversarial_and_boundary_cases() -> None:
    log_step("1.6 FastAPI Server: Adversarial, Error Handling & Zero Unhandled Exceptions")
    app = create_app()
    client = TestClient(app)

    # Case 1: Empty SQL string -> 422 Unprocessable Entity
    resp = client.post("/v1/route", json={"sql": ""})
    assert resp.status_code == 422, f"Expected 422 for empty SQL, got {resp.status_code}"
    log_pass("Empty string handled gracefully with HTTP 422")

    # Case 2: Whitespace-only string -> 400 Bad Request
    resp = client.post("/v1/route", json={"sql": "   \n\t  "})
    assert resp.status_code == 400, f"Expected 400 for whitespace SQL, got {resp.status_code}"
    assert resp.json()["error"] == "SQLParsingError"
    log_pass("Whitespace-only SQL handled gracefully with HTTP 400 SQLParsingError")

    # Case 3: Malformed SQL syntax -> 400 Bad Request
    resp = client.post("/v1/route", json={"sql": "SELECT FROM WHERE GROUP"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "SQLParsingError"
    log_pass("Malformed SQL syntax handled gracefully with HTTP 400 SQLParsingError")

    # Case 4: Multi-statement SQL injection attempt -> 400 Bad Request
    resp = client.post(
        "/v1/route",
        json={"sql": "SELECT count(*) FROM orders GROUP BY 1; DROP TABLE orders;"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "SQLParsingError"
    assert "несколько SQL-инструкций" in resp.json()["message"]
    log_pass("Multi-statement SQL injection attempt rejected with HTTP 400 SQLParsingError")

    # Case 5: Zero-table query with catalog enabled
    cat = TableCatalog(allowed_tables=["orders"])
    app_cat = create_app(catalog=cat)
    client_cat = TestClient(app_cat)

    resp = client_cat.post("/v1/route", json={"sql": "SELECT 1 GROUP BY 1"})
    assert resp.status_code == 200
    d = resp.json()
    assert d["target"] == "postgresql"
    assert d["reason_code"] == "NO_PHYSICAL_TABLES"
    assert d["physical_tables"] == []
    log_pass("Zero-table analytical query safely routed to PostgreSQL with NO_PHYSICAL_TABLES")

    # Case 6: Empty catalog blocking ClickHouse
    empty_cat = TableCatalog(allowed_tables=[])
    app_empty = create_app(catalog=empty_cat)
    client_empty = TestClient(app_empty)

    resp = client_empty.post(
        "/v1/route",
        json={"sql": "SELECT status, count(*) FROM orders GROUP BY status"},
    )
    assert resp.status_code == 200
    d = resp.json()
    assert d["target"] == "postgresql"
    assert d["reason_code"] == "TABLE_NOT_IN_CATALOG"
    log_pass("Empty catalog strictly blocks routing to ClickHouse")


# ---------------------------------------------------------------------------
# SECTION 2: BatchAnalyzer (AnalyzeAllSql) Verification
# ---------------------------------------------------------------------------


def test_batch_analyzer_five_diverse_queries() -> None:
    log_step("2.1 BatchAnalyzer: 5 Diverse Queries with TableCatalog Configured")
    catalog = TableCatalog(
        allowed_tables=["orders", "order_items"],
        pg_only_tables=["returns"],
    )

    diverse_queries = [
        # Query 1: Simple OLTP point lookup
        "SELECT id, total_amount FROM orders WHERE id = 123",
        # Query 2: Analytical report on allowed table
        "SELECT status, count(*), sum(total_amount) FROM orders GROUP BY status",
        # Query 3: Heavy JOIN query (3 JOIN operations) with uncataloged tables
        (
            "SELECT o.id, c.name, p.title, s.company "
            "FROM orders o "
            "JOIN order_items oi ON o.id = oi.order_id "
            "JOIN products p ON oi.product_id = p.id "
            "JOIN suppliers s ON p.supplier_id = s.id "
            "GROUP BY o.id, c.name, p.title, s.company"
        ),
        # Query 4: CTE chain + Window function on allowed table
        (
            "WITH ranked_orders AS ("
            "  SELECT id, customer_id, total_amount, "
            "         row_number() OVER (PARTITION BY customer_id ORDER BY created_at DESC) as rn "
            "  FROM orders"
            "), "
            "filtered_orders AS ("
            "  SELECT * FROM ranked_orders WHERE rn <= 3"
            ") "
            "SELECT customer_id, avg(total_amount) FROM filtered_orders GROUP BY customer_id"
        ),
        # Query 5: Pinned table analytical query
        "SELECT reason, count(*) FROM returns GROUP BY reason",
    ]

    analyzer = AnalyzeAllSql(queries=diverse_queries, catalog=catalog)
    summary: BatchAuditSummary = analyzer.analyze()

    assert summary.total_queries == 5, f"Expected 5 queries, got {summary.total_queries}"
    assert summary.clickhouse_count == 2
    assert summary.postgres_count == 3

    # Detailed item checks
    # Item 1: OLTP
    item1 = summary.items[0]
    assert item1.decision.target == "postgresql"
    assert item1.decision.is_analytical is False
    assert item1.decision.reason_code == "NON_ANALYTICAL_QUERY"
    assert item1.bottlenecks == []
    log_pass("Query 1 (OLTP): PostgreSQL / NON_ANALYTICAL_QUERY / 0 bottlenecks")

    # Item 2: Analytical orders -> ClickHouse
    item2 = summary.items[1]
    assert item2.decision.target == "clickhouse"
    assert item2.decision.is_analytical is True
    assert item2.decision.catalog_checked is True
    assert item2.decision.reason_code == "ANALYTICAL_CLICKHOUSE"
    assert item2.decision.physical_tables == ["orders"]
    log_pass("Query 2 (Agg on orders): ClickHouse / ANALYTICAL_CLICKHOUSE / catalog_checked=True")

    # Item 3: Heavy JOIN with uncataloged tables -> PostgreSQL
    item3 = summary.items[2]
    assert item3.decision.target == "postgresql"
    assert item3.decision.reason_code == "TABLE_NOT_IN_CATALOG"
    assert "products" in item3.decision.reason or "suppliers" in item3.decision.reason
    assert any("Heavy JOIN: 3 JOIN operations" in b for b in item3.bottlenecks)
    log_pass("Query 3 (Heavy JOIN): PostgreSQL / TABLE_NOT_IN_CATALOG / Heavy JOIN (3 operations)")

    # Item 4: CTE Chain + Window function on orders -> ClickHouse
    item4 = summary.items[3]
    assert item4.decision.target == "clickhouse"
    assert item4.decision.reason_code == "ANALYTICAL_CLICKHOUSE"
    assert item4.decision.physical_tables == ["orders"]
    assert any("Multiple CTE chain: 2 CTEs" in b for b in item4.bottlenecks)
    assert any("Window functions: 1" in b for b in item4.bottlenecks)
    log_pass("Query 4 (CTE+Window): ClickHouse / ANALYTICAL_CLICKHOUSE / CTE & Window detected")

    # Item 5: Pinned returns -> PostgreSQL
    item5 = summary.items[4]
    assert item5.decision.target == "postgresql"
    assert item5.decision.reason_code == "TABLE_PG_PINNED"
    assert "returns" in item5.decision.reason
    log_pass("Query 5 (Pinned returns): PostgreSQL / TABLE_PG_PINNED / catalog_checked=True")

    # Verify summary counters
    assert "Heavy JOIN" in summary.bottleneck_detected
    assert "Multiple CTE chain" in summary.bottleneck_detected
    assert "Window functions" in summary.bottleneck_detected
    log_pass("BatchAuditSummary counters correctly aggregated all bottlenecks")


def test_batch_analyzer_adversarial_and_stress() -> None:
    log_step("2.2 BatchAnalyzer: Edge Cases, Input Validation & HTML Dashboard Generation")

    # 1. Empty queries list raises ValueError
    try:
        AnalyzeAllSql.from_list([])
        raise VerificationFailure("AnalyzeAllSql.from_list([]) did not raise ValueError")
    except ValueError as e:
        assert "Список запросов пуст" in str(e)
        log_pass("AnalyzeAllSql.from_list([]) properly raised ValueError")

    # 2. Nonexistent file raises FileNotFoundError
    try:
        AnalyzeAllSql.from_file("definitely_non_existent_file_12345.sql")
        raise VerificationFailure("AnalyzeAllSql.from_file did not raise FileNotFoundError")
    except FileNotFoundError:
        log_pass("AnalyzeAllSql.from_file non-existent file raised FileNotFoundError")

    # 3. Nested subqueries bottleneck detection
    nested_query = (
        "SELECT * FROM ("
        "  SELECT id, count(*) FROM ("
        "    SELECT id FROM orders"
        "  ) sub1 GROUP BY id"
        ") sub2"
    )
    catalog = TableCatalog(allowed_tables=["orders"])
    analyzer = AnalyzeAllSql([nested_query], catalog=catalog)
    summary = analyzer.analyze()
    assert any("Deep nested subqueries: 2" in b for b in summary.items[0].bottlenecks)
    log_pass("Deep nested subqueries bottleneck correctly detected (count=2)")

    # 4. HTML generation with catalog report
    html = analyzer.to_html(title="Challenger 2 Verification Report")
    assert "<!DOCTYPE html>" in html
    assert "Challenger 2 Verification Report" in html
    assert "orders" in html
    log_pass("HTML report successfully generated from batch analysis")

    # 5. Stress test: Batch of 50 varied queries executed in under 2 seconds
    stress_queries = []
    for i in range(25):
        stress_queries.append(f"SELECT status, count(*) FROM orders WHERE id > {i} GROUP BY status")
        stress_queries.append(f"SELECT id, total_amount FROM orders WHERE id = {i}")

    t0 = time.perf_counter()
    stress_analyzer = AnalyzeAllSql(stress_queries, catalog=catalog)
    stress_summary = stress_analyzer.analyze()
    t_elapsed = time.perf_counter() - t0

    assert stress_summary.total_queries == 50
    assert stress_summary.clickhouse_count == 25
    assert stress_summary.postgres_count == 25
    assert t_elapsed < 2.0, f"50 queries took too long: {t_elapsed:.2f}s"
    log_pass(
        f"Stress test: 50 queries analyzed in {t_elapsed * 1000:.1f}ms without errors or leaks"
    )


# ---------------------------------------------------------------------------
# MAIN HARNESS
# ---------------------------------------------------------------------------


def main() -> None:
    print("=" * 70)
    print("Milestone 2 Adversarial Challenger 2 Test Suite")
    print("Target: FastAPI Server (/v1/route) & BatchAnalyzer (AnalyzeAllSql)")
    print("=" * 70)

    start_time = time.perf_counter()
    tests = [
        test_server_no_catalog_routes_analytical_to_clickhouse,
        test_server_with_catalog_orders_admission,
        test_server_full_response_body_schema,
        test_server_settings_configuration,
        test_server_httpx_async_client,
        test_server_adversarial_and_boundary_cases,
        test_batch_analyzer_five_diverse_queries,
        test_batch_analyzer_adversarial_and_stress,
    ]

    failed = 0
    passed = 0
    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception:
            failed += 1
            print(f"\n[FAIL] {test_fn.__name__} FAILED with exception:")
            traceback.print_exc()

    total_time = time.perf_counter() - start_time
    print("\n" + "=" * 70)
    print(f"VERIFICATION SUMMARY: {passed} PASSED, {failed} FAILED (Total time: {total_time:.2f}s)")
    print("=" * 70)

    if failed > 0:
        print("\nOVERALL VERDICT: DISPROVE (REQUEST_CHANGES)")
        sys.exit(1)
    else:
        print("\nOVERALL VERDICT: CONFIRM CORRECTNESS (APPROVE)")
        sys.exit(0)


if __name__ == "__main__":
    main()
