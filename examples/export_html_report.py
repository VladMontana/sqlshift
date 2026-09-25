"""Пример пакетного анализа SQL-запросов и генерации интерактивного HTML-дашборда.

Демонстрирует:
1. Загрузку SQL-запросов из .sql файла через `AnalyzeAllSql.from_file(...)`.
2. Анализ запросов и получение объекта сводки `BatchAuditSummary`.
3. Экспорт самодостаточного интерактивного HTML-отчета на диск.
4. Доступ к метрикам и списку архитектурных узких мест (Bottlenecks) в Python.
"""

import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore
    except Exception:
        pass

from sqlshift import AnalyzeAllSql


def main() -> None:
    # Путь к файлу с запросами
    sql_file = Path(__file__).parent / "queries.sql"
    output_report = Path(__file__).parent / "sqlshift_report.html"

    print("=" * 70)
    print(">>> SQLShift -- Пакетный аудит запросов и экспорт HTML-дашборда")
    print("=" * 70)
    print(f"[*] Чтение SQL-запросов из: {sql_file}")

    # Инициализация анализатора из файла
    analyzer = AnalyzeAllSql.from_file(sql_file)

    # Запуск анализа
    summary = analyzer.analyze()

    print(f"\n[+] Проанализировано запросов: {summary.total_queries}")
    pg_pct = round(summary.postgres_count / summary.total_queries * 100, 1)
    ch_pct = round(summary.clickhouse_count / summary.total_queries * 100, 1)
    print(f"  • PostgreSQL (OLTP): {summary.postgres_count} ({pg_pct}%)")
    print(f"  • ClickHouse (OLAP): {summary.clickhouse_count} ({ch_pct}%)")
    print(
        f"  • Сложность: {summary.complexity_counts['low']} Low / "
        f"{summary.complexity_counts['medium']} Medium / "
        f"{summary.complexity_counts['high']} High"
    )

    if summary.bottleneck_detected:
        print("\n[!] Обнаруженные потенциальные узкие места:")
        for name, count in summary.bottleneck_detected.items():
            print(f"  • {name}: {count} раз(а)")
    else:
        print("\n[✓] Критических архитектурных узких мест не обнаружено.")

    # Генерация и экспорт HTML-отчета
    print(f"\n[*] Экспорт интерактивного HTML-отчета в: {output_report.resolve()}")
    analyzer.to_html(output_path=output_report, title="SQLShift — Audit Demo Report")

    print(f"[OK] Дашборд успешно сохранен ({output_report.stat().st_size} байт).")
    print("     Вы можете открыть его в любом браузере для интерактивного анализа.")


if __name__ == "__main__":
    main()
