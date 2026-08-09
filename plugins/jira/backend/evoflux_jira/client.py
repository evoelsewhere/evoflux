"""Bounded Jira Data Center REST client used by the reference plugin."""

from __future__ import annotations

import asyncio
import re
import urllib.parse
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from .config import ConnectionConfig
from .errors import JiraPluginError


ISSUE_FIELDS = (
    "summary,issuetype,status,priority,assignee,reporter,description,"
    "created,updated,resolution,project,labels,components,fixVersions"
)
ISSUE_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*-[1-9][0-9]*$")
PROJECT_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
RETRYABLE_STATUS = {429, 502, 503, 504}
MAX_MESSAGE_CHARS = 500
MAX_FIELD_CHARS = 2_000
MAX_JQL_CHARS = 10_000
MAX_RESPONSE_BYTES = 5 * 1024 * 1024


def normalize_base_url(value: str) -> str:
    candidate = value.strip()
    try:
        parsed = urllib.parse.urlsplit(candidate)
        parsed.port
    except ValueError as exc:
        raise JiraPluginError("invalid_connection", "Jira URL is invalid.") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise JiraPluginError(
            "invalid_connection",
            "Jira URL must be an absolute http or https URL.",
        )
    if parsed.username is not None or parsed.password is not None:
        raise JiraPluginError(
            "invalid_connection",
            "Jira URL must not contain embedded credentials.",
        )
    if parsed.query or parsed.fragment:
        raise JiraPluginError(
            "invalid_connection",
            "Jira URL must not contain a query string or fragment.",
        )
    path = parsed.path.rstrip("/")
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc, path, "", ""))


def _text(value: object, *, fallback: str = "") -> str:
    return value[:MAX_FIELD_CHARS] if isinstance(value, str) else fallback


def _display(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in ("displayName", "name", "value", "key"):
        result = value.get(key)
        if isinstance(result, str):
            return result
    return None


def _error_message(payload: object, fallback: str) -> tuple[str, dict[str, str]]:
    messages: list[str] = []
    field_errors: dict[str, str] = {}
    if isinstance(payload, dict):
        raw_messages = payload.get("errorMessages")
        if isinstance(raw_messages, list):
            messages.extend(item for item in raw_messages if isinstance(item, str))
        raw_errors = payload.get("errors")
        if isinstance(raw_errors, dict):
            field_errors = {
                str(key): value[:MAX_MESSAGE_CHARS]
                for key, value in raw_errors.items()
                if isinstance(value, str)
            }
    message = "; ".join(messages) or "; ".join(field_errors.values()) or fallback
    return message[:MAX_MESSAGE_CHARS], field_errors


def _quote_jql(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_jql(
    *,
    jql: str,
    project_key: str,
    text: str,
    status: str,
    assignee: str,
    priority: str,
    issue_type: str,
) -> str:
    structured = {
        "project_key": project_key.strip(),
        "text": text.strip(),
        "status": status.strip(),
        "assignee": assignee.strip(),
        "priority": priority.strip(),
        "issue_type": issue_type.strip(),
    }
    if jql.strip() and any(structured.values()):
        raise JiraPluginError(
            "validation_failed",
            "Raw JQL and structured filters are mutually exclusive.",
        )
    if len(jql) > MAX_JQL_CHARS or any(
        len(value) > MAX_FIELD_CHARS for value in structured.values()
    ):
        raise JiraPluginError(
            "validation_failed",
            "JQL or a structured filter exceeds its safety limit.",
        )
    if jql.strip():
        return jql.strip()
    clauses: list[str] = []
    if structured["project_key"]:
        if PROJECT_KEY_RE.fullmatch(structured["project_key"]) is None:
            raise JiraPluginError("validation_failed", "Project key is invalid.")
        clauses.append(f"project = {_quote_jql(structured['project_key'].upper())}")
    if structured["text"]:
        clauses.append(f"text ~ {_quote_jql(structured['text'])}")
    for field_name in ("status", "priority", "issue_type"):
        if structured[field_name]:
            jira_field = "issuetype" if field_name == "issue_type" else field_name
            clauses.append(f"{jira_field} = {_quote_jql(structured[field_name])}")
    if structured["assignee"]:
        if structured["assignee"] == "currentUser()":
            clauses.append("assignee = currentUser()")
        else:
            clauses.append(f"assignee = {_quote_jql(structured['assignee'])}")
    if not clauses:
        clauses.append("assignee = currentUser()")
    return " AND ".join(clauses) + " ORDER BY updated DESC"


class JiraClient:
    def __init__(
        self,
        connection: ConnectionConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.connection = connection
        self.base_url = normalize_base_url(connection.base_url)
        self._sleeper = sleeper
        self._client = httpx.AsyncClient(
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {connection.api_token}",
                "User-Agent": "EvoFlux-Jira/0.1.1",
            },
            timeout=httpx.Timeout(30.0, connect=10.0),
            verify=connection.verify_ssl,
            follow_redirects=False,
            transport=transport,
        )

    async def __aenter__(self) -> "JiraClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
    ) -> Any:
        attempts = 3 if method.upper() == "GET" else 1
        response: httpx.Response | None = None
        for attempt in range(attempts):
            try:
                response = await self._client.request(
                    method,
                    self._url(path),
                    params=params,
                )
            except httpx.TimeoutException as exc:
                if attempt + 1 < attempts:
                    await self._sleeper(0.1 * (2**attempt))
                    continue
                raise JiraPluginError(
                    "network_error",
                    "Jira did not respond before the request timeout.",
                    retryable=True,
                ) from exc
            except httpx.TransportError as exc:
                if attempt + 1 < attempts:
                    await self._sleeper(0.1 * (2**attempt))
                    continue
                raise JiraPluginError(
                    "network_error",
                    "The Jira server could not be reached.",
                    retryable=True,
                ) from exc
            if response.status_code not in RETRYABLE_STATUS or attempt + 1 >= attempts:
                break
            delay = 0.1 * (2**attempt)
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                delay = min(float(retry_after), 2.0)
            await self._sleeper(delay)

        assert response is not None
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise JiraPluginError(
                "malformed_upstream_response",
                "Jira response exceeds the 5 MiB safety limit.",
            )
        if 300 <= response.status_code < 400:
            raise JiraPluginError(
                "endpoint_unavailable",
                "Jira redirected the authenticated request; redirects are blocked.",
                status_code=response.status_code,
            )

        content_type = response.headers.get("content-type", "").casefold()
        payload: object = None
        if "json" in content_type or not response.content:
            try:
                payload = response.json() if response.content else {}
            except ValueError:
                payload = None

        if response.is_success:
            if payload is None:
                raise JiraPluginError(
                    "malformed_upstream_response",
                    "Jira returned a non-JSON success response.",
                )
            return payload

        codes = {
            400: ("validation_failed", False),
            401: ("authentication_failed", False),
            403: ("permission_denied", False),
            404: ("not_found", False),
            429: ("rate_limited", True),
            502: ("upstream_unavailable", True),
            503: ("upstream_unavailable", True),
            504: ("upstream_unavailable", True),
        }
        code, retryable = codes.get(
            response.status_code,
            ("upstream_unavailable", response.status_code >= 500),
        )
        message, field_errors = _error_message(
            payload,
            f"Jira request failed with HTTP {response.status_code}.",
        )
        raise JiraPluginError(
            code,
            message,
            retryable=retryable,
            field_errors=field_errors,
            status_code=response.status_code,
        )

    async def connection_test(self) -> dict:
        server = await self._request("GET", "/rest/api/2/serverInfo")
        user = await self._request("GET", "/rest/api/2/myself")
        projects = await self._request("GET", "/rest/api/2/project")
        project_count = len(projects) if isinstance(projects, list) else 0
        return {
            "connection": self.connection.name,
            "base_url": self.base_url,
            "server": {
                "title": _text(server.get("serverTitle"))
                if isinstance(server, dict)
                else "",
                "version": _text(server.get("version"))
                if isinstance(server, dict)
                else "",
            },
            "user": {
                "display_name": _text(user.get("displayName"))
                if isinstance(user, dict)
                else "",
                "username": _text(user.get("name")) if isinstance(user, dict) else "",
            },
            "visible_project_count": project_count,
        }

    async def projects_list(self, *, limit: int = 100) -> dict:
        if limit < 1 or limit > 500:
            raise JiraPluginError(
                "validation_failed",
                "Project limit must be between 1 and 500.",
            )
        payload = await self._request("GET", "/rest/api/2/project")
        if not isinstance(payload, list):
            raise JiraPluginError(
                "malformed_upstream_response",
                "Jira project response is not a list.",
            )
        items = [
            {
                "id": _text(item.get("id")),
                "key": _text(item.get("key")),
                "name": _text(item.get("name")),
            }
            for item in payload[:limit]
            if isinstance(item, dict)
        ]
        return {
            "items": items,
            "returned": len(items),
            "truncated": len(payload) > limit,
        }

    async def project_permissions_get(self, *, project_key: str) -> dict:
        key = project_key.strip().upper()
        if PROJECT_KEY_RE.fullmatch(key) is None:
            raise JiraPluginError("validation_failed", "Project key is invalid.")
        payload = await self._request(
            "GET",
            "/rest/api/2/mypermissions",
            params={"projectKey": key},
        )
        permissions = payload.get("permissions") if isinstance(payload, dict) else None
        if not isinstance(permissions, dict):
            raise JiraPluginError(
                "malformed_upstream_response",
                "Jira permission response is invalid.",
            )
        return {
            "project_key": key,
            "permissions": {
                name: {
                    "name": _text(value.get("name")),
                    "description": _text(value.get("description")),
                    "have_permission": bool(value.get("havePermission")),
                }
                for name, value in list(permissions.items())[:500]
                if isinstance(name, str) and isinstance(value, dict)
            },
        }

    async def issues_search(
        self,
        *,
        jql: str = "",
        project_key: str = "",
        text: str = "",
        status: str = "",
        assignee: str = "",
        priority: str = "",
        issue_type: str = "",
        start_at: int = 0,
        page_size: int = 50,
    ) -> dict:
        if start_at < 0 or page_size < 1 or page_size > 100:
            raise JiraPluginError(
                "validation_failed",
                "start_at must be non-negative and page_size must be 1-100.",
            )
        query = build_jql(
            jql=jql,
            project_key=project_key,
            text=text,
            status=status,
            assignee=assignee,
            priority=priority,
            issue_type=issue_type,
        )
        payload = await self._request(
            "GET",
            "/rest/api/2/search",
            params={
                "jql": query,
                "fields": ISSUE_FIELDS,
                "startAt": start_at,
                "maxResults": page_size,
            },
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("issues"), list):
            raise JiraPluginError(
                "malformed_upstream_response",
                "Jira search response is invalid.",
            )
        items = [
            self._map_issue(item)
            for item in payload["issues"]
            if isinstance(item, dict)
        ]
        total = payload.get("total", len(items))
        total = total if isinstance(total, int) else len(items)
        actual_start = payload.get("startAt", start_at)
        actual_start = actual_start if isinstance(actual_start, int) else start_at
        return {
            "items": items,
            "page": {
                "start_at": actual_start,
                "page_size": page_size,
                "total": total,
                "is_last": actual_start + len(items) >= total,
            },
            "jql": query,
        }

    async def issue_get(self, *, issue_key: str) -> dict:
        key = issue_key.strip().upper()
        if ISSUE_KEY_RE.fullmatch(key) is None:
            raise JiraPluginError("validation_failed", "Issue key is invalid.")
        payload = await self._request(
            "GET",
            f"/rest/api/2/issue/{urllib.parse.quote(key, safe='')}",
            params={"fields": ISSUE_FIELDS},
        )
        if not isinstance(payload, dict):
            raise JiraPluginError(
                "malformed_upstream_response",
                "Jira issue response is invalid.",
            )
        return self._map_issue(payload, include_description=True)

    @staticmethod
    def _map_issue(issue: dict[str, Any], *, include_description: bool = False) -> dict:
        fields = issue.get("fields")
        fields = fields if isinstance(fields, dict) else {}
        result: dict[str, object] = {
            "id": _text(issue.get("id")),
            "key": _text(issue.get("key")),
            "summary": _text(fields.get("summary")),
            "issue_type": _display(fields.get("issuetype")),
            "status": _display(fields.get("status")),
            "priority": _display(fields.get("priority")),
            "assignee": _display(fields.get("assignee")),
            "reporter": _display(fields.get("reporter")),
            "created": _text(fields.get("created")),
            "updated": _text(fields.get("updated")),
            "resolution": _display(fields.get("resolution")),
            "labels": [
                item for item in fields.get("labels", []) if isinstance(item, str)
            ]
            if isinstance(fields.get("labels"), list)
            else [],
        }
        if include_description:
            description = fields.get("description")
            result["description"] = (
                description[:20_000] if isinstance(description, str) else None
            )
        return result
