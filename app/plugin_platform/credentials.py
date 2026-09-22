"""Host-mediated credentials for portable plugin MCP processes."""

from __future__ import annotations

import base64
import json
import os
from datetime import UTC, datetime
import re
import urllib.parse
from pathlib import Path
from typing import Callable, Protocol, cast

import keyring
import keyring.errors
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.plugin_platform.extensions import (
    CREDENTIALS_EXTENSION,
    LEGACY_CREDENTIALS_EXTENSIONS,
    resolve_extension,
)
from app.plugin_platform.models import PluginInspection
from app.plugin_platform.registry import plugin_data_root


MASKED_SECRET = "********"
MAX_CREDENTIAL_BYTES = 256 * 1024
_KEY_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_ENV_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
_CREDENTIAL_REF_RE = re.compile(r"\$\{PLUGIN_CREDENTIAL:([A-Z][A-Z0-9_]{1,63})\}")
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
    raw = resolve_extension(
        inspection.manifest.extensions,
        CREDENTIALS_EXTENSION,
        LEGACY_CREDENTIALS_EXTENSIONS,
    )
    if raw is None:
        return None
    definition = PluginCredentialDefinition.model_validate(raw)
    keys = [field.key for field in definition.fields]
    env_names = [field.env for field in definition.fields]
    if len(keys) != len(set(keys)) or len(env_names) != len(set(env_names)):
        raise ValueError("Plugin credential field keys and env names must be unique.")
    return definition


class CredentialAccessError(RuntimeError):
    """Credential access was denied by lifecycle or ownership metadata."""


class CredentialMetadata(BaseModel):
    """Non-secret scope and lifecycle metadata for one credential revision."""

    installation_id: str
    workspace_id: str | None = None
    project_id: str | None = None
    connection_profile_id: str | None = None
    tenant: str | None = None
    package_digest: str | None = None
    revision: int = 1
    created_at: str
    expires_at: str | None = None
    revoked_at: str | None = None
    revocation_reason: str | None = None

    def active(self, *, now: datetime | None = None) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at is None:
            return True
        current = now or datetime.now(UTC)
        return datetime.fromisoformat(self.expires_at) > current


class CredentialStore(Protocol):
    """Secret store contract used by the host credential broker."""

    def read(self) -> dict[str, str | bool]: ...

    def write(self, values: dict[str, str | bool]) -> None: ...

    def clear(self) -> None: ...

    def metadata(self) -> CredentialMetadata | None: ...

    def rotate(
        self, values: dict[str, str | bool], metadata: CredentialMetadata
    ) -> None: ...

    def revoke(self, reason: str) -> None: ...


class KeyringCredentialStore:
    """OS keychain/enterprise secret-manager backed credential store."""

    _SERVICE = "evoflux.plugin.credentials"

    def __init__(
        self,
        installation_id: str,
        *,
        audit_hook: Callable[[str, str], None] | None = None,
    ) -> None:
        self._account = installation_id
        self._audit_hook = audit_hook

    def _audit(self, event: str) -> None:
        if self._audit_hook is not None:
            self._audit_hook(event, self._account)

    def _payload(self) -> dict[str, object]:
        raw = keyring.get_password(self._SERVICE, self._account)
        if raw is None:
            return {"version": 2, "values": {}, "metadata": None}
        payload = json.loads(raw)
        if isinstance(payload, dict) and "values" in payload:
            return payload
        return {"version": 2, "values": payload, "metadata": None}

    def read(self) -> dict[str, str | bool]:
        payload = self._payload()
        _require_active(payload.get("metadata"))
        self._audit("read")
        return _validate_values(payload["values"])

    def write(self, values: dict[str, str | bool]) -> None:
        payload = self._payload()
        _require_active(payload.get("metadata"))
        payload.update({"version": 2, "values": values})
        keyring.set_password(
            self._SERVICE, self._account, json.dumps(payload, sort_keys=True)
        )
        self._audit("write")

    def metadata(self) -> CredentialMetadata | None:
        value = self._payload().get("metadata")
        return CredentialMetadata.model_validate(value) if value is not None else None

    def rotate(
        self, values: dict[str, str | bool], metadata: CredentialMetadata
    ) -> None:
        keyring.set_password(
            self._SERVICE,
            self._account,
            json.dumps(
                {"version": 2, "values": values, "metadata": metadata.model_dump()},
                sort_keys=True,
            ),
        )
        self._audit("rotate")

    def revoke(self, reason: str) -> None:
        payload = self._payload()
        metadata = self.metadata()
        if metadata is None:
            return
        payload["metadata"] = metadata.model_copy(
            update={
                "revoked_at": datetime.now(UTC).isoformat(),
                "revocation_reason": reason,
            }
        ).model_dump()
        keyring.set_password(
            self._SERVICE, self._account, json.dumps(payload, sort_keys=True)
        )
        self._audit("revoke")

    def clear(self) -> None:
        try:
            keyring.delete_password(self._SERVICE, self._account)
        except keyring.errors.PasswordDeleteError:
            return
        self._audit("clear")


class EncryptedFileCredentialStore:
    """Encrypted local compatibility store, with its key held by the keyring."""

    _KEY_SERVICE = "evoflux.plugin.credentials.local"
    _KEY_ACCOUNT = "master-key"

    def __init__(
        self,
        path: Path,
        *,
        audit_hook: Callable[[str, str], None] | None = None,
    ) -> None:
        self._path = path
        self._audit_hook = audit_hook

    def _audit(self, event: str) -> None:
        if self._audit_hook is not None:
            self._audit_hook(event, str(self._path))

    @classmethod
    def _key(cls) -> bytes:
        encoded = keyring.get_password(cls._KEY_SERVICE, cls._KEY_ACCOUNT)
        if encoded is None:
            key = AESGCM.generate_key(bit_length=256)
            keyring.set_password(
                cls._KEY_SERVICE,
                cls._KEY_ACCOUNT,
                base64.urlsafe_b64encode(key).decode("ascii"),
            )
            return key
        return base64.urlsafe_b64decode(encoded.encode("ascii"))

    def _payload(self) -> dict[str, object]:
        if not self._path.exists():
            return {"version": 2, "values": {}, "metadata": None}
        if self._path.stat().st_size > MAX_CREDENTIAL_BYTES:
            raise ValueError("Plugin credential store exceeds its size limit.")
        envelope = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(envelope, dict) or envelope.get("version") != 1:
            raise ValueError("Plugin credential store has an invalid envelope.")
        plaintext = AESGCM(self._key()).decrypt(
            base64.urlsafe_b64decode(str(envelope["nonce"]).encode("ascii")),
            base64.urlsafe_b64decode(str(envelope["ciphertext"]).encode("ascii")),
            None,
        )
        payload = json.loads(plaintext.decode("utf-8"))
        if isinstance(payload, dict) and "values" in payload:
            return payload
        return {"version": 2, "values": payload, "metadata": None}

    def read(self) -> dict[str, str | bool]:
        payload = self._payload()
        _require_active(payload.get("metadata"))
        return _validate_values(payload["values"])

    def _write_payload(self, payload: dict[str, object]) -> None:
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._key()).encrypt(
            nonce, json.dumps(payload, sort_keys=True).encode("utf-8"), None
        )
        _atomic_write(
            self._path,
            {
                "version": 1,
                "nonce": base64.urlsafe_b64encode(nonce).decode("ascii"),
                "ciphertext": base64.urlsafe_b64encode(ciphertext).decode("ascii"),
            },
        )

    def write(self, values: dict[str, str | bool]) -> None:
        payload = self._payload()
        _require_active(payload.get("metadata"))
        payload.update({"version": 2, "values": values})
        self._write_payload(payload)
        self._audit("write")

    def metadata(self) -> CredentialMetadata | None:
        value = self._payload().get("metadata")
        return CredentialMetadata.model_validate(value) if value is not None else None

    def rotate(
        self, values: dict[str, str | bool], metadata: CredentialMetadata
    ) -> None:
        self._write_payload(
            {"version": 2, "values": values, "metadata": metadata.model_dump()}
        )
        self._audit("rotate")

    def revoke(self, reason: str) -> None:
        metadata = self.metadata()
        if metadata is None:
            return
        payload = self._payload()
        payload["metadata"] = metadata.model_copy(
            update={
                "revoked_at": datetime.now(UTC).isoformat(),
                "revocation_reason": reason,
            }
        ).model_dump()
        self._write_payload(payload)
        self._audit("revoke")

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)
        self._audit("clear")


def _validate_values(raw: object) -> dict[str, str | bool]:
    if not isinstance(raw, dict) or not all(
        isinstance(key, str) and isinstance(value, (str, bool))
        for key, value in raw.items()
    ):
        raise ValueError("Plugin credential store contains an unsupported value.")
    return cast(dict[str, str | bool], raw)


def enforce_credential_scope(
    metadata: CredentialMetadata,
    *,
    installation_id: str,
    workspace_id: str | None = None,
    project_id: str | None = None,
    tenant: str | None = None,
    package_digest: str | None = None,
) -> None:
    if not metadata.active():
        raise CredentialAccessError("Credential is expired or revoked.")
    expected = {
        "installation_id": installation_id,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "tenant": tenant,
        "package_digest": package_digest,
    }
    for field, requested in expected.items():
        recorded = getattr(metadata, field)
        if requested is not None and recorded != requested:
            raise CredentialAccessError(f"Credential scope mismatch: {field}.")


def _require_active(value: object) -> None:
    if value is None:
        return
    metadata = CredentialMetadata.model_validate(value)
    if not metadata.active():
        raise CredentialAccessError("Credential is expired or revoked.")


def _atomic_write(path: Path, values: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as output:
            json.dump(values, output, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _store(installation_id: str) -> CredentialStore:
    if os.environ.get("EVOFLUX_CREDENTIAL_BACKEND") == "encrypted_file":
        return EncryptedFileCredentialStore(credentials_path(installation_id))
    return KeyringCredentialStore(installation_id)


def credentials_path(installation_id: str) -> Path:
    return plugin_data_root(installation_id) / "credentials.json"


def migrate_credential_file(installation_id: str) -> bool:
    """Move a legacy credential file into the keyring after read-back verification."""

    path = credentials_path(installation_id)
    if (
        not path.exists()
        or os.environ.get("EVOFLUX_CREDENTIAL_BACKEND") == "encrypted_file"
    ):
        return False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and raw.get("version") == 1 and "ciphertext" in raw:
            values = EncryptedFileCredentialStore(path).read()
        else:
            values = _validate_values(raw)
        target = KeyringCredentialStore(installation_id)
        target.write(values)
        if target.read() != values:
            raise ValueError("Credential migration read-back verification failed.")
    except Exception:
        return False
    path.unlink(missing_ok=True)
    return True


def _read_values(installation_id: str) -> dict[str, str | bool]:
    migrate_credential_file(installation_id)
    return _store(installation_id).read()


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
    _store(installation_id).write(values)
    return credential_state(installation_id, inspection)


def clear_credentials(
    installation_id: str,
    inspection: PluginInspection,
) -> PluginCredentialState:
    _store(installation_id).clear()
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


def credential_headers(
    installation_id: str,
    inspection: PluginInspection,
    headers: dict[str, str],
) -> dict[str, str]:
    """Expand only declared credential references into approved transport headers."""

    definition = credential_definition(inspection)
    if definition is None:
        return dict(headers)
    fields = {field.env: field for field in definition.fields}
    values = _read_values(installation_id)
    result: dict[str, str] = {}
    for name, template in headers.items():
        if not isinstance(template, str):
            raise ValueError("Credential header values must be strings.")

        def replace(match: re.Match[str]) -> str:
            env_name = match.group(1)
            field = fields.get(env_name)
            if field is None:
                raise ValueError("Credential header references an undeclared field.")
            value = values.get(field.key, field.default)
            _validate_field_value(field, value)
            if not _has_value(value):
                raise ValueError("Credential header references an unconfigured field.")
            return (
                "true" if value is True else "false" if value is False else str(value)
            )

        result[name] = _CREDENTIAL_REF_RE.sub(replace, template)
    return result


__all__ = [
    "CredentialStore",
    "EncryptedFileCredentialStore",
    "KeyringCredentialStore",
    "CREDENTIALS_EXTENSION",
    "MASKED_SECRET",
    "PluginCredentialDefinition",
    "PluginCredentialField",
    "PluginCredentialFieldState",
    "PluginCredentialState",
    "clear_credentials",
    "credential_definition",
    "credential_environment",
    "credential_headers",
    "credential_state",
    "enforce_credential_scope",
    "credentials_path",
    "migrate_credential_file",
    "save_credentials",
]
