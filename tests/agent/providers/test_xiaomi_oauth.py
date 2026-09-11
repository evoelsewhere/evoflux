"""Tests for app/agent/providers/xiaomi/oauth.py — the MiMo browser sign-in.

The sealing half lives on Xiaomi's platform, so these tests carry a local
copy of it, written from the wire format MiMoCode's plugin implements
(``packages/opencode/src/plugin/mimo.ts``). That pins the byte layout this
port has to keep speaking: swap the field order or the KDF and the
round-trip breaks here rather than at a user's first login.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.parse
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.agent.providers.xiaomi import oauth


def _seal(recipient_public_b64: str, payload: dict[str, str]) -> str:
    """Encrypt to *recipient_public_b64* the way the platform does."""
    spki = base64.urlsafe_b64decode(
        recipient_public_b64 + "=" * (-len(recipient_public_b64) % 4)
    )
    recipient = serialization.load_der_public_key(spki)
    ephemeral = X25519PrivateKey.generate()
    shared = ephemeral.exchange(recipient)  # type: ignore[arg-type]
    aes_key = hashlib.sha256(shared).digest()
    nonce = os.urandom(12)
    sealed = AESGCM(aes_key).encrypt(nonce, json.dumps(payload).encode("utf-8"), None)
    ephemeral_raw = ephemeral.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    blob = ephemeral_raw + nonce + sealed
    return base64.urlsafe_b64encode(blob).decode("ascii").rstrip("=")


def test_public_key_is_the_spki_der_node_sends() -> None:
    """The platform is handed a full SPKI DER, not the raw 32 bytes."""
    public_b64, _private = oauth.generate_keypair()
    raw = base64.urlsafe_b64decode(public_b64 + "=" * (-len(public_b64) % 4))

    assert len(raw) == 44
    assert raw[:12].hex() == "302a300506032b656e032100"
    assert "=" not in public_b64  # base64url, unpadded, as Node emits


def test_sealed_reply_round_trips() -> None:
    public_b64, private_key = oauth.generate_keypair()
    blob = _seal(
        public_b64, {"sk": "sk-mimo-123", "uid": "u-42", "url": "https://x/v1"}
    )

    assert oauth.decrypt_payload(private_key, blob) == {
        "sk": "sk-mimo-123",
        "uid": "u-42",
        "url": "https://x/v1",
    }


def test_reply_for_another_attempt_is_refused() -> None:
    """Each login generates its own keypair; a stale blob must not open."""
    public_b64, _private = oauth.generate_keypair()
    _other_public, other_private = oauth.generate_keypair()
    blob = _seal(public_b64, {"sk": "sk-mimo-123", "uid": "u-42"})

    with pytest.raises(ValueError, match="different login attempt"):
        oauth.decrypt_payload(other_private, blob)


@pytest.mark.parametrize(
    ("blob", "message"),
    [
        ("", "too short"),
        ("AAAA", "too short"),
        ("not valid base64!!", "base64url"),
    ],
)
def test_malformed_payloads_say_what_is_wrong(blob: str, message: str) -> None:
    _public, private_key = oauth.generate_keypair()

    with pytest.raises(ValueError, match=message):
        oauth.decrypt_payload(private_key, blob)


def test_authorize_url_carries_the_platform_parameters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(oauth.settings, "EVOFLUX_CACHE_DIR", str(tmp_path))
    public_b64, _private = oauth.generate_keypair()

    url = oauth.authorize_url(public_b64, "http://localhost:5555/")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)

    assert url.startswith(f"{oauth.PLATFORM_URL}/authorize?")
    assert query["pk"] == [public_b64]
    assert query["redirect_uri"] == ["http://localhost:5555/"]
    assert query["kn"] == [oauth.PLATFORM_CLIENT]
    # The name the user sees against the key in their MiMo console.
    assert query["key_name"][0].startswith("evoflux-cli-key-")


def test_key_name_is_stable_across_logins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Signing in twice rotates one named key, not two."""
    monkeypatch.setattr(oauth.settings, "EVOFLUX_CACHE_DIR", str(tmp_path))

    first = oauth.key_name()
    second = oauth.key_name()

    assert first == second
    assert (tmp_path / "mimo-key-name").read_text(encoding="utf-8") == first


def test_saving_writes_the_key_where_settings_reads_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(oauth.settings, "EVOFLUX_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("XIAOMI_API_KEY", raising=False)
    monkeypatch.delenv("XIAOMI_BASE_URL", raising=False)

    written = oauth.save_credentials(
        {"sk": "sk-mimo-123", "uid": "u-42", "url": "https://acct.example/v1"}
    )

    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert written == {
        "XIAOMI_API_KEY": "sk-mimo-123",
        "XIAOMI_BASE_URL": "https://acct.example/v1",
    }
    assert "XIAOMI_API_KEY=sk-mimo-123" in env
    # Mirrored into the process so the next build_provider sees it without
    # a restart, the same way PUT /settings/providers/{id} does.
    assert os.environ["XIAOMI_API_KEY"] == "sk-mimo-123"


def test_saving_without_a_key_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(oauth.settings, "EVOFLUX_CONFIG_DIR", str(tmp_path))

    with pytest.raises(ValueError, match="no API key"):
        oauth.save_credentials({"uid": "u-42"})

    assert not (tmp_path / ".env").exists()


def test_account_without_a_custom_base_url_writes_only_the_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``url`` is optional — most accounts use the catalog's endpoint."""
    monkeypatch.setattr(oauth.settings, "EVOFLUX_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("XIAOMI_BASE_URL", raising=False)

    written = oauth.save_credentials({"sk": "sk-mimo-123", "uid": "u-42"})

    assert written == {"XIAOMI_API_KEY": "sk-mimo-123"}
    assert "XIAOMI_BASE_URL" not in (tmp_path / ".env").read_text(encoding="utf-8")


def test_xiaomi_is_registered_with_the_auth_dispatcher() -> None:
    """``evoflux auth xiaomi`` and GET /api/auth/xiaomi/login share this."""
    from app.cli.commands.auth import _PROVIDERS

    module_path, _description = _PROVIDERS["xiaomi"]
    assert module_path == "app.agent.providers.xiaomi.oauth"


def test_provider_row_advertises_the_browser_sign_in() -> None:
    from app.agent.providers.catalog import find

    entry = find("xiaomi")

    assert entry is not None
    assert entry["kind"] == "api_key"  # the key field keeps working
    assert entry.get("browser_login") is True
