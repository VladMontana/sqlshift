"""Adversarial Verification Suite for SQLShift Milestone 1.

Empirical verification harness testing:
1. Deeply nested subqueries (5+ levels with conflicting aliases, WHERE/SELECT subqueries)
2. CTEs that shadow real table names and vice-versa
3. Chained CTEs (cte1 -> cte2 -> cte3 -> main query)
4. Mixed quoted identifiers ("Orders", "public"."orders", public."ORDERS", etc.)
5. Complex multi-JOINs (3+ tables with mixed ON clauses, subquery joins, cross joins)
6. Queries with comments, strange whitespace, unicode characters
7. Multi-statement attack queries (SQL injection attempts, multiple statements, semicolons)
8. Extreme queries without tables (SELECT 1, CURRENT_DATE, version(), etc.)
9. Dangerous constructs: Locking reads (FOR UPDATE), Modifying CTEs (DML in WITH)
10. Property-based stress generator testing catalog invariants across 150+ random query variations
"""

import random
import sys
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass

from sqlshift.core.catalog import TableCatalog, extract_physical_tables
from sqlshift.core.parser import parse_sql
from sqlshift.core.router import SQLShiftRouter
from sqlshift.utils.exception import SQLParsingError


@dataclass
class TestCaseResult:
    category: str
    name: str
    query: str
    passed: bool
    details: str
    duration_ms: float


class AdversarialTestHarness:
    def __init__(self) -> None:
        self.results: list[TestCaseResult] = []
        self.total_tests = 0
        self.passed_tests = 0
        self.failed_tests = 0

    def record(
        self,
        category: str,
        name: str,
        query: str,
        passed: bool,
        details: str,
        duration_ms: float,
    ) -> None:
        self.total_tests += 1
        if passed:
            self.passed_tests += 1
        else:
            self.failed_tests += 1
        self.results.append(
            TestCaseResult(
                category=category,
                name=name,
                query=query.strip(),
                passed=passed,
                details=details,
                duration_ms=duration_ms,
            )
        )
        status = "PASS" if passed else "FAIL"
        if not passed:
            print(f"[{status}] {category}::{name} -> {details}")

    def run_case(
        self,
        category: str,
        name: str,
        query: str,
        check_fn: Callable[[], tuple[bool, str]],
    ) -> None:
        t0 = time.perf_counter_ns()
        try:
            passed, details = check_fn()
        except Exception as e:
            passed = False
            details = f"Unhandled Exception: {type(e).__name__}: {e}\n{traceback.format_exc()}"
        dt_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
        self.record(category, name, query, passed, details, dt_ms)


def run_all_tests() -> AdversarialTestHarness:
    harness = AdversarialTestHarness()
    cat_default = TableCatalog(
        allowed_tables=[
            "orders",
            "order_items",
            "products",
            "users",
            "accounts",
            "logs",
            "t1",
            "t2",
            "t3",
            "t4",
            "t5",
            "raw_orders",
            "archive_orders",
            "employees",
        ],
        pg_only_tables=["returns", "secret_keys", "audit_log"],
    )
    router_cat = SQLShiftRouter(catalog=cat_default)
    router_legacy = SQLShiftRouter(catalog=None)
    router_empty = SQLShiftRouter(catalog=TableCatalog(allowed_tables=[]))

    # =========================================================================
    # 1. Deeply Nested Subqueries
    # =========================================================================
    q_nest5 = (
        "SELECT * FROM ("
        "  SELECT * FROM ("
        "    SELECT * FROM ("
        "      SELECT * FROM ("
        "        SELECT * FROM orders t"
        "      ) t"
        "    ) t"
        "  ) t"
        ") t"
    )

    def test_nest5():
        dec = router_cat.route(q_nest5)
        if dec.physical_tables != ["orders"]:
            return False, f"Expected physical_tables=['orders'], got {dec.physical_tables}"
        if dec.target != "postgresql":
            return False, f"Expected postgresql, got {dec.target}"
        return True, "OK"

    harness.run_case("NestedSubqueries", "5_levels_same_alias", q_nest5, test_nest5)

    inner = "SELECT user_id, count(*) as cnt FROM orders t GROUP BY user_id"
    for _ in range(10):
        inner = f"SELECT * FROM ({inner}) t"
    q_nest10_olap = inner

    def test_nest10_olap():
        dec = router_cat.route(q_nest10_olap)
        if dec.physical_tables != ["orders"]:
            return False, f"Expected physical_tables=['orders'], got {dec.physical_tables}"
        if dec.target != "clickhouse":
            return False, f"Expected clickhouse target, got {dec.target}"
        if dec.reason_code != "ANALYTICAL_CLICKHOUSE":
            return False, f"Expected ANALYTICAL_CLICKHOUSE, got {dec.reason_code}"
        return True, "OK"

    harness.run_case(
        "NestedSubqueries", "10_levels_olap_aggregation", q_nest10_olap, test_nest10_olap
    )

    q_where_nest5 = (
        "SELECT * FROM orders WHERE id IN ("
        "  SELECT order_id FROM order_items WHERE product_id IN ("
        "    SELECT id FROM products WHERE user_id IN ("
        "      SELECT id FROM users WHERE account_id IN ("
        "        SELECT id FROM accounts WHERE balance > 1000"
        "      )"
        "    )"
        "  )"
        ")"
    )

    def test_where_nest5():
        dec = router_cat.route(q_where_nest5)
        expected = sorted(["orders", "order_items", "products", "users", "accounts"])
        if dec.physical_tables != expected:
            return False, f"Expected {expected}, got {dec.physical_tables}"
        return True, "OK"

    harness.run_case("NestedSubqueries", "5_levels_where_in", q_where_nest5, test_where_nest5)

    q_select_scalar = (
        "SELECT "
        "  (SELECT (SELECT (SELECT count(*) FROM logs) FROM users) FROM accounts) as deep_count, "
        "  orders.id "
        "FROM orders"
    )

    def test_select_scalar():
        dec = router_cat.route(q_select_scalar)
        expected = sorted(["orders", "logs", "users", "accounts"])
        if dec.physical_tables != expected:
            return False, f"Expected {expected}, got {dec.physical_tables}"
        if dec.target != "clickhouse":
            return False, f"Expected clickhouse, got {dec.target}"
        return True, "OK"

    harness.run_case(
        "NestedSubqueries", "nested_scalar_select_subqueries", q_select_scalar, test_select_scalar
    )

    q_nest_pg_pinned = (
        "SELECT * FROM (  SELECT * FROM (    SELECT * FROM returns r GROUP BY id  ) sub1) sub2"
    )

    def test_nest_pg_pinned():
        dec = router_cat.route(q_nest_pg_pinned)
        if dec.physical_tables != ["returns"]:
            return False, f"Expected ['returns'], got {dec.physical_tables}"
        if dec.target != "postgresql":
            return False, f"Expected postgresql, got {dec.target}"
        if dec.reason_code != "TABLE_PG_PINNED":
            return False, f"Expected TABLE_PG_PINNED, got {dec.reason_code}"
        return True, "OK"

    harness.run_case(
        "NestedSubqueries", "nested_subquery_with_pg_pinned", q_nest_pg_pinned, test_nest_pg_pinned
    )

    q_corr_exists = (
        "SELECT status, count(*) FROM orders "
        "WHERE EXISTS (SELECT 1 FROM returns WHERE returns.order_id = orders.id) "
        "GROUP BY status"
    )

    def test_corr_exists():
        dec = router_cat.route(q_corr_exists)
        expected = sorted(["orders", "returns"])
        if dec.physical_tables != expected:
            return False, f"Expected {expected}, got {dec.physical_tables}"
        if dec.target != "postgresql":
            return False, f"Expected postgresql, got {dec.target}"
        if dec.reason_code != "TABLE_PG_PINNED":
            return False, f"Expected TABLE_PG_PINNED, got {dec.reason_code}"
        return True, "OK"

    harness.run_case(
        "NestedSubqueries", "correlated_exists_pg_pinned", q_corr_exists, test_corr_exists
    )

    # =========================================================================
    # 2. CTE Shadowing
    # =========================================================================
    q_shadow_pure = "WITH orders AS (SELECT 1 AS id, 'anon' AS name) SELECT * FROM orders"

    def test_shadow_pure():
        dec = router_cat.route(q_shadow_pure)
        if dec.physical_tables != []:
            return False, f"Expected [], got {dec.physical_tables}"
        if dec.target != "postgresql":
            return False, f"Expected postgresql, got {dec.target}"
        return True, "OK"

    harness.run_case("CTEShadowing", "cte_shadows_real_table_pure", q_shadow_pure, test_shadow_pure)

    q_shadow_internal = "WITH orders AS (SELECT * FROM raw_orders) SELECT * FROM orders"

    def test_shadow_internal():
        dec = router_cat.route(q_shadow_internal)
        if dec.physical_tables != ["raw_orders"]:
            return False, f"Expected ['raw_orders'], got {dec.physical_tables}"
        return True, "OK"

    harness.run_case(
        "CTEShadowing",
        "cte_shadows_real_table_with_internal",
        q_shadow_internal,
        test_shadow_internal,
    )

    q_shadow_pinned = "WITH returns AS (SELECT 1 AS ret_id) SELECT * FROM returns GROUP BY ret_id"

    def test_shadow_pinned():
        dec = router_cat.route(q_shadow_pinned)
        if dec.physical_tables != []:
            return False, f"Expected [], got {dec.physical_tables}"
        if dec.target != "postgresql":
            return False, f"Expected postgresql, got {dec.target}"
        if dec.reason_code != "NO_PHYSICAL_TABLES":
            return False, f"Expected NO_PHYSICAL_TABLES, got {dec.reason_code}"
        return True, "OK"

    harness.run_case(
        "CTEShadowing", "cte_shadows_pg_pinned_table", q_shadow_pinned, test_shadow_pinned
    )

    q_cte_and_schema = "WITH t AS (SELECT 1 AS x) SELECT * FROM t JOIN public.t ON 1=1"

    def test_cte_and_schema():
        tree = parse_sql(q_cte_and_schema)
        tables = extract_physical_tables(tree)
        if tables != ["public.t"]:
            return False, f"Expected ['public.t'], got {tables}"
        return True, "OK"

    harness.run_case(
        "CTEShadowing", "cte_and_schema_qualified_same_name", q_cte_and_schema, test_cte_and_schema
    )

    q_rec_cte = (
        "WITH RECURSIVE subordinates AS ("
        "  SELECT id, manager_id FROM employees WHERE id = 1 "
        "  UNION ALL "
        "  SELECT e.id, e.manager_id FROM employees e JOIN subordinates s ON e.manager_id = s.id"
        ") SELECT * FROM subordinates"
    )

    def test_rec_cte():
        tree = parse_sql(q_rec_cte)
        tables = extract_physical_tables(tree)
        if tables != ["employees"]:
            return False, f"Expected ['employees'], got {tables}"
        return True, "OK"

    harness.run_case("CTEShadowing", "recursive_cte_self_reference", q_rec_cte, test_rec_cte)

    # =========================================================================
    # 3. Chained CTEs
    # =========================================================================
    q_chain5 = (
        "WITH "
        "cte1 AS (SELECT id, user_id FROM orders WHERE id > 100), "
        "cte2 AS (SELECT cte1.*, p.amount FROM cte1 JOIN products p ON cte1.id = p.id), "
        "cte3 AS (SELECT cte2.*, u.email FROM cte2 JOIN users u ON cte2.user_id = u.id), "
        "cte4 AS (SELECT cte3.*, a.balance FROM cte3 JOIN accounts a ON cte3.user_id = a.id), "
        "cte5 AS (SELECT user_id, sum(amount) as total_amt FROM cte4 GROUP BY user_id) "
        "SELECT * FROM cte5 WHERE total_amt > 500"
    )

    def test_chain5():
        dec = router_cat.route(q_chain5)
        expected = sorted(["orders", "products", "users", "accounts"])
        if dec.physical_tables != expected:
            return False, f"Expected {expected}, got {dec.physical_tables}"
        for cte_name in ["cte1", "cte2", "cte3", "cte4", "cte5"]:
            if cte_name in dec.physical_tables:
                return (
                    False,
                    f"CTE name '{cte_name}' leaked into physical_tables: {dec.physical_tables}",
                )
        if dec.target != "clickhouse":
            return False, f"Expected clickhouse, got {dec.target}"
        if dec.reason_code != "ANALYTICAL_CLICKHOUSE":
            return False, f"Expected ANALYTICAL_CLICKHOUSE, got {dec.reason_code}"
        return True, "OK"

    harness.run_case("ChainedCTEs", "5_step_cte_chain_with_joins", q_chain5, test_chain5)

    q_diamond = (
        "WITH "
        "cte1 AS (SELECT * FROM orders), "
        "cte2 AS (SELECT id, sum(price) as p FROM cte1 GROUP BY id), "
        "cte3 AS (SELECT id, count(*) as c FROM cte1 GROUP BY id), "
        "cte4 AS (SELECT cte2.id, p, c FROM cte2 JOIN cte3 ON cte2.id = cte3.id) "
        "SELECT * FROM cte4"
    )

    def test_diamond():
        dec = router_cat.route(q_diamond)
        if dec.physical_tables != ["orders"]:
            return False, f"Expected ['orders'], got {dec.physical_tables}"
        if dec.target != "clickhouse":
            return False, f"Expected clickhouse, got {dec.target}"
        return True, "OK"

    harness.run_case("ChainedCTEs", "diamond_cte_dag", q_diamond, test_diamond)

    # =========================================================================
    # 4. Mixed Quoted Identifiers & Case Sensitivity
    # =========================================================================
    test_cases_quoted = [
        ('SELECT * FROM "Orders"', ["orders"]),
        ('SELECT * FROM "public"."orders"', ["orders"]),
        ('SELECT * FROM public."ORDERS"', ["orders"]),
        ('SELECT * FROM "public"."ORDERS"', ["orders"]),
    ]
    for idx, (sql, _) in enumerate(test_cases_quoted, 1):

        def make_test_quoted(q):
            def check():
                dec = router_cat.route(q + " GROUP BY 1")
                if dec.target != "clickhouse":
                    return (
                        False,
                        f"Target expected clickhouse, got {dec.target}. Reason: {dec.reason}",
                    )
                return True, "OK"

            return check

        harness.run_case("QuotedIdentifiers", f"quote_variant_{idx}", sql, make_test_quoted(sql))

    cat_strict = TableCatalog(allowed_tables=['"Orders"'], case_sensitive=True)
    router_strict = SQLShiftRouter(catalog=cat_strict)

    def test_strict_match():
        dec1 = router_strict.route('SELECT * FROM "Orders" GROUP BY 1')
        if dec1.target != "clickhouse":
            return False, f"Expected clickhouse for exact match, got {dec1.target}"
        dec2 = router_strict.route('SELECT * FROM "orders" GROUP BY 1')
        if dec2.target != "postgresql" or dec2.reason_code != "TABLE_NOT_IN_CATALOG":
            return (
                False,
                f"Expected postgresql/TABLE_NOT_IN_CATALOG, got {dec2.target}/{dec2.reason_code}",
            )
        return True, "OK"

    harness.run_case(
        "QuotedIdentifiers", "strict_case_sensitivity", 'SELECT * FROM "Orders"', test_strict_match
    )

    q_reserved = (
        'SELECT "order".id FROM "order" JOIN "user" ON "order".user_id = "user".id GROUP BY 1'
    )

    def test_reserved():
        cat_res = TableCatalog(allowed_tables=['"order"', '"user"'])
        router_res = SQLShiftRouter(catalog=cat_res)
        dec = router_res.route(q_reserved)
        if dec.target != "clickhouse":
            return False, f"Expected clickhouse, got {dec.target}. Reason: {dec.reason}"
        return True, "OK"

    harness.run_case("QuotedIdentifiers", "reserved_keywords_quoted", q_reserved, test_reserved)

    # =========================================================================
    # 5. Complex Multi-JOINs
    # =========================================================================
    q_join5_grouped = (
        "SELECT o.id, u.email, p.amount, a.balance, l.message "
        "FROM orders o "
        "INNER JOIN users u ON o.user_id = u.id "
        "LEFT JOIN products p ON o.id = p.id "
        "RIGHT JOIN accounts a ON u.id = a.id "
        "FULL OUTER JOIN logs l ON o.id = l.id "
        "GROUP BY o.id, u.email, p.amount, a.balance, l.message"
    )

    def test_join5_grouped():
        dec = router_cat.route(q_join5_grouped)
        expected = sorted(["orders", "users", "products", "accounts", "logs"])
        if dec.physical_tables != expected:
            return False, f"Expected {expected}, got {dec.physical_tables}"
        if dec.target != "clickhouse":
            return False, f"Expected clickhouse, got {dec.target}"
        return True, "OK"

    harness.run_case(
        "ComplexMultiJoins",
        "5_table_joins_with_group",
        q_join5_grouped,
        test_join5_grouped,
    )

    q_join5_nogroup = (
        "SELECT o.id, u.email, p.amount, a.balance, l.message "
        "FROM orders o "
        "INNER JOIN users u ON o.user_id = u.id "
        "LEFT JOIN products p ON o.id = p.id "
        "RIGHT JOIN accounts a ON u.id = a.id "
        "FULL OUTER JOIN logs l ON o.id = l.id"
    )

    def test_join5_nogroup():
        dec = router_cat.route(q_join5_nogroup)
        expected = sorted(["orders", "users", "products", "accounts", "logs"])
        if dec.physical_tables != expected:
            return False, f"Expected {expected}, got {dec.physical_tables}"
        if dec.target != "clickhouse":
            return False, f"Expected clickhouse, got {dec.target}"
        if "4 JOIN" not in dec.reason:
            return False, f"Expected '4 JOIN' in reason, got {dec.reason}"
        return True, "OK"

    harness.run_case(
        "ComplexMultiJoins",
        "5_table_joins_wording",
        q_join5_nogroup,
        test_join5_nogroup,
    )

    q_join_pinned = (
        "SELECT o.id, r.reason "
        "FROM orders o "
        "JOIN products p ON o.id = p.id "
        "JOIN returns r ON o.id = r.id "
        "GROUP BY o.id, r.reason"
    )

    def test_join_pinned():
        dec = router_cat.route(q_join_pinned)
        expected = sorted(["orders", "products", "returns"])
        if dec.physical_tables != expected:
            return False, f"Expected {expected}, got {dec.physical_tables}"
        if dec.target != "postgresql":
            return False, f"Expected postgresql, got {dec.target}"
        if dec.reason_code != "TABLE_PG_PINNED":
            return False, f"Expected TABLE_PG_PINNED, got {dec.reason_code}"
        if "'returns'" not in dec.reason:
            return False, f"Expected 'returns' in reason, got {dec.reason}"
        return True, "OK"

    harness.run_case("ComplexMultiJoins", "join_with_pinned_table", q_join_pinned, test_join_pinned)

    q_subquery_join = (
        "SELECT o.id, sub.total "
        "FROM orders o "
        "JOIN (SELECT order_id, sum(price) as total FROM order_items GROUP BY order_id) sub "
        "ON o.id = sub.order_id"
    )

    def test_subquery_join():
        dec = router_cat.route(q_subquery_join)
        expected = sorted(["orders", "order_items"])
        if dec.physical_tables != expected:
            return False, f"Expected {expected}, got {dec.physical_tables}"
        if dec.target != "clickhouse":
            return False, f"Expected clickhouse, got {dec.target}"
        return True, "OK"

    harness.run_case(
        "ComplexMultiJoins", "subquery_join_aggregation", q_subquery_join, test_subquery_join
    )

    q_lateral = (
        "SELECT o.id, it.product_id "
        "FROM orders o, LATERAL (SELECT * FROM order_items i WHERE i.order_id = o.id) it "
        "GROUP BY o.id, it.product_id"
    )

    def test_lateral():
        dec = router_cat.route(q_lateral)
        expected = sorted(["orders", "order_items"])
        if dec.physical_tables != expected:
            return False, f"Expected {expected}, got {dec.physical_tables}"
        return True, "OK"

    harness.run_case("ComplexMultiJoins", "lateral_join", q_lateral, test_lateral)

    # =========================================================================
    # 6. Comments, Strange Whitespace, Unicode
    # =========================================================================
    q_comments = """
    -- Leading single-line comment
    /* Multi-line comment
       spanning multiple lines
       /* potentially nested? */
    */
    \r\n\t
    SELECT
        orders.id,   -- comment after column
        orders.status /* inline block */
    FROM orders
    WHERE orders.status = 'COMPLETED'
    GROUP BY orders.id, orders.status;
    -- trailing comment
    """

    def test_comments():
        dec = router_cat.route(q_comments)
        if dec.physical_tables != ["orders"]:
            return False, f"Expected ['orders'], got {dec.physical_tables}"
        if dec.target != "clickhouse":
            return False, f"Expected clickhouse, got {dec.target}"
        return True, "OK"

    harness.run_case("Formatting", "comments_and_whitespace", q_comments, test_comments)

    q_unicode = (
        "SELECT id, count(*) FROM orders WHERE description = 'Клиент 🌟 Тест 123' GROUP BY id"
    )

    def test_unicode():
        dec = router_cat.route(q_unicode)
        if dec.physical_tables != ["orders"]:
            return False, f"Expected ['orders'], got {dec.physical_tables}"
        if dec.target != "clickhouse":
            return False, f"Expected clickhouse, got {dec.target}"
        return True, "OK"

    harness.run_case("Formatting", "unicode_and_emojis", q_unicode, test_unicode)

    q_trailing_semis = "SELECT * FROM orders WHERE id = 1;;;"

    def test_trailing_semis():
        dec = router_cat.route(q_trailing_semis)
        if dec.physical_tables != ["orders"]:
            return False, f"Expected ['orders'], got {dec.physical_tables}"
        if dec.target != "postgresql":
            return False, f"Expected postgresql, got {dec.target}"
        return True, "OK"

    harness.run_case(
        "Formatting", "trailing_multiple_semicolons", q_trailing_semis, test_trailing_semis
    )

    # =========================================================================
    # 7. Multi-statement Attacks & SQL Injections
    # =========================================================================
    multi_statements = [
        ("classic_drop", "SELECT 1; DROP TABLE users;"),
        ("two_selects", "SELECT 1; SELECT 2;"),
        ("select_and_update", "SELECT * FROM orders; UPDATE orders SET id=1;"),
        ("semicolon_with_comment", "SELECT 1; -- comment\nSELECT 2;"),
        ("string_with_semicolon_and_second_stmt", "SELECT ';'; SELECT 2;"),
        ("only_semicolons", ";;;"),
        ("empty_whitespace", "   \n\t   "),
    ]
    for name, attack_sql in multi_statements:

        def make_test_multi(sql_str):
            def check():
                try:
                    router_cat.route(sql_str)
                    return False, "Expected SQLParsingError, but no error was raised!"
                except SQLParsingError as e:
                    return True, f"Cleanly raised SQLParsingError: {e}"
                except Exception as ex:
                    return False, f"Raised wrong exception {type(ex).__name__}: {ex}"

            return check

        harness.run_case("MultiStatementAttack", name, attack_sql, make_test_multi(attack_sql))

    # =========================================================================
    # 8. Extreme Queries Without Tables
    # =========================================================================
    no_table_queries = [
        ("scalar_constant", "SELECT 1", False),
        ("current_date_version", "SELECT CURRENT_DATE, version()", False),
        ("arithmetic", "SELECT 100 * 24 + 1 AS calc", False),
        ("aggregate_without_from", "SELECT count(*)", True),
        ("group_by_without_from", "SELECT 1 GROUP BY 1", True),
        ("having_without_from", "SELECT 1 HAVING 1=1", True),
        ("union_all_constants", "SELECT 1 UNION ALL SELECT 2", False),
        (
            "derived_table_alias_shadow",
            "SELECT * FROM (SELECT 1 AS id) AS orders GROUP BY id",
            True,
        ),
    ]
    for name, sql, is_olap in no_table_queries:

        def make_test_notable(query_sql, olap_flag):
            def check():
                dec = router_cat.route(query_sql)
                if dec.physical_tables != []:
                    return False, f"Expected physical_tables=[], got {dec.physical_tables}"
                if dec.target != "postgresql":
                    return False, f"Expected target=postgresql, got {dec.target}"
                if olap_flag:
                    if dec.reason_code != "NO_PHYSICAL_TABLES":
                        return (
                            False,
                            f"Expected reason_code=NO_PHYSICAL_TABLES, got {dec.reason_code}",
                        )
                else:
                    if dec.reason_code != "NON_ANALYTICAL_QUERY":
                        return (
                            False,
                            f"Expected reason_code=NON_ANALYTICAL_QUERY, got {dec.reason_code}",
                        )
                return True, "OK"

            return check

        harness.run_case("QueriesWithoutTables", name, sql, make_test_notable(sql, is_olap))

    # =========================================================================
    # 9. Dangerous SQL Constructs: Locks, Modifying CTEs, DML, UDTFs
    # =========================================================================
    lock_queries = [
        ("for_update", "SELECT * FROM orders WHERE id = 1 FOR UPDATE"),
        ("for_share", "SELECT * FROM orders WHERE id = 1 FOR SHARE"),
        ("for_update_skip_locked", "SELECT * FROM orders FOR UPDATE SKIP LOCKED"),
        ("for_update_nowait", "SELECT * FROM orders FOR UPDATE NOWAIT"),
        ("for_update_with_group", "SELECT status, count(*) FROM orders GROUP BY status FOR UPDATE"),
    ]
    for name, sql in lock_queries:

        def make_test_lock(query_sql):
            def check():
                dec = router_cat.route(query_sql)
                if dec.target != "postgresql":
                    return False, f"Expected postgresql, got {dec.target}"
                if dec.reason_code != "LOCKING_READ":
                    return False, f"Expected LOCKING_READ, got {dec.reason_code}"
                if dec.is_analytical is not False:
                    return False, f"Expected is_analytical=False, got {dec.is_analytical}"
                return True, "OK"

            return check

        harness.run_case("DangerousConstructs", name, sql, make_test_lock(sql))

    dml_cte_queries = [
        (
            "delete_returning",
            "WITH del AS (DELETE FROM orders WHERE id = 1 RETURNING *) SELECT * FROM del",
        ),
        (
            "insert_returning",
            "WITH ins AS (INSERT INTO orders (id) VALUES (1) RETURNING *) SELECT * FROM ins",
        ),
        ("update_returning", "WITH upd AS (UPDATE orders SET id=2 RETURNING *) SELECT * FROM upd"),
        (
            "nested_dml_cte",
            "WITH c1 AS (SELECT 1), c2 AS (DELETE FROM orders RETURNING *) SELECT * FROM c2",
        ),
    ]
    for name, sql in dml_cte_queries:

        def make_test_dml_cte(query_sql):
            def check():
                dec = router_cat.route(query_sql)
                if dec.target != "postgresql":
                    return False, f"Expected postgresql, got {dec.target}"
                if dec.reason_code != "DML_OPERATION":
                    return False, f"Expected DML_OPERATION, got {dec.reason_code}"
                if "orders" not in dec.physical_tables:
                    return False, f"Expected 'orders' in physical_tables, got {dec.physical_tables}"
                return True, "OK"

            return check

        harness.run_case("DangerousConstructs", name, sql, make_test_dml_cte(sql))

    udtfs = [
        ("generate_series", "SELECT * FROM generate_series(1, 100) AS s"),
        ("unnest", "SELECT * FROM unnest(ARRAY[1, 2, 3]) AS val"),
    ]
    for name, sql in udtfs:

        def make_test_udtf(query_sql):
            def check():
                dec = router_cat.route(query_sql)
                if dec.physical_tables != []:
                    return False, f"Expected physical_tables=[], got {dec.physical_tables}"
                if dec.target != "postgresql":
                    return False, f"Expected postgresql, got {dec.target}"
                return True, "OK"

            return check

        harness.run_case("DangerousConstructs", name, sql, make_test_udtf(sql))

    # =========================================================================
    # 10. Catalog Configuration Boundaries & Determinism
    # =========================================================================
    q_olap = "SELECT status, count(*) FROM orders GROUP BY status"

    def test_empty_catalog():
        dec = router_empty.route(q_olap)
        if dec.target != "postgresql":
            return False, f"Expected postgresql, got {dec.target}"
        if dec.reason_code != "TABLE_NOT_IN_CATALOG":
            return False, f"Expected TABLE_NOT_IN_CATALOG, got {dec.reason_code}"
        return True, "OK"

    harness.run_case("CatalogBoundaries", "empty_catalog_blocks_olap", q_olap, test_empty_catalog)

    def test_none_catalog():
        dec = router_legacy.route(q_olap)
        if dec.target != "clickhouse":
            return False, f"Expected clickhouse, got {dec.target}"
        if dec.reason_code != "ANALYTICAL_CLICKHOUSE":
            return False, f"Expected ANALYTICAL_CLICKHOUSE, got {dec.reason_code}"
        if dec.catalog_checked is not False:
            return False, f"Expected catalog_checked=False, got {dec.catalog_checked}"
        return True, "OK"

    harness.run_case("CatalogBoundaries", "none_catalog_legacy_mode", q_olap, test_none_catalog)

    def test_determinism():
        first_dec = router_cat.route(q_chain5)
        for _ in range(50):
            dec = router_cat.route(q_chain5)
            if dec != first_dec:
                return False, f"Non-deterministic RouteDecision detected: {dec} != {first_dec}"
        return True, "OK"

    harness.run_case("Determinism", "50_repetition_identity", q_chain5, test_determinism)

    # =========================================================================
    # 11. Property-Based Randomized Query Generator & Oracle Invariant Checker
    # =========================================================================
    random.seed(42)
    known_allowed = ["orders", "users", "products", "accounts"]
    known_pinned = ["returns", "secret_keys"]
    missing_tables = ["unknown_logs", "legacy_billing"]

    def generate_random_query(
        i: int,
    ) -> tuple[str, set[str], set[str], bool, bool]:
        use_cte = random.choice([True, False])
        is_olap = random.choice([True, False])
        has_lock = random.choice([True, False]) if not is_olap else False
        table_pool = random.sample(
            known_allowed + known_pinned + missing_tables, k=random.randint(1, 3)
        )

        expected_phys: set[str] = set()
        pinned_present: set[str] = set()

        cte_prefix = ""
        if use_cte:
            cte_table = random.choice(table_pool)
            cte_prefix = f"WITH cte AS (SELECT * FROM {cte_table}) "
            expected_phys.add(cte_table)
            if cte_table in known_pinned:
                pinned_present.add(cte_table)

        main_table = random.choice(table_pool)
        expected_phys.add(main_table)
        if main_table in known_pinned:
            pinned_present.add(main_table)

        if is_olap:
            agg_expr = random.choice(["count(*)", "sum(val)", "avg(amount)", "max(id)"])
            sql = f"{cte_prefix}SELECT {agg_expr} FROM {main_table} GROUP BY 1"
        else:
            lock_suffix = " FOR UPDATE" if has_lock else ""
            sql = f"{cte_prefix}SELECT * FROM {main_table} WHERE id = {i}{lock_suffix}"

        return sql, expected_phys, pinned_present, is_olap, has_lock

    for i in range(1, 151):
        sql_gen, exp_tables, pinned_tables, is_olap, has_lock = generate_random_query(i)

        def make_fuzz_case(sql, exp_t, pinned_t, olap, lock):
            def check():
                dec = router_cat.route(sql)
                if set(dec.physical_tables) != exp_t:
                    return (
                        False,
                        f"Physical tables mismatch: expected {exp_t}, got {dec.physical_tables}",
                    )

                if lock:
                    if dec.target != "postgresql" or dec.reason_code != "LOCKING_READ":
                        return (
                            False,
                            f"Locking read invariant violated: {dec.target}/{dec.reason_code}",
                        )
                    return True, "OK"

                if pinned_t:
                    if dec.target != "postgresql":
                        return False, f"Pinned table went to {dec.target}!"
                    if olap and dec.reason_code != "TABLE_PG_PINNED":
                        return False, f"Expected TABLE_PG_PINNED, got {dec.reason_code}"
                    return True, "OK"

                missing = [t for t in exp_t if t in missing_tables]
                if missing:
                    if dec.target != "postgresql":
                        return False, f"Missing table {missing} allowed to ClickHouse!"
                    if olap and dec.reason_code != "TABLE_NOT_IN_CATALOG":
                        return False, f"Expected TABLE_NOT_IN_CATALOG, got {dec.reason_code}"
                    return True, "OK"

                if olap and not pinned_t and not missing:
                    if dec.target != "clickhouse" or dec.reason_code != "ANALYTICAL_CLICKHOUSE":
                        return (
                            False,
                            f"Allowed OLAP did not route to ClickHouse: "
                            f"{dec.target}/{dec.reason_code}",
                        )
                return True, "OK"

            return check

        harness.run_case(
            "FuzzOracle",
            f"random_query_{i:03d}",
            sql_gen,
            make_fuzz_case(sql_gen, exp_tables, pinned_tables, is_olap, has_lock),
        )

    return harness


if __name__ == "__main__":
    harness = run_all_tests()
    print("\n" + "=" * 70)
    print("ADVERSARIAL VERIFICATION SUITE SUMMARY")
    print(f"Total test cases executed : {harness.total_tests}")
    print(f"Total passed              : {harness.passed_tests}")
    print(f"Total failed              : {harness.failed_tests}")
    print(f"Pass rate                 : {100.0 * harness.passed_tests / harness.total_tests:.2f}%")
    avg_latency = (
        sum(r.duration_ms for r in harness.results) / len(harness.results) if harness.results else 0
    )
    max_latency = max((r.duration_ms for r in harness.results), default=0)
    print(f"Average latency per route : {avg_latency:.3f} ms")
    print(f"Max latency per route     : {max_latency:.3f} ms")
    print("=" * 70)
    if harness.failed_tests > 0:
        sys.exit(1)
    sys.exit(0)
