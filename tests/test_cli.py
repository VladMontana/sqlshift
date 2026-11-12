"""Модульные тесты для CLI интерфейса sqlshift (Typer CliRunner)."""

from pathlib import Path

from typer.testing import CliRunner

from sqlshift import __version__
from sqlshift.cli.main import app

runner = CliRunner()


def test_cli_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_cli_route_olap() -> None:
    sql = "SELECT date_trunc('month', created_at), count(*) FROM events GROUP BY 1"
    result = runner.invoke(app, ["route", sql])
    assert result.exit_code == 0
    assert "ClickHouse" in result.stdout
    assert "dateTrunc" in result.stdout or "toStartOfMonth" in result.stdout


def test_cli_route_oltp() -> None:
    sql = "SELECT id, email FROM users WHERE id = 1"
    result = runner.invoke(app, ["route", sql])
    assert result.exit_code == 0
    assert "PostgreSQL" in result.stdout
    assert "users" in result.stdout


def test_cli_route_syntax_error() -> None:
    broken_sql = "SELECT FROM WHERE GROUP"
    result = runner.invoke(app, ["route", broken_sql])
    assert result.exit_code == 1
    assert "PARSING ERROR" in result.stdout.upper()


def test_cli_benchmark() -> None:
    result = runner.invoke(app, ["benchmark", "-n", "10"])
    assert result.exit_code == 0
    assert "Benchmark completed successfully" in result.stdout
    assert "RPS" in result.stdout


def test_cli_benchmark_custom_file(tmp_path: Path) -> None:
    sql_file = tmp_path / "custom.sql"
    sql_file.write_text(
        "SELECT * FROM items WHERE id = 1;\n"
        "-- Пропускаемый комментарий\n"
        "SELECT count(*) FROM items GROUP BY category;\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["benchmark", str(sql_file), "-n", "10"])
    assert result.exit_code == 0
    assert "Loaded 2 queries" in result.stdout
    assert "Benchmark completed successfully" in result.stdout


def test_cli_benchmark_file_not_found() -> None:
    result = runner.invoke(app, ["benchmark", "non_existent_file.sql"])
    assert result.exit_code == 1
    assert "FILE NOT FOUND" in result.stdout.upper()


def test_cli_audit_success(tmp_path: Path) -> None:
    sql_file = tmp_path / "queries.sql"
    sql_file.write_text(
        "SELECT id FROM users WHERE id = 1;\n"
        "SELECT date_trunc('month', ts), sum(v) FROM stats GROUP BY 1;\n",
        encoding="utf-8",
    )
    report_file = tmp_path / "report.html"
    result = runner.invoke(app, ["audit", str(sql_file), "-o", str(report_file)])
    assert result.exit_code == 0
    assert "HTML dashboard generated" in result.stdout
    assert report_file.exists()
    assert "<!DOCTYPE html>" in report_file.read_text(encoding="utf-8")


def test_cli_audit_file_not_found() -> None:
    result = runner.invoke(app, ["audit", "missing.sql"])
    assert result.exit_code == 1
    assert "FILE NOT FOUND" in result.stdout.upper()


def test_cli_audit_empty_file(tmp_path: Path) -> None:
    empty_file = tmp_path / "empty.sql"
    empty_file.write_text("-- empty", encoding="utf-8")
    result = runner.invoke(app, ["audit", str(empty_file)])
    assert result.exit_code == 1
    assert "AUDIT ERROR" in result.stdout.upper()


def test_cli_route_with_allowed_tables() -> None:
    """Проверяет маршрутизацию в ClickHouse при явном указании --allowed-tables."""
    sql = "SELECT status, count(*) FROM orders GROUP BY status"
    result = runner.invoke(app, ["route", sql, "--allowed-tables", "orders"])
    assert result.exit_code == 0
    assert "ClickHouse" in result.stdout
    assert "Reason Code" in result.stdout
    assert "ANALYTICAL_CLICKHOUSE" in result.stdout
    assert "Physical Tables" in result.stdout
    assert "orders" in result.stdout


def test_cli_route_with_missing_table() -> None:
    """Проверяет удержание в PostgreSQL при отсутствии таблицы в --allowed-tables."""
    sql = "SELECT status, count(*) FROM payments GROUP BY status"
    result = runner.invoke(app, ["route", sql, "--allowed-tables", "orders"])
    assert result.exit_code == 0
    assert "PostgreSQL" in result.stdout
    assert "Reason Code" in result.stdout
    assert "TABLE_NOT_IN_CATALOG" in result.stdout
    assert "payments" in result.stdout


def test_cli_route_with_pg_only_tables() -> None:
    """Проверяет приоритет --pg-only-tables над --allowed-tables."""
    sql = "SELECT reason, count(*) FROM returns GROUP BY reason"
    result = runner.invoke(
        app,
        ["route", sql, "--allowed-tables", "orders,returns", "--pg-only-tables", "returns"],
    )
    assert result.exit_code == 0
    assert "PostgreSQL" in result.stdout
    assert "Reason Code" in result.stdout
    assert "TABLE_PG_PINNED" in result.stdout


def test_cli_route_with_empty_catalog() -> None:
    """Проверяет, что пустой --allowed-tables блокирует отправку в ClickHouse."""
    sql = "SELECT status, count(*) FROM orders GROUP BY status"
    result = runner.invoke(app, ["route", sql, "--allowed-tables", ""])
    assert result.exit_code == 0
    assert "PostgreSQL" in result.stdout
    assert "TABLE_NOT_IN_CATALOG" in result.stdout


def test_cli_audit_with_catalog(tmp_path: Path) -> None:
    """Проверяет аудит с передачей параметров каталога."""
    sql_file = tmp_path / "catalog_audit.sql"
    sql_file.write_text(
        "SELECT status, count(*) FROM orders GROUP BY status;\nSELECT * FROM users WHERE id = 1;\n",
        encoding="utf-8",
    )
    report_file = tmp_path / "catalog_report.html"
    result = runner.invoke(
        app,
        ["audit", str(sql_file), "-o", str(report_file), "--allowed-tables", "orders"],
    )
    assert result.exit_code == 0
    assert "HTML dashboard generated" in result.stdout
    assert report_file.exists()


def test_cli_benchmark_with_catalog() -> None:
    """Проверяет запуск бенчмарка с каталогом."""
    result = runner.invoke(app, ["benchmark", "-n", "10", "--allowed-tables", "users,orders"])
    assert result.exit_code == 0
    assert "Benchmark completed successfully" in result.stdout
