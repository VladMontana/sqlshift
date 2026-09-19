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
