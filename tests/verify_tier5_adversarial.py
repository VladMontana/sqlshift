"""Tier 5 Comprehensive Adversarial Verification Harness.

Executes white-box stress testing, edge-case probing, and empirical bug reproduction
across SQLShift core, client, server, and CLI components.
"""

import sys
import time
from typing import Any

from fastapi.testclient import TestClient

from sqlshift.client.async_client import AsyncSQLShiftClient
from sqlshift.core.catalog import TableCatalog, extract_physical_tables
from sqlshift.core.parser import parse_sql
from sqlshift.core.router import SQLShiftRouter
from sqlshift.server.app import create_app
from sqlshift.utils.exception import SQLParsingError


class AdversarialTestRunner:
    def __init__(self) -> None:
        self.passed: int = 0
        self.failed: int = 0
        self.results: list[dict[str, Any]] = []

    def record(self, name: str, category: str, success: bool, details: str) -> None:
        if success:
            self.passed += 1
            status = "PASS"
        else:
            self.failed += 1
            status = "FAIL"
        self.results.append({
            "name": name,
            "category": category,
            "status": status,
            "details": details,
        })
        print(f"[{status}] {category} :: {name} -> {details}")

    def run_all(self) -> None:
        print("=" * 80)
        print("SQLShift Tier 5 Adversarial Verification Harness Starting")
        print("=" * 80)

        self.test_category_1_deep_nested_ctes()
        self.test_category_2_scope_conflicts_and_shadowing()
        self.test_category_3_schema_casing_and_quoting()
        self.test_category_4_extreme_query_scaling()
        self.test_category_5_weird_spacing_and_comments()
        self.test_category_6_api_and_client_resilience()
        self.test_category_7_empirical_vulnerabilities()

        total = self.passed + self.failed
        print("=" * 80)
        print(
            f"Verification Completed: {self.passed} PASSED, {self.failed} FAILED (Total: {total})"
        )
        print("=" * 80)

    # -------------------------------------------------------------------------
    # Category 1: Deep Nested CTE Chains
    # -------------------------------------------------------------------------
    def test_category_1_deep_nested_ctes(self) -> None:
        cat = TableCatalog(allowed_tables=["orders", "users", "items", "stores"])
        router = SQLShiftRouter(catalog=cat)

        # 1.1: 3-level CTE chain
        sql_3 = """
        WITH
          c1 AS (SELECT id, amount, user_id FROM orders WHERE amount > 100),
          c2 AS (SELECT c1.id, c1.amount, u.name FROM c1 JOIN users u ON c1.user_id = u.id),
          c3 AS (SELECT name, sum(amount) as s FROM c2 GROUP BY name)
        SELECT * FROM c3 WHERE s > 500;
        """
        dec_3 = router.route(sql_3)
        self.record(
            "3-level CTE chain",
            "Cat 1: Nested CTEs",
            dec_3.target == "clickhouse" and dec_3.physical_tables == ["orders", "users"],
            f"target={dec_3.target}, tables={dec_3.physical_tables}",
        )

        # 1.2: 5-level CTE chain
        sql_5 = """
        WITH
          c1 AS (SELECT id, amount, user_id FROM orders),
          c2 AS (SELECT user_id, sum(amount) as total FROM c1 GROUP BY user_id),
          c3 AS (SELECT c2.user_id, c2.total, u.name FROM c2 JOIN users u ON c2.user_id = u.id),
          c4 AS (SELECT c3.name, c3.total, i.price FROM c3 JOIN items i ON c3.user_id = i.id),
          c5 AS (SELECT name, avg(price) as avg_p FROM c4 GROUP BY name)
        SELECT * FROM c5;
        """
        dec_5 = router.route(sql_5)
        self.record(
            "5-level CTE chain",
            "Cat 1: Nested CTEs",
            dec_5.target == "clickhouse"
            and dec_5.physical_tables == ["items", "orders", "users"],
            f"target={dec_5.target}, tables={dec_5.physical_tables}",
        )

        # 1.3: Recursive CTE
        sql_rec = """
        WITH RECURSIVE subordinates AS (
            SELECT id, manager_id FROM users WHERE manager_id IS NULL
            UNION ALL
            SELECT u.id, u.manager_id FROM users u JOIN subordinates s ON u.manager_id = s.id
        )
        SELECT count(*) FROM subordinates;
        """
        dec_rec = router.route(sql_rec)
        self.record(
            "Recursive CTE self-reference",
            "Cat 1: Nested CTEs",
            dec_rec.target == "clickhouse" and dec_rec.physical_tables == ["users"],
            f"target={dec_rec.target}, tables={dec_rec.physical_tables}",
        )

    # -------------------------------------------------------------------------
    # Category 2: Conflicting Table Names & Subquery Scope Shadowing
    # -------------------------------------------------------------------------
    def test_category_2_scope_conflicts_and_shadowing(self) -> None:
        cat = TableCatalog(
            allowed_tables=["orders", "users", "raw_users", "backup_users"]
        )
        router = SQLShiftRouter(catalog=cat)

        # 2.1: CTE shadows real physical table name
        sql_shadow = """
        WITH orders AS (SELECT id, name FROM raw_users)
        SELECT count(*) FROM orders;
        """
        dec_shadow = router.route(sql_shadow)
        self.record(
            "CTE shadows physical table name",
            "Cat 2: Scope Conflicts",
            dec_shadow.target == "clickhouse" and dec_shadow.physical_tables == ["raw_users"],
            f"target={dec_shadow.target}, tables={dec_shadow.physical_tables}",
        )

        # 2.2: Nested subquery CTE shadowing outer CTE
        sql_nested_shadow = """
        WITH users AS (SELECT * FROM raw_users)
        SELECT count(*) FROM (
            WITH users AS (SELECT * FROM backup_users)
            SELECT * FROM users
        ) sub JOIN users ON sub.id = users.id;
        """
        dec_nested_shadow = router.route(sql_nested_shadow)
        self.record(
            "Nested subquery CTE shadows outer CTE",
            "Cat 2: Scope Conflicts",
            dec_nested_shadow.target == "clickhouse"
            and dec_nested_shadow.physical_tables == ["backup_users", "raw_users"],
            f"target={dec_nested_shadow.target}, tables={dec_nested_shadow.physical_tables}",
        )

        # 2.3: Derived table alias matches physical table
        sql_alias_match = """
        SELECT count(*) FROM users AS orders JOIN orders ON users.id = orders.id;
        """
        dec_alias_match = router.route(sql_alias_match)
        self.record(
            "Table alias matches physical table name",
            "Cat 2: Scope Conflicts",
            dec_alias_match.target == "clickhouse"
            and dec_alias_match.physical_tables == ["orders", "users"],
            f"target={dec_alias_match.target}, tables={dec_alias_match.physical_tables}",
        )

        # 2.4: CTE named 'orders' joined with schema-qualified 'public.orders'
        sql_schema_cte = """
        WITH orders AS (SELECT * FROM raw_users)
        SELECT count(*) FROM orders JOIN public.orders ON orders.id = public.orders.id;
        """
        dec_schema_cte = router.route(sql_schema_cte)
        self.record(
            "CTE name conflicts with schema-qualified physical table",
            "Cat 2: Scope Conflicts",
            dec_schema_cte.target == "clickhouse"
            and dec_schema_cte.physical_tables == ["public.orders", "raw_users"],
            f"target={dec_schema_cte.target}, tables={dec_schema_cte.physical_tables}",
        )

    # -------------------------------------------------------------------------
    # Category 3: Schema Casing and Quoting
    # -------------------------------------------------------------------------
    def test_category_3_schema_casing_and_quoting(self) -> None:
        cat_ci = TableCatalog(
            allowed_tables=["orders", "archive.sales", "order items"],
            case_sensitive=False,
        )
        r_ci = SQLShiftRouter(catalog=cat_ci)

        # 3.1: Double quoted schema and table
        dec_q = r_ci.route('SELECT count(*) FROM "Public"."Orders";')
        self.record(
            "Quoted casing 'Public.Orders' case-insensitive",
            "Cat 3: Casing & Quoting",
            dec_q.target == "clickhouse" and dec_q.reason_code == "ANALYTICAL_CLICKHOUSE",
            f"target={dec_q.target}, code={dec_q.reason_code}",
        )

        # 3.2: Table name with spaces in quotes
        dec_space = r_ci.route('SELECT count(*) FROM "order items";')
        self.record(
            "Table name with whitespace in quotes 'order items'",
            "Cat 3: Casing & Quoting",
            dec_space.target == "clickhouse" and dec_space.reason_code == "ANALYTICAL_CLICKHOUSE",
            f"target={dec_space.target}, code={dec_space.reason_code}",
        )

        # 3.3: Case sensitive catalog rejects mismatch
        cat_cs = TableCatalog(allowed_tables=["orders"], case_sensitive=True)
        r_cs = SQLShiftRouter(catalog=cat_cs)
        dec_cs = r_cs.route('SELECT count(*) FROM "Orders";')
        self.record(
            "Case-sensitive catalog rejects 'Orders' when only 'orders' allowed",
            "Cat 3: Casing & Quoting",
            dec_cs.target == "postgresql" and dec_cs.reason_code == "TABLE_NOT_IN_CATALOG",
            f"target={dec_cs.target}, code={dec_cs.reason_code}",
        )

    # -------------------------------------------------------------------------
    # Category 4: Extreme Query Scaling
    # -------------------------------------------------------------------------
    def test_category_4_extreme_query_scaling(self) -> None:
        all_tables = ["orders"] + [f"t{i}" for i in range(50)]
        cat = TableCatalog(allowed_tables=all_tables)
        router = SQLShiftRouter(catalog=cat)

        # 4.1: 50 JOINs
        joins = " ".join(f"JOIN t{i} ON orders.id = t{i}.id" for i in range(50))
        sql_50_joins = f"SELECT count(*) FROM orders {joins};"
        t0 = time.perf_counter()
        dec_joins = router.route(sql_50_joins)
        dt_joins = time.perf_counter() - t0
        self.record(
            "50 JOIN operations query",
            "Cat 4: Scaling & Stress",
            dec_joins.target == "clickhouse"
            and len(dec_joins.physical_tables) == 51
            and dt_joins < 0.5,
            f"tables_len={len(dec_joins.physical_tables)}, latency={dt_joins*1000:.1f}ms",
        )

        # 4.2: 50 CTEs chain
        ctes_list = [
            "c0 AS (SELECT id, amount FROM orders)"
            if i == 0
            else f"c{i} AS (SELECT id, amount FROM c{i-1})"
            for i in range(50)
        ]
        sql_50_ctes = f"WITH {', '.join(ctes_list)} SELECT count(*), sum(amount) FROM c49;"
        t0 = time.perf_counter()
        dec_ctes = router.route(sql_50_ctes)
        dt_ctes = time.perf_counter() - t0
        self.record(
            "50 chained CTEs",
            "Cat 4: Scaling & Stress",
            dec_ctes.target == "clickhouse"
            and dec_ctes.physical_tables == ["orders"]
            and dt_ctes < 0.5,
            f"tables={dec_ctes.physical_tables}, latency={dt_ctes*1000:.1f}ms",
        )

        # 4.3: 1,000 IN items
        in_list = ", ".join(str(i) for i in range(1000))
        sql_in = f"SELECT count(*) FROM orders WHERE id IN ({in_list});"
        t0 = time.perf_counter()
        dec_in = router.route(sql_in)
        dt_in = time.perf_counter() - t0
        self.record(
            "1,000 IN items",
            "Cat 4: Scaling & Stress",
            dec_in.target == "clickhouse" and dt_in < 0.5,
            f"latency={dt_in*1000:.1f}ms",
        )

        # 4.4: 20-level nested subqueries
        nested = "orders"
        for i in range(20):
            nested = f"(SELECT * FROM {nested} AS s_{i})"
        sql_nested = f"SELECT count(*) FROM {nested} AS final;"
        t0 = time.perf_counter()
        dec_nested = router.route(sql_nested)
        dt_nested = time.perf_counter() - t0
        self.record(
            "20-level nested subqueries",
            "Cat 4: Scaling & Stress",
            dec_nested.target == "clickhouse"
            and dec_nested.physical_tables == ["orders"]
            and dt_nested < 0.5,
            f"tables={dec_nested.physical_tables}, latency={dt_nested*1000:.1f}ms",
        )

    # -------------------------------------------------------------------------
    # Category 5: Weird Spacing, Comments, and Newlines
    # -------------------------------------------------------------------------
    def test_category_5_weird_spacing_and_comments(self) -> None:
        cat = TableCatalog(allowed_tables=["orders"])
        router = SQLShiftRouter(catalog=cat)

        # 5.1: Windows CRLF and tabs
        sql_crlf = "SELECT\r\n\tcount(*)\r\nFROM\r\n\torders\r\nWHERE\r\n\tstatus = 'ok';"
        dec_crlf = router.route(sql_crlf)
        self.record(
            "Windows CRLF and tabs formatting",
            "Cat 5: Spacing & Comments",
            dec_crlf.target == "clickhouse" and dec_crlf.physical_tables == ["orders"],
            f"target={dec_crlf.target}, tables={dec_crlf.physical_tables}",
        )

        # 5.2: Semicolon inside string literal
        sql_semi_str = (
            "SELECT count(*), 'hello; world; SELECT * FROM users;' AS col FROM orders;"
        )
        dec_semi_str = router.route(sql_semi_str)
        self.record(
            "Semicolon inside string literal",
            "Cat 5: Spacing & Comments",
            dec_semi_str.target == "clickhouse" and dec_semi_str.physical_tables == ["orders"],
            f"target={dec_semi_str.target}, tables={dec_semi_str.physical_tables}",
        )

        # 5.3: Comments-only input rejected
        comments_caught = False
        try:
            parse_sql("-- just a comment\n/* block comment */")
        except SQLParsingError:
            comments_caught = True
        self.record(
            "Comments-only input safely rejected",
            "Cat 5: Spacing & Comments",
            comments_caught,
            "SQLParsingError raised",
        )

        # 5.4: Semicolon in line comment
        sql_comment_semi = "SELECT count(*) FROM orders WHERE id = 1; -- ; DROP TABLE orders;"
        dec_comment_semi = router.route(sql_comment_semi)
        self.record(
            "Semicolon inside trailing line comment",
            "Cat 5: Spacing & Comments",
            dec_comment_semi.target == "clickhouse"
            and dec_comment_semi.physical_tables == ["orders"],
            f"target={dec_comment_semi.target}, tables={dec_comment_semi.physical_tables}",
        )

    # -------------------------------------------------------------------------
    # Category 6: API and Client Resilience
    # -------------------------------------------------------------------------
    def test_category_6_api_and_client_resilience(self) -> None:
        app = create_app(catalog=TableCatalog(allowed_tables=["orders"]))
        client = TestClient(app)

        # 6.1: FastAPI 422 on empty string
        res_empty = client.post("/v1/route", json={"sql": ""})
        self.record(
            "FastAPI /v1/route 422 on empty string",
            "Cat 6: API & Client",
            res_empty.status_code == 422,
            f"status={res_empty.status_code}",
        )

        # 6.2: FastAPI 400 on multi-statement
        res_multi = client.post("/v1/route", json={"sql": "SELECT 1; DROP TABLE orders;"})
        self.record(
            "FastAPI /v1/route 400 on multi-statement",
            "Cat 6: API & Client",
            res_multi.status_code == 400 and res_multi.json().get("error") == "SQLParsingError",
            f"status={res_multi.status_code}, error={res_multi.json().get('error')}",
        )

        # 6.3: FastAPI 503 on /query without database connection
        res_query_no_db = client.post("/v1/query", json={"sql": "SELECT 1;"})
        self.record(
            "FastAPI /v1/query 503 when DB client not configured",
            "Cat 6: API & Client",
            res_query_no_db.status_code == 503,
            f"status={res_query_no_db.status_code}",
        )

        # 6.4: AsyncSQLShiftClient constructor & close without connect
        import asyncio

        async def run_client_lifecycle() -> bool:
            c = AsyncSQLShiftClient(
                pg_dsn="postgresql://localhost/db",
                ch_dsn="clickhouse://localhost/db",
            )
            await c.close()  # closing uninitialized client should not crash
            return True

        safe_lifecycle = asyncio.run(run_client_lifecycle())
        self.record(
            "AsyncSQLShiftClient safe lifecycle without connect",
            "Cat 6: API & Client",
            safe_lifecycle,
            "closed cleanly without exceptions",
        )

    # -------------------------------------------------------------------------
    # Category 7: Empirical Vulnerabilities (White-Box Bugs Exposed)
    # -------------------------------------------------------------------------
    def test_category_7_empirical_vulnerabilities(self) -> None:
        cat = TableCatalog(allowed_tables=["orders"])
        router = SQLShiftRouter(catalog=cat)

        # 7.1: Vulnerability A - Comment leakage on table AST node
        # In SQL: "SELECT count(*) FROM orders -- check\nWHERE status = 'ok';"
        # Bug: extract_physical_tables outputs ['orders /* check */']
        # Consequence: TableCatalog fails with TABLE_NOT_IN_CATALOG, routing to PostgreSQL!
        sql_comment_on_table = "SELECT count(*) FROM orders -- check\nWHERE status = 'ok';"
        tree_vuln_a = parse_sql(sql_comment_on_table)
        tables_vuln_a = extract_physical_tables(tree_vuln_a)
        dec_vuln_a = router.route(sql_comment_on_table)

        has_comment_leak = any("/*" in t or "--" in t for t in tables_vuln_a)
        self.record(
            "Vulnerability A: Comment leakage into table name string",
            "Cat 7: Empirical Bugs",
            not has_comment_leak,  # PASS if bug is fixed, FAIL if bug is present
            f"tables={tables_vuln_a}, target={dec_vuln_a.target}, code={dec_vuln_a.reason_code}",
        )

        # 7.2: Vulnerability B - Modifying CTE in subquery masked by top read-only CTE
        # Bug: router.py only checks tree.find(exp.With). The first WITH has no DML.
        # Consequence: DELETE statement routes to ClickHouse (ANALYTICAL_CLICKHOUSE)!
        sql_vuln_b = """
        WITH valid_cte AS (SELECT 1 AS x)
        SELECT * FROM (
            WITH modifying_cte AS (DELETE FROM orders WHERE id = 1 RETURNING id)
            SELECT * FROM modifying_cte
        ) sub;
        """
        router_no_cat = SQLShiftRouter()
        dec_vuln_b = router_no_cat.route(sql_vuln_b)

        routes_to_postgres = (
            dec_vuln_b.target == "postgresql" and dec_vuln_b.reason_code == "DML_OPERATION"
        )
        self.record(
            "Vulnerability B: Modifying CTE in subquery masked by read-only top CTE",
            "Cat 7: Empirical Bugs",
            routes_to_postgres,  # PASS if routed to postgres DML, FAIL if routed to ClickHouse
            (
                f"target={dec_vuln_b.target}, code={dec_vuln_b.reason_code}, "
                f"reason={dec_vuln_b.reason}"
            ),
        )


if __name__ == "__main__":
    runner = AdversarialTestRunner()
    runner.run_all()
    if runner.failed > 0:
        print(f"\n[ALERT] Tier 5 Hardener discovered {runner.failed} critical failure modes!")
        sys.exit(1)
    else:
        print("\n[SUCCESS] All Tier 5 checks confirmed clean.")
        sys.exit(0)
