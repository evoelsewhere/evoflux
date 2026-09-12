"""Stable Evo Conductor API contract paths."""

from __future__ import annotations

REGISTER_PATH = "/api/v1/client/register"
HEARTBEAT_PATH = "/api/v1/client/heartbeat"
TELEMETRY_PATH = "/api/v1/telemetry/batch"
RESOURCE_USAGE_PATH = "/api/v1/usage/resources"
REALTIME_EVENTS_PATH = "/api/v1/realtime/events"
CHANGES_PATH = "/api/v1/resources/changes"
INVENTORY_PATH = "/api/v1/client/inventory"

CHANGE_PAGE_LIMIT = 100

CONDUCTOR_TOKEN_PREFIX = "evc_"
API_TEXT_FIELD_MAX_LENGTH = 256
API_DEFAULT_TIMEOUT_SECONDS = 15.0
API_DEFAULT_RETRY_ATTEMPTS = 3
API_RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
API_NOT_MODIFIED_STATUS = 304
API_MAX_RETRY_DELAY_SECONDS = 8.0
API_BASE_RETRY_DELAY_SECONDS = 0.25
API_RETRY_JITTER_DIVISOR = 4

# Realtime contract; values follow evo-conductor/docs/evoflux-integration.md.
REALTIME_PROTOCOL_NAME = "evoflux.realtime.v1"
# random(0, min(30s, 500ms * 2**attempt)).
REALTIME_RETRY_BASE_DELAY_SECONDS = 0.5
REALTIME_RETRY_MAX_DELAY_SECONDS = 30.0
# A missing heartbeat for 3x the interval means a dead connection.
REALTIME_HEARTBEAT_TIMEOUT_MULTIPLIER = 3
# Replaced by control.hello's heartbeat_seconds once the stream is open.
REALTIME_DEFAULT_HEARTBEAT_SECONDS = 20.0
# Used when a 429/503 carries no Retry-After.
REALTIME_DEFAULT_RETRY_AFTER_SECONDS = 5.0
REALTIME_DEFAULT_SERVER_DRAIN_DELAY_SECONDS = 2.0
