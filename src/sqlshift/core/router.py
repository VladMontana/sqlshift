from sqlshift.core.analyzer import analyze_query
from sqlshift.core.models import RouteDecision, TargetDatabase
from sqlshift.core.parser import parse_sql
from sqlshift.core.transpiler import transpile_to_clickhouse


class SQLShiftRouter:
    """In-memory маршрутизатор и транспайлер SQL-запросов."""

    def __init__(self, default_dialect: str = "postgres") -> None:
        self.default_dialect = default_dialect

    def route(self, sql: str) -> RouteDecision:
        """Анализирует SQL-запрос и формирует решение о маршрутизации.
        Args:
            sql: Исходный текст SQL (в синтаксисе PostgreSQL).
        Returns:
            RouteDecision: Решение (база назначения, итоговый SQL, сложность, причина).
        """
        tree = parse_sql(sql, dialect=self.default_dialect)

        is_analytical, complexity, reason = analyze_query(tree)

        if is_analytical:
            target: TargetDatabase = "clickhouse"
            final_sql = transpile_to_clickhouse(tree)
        else:
            target: TargetDatabase = "postgresql"
            final_sql = sql.strip()

        return RouteDecision(
            target=target,
            sql=final_sql,
            is_analytical=is_analytical,
            estimated_complexity=complexity,
            reason=reason,
        )
