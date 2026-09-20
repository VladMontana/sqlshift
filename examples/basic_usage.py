"""Базовый пример использования библиотеки sqlshift в памяти (без подключения к БД).

Демонстрирует:
1. Создание SQLRouter.
2. Автоматическое определение типа запроса (OLTP в PostgreSQL vs OLAP в ClickHouse).
3. Оценку сложности запроса (low, medium, high).
4. Транспайлинг диалекта (PostgreSQL -> ClickHouse).
5. Обработку синтаксических ошибок в SQL.
"""

import sys

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # ty: ignore[call-non-callable]
    except Exception:
        pass

from sqlshift import SQLRouter
from sqlshift.utils.exception import SQLParsingError


def main() -> None:
    # Инициализация легковесного in-memory роутера
    router = SQLRouter()

    sample_queries = [
        (
            "Транзакционный точечный поиск (OLTP):",
            "SELECT id, email, created_at FROM users WHERE id = 100;",
        ),
        (
            "Транзакционная вставка данных (DML):",
            "INSERT INTO audit_logs (user_id, event, created_at) VALUES (100, 'login', NOW());",
        ),
        (
            "Аналитический запрос с агрегацией (OLAP):",
            "SELECT count(*) FROM analytics_events WHERE status = 'completed';",
        ),
        (
            "Аналитический запрос с группировкой и усечением даты (OLAP + Transpile):",
            "SELECT date_trunc('month', paid_at), sum(amount) FROM payments GROUP BY 1;",
        ),
        (
            "Сложная аналитическая выборка с JOIN (OLAP):",
            (
                "SELECT u.name, count(o.id) AS total_orders, sum(p.amount) AS total_spent "
                "FROM users u "
                "JOIN orders o ON u.id = o.user_id "
                "JOIN payments p ON o.id = p.order_id "
                "GROUP BY u.name;"
            ),
        ),
    ]

    print("=" * 70)
    print(">>> SQLShift -- Демонстрация работы SQLRouter в памяти")
    print("=" * 70)

    for description, sql in sample_queries:
        print(f"\n[*] {description}")
        print(f"  SQL: {sql}")

        # Маршрутизация и анализ
        decision = router.route(sql)

        # Вывод результатов
        badge = "[PostgreSQL]" if decision.target == "postgresql" else "[ClickHouse]"
        print(f"  Целевая БД:    {badge}")
        print(f"  Аналитический: {decision.is_analytical}")
        print(f"  Сложность:     {decision.estimated_complexity.upper()}")
        print(f"  Причина:       {decision.reason}")

        if decision.target == "clickhouse":
            print(f"  Итоговый SQL (ClickHouse): {decision.sql}")

    # Демонстрация перехвата ошибок парсинга
    print("\n" + "=" * 70)
    print("[!] Демонстрация обработки ошибок парсинга (SQLParsingError):")
    broken_sql = "SELECT FROM WHERE;"
    print(f"  Некорректный SQL: {broken_sql}")
    try:
        router.route(broken_sql)
    except SQLParsingError as exc:
        print(f"  [Перехвачено исключение] {type(exc).__name__}: {exc}")

    print("\n[OK] Демонстрация базового использования успешно завершена!")


if __name__ == "__main__":
    main()
