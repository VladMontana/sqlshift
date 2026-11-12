"""Главная точка входа для CLI-интерфейса sqlshift (Typer)."""

import time
from pathlib import Path
from typing import Annotated

import typer

from sqlshift import AnalyzeAllSql, __version__
from sqlshift.cli.ui import (
    console,
    print_audit_summary,
    print_error_box,
    print_header,
    print_route_decision,
    print_server_banner,
)
from sqlshift.core.catalog import TableCatalog
from sqlshift.core.router import SQLShiftRouter
from sqlshift.utils.exception import SQLShiftError

app = typer.Typer(
    name="sqlshift",
    help="SQLShift: Умный маршрутизатор и транспайлер SQL-запросов (PostgreSQL -> ClickHouse)",
    no_args_is_help=True,
    add_completion=False,
)


def _parse_table_list(tables: str | list[str] | None) -> list[str] | None:
    """Парсит строку с разделителями-запятыми или список строк в чистый список таблиц."""
    if tables is None:
        return None
    if isinstance(tables, str):
        raw_items = tables.split(",")
    else:
        raw_items = []
        for item in tables:
            raw_items.extend(item.split(","))
    return [t.strip() for t in raw_items if t.strip()]


@app.command(name="route")
def route_query(
    sql: Annotated[
        str,
        typer.Argument(
            help="Текст SQL-запроса на диалекте PostgreSQL для анализа и маршрутизации",
            show_default=False,
        ),
    ],
    allowed_tables: Annotated[
        str | None,
        typer.Option(
            "--allowed-tables",
            help="Список таблиц, доступных в ClickHouse (через запятую: 'orders,order_items')",
        ),
    ] = None,
    pg_only_tables: Annotated[
        str | None,
        typer.Option(
            "--pg-only-tables",
            help="Список таблиц, закрепленных за PostgreSQL (через запятую: 'returns')",
        ),
    ] = None,
) -> None:
    """Анализирует SQL-запрос, определяет базу (PostgreSQL или ClickHouse) и транспайлит диалект."""
    catalog = None
    if allowed_tables is not None or pg_only_tables is not None:
        allowed_list = _parse_table_list(allowed_tables) if allowed_tables is not None else None
        pg_only_list = _parse_table_list(pg_only_tables) if pg_only_tables is not None else None
        catalog = TableCatalog(
            allowed_tables=allowed_list,
            pg_only_tables=pg_only_list,
        )

    router = SQLShiftRouter(catalog=catalog)
    try:
        decision = router.route(sql)
        print_route_decision(decision, sql)
    except SQLShiftError as exc:
        print_error_box("Parsing Error", str(exc))
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        print_error_box("Unexpected Error", str(exc))
        raise typer.Exit(code=1) from exc


@app.command(name="version")
def version_cmd() -> None:
    """Показывает текущую установленную версию библиотеки sqlshift."""
    print_header(f"v{__version__}")


@app.command(name="audit")
def audit_cmd(
    file: Annotated[
        Path,
        typer.Argument(
            help="Путь к .sql файлу с запросами для комплексного анализа",
            show_default=False,
        ),
    ],
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Путь для сохранения интерактивного HTML-отчета",
        ),
    ] = Path("sqlshift_report.html"),
    title: Annotated[
        str,
        typer.Option(
            "--title",
            "-t",
            help="Заголовок HTML-отчета",
        ),
    ] = "SQLShift — Database Audit Report",
    open_browser: Annotated[
        bool,
        typer.Option(
            "--open",
            help="Автоматически открыть сгенерированный HTML-отчет в браузере",
        ),
    ] = False,
    allowed_tables: Annotated[
        str | None,
        typer.Option(
            "--allowed-tables",
            help="Список таблиц, доступных в ClickHouse (через запятую)",
        ),
    ] = None,
    pg_only_tables: Annotated[
        str | None,
        typer.Option(
            "--pg-only-tables",
            help="Список таблиц, закрепленных за PostgreSQL (через запятую)",
        ),
    ] = None,
) -> None:
    """Выполняет пакетный аудит SQL-запросов из файла и генерирует интерактивный HTML-дашборд."""
    if not file.exists() or not file.is_file():
        print_error_box("File Not Found", f"Указанный файл не существует: {file}")
        raise typer.Exit(code=1)

    try:
        catalog = None
        if allowed_tables is not None or pg_only_tables is not None:
            allowed_list = _parse_table_list(allowed_tables) if allowed_tables is not None else None
            pg_only_list = _parse_table_list(pg_only_tables) if pg_only_tables is not None else None
            catalog = TableCatalog(allowed_tables=allowed_list, pg_only_tables=pg_only_list)

        analyzer = AnalyzeAllSql.from_file(file, catalog=catalog)
        summary = analyzer.analyze()
        analyzer.to_html(output_path=output, title=title)
        print_audit_summary(summary, output)

        if open_browser:
            import webbrowser

            webbrowser.open(output.resolve().as_uri())
    except Exception as exc:
        print_error_box("Audit Error", str(exc))
        raise typer.Exit(code=1) from exc


@app.command(name="benchmark")
def benchmark_cmd(
    file: Annotated[
        Path | None,
        typer.Argument(
            help="Путь к .sql файлу с запросами (опционально, по умолчанию встроенный тест)",
            show_default=False,
        ),
    ] = None,
    iterations: Annotated[
        int,
        typer.Option(
            "--count",
            "-n",
            help="Количество итераций для стресс-теста роутера в памяти",
        ),
    ] = 1000,
    allowed_tables: Annotated[
        str | None,
        typer.Option(
            "--allowed-tables",
            help="Список таблиц, доступных в ClickHouse (через запятую)",
        ),
    ] = None,
    pg_only_tables: Annotated[
        str | None,
        typer.Option(
            "--pg-only-tables",
            help="Список таблиц, закрепленных за PostgreSQL (через запятую)",
        ),
    ] = None,
) -> None:
    """Запускает бенчмарк скорости роутинга: по встроенным шаблонам или по вашему .sql файлу."""
    print_header("Performance Benchmark ⚡")
    catalog = None
    if allowed_tables is not None or pg_only_tables is not None:
        allowed_list = _parse_table_list(allowed_tables) if allowed_tables is not None else None
        pg_only_list = _parse_table_list(pg_only_tables) if pg_only_tables is not None else None
        catalog = TableCatalog(allowed_tables=allowed_list, pg_only_tables=pg_only_list)
    router = SQLShiftRouter(catalog=catalog)

    if file is not None:
        if not file.exists() or not file.is_file():
            print_error_box("File Not Found", f"Указанный файл не существует: {file}")
            raise typer.Exit(code=1)

        try:
            sample_queries = AnalyzeAllSql.from_file(file).queries
        except Exception as exc:
            print_error_box("Read Error", f"Не удалось прочитать файл {file.name}: {exc}")
            raise typer.Exit(code=1) from exc

        if not sample_queries:
            print_error_box("Empty File", f"В файле '{file.name}' не найдено SQL-запросов.")
            raise typer.Exit(code=1)

        console.print(
            f"  [dim]Loaded {len(sample_queries)} queries from '{file.name}'. "
            f"Running {iterations} iterations...[/]"
        )
    else:
        sample_queries = [
            "SELECT * FROM users WHERE id = 42",
            "INSERT INTO audit_logs (k, v) VALUES ('action', 'login')",
            "SELECT count(*) FROM events",
            "SELECT date_trunc('month', ts), sum(amount) FROM payments GROUP BY 1",
            "SELECT u.id, o.amount FROM users u JOIN orders o ON u.id = o.user_id",
        ]
        console.print(
            f"  [dim]Running built-in benchmark across 5 AST patterns "
            f"({iterations} iterations)...[/]"
        )

    total_queries = iterations * len(sample_queries)

    start = time.perf_counter()
    for _ in range(iterations):
        for q in sample_queries:
            router.route(q)
    total_sec = time.perf_counter() - start

    avg_ms = (total_sec / total_queries) * 1000.0
    rps = total_queries / total_sec

    console.print()
    console.print("  [bold green]✓ Benchmark completed successfully[/]")
    console.print(f"  • Total queries: [bold cyan]{total_queries:,}[/]")
    console.print(f"  • Total time:    [bold cyan]{total_sec:.3f} s[/]")
    latency_us = avg_ms * 1000.0
    console.print(
        f"  • Latency:       [bold green]{avg_ms:.3f} ms[/] / query "
        f"([bold green]{latency_us:.1f} µs[/])"
    )
    console.print(f"  • Throughput:    [bold yellow]{rps:,.0f} queries/sec (RPS)[/]")
    console.print()


@app.command(name="serve")
def serve_cmd(
    host: Annotated[str, typer.Option("--host", "-h", help="Хост сервера")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", "-p", help="Порт сервера")] = 8000,
    reload: Annotated[bool, typer.Option("--reload/--no-reload", help="Автоперезагрузка")] = False,
) -> None:
    """Запускает HTTP Gateway сервер (FastAPI / Uvicorn)."""
    try:
        import uvicorn
    except ImportError as exc:
        print_error_box(
            "Missing Dependencies",
            "Для запуска сервера установите extra 'server': pip install 'sqlshift[server]'",
        )
        raise typer.Exit(code=1) from exc

    print_server_banner(host, port)
    uvicorn.run(
        "sqlshift.server.app:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    app()
