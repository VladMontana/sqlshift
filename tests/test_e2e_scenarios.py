"""Comprehensive End-to-End (E2E) Test Suite for SQLShift.

Covers Tiers 1-4 based on PROJECT.md, spec_requirements.md, and SQLShift_final_project_plan.md:
- Tier 1: Feature Coverage (R1-R4 baseline contract verification)
- Tier 2: Boundary & Corner Cases (empty catalog, multi-statement, CTE shadowing, locks, DML)
- Tier 3: Cross-Feature Combinations (CTE+JOIN, subqueries with PG-pinned tables, multi-join)
- Tier 4: Real-World Store Scenarios (Retail OLTP vs OLAP orders vs PG-pinned returns)
"""

from typing import Any

import pytest

from sqlshift.core.parser import parse_sql
from sqlshift.core.router import SQLShiftRouter
from sqlshift.utils.exception import SQLParsingError

# Public contract import for TableCatalog and AST extraction
try:
    from sqlshift.core.catalog import (  # type: ignore[import-not-found]
        TableAdmissionPolicy,
        TableCatalog,
        extract_physical_tables,
    )
except ImportError:
    TableCatalog = None  # type: ignore[assignment,misc]
    TableAdmissionPolicy = None  # type: ignore[assignment,misc]
    extract_physical_tables = None  # type: ignore[assignment]


def make_catalog(
    allowed_tables: list[str] | None = None,
    pg_only_tables: list[str] | None = None,
    default_schema: str = "public",
    case_sensitive: bool = False,
) -> Any:
    """Helper to instantiate TableCatalog supporting either postgres_only or pg_only."""
    if TableCatalog is None:
        pytest.skip("TableCatalog is not yet published in sqlshift.core.catalog")

    try:
        return TableCatalog(
            allowed_tables=allowed_tables,
            postgres_only_tables=pg_only_tables,
            default_schema=default_schema,
            case_sensitive=case_sensitive,
        )
    except TypeError:
        return TableCatalog(
            allowed_tables=allowed_tables,
            pg_only_tables=pg_only_tables,
            default_schema=default_schema,
            case_sensitive=case_sensitive,
        )


def create_router(catalog: Any = None) -> SQLShiftRouter:
    """Instantiate SQLShiftRouter with catalog parameter safely across milestones."""
    router_cls: Any = SQLShiftRouter
    if catalog is not None:
        return router_cls(catalog=catalog)  # type: ignore[no-any-return]
    try:
        return router_cls(catalog=None)  # type: ignore[no-any-return]
    except TypeError:
        return router_cls()  # type: ignore[no-any-return]


def _require_catalog() -> None:
    """Skip test if catalog module is not yet available in environment."""
    if TableCatalog is None:
        pytest.skip("sqlshift.core.catalog is not yet available")


def _normalize_table_names(tables: list[str]) -> set[str]:
    """Normalize extracted table strings down to unqualified base names for resilient assertion."""
    return {t.split(".")[-1].strip('"').lower() for t in tables}


# ============================================================================
# Tier 1: Feature Coverage (R1 - R4)
# ============================================================================


def test_t1_r1_catalog_table_admission_allowed_vs_denied() -> None:
    """R1: TableCatalog correctly admits configured tables and denies unlisted tables."""
    _require_catalog()
    catalog = make_catalog(
        allowed_tables=["orders", "order_items"],
        pg_only_tables=["returns"],
    )
    assert catalog.is_table_allowed("orders") is True
    assert catalog.is_table_allowed("order_items") is True
    assert catalog.is_table_allowed("users") is False
    assert catalog.is_table_allowed("returns") is False


def test_t1_r1_catalog_pg_only_override_priority() -> None:
    """R1: Tables present in pg_only_tables are strictly denied even if in allowed_tables."""
    _require_catalog()
    catalog = make_catalog(
        allowed_tables=["orders", "returns"],
        pg_only_tables=["returns"],
    )
    assert catalog.is_table_allowed("returns") is False
    assert catalog.is_table_allowed("orders") is True

    # Router routing with pg_only table
    router = create_router(catalog=catalog)
    decision = router.route("SELECT count(*) FROM returns")
    assert decision.target == "postgresql"
    assert decision.reason_code in ("TABLE_PG_PINNED", "PG_ONLY_TABLE")


def test_t1_r1_catalog_bidirectional_schema_normalization() -> None:
    """R1: Unqualified ('orders') and default schema ('public.orders') resolve bidirectionally."""
    _require_catalog()
    cat_unqualified = make_catalog(allowed_tables=["orders"], default_schema="public")
    assert cat_unqualified.is_table_allowed("orders") is True
    assert cat_unqualified.is_table_allowed("public.orders") is True

    cat_qualified = make_catalog(allowed_tables=["public.orders"], default_schema="public")
    assert cat_qualified.is_table_allowed("orders") is True
    assert cat_qualified.is_table_allowed("public.orders") is True


def test_t1_r1_catalog_distinct_non_default_schema() -> None:
    """R1: Non-default schemas ('archive.orders') do not match 'public.orders'."""
    _require_catalog()
    catalog = make_catalog(allowed_tables=["orders"], default_schema="public")
    assert catalog.is_table_allowed("archive.orders") is False


def test_t1_r1_dual_mode_no_catalog_vs_catalog_mode() -> None:
    """R1: Dual mode maintains 100% backward compatibility when catalog=None."""
    _require_catalog()
    # 1. No catalog mode: routes purely on AST heuristic
    legacy_router = create_router(catalog=None)
    dec_legacy = legacy_router.route("SELECT status, count(*) FROM orders GROUP BY status")
    assert dec_legacy.target == "clickhouse"
    assert dec_legacy.is_analytical is True

    # 2. Configured catalog mode
    cat_router = create_router(catalog=make_catalog(allowed_tables=["orders"]))
    dec_cat = cat_router.route("SELECT status, count(*) FROM orders GROUP BY status")
    assert dec_cat.target == "clickhouse"
    assert dec_cat.is_analytical is True
    assert getattr(dec_cat, "catalog_checked", True) is True


def test_t1_r2_extract_single_table_with_alias() -> None:
    """R2: Scope analysis extracts physical table and strips aliases."""
    _require_catalog()
    assert extract_physical_tables is not None
    tree = parse_sql("SELECT id, name FROM users u WHERE u.id = 1")
    tables = extract_physical_tables(tree)
    normalized = _normalize_table_names(tables)
    assert normalized == {"users"}
    assert "u" not in normalized


def test_t1_r2_extract_multiple_joins_and_deduplication() -> None:
    """R2: Scope analysis extracts all physical tables in JOINs with deduplication."""
    _require_catalog()
    assert extract_physical_tables is not None
    sql = (
        "SELECT o.id, oi.quantity, p.name "
        "FROM orders o "
        "JOIN order_items oi ON o.id = oi.order_id "
        "JOIN products p ON oi.product_id = p.id "
        "JOIN orders o2 ON o.id = o2.parent_id"
    )
    tree = parse_sql(sql)
    tables = extract_physical_tables(tree)
    normalized = _normalize_table_names(tables)
    assert normalized == {"orders", "order_items", "products"}


def test_t1_r2_extract_cte_isolates_physical_sources() -> None:
    """R2: Scope analysis extracts underlying table inside CTE, not the CTE alias."""
    _require_catalog()
    assert extract_physical_tables is not None
    sql = (
        "WITH summary AS ("
        "  SELECT customer_id, sum(total) AS s FROM orders GROUP BY customer_id"
        ") SELECT * FROM summary WHERE s > 100"
    )
    tree = parse_sql(sql)
    tables = extract_physical_tables(tree)
    normalized = _normalize_table_names(tables)
    assert normalized == {"orders"}
    assert "summary" not in normalized


def test_t1_r2_extract_subquery_in_from_clause() -> None:
    """R2: Scope analysis extracts tables from derived tables / subqueries in FROM."""
    _require_catalog()
    assert extract_physical_tables is not None
    sql = "SELECT * FROM (SELECT id FROM accounts) a JOIN orders o ON a.id = o.user_id"
    tree = parse_sql(sql)
    tables = extract_physical_tables(tree)
    normalized = _normalize_table_names(tables)
    assert normalized == {"accounts", "orders"}
    assert "a" not in normalized


def test_t1_r3_routing_oltp_primary_key_lookup_to_postgres() -> None:
    """R3: Non-analytical point lookups route to PostgreSQL."""
    _require_catalog()
    router = create_router(catalog=make_catalog(allowed_tables=["users"]))
    decision = router.route("SELECT id, email FROM users WHERE id = 42")
    assert decision.target == "postgresql"
    assert decision.is_analytical is False
    assert decision.reason_code in ("NON_ANALYTICAL_QUERY", "OLTP_QUERY", "DEFAULT")


def test_t1_r3_routing_dml_update_to_postgres() -> None:
    """R3: DML statements unconditionally route to PostgreSQL."""
    _require_catalog()
    router = create_router(catalog=make_catalog(allowed_tables=["orders"]))
    decision = router.route("UPDATE orders SET status = 'completed' WHERE id = 1")
    assert decision.target == "postgresql"
    assert decision.is_analytical is False
    assert decision.reason_code in ("DML_OPERATION", "DML", "DEFAULT")


def test_t1_r3_routing_olap_admitted_to_clickhouse() -> None:
    """R3: Analytical query with all physical tables in catalog routes to ClickHouse."""
    _require_catalog()
    router = create_router(catalog=make_catalog(allowed_tables=["orders"]))
    decision = router.route("SELECT status, count(*) FROM orders GROUP BY status")
    assert decision.target == "clickhouse"
    assert decision.is_analytical is True
    assert decision.reason_code in ("ANALYTICAL_CLICKHOUSE", "ALLOWED_ANALYTICAL", "DEFAULT")
    assert "GROUP BY" in decision.sql


def test_t1_r3_routing_olap_missing_table_to_postgres() -> None:
    """R3: Analytical query with missing table routes to PostgreSQL with explanation."""
    _require_catalog()
    router = create_router(catalog=make_catalog(allowed_tables=["users"]))  # orders missing
    decision = router.route("SELECT status, count(*) FROM orders GROUP BY status")
    assert decision.target == "postgresql"
    assert decision.is_analytical is True
    assert decision.reason_code in ("TABLE_NOT_IN_CATALOG", "TABLE_NOT_ADMITTED")
    assert "orders" in decision.reason.lower()


def test_t1_r3_join_wording_avoids_table_count_mislabeling() -> None:
    """R3 / §4: Multi-join reason description refers to JOIN operations, not table count."""
    _require_catalog()
    router = create_router()
    sql = "SELECT * FROM t1 JOIN t2 ON t1.id = t2.id JOIN t3 ON t2.id = t3.id"
    decision = router.route(sql)
    assert "таблиц" not in decision.reason.lower() or "join" in decision.reason.lower()


def test_t1_r4_route_decision_contract_completeness() -> None:
    """R4: RouteDecision contains all required fields and respects immutability."""
    _require_catalog()
    router = create_router()
    decision = router.route("SELECT 1")
    assert hasattr(decision, "target")
    assert hasattr(decision, "sql")
    assert hasattr(decision, "is_analytical")
    assert hasattr(decision, "estimated_complexity")
    assert hasattr(decision, "reason")
    assert hasattr(decision, "reason_code")
    assert hasattr(decision, "physical_tables")
    assert hasattr(decision, "catalog_checked")

    with pytest.raises((AttributeError, TypeError)):
        decision.target = "clickhouse"  # type: ignore[misc]


# ============================================================================
# Tier 2: Boundary & Corner Cases
# ============================================================================


def test_t2_empty_catalog_blocks_all_olap_queries() -> None:
    """Tier 2: Empty configured catalog strictly denies ClickHouse routing."""
    _require_catalog()
    empty_catalog = make_catalog(allowed_tables=[])
    assert empty_catalog.is_empty() is True

    router = create_router(catalog=empty_catalog)
    decision = router.route("SELECT status, count(*) FROM orders GROUP BY status")
    assert decision.target == "postgresql"
    assert decision.is_analytical is True
    assert decision.reason_code in ("TABLE_NOT_IN_CATALOG", "TABLE_NOT_ADMITTED", "EMPTY_CATALOG")

    # Contrast with None catalog which routes to clickhouse
    legacy_router = create_router(catalog=None)
    res_legacy = legacy_router.route("SELECT status, count(*) FROM orders GROUP BY status")
    assert res_legacy.target == "clickhouse"


def test_t2_empty_input_and_whitespace_rejected() -> None:
    """Tier 2: Empty or whitespace-only inputs are rejected with SQLParsingError."""
    router = create_router()
    with pytest.raises(SQLParsingError):
        router.route("")
    with pytest.raises(SQLParsingError):
        router.route("   \n\t  ")


def test_t2_multi_statement_query_rejected() -> None:
    """Tier 2: Multi-statement input is rejected entirely to prevent partial execution."""
    router = create_router()
    with pytest.raises(SQLParsingError) as exc_info:
        router.route("SELECT 1; DROP TABLE users;")
    assert "несколько" in str(exc_info.value).lower() or "multiple" in str(exc_info.value).lower()


def test_t2_multi_statement_with_first_valid_rejected() -> None:
    """Tier 2: Multi-statement rejected even if first statement is a valid analytical query."""
    router = create_router()
    with pytest.raises(SQLParsingError):
        router.route("SELECT * FROM orders; SELECT * FROM returns;")


def test_t2_trailing_semicolons_accepted_as_single_statement() -> None:
    """Tier 2: Redundant trailing semicolons do not trigger multi-statement rejection."""
    router = create_router()
    decision = router.route("SELECT 1;;;")
    assert decision.target == "postgresql"


def test_t2_scalar_query_without_physical_tables_routes_to_postgres() -> None:
    """Tier 2: Queries without physical tables (SELECT 1) route to PostgreSQL."""
    _require_catalog()
    router = create_router(catalog=make_catalog(allowed_tables=["orders"]))
    decision = router.route("SELECT 1 + 1")
    assert decision.target == "postgresql"
    assert decision.physical_tables == []


def test_t2_analytical_query_without_physical_tables_routes_to_postgres() -> None:
    """Tier 2: Queries without physical tables (SELECT 1 GROUP BY 1) route to PostgreSQL."""
    _require_catalog()
    router = create_router(catalog=make_catalog(allowed_tables=["orders"]))
    decision = router.route("SELECT 1 GROUP BY 1")
    assert decision.target == "postgresql"
    assert decision.reason_code == "NO_PHYSICAL_TABLES"
    assert decision.physical_tables == []


def test_t2_table_valued_function_generate_series_excluded() -> None:
    """Tier 2: Table-valued functions like generate_series() are not treated as physical tables."""
    _require_catalog()
    assert extract_physical_tables is not None
    tree = parse_sql("SELECT * FROM generate_series(1, 10) s")
    tables = extract_physical_tables(tree)
    assert tables == []

    router = create_router(catalog=make_catalog(allowed_tables=["orders"]))
    decision = router.route("SELECT * FROM generate_series(1, 10) s")
    assert decision.target == "postgresql"
    assert decision.physical_tables == []


def test_t2_cte_shadowing_real_physical_table() -> None:
    """Tier 2: A CTE shadowing a real table name prevents extracting the shadowed physical table."""
    _require_catalog()
    assert extract_physical_tables is not None
    sql = "WITH orders AS (SELECT 1 AS x) SELECT * FROM orders"
    tree = parse_sql(sql)
    tables = extract_physical_tables(tree)
    assert tables == []

    router = create_router(catalog=make_catalog(allowed_tables=["orders"]))
    decision = router.route(sql)
    assert decision.target == "postgresql"
    assert decision.physical_tables == []


def test_t2_cte_shadowing_with_internal_physical_table() -> None:
    """Tier 2: Shadowing CTE extracting underlying real table correctly."""
    _require_catalog()
    assert extract_physical_tables is not None
    sql = "WITH orders AS (SELECT * FROM real_orders) SELECT * FROM orders"
    tree = parse_sql(sql)
    tables = extract_physical_tables(tree)
    normalized = _normalize_table_names(tables)
    assert normalized == {"real_orders"}


def test_t2_chained_ctes_extracts_only_physical_sources() -> None:
    """Tier 2: Chained CTEs (c1 -> c2 -> query) resolve to physical sources t1 and t2 only."""
    _require_catalog()
    assert extract_physical_tables is not None
    sql = (
        "WITH c1 AS (SELECT * FROM t1), "
        "     c2 AS (SELECT * FROM c1 JOIN t2 ON c1.id = t2.id) "
        "SELECT * FROM c2"
    )
    tree = parse_sql(sql)
    tables = extract_physical_tables(tree)
    normalized = _normalize_table_names(tables)
    assert normalized == {"t1", "t2"}


def test_t2_locking_reads_for_update_forced_to_postgres() -> None:
    """Tier 2: Locking reads (SELECT ... FOR UPDATE) stay in PostgreSQL."""
    _require_catalog()
    router = create_router(catalog=make_catalog(allowed_tables=["orders"]))
    decision = router.route("SELECT * FROM orders WHERE id = 1 FOR UPDATE")
    assert decision.target == "postgresql"
    assert decision.reason_code in ("LOCKING_READ", "LOCK", "DEFAULT")


def test_t2_locking_reads_for_share_forced_to_postgres() -> None:
    """Tier 2: Locking reads (SELECT ... FOR SHARE) stay in PostgreSQL."""
    _require_catalog()
    router = create_router(catalog=make_catalog(allowed_tables=["orders"]))
    decision = router.route("SELECT * FROM orders WHERE id = 1 FOR SHARE")
    assert decision.target == "postgresql"
    assert decision.reason_code in ("LOCKING_READ", "LOCK", "DEFAULT")


def test_t2_data_modifying_cte_forced_to_postgres() -> None:
    """Tier 2: Data-modifying CTEs (DELETE ... RETURNING in WITH) are forced to PostgreSQL."""
    _require_catalog()
    router = create_router(catalog=make_catalog(allowed_tables=["orders"]))
    sql = (
        "WITH del AS ("
        "  DELETE FROM orders WHERE status = 'cancelled' RETURNING id"
        ") SELECT count(*) FROM del"
    )
    decision = router.route(sql)
    assert decision.target == "postgresql"
    assert decision.reason_code in ("DML_OPERATION", "DML", "DEFAULT")


def test_t2_case_sensitivity_flag_behavior() -> None:
    """Tier 2: Case sensitivity configuration behaves predictably."""
    _require_catalog()
    cat_insensitive = make_catalog(allowed_tables=["Orders"], case_sensitive=False)
    assert cat_insensitive.is_table_allowed("orders") is True
    assert cat_insensitive.is_table_allowed("ORDERS") is True

    cat_sensitive = make_catalog(allowed_tables=["Orders"], case_sensitive=True)
    assert cat_sensitive.is_table_allowed("Orders") is True
    assert cat_sensitive.is_table_allowed("orders") is False


def test_t2_quoted_identifiers_case_preservation() -> None:
    """Tier 2: Quoted identifiers preserve exact casing under case-sensitive configuration."""
    _require_catalog()
    cat = make_catalog(allowed_tables=['"Orders"'], case_sensitive=True)
    assert cat.is_table_allowed('"Orders"') is True
    assert cat.is_table_allowed('"orders"') is False


# ============================================================================
# Tier 3: Cross-Feature Combinations
# ============================================================================


def test_t3_cte_plus_join_mixed_catalog_admission() -> None:
    """Tier 3: CTE + JOIN where one table is allowed but joined table is missing."""
    _require_catalog()
    router = create_router(catalog=make_catalog(allowed_tables=["orders"]))  # payments missing
    sql = (
        "WITH customer_summary AS ("
        "  SELECT customer_id, sum(amount) AS total FROM orders GROUP BY customer_id"
        ") "
        "SELECT cs.customer_id, cs.total, p.payment_method "
        "FROM customer_summary cs "
        "JOIN payments p ON cs.customer_id = p.customer_id"
    )
    decision = router.route(sql)
    assert decision.target == "postgresql"
    assert decision.is_analytical is True
    assert decision.reason_code in ("TABLE_NOT_IN_CATALOG", "TABLE_NOT_ADMITTED")
    assert "payments" in decision.reason.lower()


def test_t3_cte_plus_join_all_tables_admitted() -> None:
    """Tier 3: CTE + JOIN where all underlying physical tables are admitted."""
    _require_catalog()
    router = create_router(catalog=make_catalog(allowed_tables=["orders", "payments"]))
    sql = (
        "WITH customer_summary AS ("
        "  SELECT customer_id, sum(amount) AS total FROM orders GROUP BY customer_id"
        ") "
        "SELECT cs.customer_id, cs.total, p.payment_method "
        "FROM customer_summary cs "
        "JOIN payments p ON cs.customer_id = p.customer_id"
    )
    decision = router.route(sql)
    assert decision.target == "clickhouse"
    assert decision.is_analytical is True
    assert decision.reason_code in ("ANALYTICAL_CLICKHOUSE", "ALLOWED_ANALYTICAL", "DEFAULT")


def test_t3_group_by_subquery_with_pg_pinned_table() -> None:
    """Tier 3: GROUP BY query referencing PG-pinned table in subquery is forced to PostgreSQL."""
    _require_catalog()
    router = create_router(
        catalog=make_catalog(
            allowed_tables=["orders", "returns"],
            pg_only_tables=["returns"],
        )
    )
    sql = (
        "SELECT o.status, count(*) "
        "FROM orders o "
        "WHERE o.id NOT IN (SELECT order_id FROM returns WHERE order_id IS NOT NULL) "
        "GROUP BY o.status"
    )
    decision = router.route(sql)
    assert decision.target == "postgresql"
    assert decision.reason_code in ("TABLE_PG_PINNED", "PG_ONLY_TABLE")


def test_t3_multi_join_three_tables_partial_catalog_coverage() -> None:
    """Tier 3: 3-way JOIN with 2 allowed tables and 1 missing table routes to PostgreSQL."""
    _require_catalog()
    router = create_router(
        catalog=make_catalog(allowed_tables=["orders", "order_items"])  # shipments missing
    )
    sql = (
        "SELECT o.id, oi.product_id, s.warehouse_id "
        "FROM orders o "
        "JOIN order_items oi ON o.id = oi.order_id "
        "JOIN shipments s ON o.id = s.order_id"
    )
    decision = router.route(sql)
    assert decision.target == "postgresql"
    assert decision.reason_code in ("TABLE_NOT_IN_CATALOG", "TABLE_NOT_ADMITTED")
    assert "shipments" in decision.reason.lower()


def test_t3_window_function_with_schema_qualified_table() -> None:
    """Tier 3: Window function with schema-qualified table routes to ClickHouse when admitted."""
    _require_catalog()
    router = create_router(catalog=make_catalog(allowed_tables=["orders"]))
    sql = (
        "SELECT id, customer_id, total_amount, "
        "row_number() OVER (PARTITION BY customer_id ORDER BY created_at DESC) AS rn "
        "FROM public.orders"
    )
    decision = router.route(sql)
    assert decision.target == "clickhouse"
    assert decision.is_analytical is True


def test_t3_having_clause_with_missing_table_fallback() -> None:
    """Tier 3: HAVING query with missing table stays in PostgreSQL with explicit reason."""
    _require_catalog()
    router = create_router(catalog=make_catalog(allowed_tables=["users"]))  # audit_logs missing
    sql = "SELECT user_id, count(*) FROM audit_logs GROUP BY user_id HAVING count(*) > 10"
    decision = router.route(sql)
    assert decision.target == "postgresql"
    assert decision.reason_code in ("TABLE_NOT_IN_CATALOG", "TABLE_NOT_ADMITTED")


# ============================================================================
# Tier 4: Real-World Store Scenarios
# ============================================================================


def test_t4_store_oltp_lookups_and_updates() -> None:
    """Tier 4: E-commerce store transactional lookups and status updates route to PostgreSQL."""
    _require_catalog()
    router = create_router(
        catalog=make_catalog(allowed_tables=["orders"], pg_only_tables=["returns"])
    )

    # 1. Point lookup
    sql_lookup = "SELECT id, customer_id, total_amount, status FROM orders WHERE id = 101"
    dec_lookup = router.route(sql_lookup)
    assert dec_lookup.target == "postgresql"
    assert dec_lookup.is_analytical is False

    # 2. Status update
    sql_update = "UPDATE orders SET status = 'shipped' WHERE id = 101"
    dec_update = router.route(sql_update)
    assert dec_update.target == "postgresql"
    assert dec_update.is_analytical is False

    # 3. New order insertion
    sql_insert = (
        "INSERT INTO orders (id, customer_id, total_amount, status) VALUES (102, 50, 150.0, 'new')"
    )
    dec_insert = router.route(sql_insert)
    assert dec_insert.target == "postgresql"
    assert dec_insert.is_analytical is False


def test_t4_store_analytics_on_orders_routed_to_clickhouse() -> None:
    """Tier 4: Analytical order aggregation report routes to ClickHouse with transpile."""
    _require_catalog()
    router = create_router(
        catalog=make_catalog(allowed_tables=["orders"], pg_only_tables=["returns"])
    )
    sql = (
        "SELECT status, count(*) AS total_orders, sum(total_amount) AS total_revenue "
        "FROM orders "
        "GROUP BY status "
        "HAVING count(*) > 5"
    )
    decision = router.route(sql)
    assert decision.target == "clickhouse"
    assert decision.is_analytical is True
    assert "orders" in _normalize_table_names(decision.physical_tables)
    assert "sum(total_amount)" in decision.sql.lower() or "sum(" in decision.sql.lower()


def test_t4_store_returns_query_rejected_due_to_pg_pinned() -> None:
    """Tier 4: Query on 'returns' is rejected from ClickHouse because returns is PG-pinned."""
    _require_catalog()
    router = create_router(
        catalog=make_catalog(allowed_tables=["orders"], pg_only_tables=["returns"])
    )
    sql = (
        "SELECT return_reason, count(*) AS return_count, sum(refund_amount) AS total_refunded "
        "FROM returns "
        "GROUP BY return_reason"
    )
    decision = router.route(sql)
    assert decision.target == "postgresql"
    assert decision.is_analytical is True
    assert decision.reason_code in ("TABLE_PG_PINNED", "PG_ONLY_TABLE")
    assert "returns" in decision.reason.lower()


def test_t4_store_cross_table_return_rate_analysis() -> None:
    """Tier 4: Joining allowed orders with PG-pinned returns keeps query in PostgreSQL."""
    _require_catalog()
    router = create_router(
        catalog=make_catalog(allowed_tables=["orders"], pg_only_tables=["returns"])
    )
    sql = (
        "SELECT o.status, "
        "count(DISTINCT o.id) AS total_orders, "
        "count(DISTINCT r.id) AS total_returns "
        "FROM orders o "
        "LEFT JOIN returns r ON o.id = r.order_id "
        "GROUP BY o.status"
    )
    decision = router.route(sql)
    assert decision.target == "postgresql"
    assert decision.is_analytical is True
    assert decision.reason_code in ("TABLE_PG_PINNED", "PG_ONLY_TABLE")


def test_t4_store_complex_quarterly_reporting_dashboard() -> None:
    """Tier 4: Complex multi-CTE quarterly sales ranking report routes to ClickHouse."""
    _require_catalog()
    router = create_router(
        catalog=make_catalog(allowed_tables=["orders"], pg_only_tables=["returns"])
    )
    sql = (
        "WITH monthly_sales AS ("
        "  SELECT date_trunc('month', created_at) AS sale_month, sum(total_amount) AS monthly_rev "
        "  FROM orders "
        "  GROUP BY 1"
        "), "
        "ranked_sales AS ("
        "  SELECT sale_month, monthly_rev, rank() OVER (ORDER BY monthly_rev DESC) AS rev_rank "
        "  FROM monthly_sales"
        ") "
        "SELECT * FROM ranked_sales WHERE rev_rank <= 3"
    )
    decision = router.route(sql)
    assert decision.target == "clickhouse"
    assert decision.is_analytical is True
    assert _normalize_table_names(decision.physical_tables) == {"orders"}
