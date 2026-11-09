import secrets

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .config import Settings
from .engine import Engine
from .errors import ServiceError
from .models import (
    AnalysisResponse,
    BriefResponse,
    ContributionResponse,
    ImageRequest,
    ImageResponse,
    ProjectContext,
    QuestionRequest,
    QuestionResponse,
    SearchRequest,
    SearchResponse,
)
from .retrieval import search


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = engine or Engine(settings)
    app = FastAPI(title="Idea2IP AI API", version="1.0.0")

    def authorize(x_service_token: str | None = Header(default=None)):
        expected = settings.service_token.get_secret_value()
        if expected and not secrets.compare_digest(
            (x_service_token or "").encode(), expected.encode()
        ):
            raise ServiceError("UNAUTHORIZED", "내부 서비스 인증 실패", 401)

    def scope(project_id: str, context: ProjectContext):
        if project_id != context.project_id:
            raise ServiceError("PROJECT_MISMATCH", "경로와 본문의 프로젝트가 다릅니다", 422)

    @app.exception_handler(ServiceError)
    async def service_error(_request: Request, exc: ServiceError):
        return JSONResponse(
            status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}}
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _exc: RequestValidationError):
        # Do not echo uploaded text, base64 images or credentials in validation responses.
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "요청 스키마/출처 범위를 확인하세요",
                }
            },
        )

    @app.exception_handler(ValidationError)
    async def invalid_internal_data(_request: Request, _exc: ValidationError):
        return JSONResponse(
            status_code=502,
            content={
                "error": {"code": "INVALID_INTERNAL_DATA", "message": "내부 자료 스키마 검증 실패"}
            },
        )

    @app.get("/health/live")
    def health():
        return {
            "status": "ok",
            "mode": settings.mode,
            "retrieval": settings.retrieval,
            "dependencies_checked": False,
        }

    options = {"dependencies": [Depends(authorize)]}
    root = "/v1/projects/{project_id}"

    @app.post(root + "/questions", response_model=QuestionResponse, **options)
    def question(project_id: str, request: QuestionRequest):
        scope(project_id, request.context)
        return engine.question(request)

    @app.post(root + "/answers/analyze", response_model=AnalysisResponse, **options)
    def analyze(project_id: str, context: ProjectContext):
        scope(project_id, context)
        return engine.analyze(context)

    @app.post(root + "/contributions", response_model=ContributionResponse, **options)
    def contributions(project_id: str, context: ProjectContext):
        scope(project_id, context)
        return engine.contributions_from(engine.analyze(context))

    @app.post(root + "/brief", response_model=BriefResponse, **options)
    def brief(project_id: str, context: ProjectContext):
        scope(project_id, context)
        return engine.brief(context)

    @app.post(root + "/images/observe", response_model=ImageResponse, **options)
    def observe(project_id: str, request: ImageRequest):
        scope(project_id, request.context)
        return engine.observe(request)

    @app.post(root + "/retrieval/search", response_model=SearchResponse, **options)
    def retrieve(project_id: str, request: SearchRequest):
        scope(project_id, request.context)
        return search(request, settings)

    return app


app = create_app()
