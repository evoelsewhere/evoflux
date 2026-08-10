"""Host-mediated credentials for portable plugin MCP processes."""

from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.parse
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.plugin_platform.models import PluginInspection
from app.plugin_platform.registry import plugin_data_root


CREDENTIALS_EXTENSION = "evoflux.credentials"
MASKED_SECRET = "********"
MAX_CREDENTIAL_BYTES = 256 * 1024
_KEY_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_ENV_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
_RESERVED_ENV = {"PATH", "PLUGIN_ROOT", "PLUGIN_DATA"}


class PluginCredentialField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    type: Literal["text", "secret", "url", "boolean"] = "text"
    env: str
    required: bool = False
    description: str = ""
    placeholder: str = ""
    default: str | bool | None = None

    @field_validator("key")
    @classmethod
    def valid_key(cls, value: str) -> str:
        if _KEY_RE.fullmatch(value) is None:
            raise ValueError("credential key must be a lowercase identifier")
        return value

    @field_validator("env")
    @classmethod
    def valid_env(cls, value: str) -> str:
        if _ENV_RE.fullmatch(value) is None or value in _RESERVED_ENV:
            raise ValueError("credential env name is invalid or reserved")
        return value

    @model_validator(mode="after")
    def valid_default(self) -> PluginCredentialField:
        _validate_field_value(self, self.default)
        return self


class PluginCredentialDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: list[PluginCredentialField] = Field(max_length=32)


class PluginCredentialFieldState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    type: Literal["text", "secret", "url", "boolean"]
    env: str
    required: bool
    description: str
    placeholder: str
    configured: bool
    value: str | bool | None = None


class PluginCredentialState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supported: bool
    configured: bool
    fields: list[PluginCredentialFieldState] = Field(default_factory=list)
    error: str | None = None


def credential_definition(
    inspection: PluginInspection,
) -> PluginCredentialDefinition | None:
    if inspection.manifest is None:
        return None
    raw = inspection.manifest.extensions.get(CREDENTIALS_EXTENSION)
    if raw is None:
        return None
    definition = PluginCredentialDefinition.model_validate(raw)
    keys = [field.key for field in definition.fields]
    env_names = [field.env for field in definition.fields]
    if len(keys) != len(set(keys)) or len(env_names) != len(set(env_names)):
        raise ValueError("Plugin credential field keys and env names must be unique.")
    return definition


def credentials_path(installation_id: str) -> Path:
    return plugin_data_root(installation_id) / "credentials.json"


def _read_values(installation_id: str) -> dict[str, str | bool]:
    path = credentials_path(installation_id)
    if not path.exists():
        return {}
    if path.stat().st_size > MAX_CREDENTIAL_BYTES:
        raise ValueError("Plugin credential store exceeds its size limit.")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Plugin credential store must be a JSON object.")
    if not all(
        isinstance(key, str) and isinstance(value, (str, bool))
        for key, value in raw.items()
    ):
        raise ValueError("Plugin credential store contains an unsupported value.")
    return raw


def _has_value(value: str | bool | None) -> bool:
    return isinstance(value, bool) or isinstance(value, str) and bool(value)


def _validate_field_value(
    field: PluginCredentialField,
    value: str | bool | None,
) -> None:
    if value is None or value == "":
        return
    if field.type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"Credential {field.key!r} must be a boolean.")
        return
    if not isinstance(value, str):
        raise ValueError(f"Credential {field.key!r} must be text.")
    if field.type != "url":
        return
    try:
        parsed = urllib.parse.urlsplit(value)
        hostname = parsed.hostname
        parsed.port
    except ValueError as exc:
        raise ValueError(f"Credential {field.key!r} must be a valid URL.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError(
            f"Credential {field.key!r} must be an absolute HTTP(S) URL "
            "without user information or a fragment."
        )


def credential_state(
    installation_id: str,
    inspection: PluginInspection,
) -> PluginCredentialState:
    definition = credential_definition(inspection)
    if definition is None:
        return PluginCredentialState(supported=False, configured=True)
    values = _read_values(installation_id)
    fields: list[PluginCredentialFieldState] = []
    for field in definition.fields:
        value = values.get(field.key, field.default)
        _validate_field_value(field, value)
        configured = _has_value(value)
        fields.append(
            PluginCredentialFieldState(
                key=field.key,
                label=field.label,
                type=field.type,
                env=field.env,
                required=field.required,
                description=field.description,
                placeholder=field.placeholder,
                configured=configured,
                value=MASKED_SECRET if field.type == "secret" and configured else value,
            )
        )
    return PluginCredentialState(
        supported=True,
        configured=all(not field.required or field.configured for field in fields),
        fields=fields,
    )


def save_credentials(
    installation_id: str,
    inspection: PluginInspection,
    updates: dict[str, str | bool | None],
) -> PluginCredentialState:
    definition = credential_definition(inspection)
    if definition is None:
        raise ValueError("This plugin does not declare an EvoFlux credential schema.")
    by_key = {field.key: field for field in definition.fields}
    unknown = set(updates).difference(by_key)
    if unknown:
        raise ValueError(
            f"Unknown plugin credential fields: {', '.join(sorted(unknown))}"
        )
    values = _read_values(installation_id)
    for key, value in updates.items():
        field = by_key[key]
        if value == MASKED_SECRET and field.type == "secret":
            continue
        if value is None or value == "":
            values.pop(key, None)
            continue
        _validate_field_value(field, value)
        values[key] = value

    allowed = set(by_key)
    values = {key: value for key, value in values.items() if key in allowed}
    path = credentials_path(installation_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".credentials.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(values, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)
    return credential_state(installation_id, inspection)


def clear_credentials(
    installation_id: str,
    inspection: PluginInspection,
) -> PluginCredentialState:
    credentials_path(installation_id).unlink(missing_ok=True)
    return credential_state(installation_id, inspection)


def credential_environment(
    installation_id: str,
    inspection: PluginInspection,
) -> dict[str, str]:
    definition = credential_definition(inspection)
    if definition is None:
        return {}
    values = _read_values(installation_id)
    result: dict[str, str] = {}
    for field in definition.fields:
        value = values.get(field.key, field.default)
        _validate_field_value(field, value)
        if not _has_value(value):
            continue
        result[field.env] = (
            "true" if value is True else "false" if value is False else str(value)
        )
    return result


__all__ = [
    "CREDENTIALS_EXTENSION",
    "MASKED_SECRET",
    "PluginCredentialDefinition",
    "PluginCredentialField",
    "PluginCredentialFieldState",
    "PluginCredentialState",
    "clear_credentials",
    "credential_definition",
    "credential_environment",
    "credential_state",
    "credentials_path",
    "save_credentials",
]
