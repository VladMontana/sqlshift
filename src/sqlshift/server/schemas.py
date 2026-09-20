from typing import Any

from pydantic import BaseModel, Field

from sqlshift.core.models import QueryComplexity, TargetDatabase


class RouteRequest(BaseModel):
    sql: str = Field(
        ...,
        min_length=1,
        description="SQL-запрос в синтаксисе PostgreSQL",
        examples=["SELECT count(*) FROM events"],
    )


class RouteResponse(BaseModel):
    target: TargetDatabase
    sql: str
    is_analytical: bool
    estimated_complexity: QueryComplexity
    reason: str

    model_config = {"from_attributes": True}


class QueryRequest(BaseModel):
    sql: str


class QueryResponse(BaseModel):
    target: TargetDatabase
    executed_sql: str
    data: list[dict[str, Any]]
    row_count: int
    exec_time_ms: float


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    postgres_conf: bool
    clickhouse_conf: bool


class ErrorResponse(BaseModel):
    error: str
    message: str
