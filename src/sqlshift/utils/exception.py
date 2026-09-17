class SQLShiftError(Exception):
    """Базовое исключение для SQLShift."""


class SQLParsingError(SQLShiftError):
    """Исключение при ошибке парсинга SQL."""


class TranspilationError(SQLShiftError):
    """Исключение при ошибке транспайлинга SQL в целевой диалект."""
