from dataclasses import dataclass
from typing import Literal

TargetDatabase = Literal["postgresql", "clickhouse"]

QueryComplexity = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class RouteDecision:
    target: TargetDatabase
    sql: str
    is_analytical: bool
    estimated_complexity: QueryComplexity
    reason: str
