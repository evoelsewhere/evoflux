from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.plugin_platform.credentials import (
    CredentialAccessError,
    CredentialMetadata,
    EncryptedFileCredentialStore,
    credential_environment,
    credential_headers,
    credential_state,
    KeyringCredentialStore,
    migrate_credential_file,
)
from app.plugin_platform.extensions import CREDENTIALS_EXTENSION


def test_keyring_store_round_trips_and_clears(monkeypatch) -> None:
    values: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(
        "app.plugin_platform.credentials.keyring.get_password",
        lambda service, account: values.get((service, account)),
    )
    monkeypatch.setattr(
        "app.plugin_platform.credentials.keyring.set_password",
        lambda service, account, value: values.__setitem__((service, account), value),
    )
    monkeypatch.setattr(
        "app.plugin_platform.credentials.keyring.delete_password",
        lambda service, account: values.pop((service, account)),
    )

    store = KeyringCredentialStore("installation-a")
    store.write({"token": "secret", "enabled": True})

    assert store.read() == {"token": "secret", "enabled": True}
    store.clear()
    assert store.read() == {}


def test_keyring_store_rotation_expiry_and_revocation(monkeypatch) -> None:
    values: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(
        "app.plugin_platform.credentials.keyring.get_password",
        lambda service, account: values.get((service, account)),
    )
    monkeypatch.setattr(
        "app.plugin_platform.credentials.keyring.set_password",
        lambda service, account, value: values.__setitem__((service, account), value),
    )

    store = KeyringCredentialStore("installation-b")
    metadata = CredentialMetadata(
        installation_id="installation-b",
        tenant="tenant-a",
        revision=2,
        created_at=datetime.now(UTC).isoformat(),
        expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    )
    store.rotate({"token": "rotated"}, metadata)
    assert store.read() == {"token": "rotated"}
    assert store.metadata().revision == 2

    expired = metadata.model_copy(
        update={"expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()}
    )
    store.rotate({"token": "expired"}, expired)
    with pytest.raises(CredentialAccessError, match="expired or revoked"):
        store.read()

    store.rotate({"token": "active"}, metadata)
    store.revoke("tenant disabled")
    with pytest.raises(CredentialAccessError, match="expired or revoked"):
        store.read()
    assert store.metadata().revocation_reason == "tenant disabled"


def test_credentials_are_process_environment_or_approved_header_only(
    monkeypatch,
) -> None:
    inspection = SimpleNamespace(
        manifest=SimpleNamespace(
            extensions={
                CREDENTIALS_EXTENSION: {
                    "fields": [
                        {
                            "key": "token",
                            "label": "Token",
                            "type": "secret",
                            "env": "API_TOKEN",
                            "required": True,
                        }
                    ]
                }
            }
        )
    )
    monkeypatch.setattr(
        "app.plugin_platform.credentials._read_values", lambda _id: {"token": "secret"}
    )

    assert credential_environment("installation-c", inspection) == {
        "API_TOKEN": "secret"
    }
    state = credential_state("installation-c", inspection)
    assert state.fields[0].value == "********"
    assert "value='secret'" not in repr(state)
    assert credential_headers(
        "installation-c",
        inspection,
        {"Authorization": "Bearer ${PLUGIN_CREDENTIAL:API_TOKEN}"},
    ) == {"Authorization": "Bearer secret"}
    with pytest.raises(ValueError, match="undeclared"):
        credential_headers(
            "installation-c",
            inspection,
            {"Authorization": "${PLUGIN_CREDENTIAL:OTHER}"},
        )


def test_legacy_file_migrates_only_after_keyring_readback(
    monkeypatch, tmp_path
) -> None:
    values: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(
        "app.plugin_platform.credentials.keyring.get_password",
        lambda service, account: values.get((service, account)),
    )
    monkeypatch.setattr(
        "app.plugin_platform.credentials.keyring.set_password",
        lambda service, account, value: values.__setitem__((service, account), value),
    )
    monkeypatch.setattr(
        "app.plugin_platform.credentials.plugin_data_root", lambda _id: tmp_path
    )
    path = tmp_path / "credentials.json"
    path.write_text('{"token": "legacy"}', encoding="utf-8")

    assert migrate_credential_file("installation-c") is True
    assert not path.exists()
    assert KeyringCredentialStore("installation-c").read() == {"token": "legacy"}


def test_encrypted_file_store_never_writes_plaintext(monkeypatch, tmp_path) -> None:
    values: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(
        "app.plugin_platform.credentials.keyring.get_password",
        lambda service, account: values.get((service, account)),
    )
    monkeypatch.setattr(
        "app.plugin_platform.credentials.keyring.set_password",
        lambda service, account, value: values.__setitem__((service, account), value),
    )

    path = tmp_path / "credentials.json"
    store = EncryptedFileCredentialStore(path)
    store.write({"api_token": "top-secret"})

    encoded = path.read_text(encoding="utf-8")
    assert "top-secret" not in encoded
    assert base64.urlsafe_b64decode(values[(store._KEY_SERVICE, store._KEY_ACCOUNT)])
    assert store.read() == {"api_token": "top-secret"}
