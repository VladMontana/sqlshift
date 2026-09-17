"""Комплексные тесты для SQLShiftRouter: функциональность, логирование и замеры скорости."""

import logging
import time

import pytest

from sqlshift import (
    RouteDecision,
    SQLParsingError,
    SQLRouter,
    SQLShiftRouter,
)

# Настраиваем логгер для тестов
logger = logging.getLogger("sqlshift.test")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def _route_with_timing(router: SQLShiftRouter, sql: str) -> tuple[RouteDecision, float]:
    """Вспомогательная функция: выполняет роутинг и замеряет время в миллисекундах."""
    start = time.perf_counter()
    decision = router.route(sql)
    duration_ms = (time.perf_counter() - start) * 1000.0

    logger.info(
        "ROUTED in %.3f ms | Target: %-10s | Complexity: %-6s | Reason: %s\n"
        "  IN  SQL: %s\n"
        "  OUT SQL: %s",
        duration_ms,
        decision.target,
        decision.estimated_complexity,
        decision.reason,
        sql,
        decision.sql,
    )
    return decision, duration_ms


@pytest.fixture
def router() -> SQLShiftRouter:
    """Фикстура создания чистого роутера."""
    return SQLRouter()


# ============================================================================
# 1. Тесты OLTP запросов (транзакционные операции, чтение по ключу)
# ============================================================================


def test_oltp_primary_key_lookup(router: SQLShiftRouter) -> None:
    sql = "SELECT id, email FROM users WHERE id = 42"
    decision, duration_ms = _route_with_timing(router, sql)

    assert decision.target == "postgresql"
    assert not decision.is_analytical
    assert decision.estimated_complexity == "low"
    assert "WHERE id = 42" in decision.sql
    assert duration_ms >= 0.0


def test_oltp_simple_select_limit(router: SQLShiftRouter) -> None:
    sql = "SELECT name, status FROM tenants LIMIT 10"
    decision, _ = _route_with_timing(router, sql)

    assert decision.target == "postgresql"
    assert not decision.is_analytical
    assert decision.estimated_complexity == "low"


# ============================================================================
# 2. Тесты DML операций (INSERT / UPDATE / DELETE всегда идут в Postgres)
# ============================================================================


@pytest.mark.parametrize(
    "dml_query,expected_keyword",
    [
        ("INSERT INTO audit_logs (user_id, action) VALUES (1, 'login')", "INSERT"),
        ("UPDATE accounts SET balance = balance - 100 WHERE id = 5", "UPDATE"),
        ("DELETE FROM sessions WHERE expires_at < NOW()", "DELETE"),
    ],
)
def test_dml_always_routes_to_postgresql(
    router: SQLShiftRouter, dml_query: str, expected_keyword: str
) -> None:
    decision, _ = _route_with_timing(router, dml_query)

    assert decision.target == "postgresql"
    assert not decision.is_analytical
    assert decision.estimated_complexity == "low"
    assert expected_keyword in decision.reason


# ============================================================================
# 3. Тесты аналитических OLAP запросов и транспайлинга в ClickHouse
# ============================================================================


def test_olap_aggregation_count(router: SQLShiftRouter) -> None:
    sql = "SELECT count(*) FROM analytics_events"
    decision, _ = _route_with_timing(router, sql)

    assert decision.target == "clickhouse"
    assert decision.is_analytical
    assert "COUNT" in decision.reason
    assert "COUNT(*)" in decision.sql


def test_olap_group_by_with_date_trunc(router: SQLShiftRouter) -> None:
    sql = "SELECT date_trunc('month', created_at), sum(amount) FROM payments GROUP BY 1"
    decision, _ = _route_with_timing(router, sql)

    assert decision.target == "clickhouse"
    assert decision.is_analytical
    assert decision.estimated_complexity == "high"
    # Проверяем корректность транспайлинга в диалект ClickHouse
    assert "dateTrunc" in decision.sql or "toStartOfMonth" in decision.sql
    assert "GROUP BY 1" in decision.sql


def test_olap_window_function(router: SQLShiftRouter) -> None:
    sql = (
        "SELECT user_id, amount, "
        "ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at DESC) FROM orders"
    )
    decision, _ = _route_with_timing(router, sql)

    assert decision.target == "clickhouse"
    assert decision.is_analytical
    assert decision.estimated_complexity == "high"
    assert "оконных" in decision.reason or "Window" in decision.reason


def test_olap_cte_expression(router: SQLShiftRouter) -> None:
    sql = """
    WITH monthly_revenue AS (
        SELECT date_trunc('month', paid_at) AS month, sum(total) AS rev
        FROM invoices
        GROUP BY 1
    )
    SELECT month, rev FROM monthly_revenue WHERE rev > 10000
    """
    decision, _ = _route_with_timing(router, sql)

    assert decision.target == "clickhouse"
    assert decision.is_analytical
    assert decision.estimated_complexity == "high"
    assert "CTE" in decision.reason


def test_olap_joins(router: SQLShiftRouter) -> None:
    sql = """
    SELECT u.id, o.amount, p.status
    FROM users u
    JOIN orders o ON u.id = o.user_id
    JOIN payments p ON o.id = p.order_id
    """
    decision, _ = _route_with_timing(router, sql)

    assert decision.target == "clickhouse"
    assert decision.is_analytical
    assert decision.estimated_complexity == "high"
    assert "2" in decision.reason or "соединени" in decision.reason


# ============================================================================
# 4. Тесты валидации и обработки синтаксических ошибок
# ============================================================================


@pytest.mark.parametrize("empty_query", ["", "   ", "\n\t  "])
def test_empty_sql_raises_parsing_error(router: SQLShiftRouter, empty_query: str) -> None:
    with pytest.raises(SQLParsingError) as exc_info:
        router.route(empty_query)
    logger.info("Успешно перехвачена ошибка пустого запроса: %s", exc_info.value)


def test_syntax_error_raises_parsing_error(router: SQLShiftRouter) -> None:
    broken_sql = "SELECT FROM WHERE GROUP ORDER"
    with pytest.raises(SQLParsingError) as exc_info:
        router.route(broken_sql)
    logger.info("Успешно перехвачена синтаксическая ошибка: %s", exc_info.value)


# ============================================================================
# 5. Нагрузочный бенчмарк (замер производительности чистого in-memory роутинга)
# ============================================================================


def test_benchmark_in_memory_routing_speed(router: SQLShiftRouter) -> None:
    """Бенчмарк: прогон 1000 разнообразных запросов для оценки RPS и latency."""
    sample_queries = [
        "SELECT * FROM users WHERE id = 1",
        "INSERT INTO metrics (k, v) VALUES ('cpu', 99)",
        "SELECT count(*) FROM events",
        "SELECT date_trunc('day', ts), sum(v) FROM stats GROUP BY 1",
        "SELECT a.x, b.y FROM a JOIN b ON a.id = b.id JOIN c ON b.id = c.id",
    ]

    iterations = 200  # 200 * 5 = 1000 вызовов роутинга
    total_calls = iterations * len(sample_queries)

    start_time = time.perf_counter()
    for _ in range(iterations):
        for q in sample_queries:
            router.route(q)
    total_time = time.perf_counter() - start_time

    avg_ms = (total_time / total_calls) * 1000.0
    rps = total_calls / total_time

    logger.info(
        "\n==================== BENCHMARK RESULTS ====================\n"
        "  Total Queries Routed: %d\n"
        "  Total Time:           %.3f seconds\n"
        "  Average Latency:      %.3f ms / query (%.1f µs)\n"
        "  Throughput:           %.0f queries / sec (RPS)\n"
        "===========================================================",
        total_calls,
        total_time,
        avg_ms,
        avg_ms * 1000.0,
        rps,
    )

    # Среднее время одного роутинга должно быть меньше 1.5 мс даже на скромном железе
    assert avg_ms < 1.5, f"Слишком медленный роутинг: {avg_ms:.3f} мс / запрос"
