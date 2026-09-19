"""Keyed storage for integration credentials in the operating-system vault."""

from __future__ import annotations

from typing import Protocol


class CredentialStoreProtocol(Protocol):
    def load(self) -> str | None: ...

    def save(self, credential: str) -> None: ...

    def delete(self) -> None: ...


class CredentialStoreError(RuntimeError):
    """The operating-system credential vault could not complete an operation."""


class CredentialStore:
    """Store one credential under an explicit service and account key."""

    def __init__(self, *, service: str, account: str) -> None:
        if not service.strip() or not account.strip():
            raise ValueError("Credential service and account must not be empty.")
        self._service = service
        self._account = account

    def load(self) -> str | None:
        try:
            import keyring

            return keyring.get_password(self._service, self._account)
        except Exception as exc:
            raise CredentialStoreError(
                "The operating system credential vault is unavailable."
            ) from exc

    def save(self, credential: str) -> None:
        try:
            import keyring

            keyring.set_password(self._service, self._account, credential)
        except Exception as exc:
            raise CredentialStoreError(
                "The credential could not be saved to the operating system credential vault."
            ) from exc

    def delete(self) -> None:
        try:
            import keyring
            from keyring.errors import PasswordDeleteError
        except Exception as exc:
            raise CredentialStoreError(
                "The operating system credential vault is unavailable."
            ) from exc

        try:
            keyring.delete_password(self._service, self._account)
        except PasswordDeleteError:
            return
        except Exception as exc:
            raise CredentialStoreError(
                "The credential could not be deleted from the operating system credential vault."
            ) from exc


__all__ = ["CredentialStore", "CredentialStoreError", "CredentialStoreProtocol"]
