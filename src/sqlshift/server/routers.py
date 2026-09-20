import time

from fastapi import APIRouter, HTTPException, Request, status

from sqlshift.server.schemas import (
    HealthResponse,
    QueryRequest,
    QueryResponse,
    RouteRequest,
    RouteResponse,
)

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    postgres_conf = bool(settings.pg_dsn)
    clickhouse_conf = bool(settings.ch_dsn)

    return HealthResponse(
        status="ok",
        version=settings.version,
        postgres_conf=postgres_conf,
        clickhouse_conf=clickhouse_conf,
    )


@router.post("/route", response_model=RouteResponse, tags=["Routing"])
async def routing(payload: RouteRequest, request: Request) -> RouteResponse:
    shift_router = request.app.state.router
    decision = shift_router.route(payload.sql)

    return RouteResponse.model_validate(decision)


@router.post("/query", response_model=QueryResponse, tags=["Query"])
async def query(payload: QueryRequest, request: Request) -> QueryResponse:
    client = request.app.state.client
    if not client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database client not configured"
        )
    start_time = time.perf_counter()
    shift_router = request.app.state.router
    decision = shift_router.route(payload.sql)
    data = await client.fetch(payload.sql)
    exec_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

    return QueryResponse(
        target=decision.target,
        executed_sql=decision.sql,
        data=data,
        row_count=len(data),
        exec_time_ms=exec_time_ms,
    )
