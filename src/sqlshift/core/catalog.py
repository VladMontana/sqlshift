"""Каталог таблиц и правила допуска для гибридной маршрутизации SQL-запросов."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope


@dataclass(frozen=True)
class TableReference:
    """Нормализованное представление имени таблицы со схемой."""

    schema: str
    name: str

    def to_string(self) -> str:
        """Возвращает каноническую строку вида 'schema.name'."""
        return f"{self.schema}.{self.name}"

    def __str__(self) -> str:
        return self.to_string()


@dataclass(frozen=True)
class TableAdmissionResult:
    """Результат проверки физических таблиц по каталогу."""

    is_admitted: bool
    reason_code: str
    reason_description: str
    missing_tables: list[str] = field(default_factory=list)
    pinned_tables: list[str] = field(default_factory=list)

    def __iter__(self) -> Any:
        """Поддержка распаковки кортежа (is_admitted, reason_code, missing_tables)."""
        yield self.is_admitted
        yield self.reason_code
        yield self.missing_tables


class TableCatalog:
    """Каталог допустимых и запрещенных таблиц для маршрутизации в ClickHouse."""

    def __init__(
        self,
        allowed_tables: Iterable[str] | None = None,
        postgres_only_tables: Iterable[str] | None = None,
        pg_only_tables: Iterable[str] | None = None,
        default_schema: str = "public",
        case_sensitive: bool = False,
        schema_mapping: dict[str, str | None] | None = None,
    ) -> None:
        self.default_schema = (default_schema or "public").strip()
        self.case_sensitive = case_sensitive
        # По умолчанию PostgreSQL схема (public) отображается в default базу ClickHouse
        self.schema_mapping: dict[str, str | None] = (
            schema_mapping if schema_mapping is not None else {self.default_schema.lower(): None}
        )

        # Поддержка обоих вариантов имени аргумента: pg_only_tables и postgres_only_tables
        pg_only_source = pg_only_tables if pg_only_tables is not None else postgres_only_tables
        self._pg_only: set[TableReference] = {self._normalize(t) for t in (pg_only_source or [])}

        # allowed_tables: пустой список [] означает пустой каталог (строго блокирует ClickHouse)
        self._allowed: set[TableReference] = {self._normalize(t) for t in (allowed_tables or [])}

    def _normalize(
        self, table: str | TableReference | tuple[str, str] | exp.Table
    ) -> TableReference:
        """Нормализует имя таблицы в TableReference с сохранением семантики кавычек AST.

        Различает:
        - Обычные идентификаторы (orders / Orders) -> приводятся к нижнему регистру.
        - Идентификаторы в кавычках ("Orders") -> сохраняют точный регистр.
        - Имена со встроенной точкой ("public.orders") -> единое имя (без схемы).
        - Квалифицированные имена (public.orders) -> схема public, таблица orders.
        """
        if isinstance(table, TableReference):
            return table

        if isinstance(table, exp.Table):
            tbl = table
        elif isinstance(table, tuple):
            schema_str, name_str = str(table[0]).strip(), str(table[1]).strip()
            tbl = exp.Table(
                this=exp.to_identifier(name_str),
                db=exp.to_identifier(schema_str),
            )
        else:
            table_str = str(table).strip()
            try:
                tbl = sqlglot.parse_one(table_str, read="postgres", into=exp.Table)
            except Exception:
                tbl = exp.Table(this=exp.to_identifier(table_str))

        db_node = tbl.args.get("db")
        db_quoted = getattr(db_node, "quoted", False) if db_node else False
        if tbl.db:
            schema = tbl.db if (db_quoted or self.case_sensitive) else tbl.db.lower()
        else:
            schema = self.default_schema if self.case_sensitive else self.default_schema.lower()

        name_quoted = (
            getattr(tbl.this, "quoted", False) if isinstance(tbl.this, exp.Identifier) else False
        )
        name = tbl.name if (name_quoted or self.case_sensitive) else tbl.name.lower()

        return TableReference(schema=schema, name=name)

    def is_empty(self) -> bool:
        """Возвращает True, если список разрешенных таблиц пуст."""
        return len(self._allowed) == 0

    def is_table_allowed(self, table: str | TableReference | tuple[str, str] | exp.Table) -> bool:
        """Проверяет допуск одной таблицы в ClickHouse."""
        ref = self._normalize(table)
        if ref in self._pg_only:
            return False
        return ref in self._allowed

    def check_admission(
        self, physical_tables: Sequence[str | TableReference | tuple[str, str] | exp.Table]
    ) -> TableAdmissionResult:
        """Выполняет детерминированную проверку списка физических таблиц."""
        pinned: list[str] = []
        missing: list[str] = []

        for t in physical_tables:
            raw_str = (
                t.to_string()
                if isinstance(t, TableReference)
                else (f"{t[0]}.{t[1]}" if isinstance(t, tuple) else str(t))
            )
            ref = self._normalize(t)
            if ref in self._pg_only:
                pinned.append(raw_str)
            elif ref not in self._allowed:
                missing.append(raw_str)

        if pinned:
            pinned_unique = sorted(set(pinned))
            missing_unique = sorted(set(missing))
            if len(pinned_unique) == 1:
                desc = f"Таблица '{pinned_unique[0]}' закреплена за PostgreSQL. Выбрана PostgreSQL."
            else:
                formatted_list = ", ".join(f"'{p}'" for p in pinned_unique)
                desc = f"Таблицы {formatted_list} закреплены за PostgreSQL. Выбрана PostgreSQL."
            return TableAdmissionResult(
                is_admitted=False,
                reason_code="TABLE_PG_PINNED",
                reason_description=desc,
                missing_tables=missing_unique,
                pinned_tables=pinned_unique,
            )

        if missing:
            missing_unique = sorted(set(missing))
            if len(missing_unique) == 1:
                desc = (
                    f"Таблица '{missing_unique[0]}' отсутствует в каталоге ClickHouse. "
                    "Выбрана PostgreSQL."
                )
            else:
                formatted_list = ", ".join(f"'{m}'" for m in missing_unique)
                desc = (
                    f"Таблицы {formatted_list} отсутствуют в каталоге ClickHouse. "
                    "Выбрана PostgreSQL."
                )
            return TableAdmissionResult(
                is_admitted=False,
                reason_code="TABLE_NOT_IN_CATALOG",
                reason_description=desc,
                missing_tables=missing_unique,
                pinned_tables=[],
            )

        return TableAdmissionResult(
            is_admitted=True,
            reason_code="ANALYTICAL_CLICKHOUSE",
            reason_description=(
                "Все используемые таблицы разрешены в ClickHouse. Выбрана ClickHouse."
            ),
            missing_tables=[],
            pinned_tables=[],
        )


TableAdmissionPolicy = TableCatalog


def extract_physical_tables(tree: exp.Expression) -> list[str]:
    """Извлекает имена физических таблиц запроса через анализ областей видимости (Scope).

    Исключает:
    - CTE и ссылки на них
    - Подзапросы (derived tables)
    - Псевдонимы (aliases)
    - Табличные функции (generate_series)

    Возвращает дедуплицированный и отсортированный по алфавиту список строк.
    """
    found_tables: list[exp.Table] = []

    # 1. Если это DML-запрос на верхнем уровне (INSERT, UPDATE, DELETE)
    if isinstance(tree, (exp.Insert, exp.Update, exp.Delete)):
        for t in tree.find_all(exp.Table):
            if isinstance(t.this, exp.Identifier) and bool(t.name):
                found_tables.append(t)
    else:
        # 2. Обнаруживаем модифицирующие CTE (DML внутри WITH)
        modifying_cte_names: set[str] = set()
        for with_node in tree.find_all(exp.With):
            for cte in with_node.expressions:
                if isinstance(cte, exp.CTE):
                    dml_nodes = list(cte.find_all(exp.Insert, exp.Update, exp.Delete))
                    if dml_nodes:
                        if cte.alias:
                            modifying_cte_names.add(cte.alias)
                        for dml in dml_nodes:
                            for t in dml.find_all(exp.Table):
                                if isinstance(t.this, exp.Identifier) and bool(t.name):
                                    found_tables.append(t)

        # 3. Обходим области видимости traverse_scope
        scopes = traverse_scope(tree)
        for scope in scopes:
            for source in scope.sources.values():
                if isinstance(source, exp.Table):
                    if isinstance(source.this, exp.Identifier) and bool(source.name):
                        if source.name not in modifying_cte_names:
                            found_tables.append(source)

    # 4. Форматируем имена (без alias) и дедуплицируем
    results: set[str] = set()
    for t in found_tables:
        t_copy = t.copy()
        t_copy.set("alias", None)
        formatted = t_copy.sql("postgres", comments=False)
        if formatted:
            results.add(formatted)

    return sorted(results)
