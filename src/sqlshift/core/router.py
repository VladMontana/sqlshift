from sqlglot import exp

from sqlshift.core.analyzer import analyze_query
from sqlshift.core.catalog import TableCatalog, extract_physical_tables
from sqlshift.core.models import RouteDecision
from sqlshift.core.parser import parse_sql
from sqlshift.core.transpiler import transpile_to_clickhouse


class SQLShiftRouter:
    """In-memory маршрутизатор и транспайлер SQL-запросов."""

    def __init__(
        self,
        default_dialect: str = "postgres",
        catalog: TableCatalog | None = None,
    ) -> None:
        self.default_dialect = default_dialect
        self.catalog = catalog

    def route_tree(self, tree: exp.Expression, original_sql: str | None = None) -> RouteDecision:
        """Формирует решение о маршрутизации на основе уже разобранного AST-дерева.

        Args:
            tree: AST-выражение sqlglot.
            original_sql: Опциональный исходный текст SQL.

        Returns:
            RouteDecision: Решение (база назначения, итоговый SQL, сложность, причина).
        """
        pg_sql = (
            original_sql.strip()
            if original_sql is not None
            else tree.sql(dialect=self.default_dialect)
        )
        catalog_checked = self.catalog is not None

        # 1. Чтение с блокировкой строк (FOR UPDATE / FOR SHARE) -> строго PostgreSQL
        if tree.find(exp.Lock):
            physical_tables = extract_physical_tables(tree)
            return RouteDecision(
                target="postgresql",
                sql=pg_sql,
                is_analytical=False,
                estimated_complexity="low",
                reason="Чтение с блокировкой строк (FOR UPDATE/SHARE). Выбрана PostgreSQL.",
                reason_code="LOCKING_READ",
                physical_tables=physical_tables,
                catalog_checked=catalog_checked,
            )

        # 2. Любая DML-операция (DML на верхнем уровне или модифицирующий CTE) -> PostgreSQL
        if tree.find(exp.Insert, exp.Update, exp.Delete):
            physical_tables = extract_physical_tables(tree)
            if isinstance(tree, (exp.Insert, exp.Update, exp.Delete)):
                reason = f"Транзакционная операция (DML), ({tree.key.upper()})"
            else:
                reason = (
                    "Модифицирующая DML-операция (включая модифицирующие CTE). "
                    "Выбрана PostgreSQL."
                )
            return RouteDecision(
                target="postgresql",
                sql=pg_sql,
                is_analytical=False,
                estimated_complexity="low",
                reason=reason,
                reason_code="DML_OPERATION",
                physical_tables=physical_tables,
                catalog_checked=catalog_checked,
            )

        # 4. Команды управления DDL / TCL -> строго PostgreSQL
        if isinstance(
            tree,
            (
                exp.Create,
                exp.Drop,
                exp.TruncateTable,
                exp.Alter,
                exp.Transaction,
                exp.Commit,
                exp.Rollback,
                exp.Command,
                exp.Set,
            ),
        ):
            return RouteDecision(
                target="postgresql",
                sql=pg_sql,
                is_analytical=False,
                estimated_complexity="low",
                reason=f"Команда управления DDL/TCL, ({tree.key.upper()})",
                reason_code="DDL_TCL_COMMAND",
                physical_tables=[],
                catalog_checked=catalog_checked,
            )

        # 5. Анализ синтаксических признаков запроса
        is_analytical, complexity, reason = analyze_query(tree)
        physical_tables = extract_physical_tables(tree)

        # 6. Простые неаналитические запросы (OLTP) -> PostgreSQL
        if not is_analytical:
            return RouteDecision(
                target="postgresql",
                sql=pg_sql,
                is_analytical=False,
                estimated_complexity=complexity,
                reason=reason,
                reason_code="NON_ANALYTICAL_QUERY",
                physical_tables=physical_tables,
                catalog_checked=catalog_checked,
            )

        # 7. Аналитические запросы (OLAP)
        # Режим А: Без каталога (catalog is None) — 100% обратная совместимость
        if self.catalog is None:
            final_sql = transpile_to_clickhouse(tree)
            return RouteDecision(
                target="clickhouse",
                sql=final_sql,
                is_analytical=True,
                estimated_complexity=complexity,
                reason=reason,
                reason_code="ANALYTICAL_CLICKHOUSE",
                physical_tables=physical_tables,
                catalog_checked=False,
            )

        # Режим Б: С каталогом — проверка допустимости таблиц
        # Б.1. Запросы без физических таблиц (например, SELECT 1 GROUP BY 1) -> PostgreSQL
        if not physical_tables:
            return RouteDecision(
                target="postgresql",
                sql=pg_sql,
                is_analytical=True,
                estimated_complexity=complexity,
                reason=(
                    f"{reason}. Запрос не содержит физических таблиц для чтения из ClickHouse. "
                    "Выбрана PostgreSQL."
                ),
                reason_code="NO_PHYSICAL_TABLES",
                physical_tables=[],
                catalog_checked=True,
            )

        # Б.2. Проверка допуска физических таблиц по каталогу
        admission = self.catalog.check_admission(physical_tables)
        if admission.is_admitted:
            final_sql = transpile_to_clickhouse(tree)
            return RouteDecision(
                target="clickhouse",
                sql=final_sql,
                is_analytical=True,
                estimated_complexity=complexity,
                reason=f"{reason}. {admission.reason_description}",
                reason_code="ANALYTICAL_CLICKHOUSE",
                physical_tables=physical_tables,
                catalog_checked=True,
            )
        else:
            return RouteDecision(
                target="postgresql",
                sql=pg_sql,
                is_analytical=True,
                estimated_complexity=complexity,
                reason=f"{reason}. {admission.reason_description}",
                reason_code=admission.reason_code,
                physical_tables=physical_tables,
                catalog_checked=True,
            )

    def route(self, sql: str) -> RouteDecision:
        """Анализирует SQL-запрос и формирует решение о маршрутизации.

        Args:
            sql: Исходный текст SQL (в синтаксисе PostgreSQL).

        Returns:
            RouteDecision: Решение (база назначения, итоговый SQL, сложность, причина).
        """
        tree = parse_sql(sql, dialect=self.default_dialect)
        return self.route_tree(tree, original_sql=sql)
