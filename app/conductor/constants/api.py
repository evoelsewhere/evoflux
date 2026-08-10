"""Stable Evo Conductor V1 API contract paths."""

from __future__ import annotations

V1_RESOURCE_KINDS = frozenset({"agent", "skill", "mcp"})
V1_SUBSCRIBE_PATH = "/api/v1/subscribe/resources"
V1_REGISTER_PATH = "/api/v1/client/register"
V1_HEARTBEAT_PATH = "/api/v1/client/heartbeat"
V1_TELEMETRY_PATH = "/api/v1/telemetry/batch"

CONDUCTOR_TOKEN_PREFIX = "evc_"
API_TEXT_FIELD_MAX_LENGTH = 256
API_DEFAULT_TIMEOUT_SECONDS = 15.0
API_DEFAULT_RETRY_ATTEMPTS = 3
API_RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
API_NOT_MODIFIED_STATUS = 304
API_MAX_RETRY_DELAY_SECONDS = 8.0
API_BASE_RETRY_DELAY_SECONDS = 0.25
API_RETRY_JITTER_DIVISOR = 4
