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
        SQLParsingError: Если запрос некорректен, пуст или содержит несколько инструкций.
    """
    if not sql or not sql.strip():
        raise SQLParsingError("Входящий SQL запрос не может быть пустым.")

    try:
        expressions = [
            e
            for e in sqlglot.parse(sql, read=dialect)
            if e is not None and not isinstance(e, exp.Semicolon)
        ]
        if not expressions:
            raise SQLParsingError("Не удалось разобрать SQL запрос.")
        if len(expressions) > 1:
            raise SQLParsingError(
                "Обнаружено несколько SQL-инструкций в запросе. Разрешена только одна."
            )
        expression = expressions[0]
        if not isinstance(expression, exp.Expression):
            raise SQLParsingError("Не удалось разобрать SQL запрос.")
        return expression
    except ParseError as e:
        raise SQLParsingError(f"Ошибка разбора SQL запроса: {e}") from e
