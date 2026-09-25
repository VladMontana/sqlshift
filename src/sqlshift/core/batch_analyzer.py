from collections import Counter
from pathlib import Path

from sqlglot import exp

from sqlshift.core.models import BatchAuditSummary, QueryAuditItem
from sqlshift.core.parser import parse_sql
from sqlshift.core.router import SQLShiftRouter


class AnalyzeAllSql:
    def __init__(self, queries: list[str], router: SQLShiftRouter | None = None) -> None:
        self.queries = queries
        self.router = router or SQLShiftRouter()

    @classmethod
    def from_file(
        cls, file_path: str | Path, router: SQLShiftRouter | None = None
    ) -> "AnalyzeAllSql":
        file = Path(file_path)
        if not file.exists():
            raise FileNotFoundError(f"Файл не найден: {file}")
        if file.is_dir():
            raise ValueError(f"Ожидается файл, получен каталог: {file}")

        content = file.read_text(encoding="utf-8")

        raw_statements = content.split(";")
        queries: list[str] = []

        for stmnt in raw_statements:
            lines = [line for line in stmnt.splitlines() if not line.strip().startswith("--")]
            cleaned = "\n".join(lines).strip()
            if cleaned:
                queries.append(cleaned)

        if not queries:
            raise ValueError(f"В файле {file} не найдены валидные SQL-запросы")

        return cls(queries, router)

    @classmethod
    def from_list(cls, queries: list[str], router: SQLShiftRouter | None = None) -> "AnalyzeAllSql":
        if not queries:
            raise ValueError("Список запросов пуст")
        return cls(queries, router)

    def _detect_bottlenecks(self, tree: exp.Expression) -> list[str]:
        """Анализирует AST и выявляет архитектурные узкие места (Bottlenecks)."""
        bottlenecks: list[str] = []
        # 1. Тяжелые многотабличные JOIN (3 и более)
        joins = list(tree.find_all(exp.Join))
        if len(joins) >= 3:
            bottlenecks.append(f"Heavy JOIN: {len(joins)} tables joined")
        # 2. Длинные цепочки CTE (WITH ... AS)
        ctes = list(tree.find_all(exp.CTE))
        if len(ctes) >= 2:
            bottlenecks.append(f"Multiple CTE chain: {len(ctes)} CTEs")
        # 3. Оконные функции (OVER (...))
        windows = list(tree.find_all(exp.Window))
        if windows:
            bottlenecks.append(f"Window functions: {len(windows)}")
        # 4. Вложенные подзапросы
        subqueries = list(tree.find_all(exp.Subquery))
        if len(subqueries) >= 2:
            bottlenecks.append(f"Deep nested subqueries: {len(subqueries)}")
        return bottlenecks

    def analyze(self) -> BatchAuditSummary:
        """Выполняет пакетный анализ всех загруженных SQL-запросов.

        Возвращает:
            BatchAuditSummary: Сводная статистика аудита и детальная информация по каждому запросу.
        """
        items: list[QueryAuditItem] = []
        bottleneck_counter: Counter[str] = Counter()

        for idx, sql in enumerate(self.queries, start=1):
            decision = self.router.route(sql)

            # Парсим AST для поиска архитектурных узких мест
            try:
                tree = parse_sql(sql)
                bottlenecks = self._detect_bottlenecks(tree)
            except Exception:
                bottlenecks = ["Parsing issue detected during deep AST audit"]

            for b in bottlenecks:
                b_category = b.split(":")[0].strip()
                bottleneck_counter[b_category] += 1

            items.append(
                QueryAuditItem(
                    index=idx,
                    original_sql=sql,
                    decision=decision,
                    bottlenecks=bottlenecks,
                )
            )

        postgres_count = sum(1 for item in items if item.decision.target == "postgresql")
        clickhouse_count = sum(1 for item in items if item.decision.target == "clickhouse")

        complexity_counts = {
            "low": sum(1 for item in items if item.decision.estimated_complexity == "low"),
            "medium": sum(1 for item in items if item.decision.estimated_complexity == "medium"),
            "high": sum(1 for item in items if item.decision.estimated_complexity == "high"),
        }

        return BatchAuditSummary(
            total_queries=len(items),
            postgres_count=postgres_count,
            clickhouse_count=clickhouse_count,
            complexity_counts=complexity_counts,
            bottleneck_detected=dict(bottleneck_counter),
            items=items,
        )

    def to_html(
        self,
        output_path: str | Path | None = None,
        title: str = "SQLShift — Database Audit Report",
    ) -> str:
        """Запускает аудит и генерирует интерактивный HTML-дашборд.

        Args:
            output_path: Путь для сохранения .html файла (опционально).
            title: Заголовок отчета.

        Returns:
            str: Сгенерированный HTML-код страницы.
        """
        from sqlshift.core.html_report import generate_html_report

        summary = self.analyze()
        html_code = generate_html_report(summary, title=title)

        if output_path is not None:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(html_code, encoding="utf-8")

        return html_code
