from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.credential_store import CredentialStore, CredentialStoreError


def test_keyed_store_keeps_connection_credentials_isolated(monkeypatch) -> None:
    values: dict[tuple[str, str], str] = {}

    fake_keyring = SimpleNamespace(
        get_password=lambda service, account: values.get((service, account)),
        set_password=lambda service, account, value: values.__setitem__(
            (service, account), value
        ),
        delete_password=lambda service, account: values.pop((service, account)),
    )
    monkeypatch.setitem(__import__("sys").modules, "keyring", fake_keyring)

    first = CredentialStore(service="EvoFlux Remote", account="connection:first")
    second = CredentialStore(service="EvoFlux Remote", account="connection:second")

    first.save("first-secret")
    second.save("second-secret")

    assert first.load() == "first-secret"
    assert second.load() == "second-secret"


def test_keyed_store_wraps_save_failure_without_echoing_secret(monkeypatch) -> None:
    def fail_save(service: str, account: str, value: str) -> None:
        del service, account, value
        raise RuntimeError("backend failed")

    fake_keyring = SimpleNamespace(set_password=fail_save)
    monkeypatch.setitem(__import__("sys").modules, "keyring", fake_keyring)

    store = CredentialStore(service="EvoFlux Remote", account="connection:first")
    with pytest.raises(CredentialStoreError) as exc_info:
        store.save("must-not-appear")

    assert str(exc_info.value) == "The credential could not be saved to the operating system credential vault."
    assert "must-not-appear" not in str(exc_info.value)


def test_keyed_store_treats_missing_credential_as_successful_delete(monkeypatch) -> None:
    class PasswordDeleteError(Exception):
        pass

    def missing(service: str, account: str) -> None:
        del service, account
        raise PasswordDeleteError

    fake_keyring = SimpleNamespace(
        delete_password=missing,
        errors=SimpleNamespace(PasswordDeleteError=PasswordDeleteError),
    )
    monkeypatch.setitem(__import__("sys").modules, "keyring", fake_keyring)
    monkeypatch.setitem(
        __import__("sys").modules,
        "keyring.errors",
        fake_keyring.errors,
    )

    CredentialStore(
        service="EvoFlux Remote", account="connection:missing"
    ).delete()
