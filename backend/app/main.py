from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .claims import ClaimExtractor
from .config import Settings, get_settings
from .errors import PipelineError
from .keenable import KeenableClient
from .models import AnalyzeRequest, AnalyzeResponse, CaptionLine, ReportRequest, ReportResponse
from .transcript import TranscriptService, clean_segments
from .verification import VerificationEngine

logger = logging.getLogger("video_context_overlay")


class Pipeline:
    def __init__(self, settings: Settings, transcripts: TranscriptService, keenable: KeenableClient):
        self.transcripts = transcripts
        self.extractor = ClaimExtractor(settings.max_claims)
        self.verifier = VerificationEngine(
            keenable,
            max_results=settings.search_max_results,
            snippet_max_length=settings.snippet_max_length,
            fetch_max_chars=settings.fetch_max_chars,
            max_words=settings.max_note_words,
            concurrency=settings.concurrency,
        )

    async def analyze(self, video_id: str, captions: list[CaptionLine] | None = None) -> AnalyzeResponse:
        if captions is not None:
            segments = clean_segments((c.text, c.start, c.duration) for c in captions)
        else:
            segments = await self.transcripts.fetch(video_id)
        claims = await self.extractor.extract(segments)
        notes = await self.verifier.verify_all(claims)
        logger.info("analyzed video=%s claims=%d notes=%d", video_id, len(claims), len(notes))
        return AnalyzeResponse(video_id=video_id, notes_count=len(notes), notes=notes)


def build_pipeline(settings: Settings, http: httpx.AsyncClient) -> Pipeline:
    keenable = KeenableClient(settings.keenable_api_key, settings.keenable_base_url, client=http)
    return Pipeline(settings, TranscriptService(), keenable)


def create_app(settings: Settings | None = None, pipeline: Pipeline | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(timeout=60.0) as http:
            app.state.http = http
            app.state.pipeline = pipeline
            if app.state.pipeline is None:
                try:
                    app.state.pipeline = build_pipeline(settings, http)
                except PipelineError as exc:
                    logger.warning("pipeline not configured: %s", exc.message)
                    app.state.config_error = exc
            yield

    app = FastAPI(title="Video Context Overlay API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_origin_regex=r"^chrome-extension://[a-p]{32}$",
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(PipelineError)
    async def pipeline_error_handler(_: Request, exc: PipelineError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.code, "message": exc.message})

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(part) for part in first.get("loc", []) if part != "body")
        return JSONResponse(
            status_code=400,
            content={"error": "INVALID_REQUEST", "message": f"{field}: {first.get('msg', 'invalid')}".strip(": ")},
        )

    @app.get("/healthz")
    async def healthz(request: Request) -> dict:
        return {"status": "ok", "configured": getattr(request.app.state, "pipeline", None) is not None}

    @app.post("/api/v1/analyze", response_model=AnalyzeResponse)
    async def analyze(body: AnalyzeRequest, request: Request) -> AnalyzeResponse:
        active = request.app.state.pipeline
        if active is None:
            raise request.app.state.config_error
        return await active.analyze(body.video_id, body.segments)

    @app.post("/api/v1/report", response_model=ReportResponse, status_code=202)
    async def report(body: ReportRequest, request: Request) -> ReportResponse:
        payload = body.model_dump(mode="json")
        logger.warning("note report: %s", payload)
        if settings.report_webhook_url:
            try:
                await request.app.state.http.post(settings.report_webhook_url, json=payload, timeout=10.0)
            except httpx.HTTPError as exc:
                logger.error("report webhook failed: %s", type(exc).__name__)
        return ReportResponse()

    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
