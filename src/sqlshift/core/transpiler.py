from sqlglot import exp

from sqlshift.utils.exception import TranspilationError


def transpile_to_clickhouse(
    tree: exp.Expression,
    schema_mapping: dict[str, str | None] | None = None,
) -> str:
    """Транспайлит AST-дерево PostgreSQL в SQL-диалект ClickHouse.

    Поддерживает сопоставление схем: по умолчанию схема 'public' удаляется,
    так как в ClickHouse таблицы создаются в текущей/default базе данных.

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
        for t in tree_copy.find_all(exp.Table):
            if t.db:
                db_name = t.db.lower()
                if db_name in mapping:
                    target_db = mapping[db_name]
                    if target_db is None or target_db == "":
                        t.set("db", None)
                    else:
                        t.set("db", exp.to_identifier(target_db))

        return tree_copy.sql(dialect="clickhouse")
    except Exception as exc:
        raise TranspilationError(f"Ошибка транспайлинга запроса в ClickHouse: {exc}") from exc
