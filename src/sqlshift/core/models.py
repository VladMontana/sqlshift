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


@dataclass
class QueryAuditItem:
    index: int
    original_sql: str
    decision: RouteDecision
    bottlenecks: list[str]


@dataclass
class BatchAuditSummary:
    total_queries: int
    postgres_count: int
    clickhouse_count: int
    complexity_counts: dict[str, int]
    bottleneck_detected: dict[str, int]
    items: list[QueryAuditItem]
