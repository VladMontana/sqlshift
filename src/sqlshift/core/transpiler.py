from sqlglot import exp

from sqlshift.utils.exception import TranspilationError


def _normalize_ident(node: exp.Expression | None, val: str | None) -> str:
    """Нормализует строковый идентификатор с учетом наличия кавычек.

    - Без кавычек -> приводится к нижнему регистру (PostgreSQL case-folding).
    - В кавычках -> регистр строго сохраняется.
    """
    if not val:
        return ""
    is_quoted = getattr(node, "quoted", False) if node else False
    return val if is_quoted else val.lower()


def transpile_to_clickhouse(
    tree: exp.Expression,
    schema_mapping: dict[str, str | None] | None = None,
) -> str:
    """Транспайлит AST-дерево PostgreSQL в SQL-диалект ClickHouse.

    Поддерживает сопоставление схем: по умолчанию схема 'public' удаляется у таблиц
    и ссылок на столбцы, так как в ClickHouse таблицы создаются в default базе данных.
    Строго учитывает кавычки идентификаторов схем при сопоставлении с правилами mapping.

    Args:
        tree: Корень AST-выражения sqlglot.
        schema_mapping: Словарь сопоставления схем PostgreSQL в базы ClickHouse.
            Значение None удаляет квалификатор схемы из SQL.

    Returns:
        str: SQL-запрос в синтаксисе ClickHouse.

    Raises:
        TranspilationError: Если во время генерации диалекта произошла ошибка.
    """
    try:
        tree_copy = tree.copy()
        mapping = schema_mapping if schema_mapping is not None else {"public": None}

        # 1. Сопоставление схем у физических таблиц
        for t in tree_copy.find_all(exp.Table):
            if t.db:
                db_norm = _normalize_ident(t.args.get("db"), t.db)
                if db_norm in mapping:
                    target_db = mapping[db_norm]
                    if target_db is None or target_db == "":
                        t.set("db", None)
                    else:
                        t.set("db", exp.to_identifier(target_db))

        # 2. Согласованное обновление ссылок на столбцы вида schema.table.column
        for col in tree_copy.find_all(exp.Column):
            if col.db:
                col_db_norm = _normalize_ident(col.args.get("db"), col.db)
                if col_db_norm in mapping:
                    target_db = mapping[col_db_norm]
                    if target_db is None or target_db == "":
                        col.set("db", None)
                    else:
                        col.set("db", exp.to_identifier(target_db))

        return tree_copy.sql(dialect="clickhouse")
    except Exception as exc:
        raise TranspilationError(f"Ошибка транспайлинга запроса в ClickHouse: {exc}") from exc
