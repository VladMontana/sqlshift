"""Красивый CLI интерфейс в стиле FastAPI (Typer + Rich)."""

import sys

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from sqlshift.core.models import RouteDecision

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        reconfigure_fn = getattr(sys.stdout, "reconfigure")
        reconfigure_fn(encoding="utf-8")
    except Exception:
        pass

console = Console()

COLOR_BRAND = "#0d9488"  # Изумрудный (главный бренд)
COLOR_TARGET = "#0284c7"  # Лазурный (база данных)
COLOR_COMPLEX = "#7c3aed"  # Фиолетовый (сложность)
COLOR_REASON = "#0f766e"  # Бирюзовый (причина)
COLOR_INFO = "#059669"  # Зеленый (инфо)
COLOR_ERROR = "#dc2626"  # Красный (ошибки)

AnyText = str | Text


def print_header(title: str = "Query Router & Transpiler 🚀") -> None:
    """Печатает заголовок утилиты с фирменным бейджем SQLShift."""
    console.print()
    badge = Text(" SQLShift ", style="bold white on " + COLOR_BRAND)
    text = Text(f" {title}", style="bold white")
    console.print(badge + text)
    console.print()


def print_badge_line(label: str, content: AnyText, badge_bg: str = COLOR_TARGET) -> None:
    """Печатает строку с выровненным бейджем слева в точности как у FastAPI CLI."""
    badge_label = f" {label.center(8)} "
    badge = Text(badge_label, style=f"bold white on {badge_bg}")
    if isinstance(content, str):
        content_text = Text(content)
    else:
        content_text = content
    console.print(Text("  ") + badge + Text(" ") + content_text)


def print_route_decision(decision: RouteDecision, original_sql: str) -> None:
    """Отображает результат маршрутизации и транспайлинга в стиле FastAPI dev."""
    print_header()

    # 1. Целевая база
    if decision.target == "clickhouse":
        target_styled = Text("ClickHouse (OLAP) 📦", style="bold yellow")
    else:
        target_styled = Text("PostgreSQL (OLTP) 🐘", style="bold green")
    print_badge_line("target", target_styled, badge_bg=COLOR_TARGET)

    # 2. Сложность
    complexity_colors = {
        "low": "bold green",
        "medium": "bold yellow",
        "high": "bold red",
    }
    c_color = complexity_colors.get(decision.estimated_complexity, "white")
    complex_styled = Text(f"{decision.estimated_complexity.upper()} ⚡", style=c_color)
    print_badge_line("complex", complex_styled, badge_bg=COLOR_COMPLEX)

    # 3. Причина маршрутизации
    reason_styled = Text(f"{decision.reason}", style="white")
    print_badge_line("reason", reason_styled, badge_bg=COLOR_REASON)

    console.print()

    # 4. Исходный SQL запрос (подсветка PostgreSQL)
    print_badge_line("input", Text("PostgreSQL query:", style="dim white"), badge_bg="#334155")
    console.print(
        Panel(
            Syntax(
                original_sql.strip(),
                "sql",
                theme="monokai",
                line_numbers=False,
                word_wrap=True,
            ),
            border_style="dim white",
            padding=(0, 1),
        )
    )

    # 5. Итоговый SQL запрос (если уходит в ClickHouse — подсвечиваем транспайлинг)
    if decision.target == "clickhouse":
        print_badge_line(
            "output",
            Text("ClickHouse transpiled SQL:", style="bold yellow"),
            badge_bg="#854d0e",
        )
        console.print(
            Panel(
                Syntax(
                    decision.sql.strip(),
                    "sql",
                    theme="monokai",
                    line_numbers=False,
                    word_wrap=True,
                ),
                border_style="yellow",
                padding=(0, 1),
            )
        )
    else:
        print_badge_line(
            "output",
            Text("Execution query (unaltered):", style="bold green"),
            badge_bg="#15803d",
        )
        console.print(
            Panel(
                Syntax(
                    decision.sql.strip(),
                    "sql",
                    theme="monokai",
                    line_numbers=False,
                    word_wrap=True,
                ),
                border_style="green",
                padding=(0, 1),
            )
        )
    console.print()


def print_server_banner(host: str, port: int) -> None:
    """Печатает стартовый баннер запуска сервера точь-в-точь как у fastapi dev."""
    print_header("Starting Gateway Server 🚀")
    print_badge_line(
        "server",
        Text(f"Server started at http://{host}:{port}", style="bold cyan"),
        badge_bg=COLOR_TARGET,
    )
    print_badge_line(
        "docs",
        Text(f"Interactive documentation at http://{host}:{port}/docs", style="bold cyan"),
        badge_bg=COLOR_TARGET,
    )
    print_badge_line(
        "status",
        Text("Ready to route queries via REST API", style="bold green"),
        badge_bg=COLOR_INFO,
    )
    console.print()


def print_error_box(title: str, detail: str) -> None:
    """Отображает ошибку с красивым красным бейджем."""
    console.print()
    badge = Text(f" {title.upper()} ", style="bold white on " + COLOR_ERROR)
    console.print(badge + Text(f" {detail}", style="bold red"))
    console.print()
