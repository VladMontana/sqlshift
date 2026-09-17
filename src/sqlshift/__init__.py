"""sqlshift: Cross-dialect SQL query router and transpiler."""

from sqlshift.core.models import QueryComplexity, RouteDecision, TargetDatabase
from sqlshift.core.router import SQLShiftRouter
from sqlshift.utils.exception import SQLParsingError, SQLShiftError, TranspilationError

# Делаем алиас SQLRouter для удобства и обратной совместимости
SQLRouter = SQLShiftRouter

__version__ = "0.1.0"

__all__ = [
    "SQLRouter",
    "SQLShiftRouter",
    "RouteDecision",
    "TargetDatabase",
    "QueryComplexity",
    "SQLShiftError",
    "SQLParsingError",
    "TranspilationError",
    "__version__",
]
