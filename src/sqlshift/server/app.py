from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from sqlshift.core.router import SQLShiftRouter
from sqlshift.server.config import ServerSettings
from sqlshift.server.routers import router as api_router
from sqlshift.utils.exception import SQLParsingError, TranspilationError

if TYPE_CHECKING:
    from sqlshift.client.async_client import AsyncSQLShiftClient


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    client = getattr(app.state, "client", None)
    if client is not None:
        await client.connect()
    yield
    if client is not None:
        await client.close()


def create_app(
    setting: ServerSettings | None = None,
    router: SQLShiftRouter | None = None,
    client: "AsyncSQLShiftClient | None" = None,
) -> FastAPI:
    settings = setting or ServerSettings()
    router = router or SQLShiftRouter()

    app = FastAPI(title=settings.title, version=settings.version, lifespan=lifespan)
    app.include_router(api_router, prefix=settings.api_prefix)

    @app.exception_handler(SQLParsingError)
    async def handle_parsing_error(request: Request, exc: SQLParsingError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "SQLParsingError", "message": str(exc)},
        )

    @app.exception_handler(TranspilationError)
    async def handle_transpilation_error(request: Request, exc: TranspilationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": "TranspilationError", "message": str(exc)},
        )

    if client is None and settings.pg_dsn and settings.ch_dsn:
        try:
            from sqlshift.client.async_client import AsyncSQLShiftClient

            client = AsyncSQLShiftClient(
                pg_dsn=settings.pg_dsn, ch_dsn=settings.ch_dsn, router=router
            )
        except ImportError:
            client = None

    app.state.settings = settings
    app.state.router = router
    app.state.client = client

    return app


app = create_app()
