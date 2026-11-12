"""Модульные тесты для TableCatalog, извлечения AST Scope и политики маршрутизации."""

import pytest

from sqlshift.core.catalog import (
    TableAdmissionPolicy,
    TableAdmissionResult,
    TableCatalog,
    TableReference,
    extract_physical_tables,
)
from sqlshift.core.parser import parse_sql
from sqlshift.core.router import SQLShiftRouter
from sqlshift.utils.exception import SQLParsingError

# ============================================================================
# 1. Модульные тесты TableReference и TableCatalog
# ============================================================================


def test_table_reference_normalization() -> None:
    ref = TableReference(schema="public", name="orders")
    assert ref.to_string() == "public.orders"
    assert str(ref) == "public.orders"


def test_catalog_empty_behavior() -> None:
    # Пустой список allowed_tables
    cat_empty = TableCatalog(allowed_tables=[])
    assert cat_empty.is_empty() is True
    assert cat_empty.is_table_allowed("orders") is False

    # None allowed_tables
    cat_none = TableCatalog(allowed_tables=None)
    assert cat_none.is_empty() is True

    # Заполненный каталог
    cat_full = TableCatalog(allowed_tables=["orders"])
    assert cat_full.is_empty() is False
    assert cat_full.is_table_allowed("orders") is True


def test_catalog_table_admission_policy_alias() -> None:
    assert TableAdmissionPolicy is TableCatalog
    policy = TableAdmissionPolicy(allowed_tables=["users"])
    assert policy.is_table_allowed("users") is True


def test_catalog_schema_normalization_bidirectional() -> None:
    # Разрешено orders -> матчит и orders, и public.orders
    cat1 = TableCatalog(allowed_tables=["orders"], default_schema="public")
    assert cat1.is_table_allowed("orders") is True
    assert cat1.is_table_allowed("public.orders") is True
    assert cat1.is_table_allowed("archive.orders") is False

    # Разрешено public.orders -> матчит и orders, и public.orders
    cat2 = TableCatalog(allowed_tables=["public.orders"], default_schema="public")
    assert cat2.is_table_allowed("orders") is True
    assert cat2.is_table_allowed("public.orders") is True
    assert cat2.is_table_allowed("archive.orders") is False


def test_catalog_distinct_non_default_schema() -> None:
    cat = TableCatalog(allowed_tables=["archive.orders", "public.events"], default_schema="public")
    assert cat.is_table_allowed("archive.orders") is True
    assert cat.is_table_allowed("public.orders") is False
    assert cat.is_table_allowed("orders") is False
    assert cat.is_table_allowed("events") is True


def test_catalog_case_handling() -> None:
    # По умолчанию case_sensitive=False
    cat_ci = TableCatalog(allowed_tables=["Orders"], case_sensitive=False)
    assert cat_ci.is_table_allowed("orders") is True
    assert cat_ci.is_table_allowed("ORDERS") is True
    assert cat_ci.is_table_allowed("Orders") is True

    # При case_sensitive=True
    cat_cs = TableCatalog(allowed_tables=["Orders"], case_sensitive=True)
    assert cat_cs.is_table_allowed("Orders") is True
    assert cat_cs.is_table_allowed("orders") is False
    assert cat_cs.is_table_allowed("ORDERS") is False


def test_catalog_quoted_identifiers() -> None:
    cat = TableCatalog(allowed_tables=['"Orders"'], case_sensitive=True)
    assert cat.is_table_allowed('"Orders"') is True
    assert cat.is_table_allowed('"orders"') is False


def test_catalog_pg_only_priority_override() -> None:
    # Таблица returns указана и в allowed, и в pg_only -> pg_only побеждает
    cat = TableCatalog(
        allowed_tables=["orders", "returns"],
        postgres_only_tables=["returns"],
    )
    assert cat.is_table_allowed("orders") is True
    assert cat.is_table_allowed("returns") is False

    # Проверка имени аргумента pg_only_tables
    cat2 = TableCatalog(
        allowed_tables=["orders", "returns"],
        pg_only_tables=["returns"],
    )
    assert cat2.is_table_allowed("returns") is False


def test_catalog_check_admission_result_and_unpacking() -> None:
    cat = TableCatalog(
        allowed_tables=["orders", "order_items"],
        pg_only_tables=["returns"],
    )

    # 1. Все разрешены
    res_ok = cat.check_admission(["orders", "order_items"])
    assert isinstance(res_ok, TableAdmissionResult)
    assert res_ok.is_admitted is True
    assert res_ok.reason_code == "ANALYTICAL_CLICKHOUSE"
    assert "Все используемые таблицы разрешены" in res_ok.reason_description

    # Проверка распаковки в кортеж
    admitted, code, missing = res_ok
    assert admitted is True
    assert code == "ANALYTICAL_CLICKHOUSE"
    assert missing == []

    # 2. Таблица отсутствует
    res_missing = cat.check_admission(["orders", "payments"])
    assert res_missing.is_admitted is False
    assert res_missing.reason_code == "TABLE_NOT_IN_CATALOG"
    assert "payments" in res_missing.reason_description
    assert res_missing.missing_tables == ["payments"]

    # 3. Закрепленная таблица
    res_pinned = cat.check_admission(["orders", "returns"])
    assert res_pinned.is_admitted is False
    assert res_pinned.reason_code == "TABLE_PG_PINNED"
    assert "returns" in res_pinned.reason_description
    assert res_pinned.pinned_tables == ["returns"]


# ============================================================================
# 2. Модульные тесты извлечения физических таблиц (AST / Scope SQLGlot)
# ============================================================================


def test_scope_single_table_with_alias() -> None:
    tree = parse_sql("SELECT * FROM users u WHERE u.id = 1")
    assert extract_physical_tables(tree) == ["users"]


def test_scope_multiple_joins() -> None:
    tree = parse_sql(
        "SELECT * FROM orders o "
        "JOIN order_items oi ON o.id = oi.order_id "
        "JOIN products p ON oi.product_id = p.id"
    )
    assert extract_physical_tables(tree) == ["order_items", "orders", "products"]


def test_scope_subquery_in_from() -> None:
    tree = parse_sql("SELECT * FROM (SELECT id FROM accounts) a JOIN orders o ON a.id = o.user_id")
    assert extract_physical_tables(tree) == ["accounts", "orders"]


def test_scope_chained_ctes() -> None:
    tree = parse_sql(
        "WITH c1 AS (SELECT * FROM t1), "
        "     c2 AS (SELECT * FROM c1 JOIN t2 ON 1=1) "
        "SELECT * FROM c2"
    )
    assert extract_physical_tables(tree) == ["t1", "t2"]


def test_scope_cte_shadowing_physical_table() -> None:
    # CTE orders затеняет физическую таблицу orders
    tree = parse_sql("WITH orders AS (SELECT 1 AS x) SELECT * FROM orders")
    assert extract_physical_tables(tree) == []


def test_scope_cte_shadowing_with_internal_table() -> None:
    tree = parse_sql("WITH orders AS (SELECT * FROM real_orders) SELECT * FROM orders")
    assert extract_physical_tables(tree) == ["real_orders"]


def test_scope_deduplication() -> None:
    tree = parse_sql("SELECT * FROM orders o1 JOIN orders o2 ON o1.id = o2.parent_id")
    assert extract_physical_tables(tree) == ["orders"]


def test_scope_schema_qualified() -> None:
    tree = parse_sql("SELECT * FROM public.orders")
    assert extract_physical_tables(tree) == ["public.orders"]


def test_scope_case_and_quotes() -> None:
    tree = parse_sql('SELECT * FROM "Public"."Orders"')
    assert extract_physical_tables(tree) == ['"Public"."Orders"']


def test_scope_locking_read_for_update() -> None:
    tree = parse_sql("SELECT * FROM orders WHERE id = 1 FOR UPDATE")
    assert extract_physical_tables(tree) == ["orders"]


def test_scope_data_modifying_cte() -> None:
    tree = parse_sql("WITH del AS (DELETE FROM orders RETURNING *) SELECT * FROM del")
    assert extract_physical_tables(tree) == ["orders"]


def test_scope_table_valued_function() -> None:
    tree = parse_sql("SELECT * FROM generate_series(1, 10) s")
    assert extract_physical_tables(tree) == []


def test_scope_query_without_tables() -> None:
    tree = parse_sql("SELECT 1 + 1")
    assert extract_physical_tables(tree) == []


def test_scope_dml_statements() -> None:
    assert extract_physical_tables(parse_sql("UPDATE orders SET x = 1")) == ["orders"]
    assert extract_physical_tables(parse_sql("INSERT INTO logs (id) VALUES (1)")) == ["logs"]
    assert extract_physical_tables(parse_sql("DELETE FROM sessions")) == ["sessions"]


def test_scope_union_all_tables() -> None:
    tree = parse_sql("SELECT * FROM orders UNION ALL SELECT * FROM archived_orders")
    assert extract_physical_tables(tree) == ["archived_orders", "orders"]


# ============================================================================
# 3. Модульные тесты политики маршрутизации (Decision Matrix)
# ============================================================================


def test_router_oltp_primary_key_lookup() -> None:
    router = SQLShiftRouter(catalog=TableCatalog(allowed_tables=["users"]))
    decision = router.route("SELECT id, email FROM users WHERE id = 42")
    assert decision.target == "postgresql"
    assert decision.is_analytical is False
    assert decision.reason_code == "NON_ANALYTICAL_QUERY"
    assert decision.physical_tables == ["users"]
    assert decision.catalog_checked is True


def test_router_dml_update_status() -> None:
    router = SQLShiftRouter(catalog=TableCatalog(allowed_tables=["orders"]))
    decision = router.route("UPDATE orders SET status = 'completed' WHERE id = 1")
    assert decision.target == "postgresql"
    assert decision.is_analytical is False
    assert decision.reason_code == "DML_OPERATION"
    assert decision.physical_tables == ["orders"]


def test_router_olap_report_orders_allowed() -> None:
    router = SQLShiftRouter(catalog=TableCatalog(allowed_tables=["orders"]))
    decision = router.route("SELECT status, count(*) FROM orders GROUP BY status")
    assert decision.target == "clickhouse"
    assert decision.is_analytical is True
    assert decision.reason_code == "ANALYTICAL_CLICKHOUSE"
    assert "Все используемые таблицы разрешены" in decision.reason
    assert "GROUP BY" in decision.sql


def test_router_olap_report_orders_missing() -> None:
    router = SQLShiftRouter(catalog=TableCatalog(allowed_tables=["users"]))
    decision = router.route("SELECT status, count(*) FROM orders GROUP BY status")
    assert decision.target == "postgresql"
    assert decision.is_analytical is True
    assert decision.reason_code == "TABLE_NOT_IN_CATALOG"
    assert "orders" in decision.reason
    assert "отсутствует" in decision.reason


def test_router_olap_report_join_partial_missing() -> None:
    router = SQLShiftRouter(catalog=TableCatalog(allowed_tables=["orders"]))
    sql = "SELECT o.id, sum(p.amount) FROM orders o JOIN payments p ON o.id = p.order_id GROUP BY 1"
    decision = router.route(sql)
    assert decision.target == "postgresql"
    assert decision.is_analytical is True
    assert decision.reason_code == "TABLE_NOT_IN_CATALOG"
    assert "payments" in decision.reason


def test_router_olap_report_pg_pinned_table() -> None:
    router = SQLShiftRouter(
        catalog=TableCatalog(
            allowed_tables=["orders", "returns"],
            pg_only_tables=["returns"],
        )
    )
    decision = router.route("SELECT reason, count(*) FROM returns GROUP BY reason")
    assert decision.target == "postgresql"
    assert decision.is_analytical is True
    assert decision.reason_code == "TABLE_PG_PINNED"
    assert "returns" in decision.reason
    assert "закреплена за PostgreSQL" in decision.reason


def test_router_olap_cte_physical_sources() -> None:
    router = SQLShiftRouter(catalog=TableCatalog(allowed_tables=["orders"]))
    sql = (
        "WITH rev AS ("
        "  SELECT date_trunc('month', created_at) AS m, sum(amount) AS s "
        "  FROM orders GROUP BY 1"
        ") SELECT * FROM rev WHERE s > 1000"
    )
    decision = router.route(sql)
    assert decision.target == "clickhouse"
    assert decision.is_analytical is True
    assert decision.reason_code == "ANALYTICAL_CLICKHOUSE"
    assert decision.physical_tables == ["orders"]


def test_router_multi_statement_rejected() -> None:
    router = SQLShiftRouter()
    with pytest.raises(SQLParsingError) as exc_info:
        router.route("SELECT 1; DROP TABLE users;")
    assert "несколько SQL-инструкций" in str(exc_info.value)


def test_router_empty_catalog_blocks_all_olap() -> None:
    router = SQLShiftRouter(catalog=TableCatalog(allowed_tables=[]))
    decision = router.route("SELECT count(*) FROM orders")
    assert decision.target == "postgresql"
    assert decision.is_analytical is True
    assert decision.reason_code == "TABLE_NOT_IN_CATALOG"


def test_router_no_catalog_mode_preserves_heuristic() -> None:
    # В режиме без каталога (None) сохраняется исходное поведение
    router = SQLShiftRouter(catalog=None)
    decision = router.route("SELECT count(*) FROM orders")
    assert decision.target == "clickhouse"
    assert decision.is_analytical is True
    assert decision.reason_code == "ANALYTICAL_CLICKHOUSE"
    assert "COUNT" in decision.reason
    assert decision.catalog_checked is False


def test_router_query_without_physical_tables() -> None:
    router = SQLShiftRouter(catalog=TableCatalog(allowed_tables=["orders"]))
    decision = router.route("SELECT 1")
    assert decision.target == "postgresql"
    assert decision.is_analytical is False
    assert decision.reason_code == "NON_ANALYTICAL_QUERY"
    assert decision.physical_tables == []


def test_router_analytical_without_physical_tables() -> None:
    router = SQLShiftRouter(catalog=TableCatalog(allowed_tables=["orders"]))
    decision = router.route("SELECT 1 GROUP BY 1")
    assert decision.target == "postgresql"
    assert decision.is_analytical is True
    assert decision.reason_code == "NO_PHYSICAL_TABLES"
    assert decision.physical_tables == []
    assert "не содержит физических таблиц" in decision.reason


def test_router_locking_read_for_update_forced_to_postgres() -> None:
    router = SQLShiftRouter(catalog=TableCatalog(allowed_tables=["orders"]))
    decision = router.route("SELECT * FROM orders WHERE id = 1 FOR UPDATE")
    assert decision.target == "postgresql"
    assert decision.is_analytical is False
    assert decision.reason_code == "LOCKING_READ"
    assert "FOR UPDATE" in decision.reason


def test_router_data_modifying_cte_forced_to_postgres() -> None:
    router = SQLShiftRouter(catalog=TableCatalog(allowed_tables=["orders"]))
    decision = router.route("WITH del AS (DELETE FROM orders RETURNING *) SELECT * FROM del")
    assert decision.target == "postgresql"
    assert decision.is_analytical is False
    assert decision.reason_code == "DML_OPERATION"
    assert "DML" in decision.reason


def test_router_join_wording_fix() -> None:
    router = SQLShiftRouter()
    sql = "SELECT * FROM t1 JOIN t2 ON t1.id = t2.id JOIN t3 ON t2.id = t3.id"
    decision = router.route(sql)
    assert "таблиц" not in decision.reason
    assert "2 JOIN" in decision.reason


def test_router_ast_identifier_normalization_and_quotes() -> None:
    """Проверяет строгое разделение идентификаторов: кавычки, регистры и встроенные точки."""
    catalog = TableCatalog(allowed_tables=["orders"])
    router = SQLShiftRouter(catalog=catalog)

    # 1. Quoted "Orders" сохраняет регистр и не совпадает с orders -> в PostgreSQL
    d1 = router.route('SELECT count(*) FROM "Orders"')
    assert d1.target == "postgresql"
    assert d1.reason_code == "TABLE_NOT_IN_CATALOG"
    assert d1.physical_tables == ['"Orders"']

    # 2. Имя со встроенной точкой "public.orders" трактуется как единое имя таблицы -> в PostgreSQL
    d2 = router.route('SELECT count(*) FROM "public.orders"')
    assert d2.target == "postgresql"
    assert d2.reason_code == "TABLE_NOT_IN_CATALOG"
    assert d2.physical_tables == ['"public.orders"']

    # 3. Квалифицированное имя public.orders -> разрешено, уходит в ClickHouse
    d3 = router.route("SELECT count(*) FROM public.orders")
    assert d3.target == "clickhouse"
    assert d3.reason_code == "ANALYTICAL_CLICKHOUSE"
    # Для ClickHouse префикс public. удаляется во избежание ошибки Database public doesn't exist
    assert "public." not in d3.sql
    assert "orders" in d3.sql

    # 4. Двойные кавычки "public"."orders" -> разрешено, уходит в ClickHouse
    d4 = router.route('SELECT count(*) FROM "public"."orders"')
    assert d4.target == "clickhouse"
    assert d4.reason_code == "ANALYTICAL_CLICKHOUSE"

    # 5. Обычный Orders без кавычек -> приводится к нижнему регистру orders -> разрешено
    d5 = router.route("SELECT count(*) FROM Orders")
    assert d5.target == "clickhouse"
    assert d5.reason_code == "ANALYTICAL_CLICKHOUSE"


def test_catalog_explicit_quoted_table_allowed() -> None:
    """Проверяет, что если в каталоге явно разрешена \"Orders\", матчится именно она."""
    catalog = TableCatalog(allowed_tables=['"Orders"'])
    router = SQLShiftRouter(catalog=catalog)

    assert router.route('SELECT count(*) FROM "Orders"').target == "clickhouse"
    assert router.route("SELECT count(*) FROM orders").target == "postgresql"


def test_clickhouse_transpile_schema_mapping() -> None:
    """Проверяет сопоставление схем при транспайлинге в ClickHouse."""
    catalog = TableCatalog(allowed_tables=["orders"], schema_mapping={"public": "default"})
    router = SQLShiftRouter(catalog=catalog)

    decision = router.route("SELECT count(*) FROM public.orders GROUP BY status")
    assert decision.target == "clickhouse"
    assert "default.orders" in decision.sql

