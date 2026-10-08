"""Request and response contracts for local skill demonstration traces."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    model_validator,
)

RecordingEventKind = Literal[
    "click",
    "double_click",
    "scroll",
    "window_change",
    "focus",
    "invoked",
    "selected",
    "value_changed",
    "state_change",
    "window_opened",
    "window_closed",
    "gap",
    "screenshot",
]
RecordingValueState = Literal[
    "not_captured", "captured", "omitted_secure", "unavailable"
]
RecordingPointerButton = Literal["left", "middle", "right"]


class RecordingPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: StrictInt = Field(ge=-32768, le=32767)
    y: StrictInt = Field(ge=-32768, le=32767)
    display_id: str | None = Field(default=None, max_length=128)


class RecordingScrollDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: StrictInt = Field(ge=-100_000, le=100_000)
    y: StrictInt = Field(ge=-100_000, le=100_000)


class RecordingElementTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    automation_id: str | None = Field(default=None, max_length=2048)
    control_type: str | None = Field(default=None, max_length=128)
    name: str | None = Field(default=None, max_length=2048)


class SkillRecordingEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    elapsed_ms: int = Field(ge=0)
    kind: RecordingEventKind
    point: RecordingPoint | None = None
    button: RecordingPointerButton | None = None
    scroll_delta: RecordingScrollDelta | None = None
    target: RecordingElementTarget | None = None
    value_state: RecordingValueState = "not_captured"
    value: str | None = None
    screenshot: str | None = Field(default=None, max_length=3 * 1024 * 1024)

    @model_validator(mode="after")
    def validate_privacy_shape(self) -> SkillRecordingEvent:
        click_kind = self.kind in {"click", "double_click"}
        if click_kind and (self.point is None or self.button is None):
            raise ValueError("Click events require a point and a supported button.")
        if self.kind == "scroll" and (
            self.point is None or self.scroll_delta is None or self.button is not None
        ):
            raise ValueError("Scroll events require a point and scroll delta.")
        if self.kind not in {"click", "double_click", "scroll"} and any(
            field is not None for field in (self.point, self.button, self.scroll_delta)
        ):
            raise ValueError("Pointer fields are only valid on pointer events.")
        if click_kind and self.scroll_delta is not None:
            raise ValueError("Click events cannot contain a scroll delta.")
        if self.kind == "focus" and self.target is not None:
            self.target.name = None
        if self.target is not None and (self.target.control_type or "").lower() in {
            "edit",
            "text",
            "pane",
        }:
            self.target.name = None
        if self.value is not None and (
            self.kind != "value_changed" or self.value_state != "captured"
        ):
            raise ValueError(
                "Only positively captured value-change events may contain a value."
            )
        if self.kind == "screenshot" and self.screenshot is None:
            raise ValueError("Screenshot checkpoint requires an image.")
        if self.kind != "screenshot" and self.screenshot is not None:
            raise ValueError("Screenshots are only valid on checkpoint events.")
        return self


class SkillRecordingEventBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[SkillRecordingEvent] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def limit_screenshot_payload(self) -> SkillRecordingEventBatch:
        total = sum(len(event.screenshot or "") for event in self.events)
        if total > 3 * 1024 * 1024:
            raise ValueError("Screenshot payload in this batch is too large.")
        return self


class SkillRecordingPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_event_ids: list[StrictInt] = Field(min_length=1, max_length=64)
    redactions: dict[str, str] = Field(default_factory=dict, max_length=32)
    goal: str = Field(default="", max_length=2000)
    model: str | None = Field(default=None, max_length=256)


class SkillRecordingDraftRequest(SkillRecordingPreviewRequest):
    model: str = Field(min_length=3, max_length=256)
    confirm_processing: StrictBool
    preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SkillRecordingCreated(BaseModel):
    id: str
    schema_version: Literal[2]
    status: Literal["recording"]


class SkillRecordingArtifactUploaded(BaseModel):
    recording_id: str
    artifact_id: Literal["video"]
    media_type: Literal["video/webm"]
    byte_length: StrictInt = Field(ge=1)
    expires_at: datetime


class SkillRecordingDeleteResponse(BaseModel):
    id: str
    deleted: Literal[True] = True
