import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from sqlshift.utils.exception import SQLParsingError


def parse_sql(sql: str, dialect: str = "postgres") -> exp.Expression:
    """Парсит SQL строку в AST-выражение sqlglot.
    Args:
        sql: Текст SQL запроса.
        dialect: Диалект входящего SQL (по умолчанию postgres).
    Returns:
        exp.Expression: Корень абстрактного синтаксического дерева (AST).
    Raises:
        SQLParsingError: Если запрос синтаксически некорректен или пуст.
    """
    if not sql or not sql.strip():
        raise SQLParsingError("Входящий SQL запрос не может быть пустым.")

    try:
        expression = sqlglot.parse_one(sql, read=dialect)
        if not isinstance(expression, exp.Expression):
            raise SQLParsingError("Не удалось разобрать SQL запрос.")
        return expression
    except ParseError as e:
        raise SQLParsingError(f"Ошибка разбора SQL запроса: {e}") from e
