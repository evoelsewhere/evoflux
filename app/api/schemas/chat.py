"""Form bodies for POST /api/chat and POST /api/team/chat."""

from __future__ import annotations

from fastapi import Form, HTTPException
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.api.schemas.base import _validation_detail
from app.models.chat import normalize_mode

# ── Form models (multipart/form-data) ────────────────────────────────────────
#
# FastAPI < 1.0 cannot combine ``Annotated[Model, Form()]`` with ``File()``
# in the same endpoint.  The ``as_form`` classmethod works around this by
# reading individual Form() fields and constructing the validated model
# via ``Depends(Model.as_form)``.


class ChatForm(BaseModel):
    """Validated form body for POST /api/chat and POST /api/team/chat.

    Modes (mutually exclusive):
    - **Normal send** (interrupt=false, message required)
    - **Interrupt** (interrupt=true, session_id required, no message)
    """

    message: str | None = Field(None, description="The user's message.")
    session_id: str | None = Field(
        None, description="Resume an existing session by UUID."
    )
    interrupt: bool = Field(
        False,
        description="Interrupt the running agent. Mutually exclusive with message.",
    )
    mode: str = Field("work", description="Chat mode: work or coding.")
    workspace: str | None = Field(
        None, description="Workspace directory for coding mode."
    )
    model: str | None = Field(None, description="Per-session lead model override.")
    thinking_level: str | None = Field(
        None, description="Per-session lead thinking level override."
    )
    fast_mode: bool = Field(
        False,
        description="Per-request fast mode. Ignored by unsupported providers.",
    )
    shell: bool = Field(
        False,
        description="Run message text as a shell command instead of an agent prompt.",
    )
    webbridge_enabled: bool | None = Field(
        None,
        description="Whether this turn enables real-browser WebBridge for its session.",
    )
    folder_id: str | None = Field(
        None,
        description=(
            "Sidebar folder to file the session in. Only read when this "
            "message creates the session; a persisted session owns its folder."
        ),
    )
    project_id: str | None = Field(
        None,
        description=(
            "Coding project the session belongs to. Only read when this "
            "message creates the session; otherwise the persisted value wins."
        ),
    )

    @classmethod
    def as_form(
        cls,
        message: str | None = Form(None),
        session_id: str | None = Form(None),
        interrupt: bool = Form(False),
        mode: str = Form("work"),
        workspace: str | None = Form(None),
        model: str | None = Form(None),
        thinking_level: str | None = Form(None),
        fast_mode: bool = Form(False),
        shell: bool = Form(False),
        webbridge_enabled: bool | None = Form(None),
        folder_id: str | None = Form(None),
        project_id: str | None = Form(None),
    ) -> "ChatForm":
        try:
            return cls(
                message=message,
                session_id=session_id,
                interrupt=interrupt,
                mode=mode,
                workspace=workspace,
                model=model,
                thinking_level=thinking_level,
                fast_mode=fast_mode,
                shell=shell,
                webbridge_enabled=webbridge_enabled,
                folder_id=folder_id,
                project_id=project_id,
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=422, detail=_validation_detail(exc)
            ) from exc

    @model_validator(mode="after")
    def _validate_message_or_interrupt(self) -> "ChatForm":
        if self.interrupt and self.message:
            raise ValueError("interrupt and message are mutually exclusive.")
        if self.interrupt and not self.session_id:
            raise ValueError("session_id is required when interrupt=true.")
        if not self.interrupt and not self.message:
            raise ValueError("message is required when interrupt=false.")
        if self.message is not None and len(self.message.strip()) == 0:
            raise ValueError("message must not be blank.")
        self.mode = normalize_mode(self.mode)
        if self.mode not in {"work", "coding"}:
            raise ValueError("mode must be 'work' or 'coding'.")
        if self.mode == "coding" and not self.workspace and not self.project_id:
            # A project session spans repos and its primary path is the
            # project's to derive, so naming the project is enough. Every
            # other Coding send still has to say which workspace it means.
            raise ValueError(
                "workspace is required when mode='coding' (or name a project_id)."
            )
        if (
            self.model is not None
            and self.model.strip()
            and ":" not in self.model.strip()
        ):
            raise ValueError("model must use 'provider:model' format.")
        return self
