"""FastAPI service for DeepScout research execution."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langgraph.types import Command
from opentelemetry.sdk.trace import TracerProvider
from pydantic import BaseModel

from deepscout import __version__
from deepscout.api.observability import RESEARCH_RUNS, ObservabilityMiddleware, metrics_response
from deepscout.api.rate_limit import (
    close_rate_limiters,
    enforce_rate_limit,
    rate_limit_readiness,
)
from deepscout.api.runtime import api_graph_runtime
from deepscout.api.schemas import (
    ResearchRequest,
    ResearchResponse,
    ResumeRequest,
    ThreadStateResponse,
)
from deepscout.api.security import require_api_principal
from deepscout.api.tracing import build_tracer_provider
from deepscout.config import get_settings
from deepscout.models.hitl import HumanReview


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "value") and hasattr(value, "id"):
        return {"value": _jsonable(value.value), "id": str(value.id)}
    return str(value)


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _initial_state(request: ResearchRequest) -> dict:
    return {
        "query": request.query,
        "task_results": [],
        "iteration": 0,
        "require_approval": request.require_approval,
    }


def _response_from_result(thread_id: str, result: dict) -> ResearchResponse:
    raw_interrupts = result.get("__interrupt__", [])
    interrupts = _jsonable(raw_interrupts)
    status = "interrupted" if raw_interrupts else "completed"
    RESEARCH_RUNS.labels(status).inc()
    return ResearchResponse(
        thread_id=thread_id,
        status=status,
        final_report=result.get("final_report"),
        interrupts=interrupts,
    )


async def _stream_graph(
    graph: Any, input_value: Any, thread_id: str
) -> AsyncIterator[ServerSentEvent]:
    event_id = 1
    interrupted = False
    yield ServerSentEvent(
        data={"thread_id": thread_id},
        event="metadata",
        id=str(event_id),
    )
    async for chunk in graph.astream(input_value, _config(thread_id), stream_mode="updates"):
        event_id += 1
        is_interrupt = "__interrupt__" in chunk
        interrupted = interrupted or is_interrupt
        yield ServerSentEvent(
            data=_jsonable(chunk),
            event="interrupt" if is_interrupt else "update",
            id=str(event_id),
        )
    event_id += 1
    run_status = "interrupted" if interrupted else "completed"
    RESEARCH_RUNS.labels(run_status).inc()
    yield ServerSentEvent(
        data={"thread_id": thread_id, "status": run_status},
        event="paused" if interrupted else "done",
        id=str(event_id),
    )


def create_app(
    *, graph: Any | None = None, tracer_provider: TracerProvider | None = None
) -> FastAPI:
    """Create the DeepScout API app, optionally injecting a graph for tests."""

    configured_tracer = tracer_provider or build_tracer_provider()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            if graph is not None:
                app.state.graph = graph
                yield
                return
            async with api_graph_runtime() as runtime_graph:
                app.state.graph = runtime_graph
                yield
        finally:
            await close_rate_limiters()
            if configured_tracer is not None:
                configured_tracer.shutdown()

    app = FastAPI(title="DeepScout API", version=__version__, lifespan=lifespan)
    app.add_middleware(ObservabilityMiddleware, tracer_provider=configured_tracer)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz():
        ready, limiter_backend = await rate_limit_readiness()
        payload = {
            "status": "ready" if ready else "not_ready",
            "rate_limit": limiter_backend,
            "checkpoint": get_settings().api_checkpoint,
        }
        if not ready:
            return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
        return payload

    @app.get("/metrics", dependencies=[Depends(require_api_principal)])
    async def metrics():
        if not get_settings().api_metrics_enabled:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return metrics_response()

    @app.post(
        "/v1/research",
        response_model=ResearchResponse,
        dependencies=[Depends(enforce_rate_limit)],
    )
    async def research(request: ResearchRequest) -> ResearchResponse:
        thread_id = request.thread_id or str(uuid4())
        result = await app.state.graph.ainvoke(_initial_state(request), _config(thread_id))
        return _response_from_result(thread_id, result)

    @app.post(
        "/v1/research/stream",
        response_class=EventSourceResponse,
        dependencies=[Depends(enforce_rate_limit)],
    )
    async def research_stream(request: ResearchRequest) -> AsyncIterator[ServerSentEvent]:
        thread_id = request.thread_id or str(uuid4())
        async for event in _stream_graph(
            app.state.graph,
            _initial_state(request),
            thread_id,
        ):
            yield event

    @app.post(
        "/v1/research/{thread_id}/resume",
        response_model=ResearchResponse,
        dependencies=[Depends(enforce_rate_limit)],
    )
    async def resume(thread_id: str, request: ResumeRequest) -> ResearchResponse:
        review = HumanReview.model_validate(request.model_dump())
        result = await app.state.graph.ainvoke(
            Command(resume=review.model_dump(mode="json")),
            _config(thread_id),
        )
        return _response_from_result(thread_id, result)

    @app.post(
        "/v1/research/{thread_id}/resume/stream",
        response_class=EventSourceResponse,
        dependencies=[Depends(enforce_rate_limit)],
    )
    async def resume_stream(
        thread_id: str,
        request: ResumeRequest,
    ) -> AsyncIterator[ServerSentEvent]:
        review = HumanReview.model_validate(request.model_dump())
        command = Command(resume=review.model_dump(mode="json"))
        async for event in _stream_graph(app.state.graph, command, thread_id):
            yield event

    @app.get(
        "/v1/research/{thread_id}",
        response_model=ThreadStateResponse,
        dependencies=[Depends(enforce_rate_limit)],
    )
    async def thread_state(thread_id: str) -> ThreadStateResponse:
        snapshot = await app.state.graph.aget_state(_config(thread_id))
        return ThreadStateResponse(
            thread_id=thread_id,
            next_nodes=list(snapshot.next),
            values=_jsonable(snapshot.values),
        )

    return app


app = create_app()
