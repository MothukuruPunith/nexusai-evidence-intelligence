from contextlib import asynccontextmanager
from time import perf_counter
from uuid import UUID, uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from nexusai import __version__
from nexusai.core.config import Settings
from nexusai.core.logging import configure_logging
from nexusai.database.health import check_database, create_database_engine
from nexusai.documents.api import router
from nexusai.documents.embedding import Embedder
from nexusai.documents.errors import DocumentError
from nexusai.documents.limits import UploadBodyLimit
from nexusai.rag.api import router as rag_router
from nexusai.rag.generator import Generator


class HealthResponse(BaseModel):
    status: str
    version: str
    phase: int = 4
    database: str


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings if settings is not None else Settings()
    logger = configure_logging()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.engine = create_database_engine(configuration)
        application.state.settings = configuration
        application.state.embedder = Embedder(configuration.model_dir)
        application.state.generator = Generator(configuration)
        try:
            yield
        finally:
            if application.state.engine is not None:
                application.state.engine.dispose()

    application = FastAPI(title="NexusAI", version=__version__, lifespan=lifespan)

    application.add_middleware(UploadBodyLimit)
    application.include_router(router)
    application.include_router(rag_router)

    @application.exception_handler(DocumentError)
    async def document_error(request: Request, exc: DocumentError):
        return JSONResponse(
            status_code=exc.status,
            content={"error": exc.code, "request_id": request.state.request_id},
        )

    @application.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):
        return JSONResponse(
            status_code=503,
            content={"error": "database_unavailable", "request_id": request.state.request_id},
        )

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        try:
            request_id = str(UUID(request.headers.get("x-request-id", "")))
        except ValueError:
            request_id = str(uuid4())
        request.state.request_id = request_id
        start = perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            response = JSONResponse(
                status_code=500,
                content={"error": "internal_error", "request_id": request_id},
            )
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request",
            extra={
                "event": "request_completed",
                "request_id": request_id,
                "status_code": response.status_code,
                "duration_ms": round((perf_counter() - start) * 1000, 2),
            },
        )
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": "invalid_request",
                "request_id": request.state.request_id,
                "fields": [{"location": list(e["loc"]), "type": e["type"]} for e in exc.errors()],
            },
        )

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "not_found" if exc.status_code == 404 else "request_rejected",
                "request_id": request.state.request_id,
            },
            headers=exc.headers,
        )

    @application.get("/health/live", response_model=HealthResponse, tags=["health"])
    def live():
        return HealthResponse(status="ok", version=__version__, database="not_checked")

    @application.get("/health", response_model=HealthResponse, tags=["health"])
    @application.get("/health/ready", response_model=HealthResponse, tags=["health"])
    def ready(request: Request, response: Response):
        state = check_database(request.app.state.engine)
        response.status_code = 200 if state == "ready" else 503
        return HealthResponse(
            status="ready" if state == "ready" else "degraded",
            version=__version__,
            database=state,
        )

    return application


app = create_app()
