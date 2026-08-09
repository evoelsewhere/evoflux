"""Installation-scoped Jira connection configuration.

This file-backed store is intentionally a developer/reference fallback. The
planned EvoFlux client extension will replace it with host-mediated secrets.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import JiraPluginError


MAX_CONNECTION_FILE_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class ConnectionConfig:
    name: str
    base_url: str
    api_token: str
    verify_ssl: bool = True

    def public_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "base_url": self.base_url,
            "verify_ssl": self.verify_ssl,
            "has_api_token": bool(self.api_token),
        }


class ConnectionStore:
    def __init__(
        self,
        path: str | Path,
        *,
        environment_connection: ConnectionConfig | None = None,
    ) -> None:
        self.path = Path(path).expanduser().absolute()
        self.environment_connection = environment_connection

    @classmethod
    def from_environment(cls) -> "ConnectionStore":
        data_root = os.environ.get("PLUGIN_DATA")
        base_url = os.environ.get("JIRA_URL", "").strip()
        api_token = os.environ.get("JIRA_API_TOKEN", "")
        if base_url and api_token:
            verify_raw = os.environ.get("JIRA_VERIFY_SSL", "true").casefold()
            verify_ssl = verify_raw not in {"0", "false", "no", "off"}
            path = Path(data_root or ".") / "connections.json"
            return cls(
                path,
                environment_connection=ConnectionConfig(
                    name="default",
                    base_url=base_url,
                    api_token=api_token,
                    verify_ssl=verify_ssl,
                ),
            )
        configured = os.environ.get("JIRA_CONNECTIONS_FILE")
        if configured:
            return cls(configured)
        if not data_root:
            raise JiraPluginError(
                "invalid_connection",
                "PLUGIN_DATA is unavailable; run Jira through the plugin runtime.",
            )
        return cls(Path(data_root) / "connections.json")

    def _read(self) -> dict[str, Any]:
        try:
            size = self.path.stat().st_size
        except FileNotFoundError as exc:
            raise JiraPluginError(
                "invalid_connection",
                "No Jira connections are configured for this plugin installation.",
            ) from exc
        except OSError as exc:
            raise JiraPluginError(
                "invalid_connection",
                "The Jira connection file cannot be read.",
            ) from exc
        if size > MAX_CONNECTION_FILE_BYTES:
            raise JiraPluginError(
                "invalid_connection",
                "The Jira connection file exceeds the 1 MiB safety limit.",
            )
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise JiraPluginError(
                "invalid_connection",
                "The Jira connection file is not valid UTF-8 JSON.",
            ) from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("connections"), dict):
            raise JiraPluginError(
                "invalid_connection",
                "The Jira connection file must contain a connections object.",
            )
        return raw

    def get(self, name: str = "default") -> ConnectionConfig:
        if self.environment_connection is not None and name == "default":
            return self.environment_connection
        record = self._read()["connections"].get(name)
        if not isinstance(record, dict):
            raise JiraPluginError(
                "invalid_connection",
                f"Jira connection {name!r} does not exist.",
            )
        base_url = record.get("base_url")
        api_token = record.get("api_token")
        verify_ssl = record.get("verify_ssl", True)
        if (
            not isinstance(base_url, str)
            or not base_url.strip()
            or not isinstance(api_token, str)
            or not api_token
            or not isinstance(verify_ssl, bool)
        ):
            raise JiraPluginError(
                "invalid_connection",
                f"Jira connection {name!r} is incomplete.",
            )
        return ConnectionConfig(
            name=name,
            base_url=base_url,
            api_token=api_token,
            verify_ssl=verify_ssl,
        )

    def list_public(self) -> list[dict[str, object]]:
        if self.environment_connection is not None:
            return [self.environment_connection.public_dict()]
        result: list[dict[str, object]] = []
        for name in sorted(self._read()["connections"]):
            try:
                result.append(self.get(name).public_dict())
            except JiraPluginError:
                continue
        return result

    def save(self, connection: ConnectionConfig) -> None:
        try:
            raw = self._read()
        except JiraPluginError as exc:
            if self.path.exists() or exc.code != "invalid_connection":
                raise
            raw = {"connections": {}}
        raw["connections"][connection.name] = {
            "base_url": connection.base_url,
            "api_token": connection.api_token,
            "verify_ssl": connection.verify_ssl,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".connections.",
            suffix=".tmp",
            dir=self.path.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(raw, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(0o600)
            os.replace(temporary, self.path)
            self.path.chmod(0o600)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
