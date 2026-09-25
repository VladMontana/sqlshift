"""Модульные тесты для пакетного анализатора запросов и генератора HTML-дашборда."""

from pathlib import Path

import pytest

from sqlshift import (
    AnalyzeAllSql,
    BatchAuditSummary,
    generate_html_report,
)


def test_analyze_from_list() -> None:
    queries = [
        "SELECT id, name FROM users WHERE id = 1",
        "INSERT INTO logs (msg) VALUES ('test')",
        "SELECT count(*) FROM events",
        "SELECT date_trunc('month', ts), sum(v) FROM stats GROUP BY 1",
        (
            "SELECT u.id, o.id, p.id, i.id "
            "FROM users u "
            "JOIN orders o ON u.id = o.user_id "
            "JOIN payments p ON o.id = p.order_id "
            "JOIN invoices i ON p.id = i.payment_id"
        ),
    ]

    analyzer = AnalyzeAllSql.from_list(queries)
    summary = analyzer.analyze()

    assert isinstance(summary, BatchAuditSummary)
    assert summary.total_queries == 5
    assert summary.postgres_count == 2
    assert summary.clickhouse_count == 3
    assert summary.complexity_counts["low"] >= 2
    assert summary.complexity_counts["high"] >= 2
    assert "Heavy JOIN" in summary.bottleneck_detected
    assert len(summary.items) == 5


def test_analyze_empty_list_raises() -> None:
    with pytest.raises(ValueError, match="Список запросов пуст"):
        AnalyzeAllSql.from_list([])


def test_analyze_from_file(tmp_path: Path) -> None:
    sql_file = tmp_path / "batch.sql"
    sql_file.write_text(
        "-- Initial comment\n"
        "SELECT * FROM items WHERE id = 10;\n"
        "-- Another comment\n"
        "SELECT count(*) FROM items GROUP BY category;\n",
        encoding="utf-8",
    )

    analyzer = AnalyzeAllSql.from_file(sql_file)
    summary = analyzer.analyze()

    assert summary.total_queries == 2
    assert summary.postgres_count == 1
    assert summary.clickhouse_count == 1


def test_analyze_from_file_not_found() -> None:
    with pytest.raises(FileNotFoundError):
        AnalyzeAllSql.from_file("non_existent_file_path.sql")


def test_analyze_from_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Ожидается файл"):
        AnalyzeAllSql.from_file(tmp_path)


def test_analyze_from_empty_file_raises(tmp_path: Path) -> None:
    empty_file = tmp_path / "empty.sql"
    empty_file.write_text("-- only comments\n-- nothing else\n", encoding="utf-8")
    with pytest.raises(ValueError, match="не найдены валидные SQL-запросы"):
        AnalyzeAllSql.from_file(empty_file)


def test_to_html_export(tmp_path: Path) -> None:
    queries = [
        "SELECT id FROM users WHERE id = 1",
        "SELECT date_trunc('month', ts), sum(v) FROM stats GROUP BY 1",
    ]
    analyzer = AnalyzeAllSql.from_list(queries)
    output_file = tmp_path / "subfolder" / "report.html"

    html_content = analyzer.to_html(output_path=output_file, title="Custom Test Title")

    assert "<!DOCTYPE html>" in html_content
    assert "Custom Test Title" in html_content
    assert "SQLShift" in html_content
    assert "modalBackdrop" in html_content
    assert output_file.exists()
    assert output_file.read_text(encoding="utf-8") == html_content


def test_generate_html_report_direct() -> None:
    queries = ["SELECT 1"]
    analyzer = AnalyzeAllSql.from_list(queries)
    summary = analyzer.analyze()

    html = generate_html_report(summary, title="Direct Report")
    assert "<!DOCTYPE html>" in html
    assert "Direct Report" in html
    assert "SELECT 1" in html
