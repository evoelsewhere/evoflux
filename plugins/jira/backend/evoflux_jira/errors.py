"""Stable, sanitized error envelopes for Jira operations."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class JiraPluginError(Exception):
    code: str
    message: str
    retryable: bool = False
    field_errors: dict[str, str] = field(default_factory=dict)
    status_code: int | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "field_errors": dict(self.field_errors),
        }
        if self.status_code is not None:
            payload["status_code"] = self.status_code
        return payload
