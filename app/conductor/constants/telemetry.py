"""Privacy-safe telemetry wire enums, allowlists, and queue limits."""

from __future__ import annotations

from enum import StrEnum


class TelemetryEventType(StrEnum):
    MODEL_CALL = "model_call"
    TOOL_CALL = "tool_call"


class TelemetryEventStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    BLOCKED = "blocked"


class TelemetryToolCategory(StrEnum):
    MCP = "mcp"
    FILESYSTEM = "filesystem"
    WEB = "web"
    VERSION_CONTROL = "version_control"
    COLLABORATION = "collaboration"
    OTHER = "other"


class TelemetryCollectionLevel(StrEnum):
    OFF = "L0"
    COUNTERS = "L1"
    EXTENDED = "L2"


class TelemetryField(StrEnum):
    EVENT = "event"
    KIND = "kind"
    RESOURCE_KIND = "resource_kind"
    RESOURCE_SLUG = "resource_slug"
    REVISION = "revision"
    STATE = "state"
    CATEGORY = "category"
    DURATION_MS = "duration_ms"
    TOKENS_IN = "tokens_in"
    TOKENS_OUT = "tokens_out"
    TOOL_CALLS = "tool_calls"
    ACTIVE_AGENTS = "active_agents"
    MACHINE_ID = "machine_id"
    EVOFLUX_VERSION = "evoflux_version"
    PLATFORM = "platform"
    AGENTS_COUNT = "agents_count"
    SKILLS_COUNT = "skills_count"
    MCP_COUNT = "mcp_count"
    LAST_HEARTBEAT_AT = "last_heartbeat_at"
    REPORTED_AT = "reported_at"
    EVENT_ID = "event_id"
    INSTALLATION_ID = "installation_id"
    REQUEST_ID = "request_id"
    SESSION_ID = "session_id"
    EVENT_TYPE = "event_type"
    SEQUENCE = "sequence"
    AGENT_NAME = "agent_name"
    PROVIDER = "provider"
    MODEL = "model"
    CACHE_READ_TOKENS = "cache_read_tokens"
    REASONING_TOKENS = "reasoning_tokens"
    TOOL_USE_TOKENS = "tool_use_tokens"
    TOOL_NAME = "tool_name"
    TOOL_CATEGORY = "tool_category"
    STATUS = "status"
    ERROR_CATEGORY = "error_category"


class TelemetryBatchField(StrEnum):
    INSTALLATION_ID = "installation_id"
    EVENTS = "events"


TELEMETRY_EVENT_FIELD_ALLOWLIST = frozenset(field.value for field in TelemetryField)
TELEMETRY_NUMERIC_TOKEN_FIELDS = frozenset(
    {
        TelemetryField.TOKENS_IN.value,
        TelemetryField.TOKENS_OUT.value,
        TelemetryField.CACHE_READ_TOKENS.value,
        TelemetryField.REASONING_TOKENS.value,
        TelemetryField.TOOL_USE_TOKENS.value,
    }
)
TELEMETRY_REQUIRED_STRING_FIELDS = (
    TelemetryField.EVENT_ID,
    TelemetryField.INSTALLATION_ID,
    TelemetryField.REQUEST_ID,
    TelemetryField.EVENT_TYPE,
    TelemetryField.STATUS,
    TelemetryField.REPORTED_AT,
)
TELEMETRY_SECRET_FIELD_MARKERS = (
    "secret",
    "password",
    "authorization",
    "cookie",
    "credential",
    "prompt",
    "response",
    "code",
    "argument",
    "result",
)

TELEMETRY_MAX_LABEL_LENGTH = 256
TELEMETRY_OUTBOX_MAX_EVENTS = 1_000
TELEMETRY_BATCH_SIZE = 100
TELEMETRY_ELAPSED_MS_MULTIPLIER = 1_000
TELEMETRY_OUTBOX_DIRECTORY = "conductor"
TELEMETRY_OUTBOX_FILENAME = "telemetry-outbox.json"
CONDUCTOR_TELEMETRY_HOOK_NAME = "conductor-telemetry"

MCP_TOOL_PREFIX = "mcp_"
TELEMETRY_TOOL_CATEGORY_RULES = (
    (
        TelemetryToolCategory.FILESYSTEM,
        ("file", "read", "write", "edit", "glob", "grep"),
    ),
    (TelemetryToolCategory.WEB, ("browser", "web", "http")),
    (TelemetryToolCategory.VERSION_CONTROL, ("git",)),
    (TelemetryToolCategory.COLLABORATION, ("team", "message", "task")),
)
