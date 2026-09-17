from sqlglot import exp

from sqlshift.utils.exception import TranspilationError


def transpile_to_clickhouse(tree: exp.Expression) -> str:
    """Транспайлит AST-дерево PostgreSQL в SQL-диалект ClickHouse.
    Args:
        tree: Корень AST-выражения sqlglot.
    Returns:
        str: SQL-запрос в синтаксисе ClickHouse.
    Raises:
        TranspilationError: Если во время генерации диалекта произошла ошибка.
    """
    try:
        return tree.sql(dialect="clickhouse")
    except Exception as exc:
        raise TranspilationError(f"Ошибка транспайлинга запроса в ClickHouse: {exc}") from exc
