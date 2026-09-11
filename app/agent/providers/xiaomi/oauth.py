"""Xiaomi MiMo Platform browser login — provisions an API key without typing one.

Ported from MiMoCode's ``mimo`` plugin (XiaomiMiMo/MiMo-Code,
``packages/opencode/src/plugin/mimo.ts``).

What it replaces: opening platform.xiaomimimo.com, creating a key by hand,
and pasting it into Settings. The platform mints the key for us and hands
it back over the loopback redirect — encrypted, so the secret never rides
in a URL that a browser history, a proxy log, or a shoulder can read.

The exchange
------------

1. Generate an X25519 keypair; the private half never leaves this process.
2. Open ``{platform}/authorize?pk=<SPKI DER, base64url>&redirect_uri=…``.
   The user signs in to Xiaomi there.
3. The platform redirects to our loopback server with ``?u=<blob>``.
4. ``blob = ephemeral_public(32) ‖ nonce(12) ‖ ciphertext ‖ tag(16)``.
   X25519 with the ephemeral public key gives a shared secret; its SHA-256
   is the AES-256-GCM key.
5. The plaintext is ``{"sk": …, "uid": …, "url": …?}`` — the API key, the
   account it belongs to, and optionally a per-account base URL.

The key lands in ``$EVOFLUX_CONFIG_DIR/.env`` as ``XIAOMI_API_KEY``, which
is the same place Settings → Providers writes it, so everything
downstream (discovery, the model picker, the chat validator) sees an
ordinary configured provider.

Called by the ``app.cli.commands.auth`` dispatcher::

    evoflux auth xiaomi

and by ``GET /api/auth/xiaomi/login`` for the Settings button.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sys
import urllib.parse
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Event, Thread
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from loguru import logger

from app.core.config import settings

# -- Constants ----------------------------------------------------------------

#: Where the browser is sent to sign in. Overridable for staging.
PLATFORM_URL = os.environ.get(
    "MIMO_PLATFORM_URL", "https://platform.xiaomimimo.com"
).rstrip("/")

#: The client identifier the authorize endpoint expects. It is part of the
#: platform's protocol rather than a display name — the name the user
#: actually sees against the minted key is ``key_name`` below, which says
#: EvoFlux.
PLATFORM_CLIENT = os.environ.get("MIMO_PLATFORM_CLIENT", "mimocode")

#: How long to wait for the user to finish signing in.
LOGIN_TIMEOUT_S = 300.0

#: base64url -> standard alphabet, for strict decoding (see _b64url_decode).
_URLSAFE_TO_STANDARD = bytes.maketrans(b"-_", b"+/")

EventSink = Callable[[str, dict[str, Any]], None]


def _say(event_sink: EventSink | None, event: str, message: str, **data: Any) -> None:
    """Dual stdout/event-sink emitter — see codex/oauth.py._say."""
    if event_sink is None:
        print(message)
        return
    event_sink(event, {"message": message, **data})


# -- Key naming ---------------------------------------------------------------


def _key_name_file() -> Path:
    return Path(settings.EVOFLUX_CACHE_DIR or "") / "mimo-key-name"


def key_name() -> str:
    """The name this installation's key carries in the MiMo console.

    Stable across logins so signing in again rotates the same named key
    instead of littering the user's account with one key per attempt.
    """
    path = _key_name_file()
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except (OSError, ValueError):
        pass
    name = f"evoflux-cli-key-{secrets.token_hex(4)}"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name, encoding="utf-8")
    except OSError as exc:
        logger.debug("mimo_key_name_persist_failed path={} error={}", path, exc)
    return name


# -- Crypto -------------------------------------------------------------------


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    # Translate then decode strictly. ``urlsafe_b64decode`` takes no
    # ``validate`` flag, and lax decoding silently drops characters outside
    # the alphabet — a mangled paste would come back short and be reported
    # as "too short" rather than as the malformed input it is.
    padded = (value + "=" * (-len(value) % 4)).encode("ascii")
    return base64.b64decode(padded.translate(_URLSAFE_TO_STANDARD), validate=True)


def generate_keypair() -> tuple[str, X25519PrivateKey]:
    """Return ``(public key as base64url SPKI DER, private key)``."""
    private_key = X25519PrivateKey.generate()
    public_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return _b64url_encode(public_der), private_key


def decrypt_payload(private_key: X25519PrivateKey, blob: str) -> dict[str, str]:
    """Open the platform's sealed reply.

    Raises ``ValueError`` for anything that is not a well-formed blob this
    key can open — a truncated redirect, a stale paste, a mismatched
    keypair all land here rather than as an opaque crypto error.
    """
    try:
        raw = _b64url_decode(blob)
    except (ValueError, TypeError) as exc:
        raise ValueError("Authorization payload is not valid base64url.") from exc
    # 32 ephemeral public + 12 nonce + 16 tag, before any ciphertext.
    if len(raw) < 60:
        raise ValueError("Authorization payload is too short to be valid.")

    ephemeral_public, nonce, sealed = raw[:32], raw[32:44], raw[44:]
    try:
        shared = private_key.exchange(
            X25519PublicKey.from_public_bytes(ephemeral_public)
        )
        aes_key = hashlib.sha256(shared).digest()
        plaintext = AESGCM(aes_key).decrypt(nonce, sealed, None)
    except Exception as exc:  # noqa: BLE001 - any crypto failure is one answer
        raise ValueError(
            "Could not decrypt the authorization payload — it was issued for "
            "a different login attempt."
        ) from exc

    try:
        payload = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Authorization payload was not the expected JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Authorization payload was not the expected JSON object.")
    return {str(k): str(v) for k, v in payload.items() if v is not None}


# -- URL ----------------------------------------------------------------------


def authorize_url(public_key: str, redirect_uri: str) -> str:
    params = urllib.parse.urlencode(
        {
            "pk": public_key,
            "redirect_uri": redirect_uri,
            "kn": PLATFORM_CLIENT,
            "key_name": key_name(),
        }
    )
    return f"{PLATFORM_URL}/authorize?{params}"


# -- Persistence --------------------------------------------------------------


def save_credentials(payload: dict[str, str]) -> dict[str, str]:
    """Write the minted key where every other provider path reads it.

    Returns the env vars written, so the caller can report them without
    echoing the secret.
    """
    from app.cli.seed import write_env_credentials

    key = payload.get("sk", "").strip()
    if not key:
        raise ValueError("The platform returned no API key for this account.")

    creds: dict[str, str] = {"XIAOMI_API_KEY": key}
    base_url = payload.get("url", "").strip()
    if base_url:
        creds["XIAOMI_BASE_URL"] = base_url

    env_file = Path(settings.EVOFLUX_CONFIG_DIR) / ".env"
    write_env_credentials(env_file, creds)
    # Mirror into the process so the very next build_provider sees it,
    # exactly as PUT /settings/providers/{id} does.
    for name, value in creds.items():
        os.environ[name] = value
    return creds


# -- Flow ---------------------------------------------------------------------


def _serve_callback(
    private_key: X25519PrivateKey,
) -> tuple[HTTPServer, dict[str, Any], Event]:
    """Start the loopback server the platform redirects back to."""
    result: dict[str, Any] = {}
    done = Event()

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            pass

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            blob = (query.get("u") or [""])[0]
            if not blob:
                result["error"] = "The platform redirect carried no payload."
                self._redirect("error", "missing_data")
                done.set()
                return
            try:
                result["payload"] = decrypt_payload(private_key, blob)
            except ValueError as exc:
                result["error"] = str(exc)
                self._redirect("error", "decrypt_failed")
                done.set()
                return
            self._redirect("success")
            done.set()

        def _redirect(self, status: str, message: str = "") -> None:
            params = {"status": status}
            if message:
                params["message"] = message
            location = (
                f"{PLATFORM_URL}/authorize/callback?{urllib.parse.urlencode(params)}"
            )
            self.send_response(302)
            self.send_header("Location", location)
            self.end_headers()

    # Bound by the same name the redirect_uri uses, so however this host
    # resolves "localhost" the browser and the listener land together.
    # Loopback only: this socket receives the account's API key.
    server = HTTPServer(("localhost", 0), _Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    return server, result, done


def login(*, event_sink: EventSink | None = None) -> None:
    """Sign in to the MiMo platform and store the key it mints.

    With no ``event_sink`` this is the CLI flow: it opens a browser and
    prints progress. With one, it is the UI flow: the caller opens the URL
    and renders the events, and failures raise instead of exiting.
    """
    public_key, private_key = generate_keypair()
    server, result, done = _serve_callback(private_key)
    port = server.server_address[1]
    redirect_uri = f"http://localhost:{port}/"
    url = authorize_url(public_key, redirect_uri)

    _say(
        event_sink,
        "browser_auth",
        f"Opening browser to sign in to MiMo: {url}",
        verification_uri=url,
    )
    if event_sink is None:
        webbrowser.open(url)

    try:
        if not done.wait(timeout=LOGIN_TIMEOUT_S):
            _fail(event_sink, "Timed out waiting for the MiMo sign-in to finish.")
            return
        if result.get("error"):
            _fail(event_sink, str(result["error"]))
            return
        try:
            written = save_credentials(result.get("payload") or {})
        except ValueError as exc:
            _fail(event_sink, str(exc))
            return
    finally:
        server.shutdown()
        server.server_close()

    payload = result.get("payload") or {}
    _say(
        event_sink,
        "success",
        f"Signed in to MiMo. Saved {', '.join(sorted(written))}.",
        uid=payload.get("uid", ""),
        env_vars=sorted(written),
    )


def _fail(event_sink: EventSink | None, message: str) -> None:
    _say(event_sink, "failed", message)
    if event_sink is not None:
        raise RuntimeError(message)
    sys.exit(1)
