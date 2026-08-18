from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class EditorSelection(BaseModel):
    text: str = Field(max_length=200_000)
    start_line: int = Field(ge=1)
    start_column: int = Field(ge=1)
    end_line: int = Field(ge=1)
    end_column: int = Field(ge=1)


class EditorContextRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=128)
    active_file: str = Field(min_length=1, max_length=4096)
    content: str = Field(max_length=2_000_000)
    document_version: int | None = Field(default=None, ge=0)
    selection: EditorSelection | None = None
    cursor_symbol: str | None = Field(default=None, max_length=512)
    diagnostics: list[dict] = Field(default_factory=list, max_length=200)
    mention_paths: list[str] = Field(default_factory=list, max_length=20)
    relevant_terminal_failure: str | None = Field(default=None, max_length=128_000)


class EditorActionRequest(EditorContextRequest):
    action: Literal[
        "explain_code",
        "fix_diagnostic",
        "refactor_selection",
        "generate_tests",
        "generate_documentation",
        "find_problems",
        "simplify_code",
        "convert_pattern",
        "propagate_api_change",
        "explain_failure",
    ]
    instruction: str | None = Field(default=None, max_length=8000)


class EditorContextResponse(BaseModel):
    context: dict


class EditorActionResponse(BaseModel):
    kind: Literal["explanation", "changes", "findings"]
    summary: str
    explanation: str | None = None
    verification_commands: list[str] = Field(default_factory=list)
    context: dict
    change_set: dict | None = None
    findings: list[str] = Field(default_factory=list)
