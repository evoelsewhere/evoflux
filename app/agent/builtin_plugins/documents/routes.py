"""Host API bridge contributed by the trusted Documents plugin."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.agent.builtin_plugins.documents.engines.html_slide_broker import (
    get_html_slide_render_broker,
)
from app.agent.builtin_plugins.documents.engines.pptx_html import (
    NativeImageElement,
    NativeTextElement,
    TextCoverage,
)

router = APIRouter()


class HtmlSlideRenderResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_png_base64: str = Field(min_length=1, max_length=56_000_000)
    shell_png_base64: str = Field(min_length=1, max_length=56_000_000)
    editable_elements: list[NativeTextElement | NativeImageElement] = Field(
        default_factory=list, max_length=1000
    )
    text_coverage: TextCoverage
    issues: list[dict] = Field(default_factory=list, max_length=1000)


class HtmlSlideRenderFailure(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@router.post(
    "/renderers/global/{renderer_id}/heartbeat",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def heartbeat_global_html_slide_renderer(renderer_id: UUID) -> Response:
    await get_html_slide_render_broker().heartbeat_renderer(str(renderer_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/renderers/global/{renderer_id}/next", response_model=None)
async def claim_global_html_slide_render(
    renderer_id: UUID, response: Response
) -> Response | dict:
    response.headers["Cache-Control"] = "no-store"
    value = await get_html_slide_render_broker().claim_next(str(renderer_id))
    if value is None:
        response.status_code = status.HTTP_204_NO_CONTENT
        return response
    return value


@router.post(
    "/renderers/global/{renderer_id}/requests/{request_id}/complete",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def complete_global_html_slide_render(
    renderer_id: UUID,
    request_id: UUID,
    body: HtmlSlideRenderResult,
) -> Response:
    del renderer_id
    accepted = await get_html_slide_render_broker().complete_claim(
        request_id, body.model_dump()
    )
    if not accepted:
        raise HTTPException(status_code=404, detail="Slide render request not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/renderers/global/{renderer_id}/requests/{request_id}/fail",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def fail_global_html_slide_render(
    renderer_id: UUID,
    request_id: UUID,
    body: HtmlSlideRenderFailure,
) -> Response:
    del renderer_id
    accepted = await get_html_slide_render_broker().fail_claim(request_id, body.message)
    if not accepted:
        raise HTTPException(status_code=404, detail="Slide render request not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/renderers/{session_id}/heartbeat", status_code=status.HTTP_204_NO_CONTENT
)
async def heartbeat_html_slide_renderer(session_id: UUID) -> Response:
    await get_html_slide_render_broker().heartbeat(str(session_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/renderers/{session_id}/next", response_model=None)
async def claim_html_slide_render(
    session_id: UUID, response: Response
) -> Response | dict:
    response.headers["Cache-Control"] = "no-store"
    value = await get_html_slide_render_broker().claim(str(session_id))
    if value is None:
        response.status_code = status.HTTP_204_NO_CONTENT
        return response
    return value


@router.post(
    "/renderers/{session_id}/requests/{request_id}/complete",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def complete_html_slide_render(
    session_id: UUID,
    request_id: UUID,
    body: HtmlSlideRenderResult,
) -> Response:
    accepted = await get_html_slide_render_broker().complete(
        str(session_id), request_id, body.model_dump()
    )
    if not accepted:
        raise HTTPException(status_code=404, detail="Slide render request not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/renderers/{session_id}/requests/{request_id}/fail",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def fail_html_slide_render(
    session_id: UUID,
    request_id: UUID,
    body: HtmlSlideRenderFailure,
) -> Response:
    accepted = await get_html_slide_render_broker().fail(
        str(session_id), request_id, body.message
    )
    if not accepted:
        raise HTTPException(status_code=404, detail="Slide render request not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
