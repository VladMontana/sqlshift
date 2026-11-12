"""Модульные тесты для BatchAnalyzer с поддержкой каталога и проверки узких мест."""

from pathlib import Path

from sqlshift.core.batch_analyzer import AnalyzeAllSql
from sqlshift.core.catalog import TableCatalog
from sqlshift.core.parser import parse_sql
from sqlshift.core.router import SQLShiftRouter


def test_batch_analyzer_default_no_catalog() -> None:
    """Проверяет режим по умолчанию без каталога (эвристическая маршрутизация)."""
    queries = [
        "SELECT id, name FROM users WHERE id = 1",
        "SELECT count(*) FROM events GROUP BY user_id",
    ]
    analyzer = AnalyzeAllSql(queries)
    summary = analyzer.analyze()

    assert summary.total_queries == 2
    assert summary.postgres_count == 1
    assert summary.clickhouse_count == 1
    assert summary.items[0].decision.target == "postgresql"
    assert summary.items[1].decision.target == "clickhouse"
    assert summary.items[1].decision.catalog_checked is False


def test_batch_analyzer_with_catalog() -> None:
    """Проверяет пакетный анализ с явной передачей TableCatalog."""
    catalog = TableCatalog(
        allowed_tables=["orders", "order_items"],
        pg_only_tables=["returns"],
    )
    queries = [
        # Разрешенная таблица -> ClickHouse
        "SELECT status, sum(amount) FROM orders GROUP BY status",
        # Отсутствующая таблица -> PostgreSQL
        "SELECT user_id, count(*) FROM payments GROUP BY user_id",
        # Закрепленная за PG таблица -> PostgreSQL
        "SELECT reason, count(*) FROM returns GROUP BY reason",
        # Транзакционный запрос -> PostgreSQL
        "SELECT * FROM orders WHERE id = 10",
    ]
    analyzer = AnalyzeAllSql(queries, catalog=catalog)
    summary = analyzer.analyze()

    assert summary.total_queries == 4
    assert summary.clickhouse_count == 1
    assert summary.postgres_count == 3

    # orders -> clickhouse
    assert summary.items[0].decision.target == "clickhouse"
    assert summary.items[0].decision.reason_code == "ANALYTICAL_CLICKHOUSE"
    assert summary.items[0].decision.catalog_checked is True

    # payments -> postgresql (missing table)
    assert summary.items[1].decision.target == "postgresql"
    assert summary.items[1].decision.reason_code == "TABLE_NOT_IN_CATALOG"
    assert "payments" in summary.items[1].decision.reason

    # returns -> postgresql (pinned table)
    assert summary.items[2].decision.target == "postgresql"
    assert summary.items[2].decision.reason_code == "TABLE_PG_PINNED"
    assert "returns" in summary.items[2].decision.reason

    # OLTP -> postgresql
    assert summary.items[3].decision.target == "postgresql"
    assert summary.items[3].decision.reason_code == "NON_ANALYTICAL_QUERY"


def test_batch_analyzer_from_file_with_catalog(tmp_path: Path) -> None:
    """Проверяет загрузку из файла с передачей каталога."""
    sql_file = tmp_path / "batch_catalog.sql"
    sql_file.write_text(
        "SELECT status, count(*) FROM orders GROUP BY status;\n"
        "SELECT customer_id, count(*) FROM secret_table GROUP BY customer_id;\n",
        encoding="utf-8",
    )

    catalog = TableCatalog(allowed_tables=["orders"])
    analyzer = AnalyzeAllSql.from_file(sql_file, catalog=catalog)
    summary = analyzer.analyze()

    assert summary.total_queries == 2
    assert summary.clickhouse_count == 1
    assert summary.postgres_count == 1
    assert summary.items[0].decision.target == "clickhouse"
    assert summary.items[1].decision.target == "postgresql"


def test_batch_analyzer_from_list_with_catalog() -> None:
    """Проверяет from_list с передачей каталога."""
    catalog = TableCatalog(allowed_tables=["events"])
    queries = ["SELECT event_type, count(*) FROM events GROUP BY event_type"]
    analyzer = AnalyzeAllSql.from_list(queries, catalog=catalog)
    summary = analyzer.analyze()

    assert summary.clickhouse_count == 1
    assert summary.items[0].decision.target == "clickhouse"
    assert summary.items[0].decision.catalog_checked is True


def test_batch_analyzer_custom_router_precedence() -> None:
    """Проверяет приоритет переданного router над catalog."""
    cat1 = TableCatalog(allowed_tables=["orders"])
    cat2 = TableCatalog(allowed_tables=["payments"])
    custom_router = SQLShiftRouter(catalog=cat1)

    analyzer = AnalyzeAllSql(
        queries=["SELECT * FROM orders"],
        router=custom_router,
        catalog=cat2,
    )
    assert analyzer.router is custom_router
    assert analyzer.router.catalog is cat1


def test_detect_bottlenecks_join_wording() -> None:
    """Проверяет формулировку узкого места JOIN operations вместо tables joined."""
    sql = "SELECT * FROM a JOIN b ON a.id = b.a_id JOIN c ON b.id = c.b_id JOIN d ON c.id = d.c_id"
    tree = parse_sql(sql)
    analyzer = AnalyzeAllSql(["SELECT 1"])
    bottlenecks = analyzer._detect_bottlenecks(tree)

    join_bottlenecks = [b for b in bottlenecks if "JOIN" in b]
    assert len(join_bottlenecks) == 1
    # Проверяем точную формулировку 'JOIN operations'
    assert "JOIN operations" in join_bottlenecks[0]
    assert "tables joined" not in join_bottlenecks[0]
    assert join_bottlenecks[0] == "Heavy JOIN: 3 JOIN operations"


def test_batch_analyzer_html_generation_with_catalog(tmp_path: Path) -> None:
    """Проверяет корректность генерации HTML дашборда при анализе с каталогом."""
    catalog = TableCatalog(allowed_tables=["orders"])
    queries = [
        "SELECT status, count(*) FROM orders GROUP BY status",
        "SELECT count(*) FROM unallowed_table GROUP BY 1",
    ]
    analyzer = AnalyzeAllSql(queries, catalog=catalog)
    out_html = tmp_path / "catalog_report.html"
    html = analyzer.to_html(output_path=out_html)

    assert out_html.exists()
    assert "orders" in html
    assert "unallowed_table" in html
    assert "<!DOCTYPE html>" in html
