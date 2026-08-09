"""GitHub Copilot device-flow OAuth login and credential storage.

Credentials live in ``{CACHE_DIR}/copilot_oauth.json``.

Called by ``app.cli.commands.auth`` central dispatcher::

    evoflux auth copilot

For UI-driven login, ``app.api.routes.auth`` passes an ``event_sink``
that turns user-facing print calls into structured SSE events so the
desktop/web UI can render a "Connect with GitHub Copilot" modal with
live device-code display.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, SecretStr

# Callable invoked at every user-visible milestone. ``event`` is the
# short discriminator (e.g. "device_code", "polling", "success",
# "failed") and ``data`` is the JSON-serialisable payload.
EventSink = Callable[[str, dict[str, Any]], None]


def _say(event_sink: EventSink | None, event: str, message: str, **data: Any) -> None:
    """Either pretty-print to stdout (CLI) or push a typed event (UI).

    The dual behaviour keeps the CLI experience unchanged while letting
    the HTTP route consume structured events without parsing stdout.
    """
    if event_sink is None:
        print(message)
        return
    payload = {"message": message, **data}
    event_sink(event, payload)


# -- Persistence --------------------------------------------------------------


def _default_oauth_file() -> Path:
    """Resolve the OAuth credentials path from settings.

    Lazy so the file location tracks ``EVOFLUX_CACHE_DIR`` even when settings
    are swapped (tests, env overrides).
    """
    from app.core.config import settings

    return Path(settings.EVOFLUX_CACHE_DIR) / "copilot_oauth.json"


class CopilotOAuth(BaseModel):
    """Persisted GitHub OAuth credentials for the Copilot provider."""

    github_token: SecretStr  # long-lived (gho_*/ghu_*/ghp_*/github_pat_*)

    @classmethod
    def load(cls, path: Path | None = None) -> CopilotOAuth | None:
        """Load from disk. Returns None if file missing or invalid."""
        p = path or _default_oauth_file()
        if not p.exists():
            return None
        try:
            return cls.model_validate_json(p.read_text())
        except Exception:
            return None

    def save(self, path: Path | None = None) -> None:
        """Write to disk, exposing secret for persistence."""
        p = path or _default_oauth_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        # Me must reveal secret for JSON file — model_dump_json hides it
        data = {"github_token": self.github_token.get_secret_value()}
        import json

        p.write_text(json.dumps(data, indent=2) + "\n")


# -- Device-flow constants ----------------------------------------------------

_CLIENT_ID = "Ov23li8tweQw6odWQebz"
# EvoFlux OAuth App client ID, pending Copilot model-catalog access.
# _CLIENT_ID = "Ov23li7j8EJwKLcVR4ur"
_SCOPE = "read:user"
_DEVICE_CODE_URL = "https://github.com/login/device/code"
_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
_COPILOT_MODELS_URL = "https://api.githubcopilot.com/models"

_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "EvoFlux/1.0.0",
}


# -- Device-flow steps --------------------------------------------------------


def _request_device_code() -> dict:
    r = httpx.post(
        _DEVICE_CODE_URL,
        headers=_HEADERS,
        json={"client_id": _CLIENT_ID, "scope": _SCOPE},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()


def _poll_for_token(
    device_code: str,
    interval: int,
    expires_in: int,
    *,
    event_sink: EventSink | None = None,
) -> str:
    """Poll GitHub for the access token; emit ``polling`` events while waiting.

    Raises ``RuntimeError`` on terminal failures when ``event_sink`` is set
    (so the HTTP route can return a proper 4xx instead of the CLI's
    ``sys.exit``). The CLI path keeps the ``sys.exit`` behaviour because
    interactive users expect the process to terminate on these errors.
    """
    deadline = time.time() + expires_in
    # ``started`` is only used by the heartbeat emission, which is gated
    # on ``event_sink is not None``. Computing it conditionally keeps the
    # CLI path's ``time.time()`` call count stable so existing tests that
    # mock the clock keep working without modification.
    started = time.time() if event_sink is not None else 0.0
    while time.time() < deadline:
        time.sleep(interval)
        # Per-iteration heartbeat so the UI's timer doesn't appear frozen.
        if event_sink is not None:
            _say(
                event_sink,
                "polling",
                f"Waiting for authorization… {int(time.time() - started)}s",
                elapsed_s=int(time.time() - started),
            )
        r = httpx.post(
            _ACCESS_TOKEN_URL,
            headers=_HEADERS,
            json={
                "client_id": _CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            timeout=30.0,
        )
        r.raise_for_status()
        data = r.json()

        if "access_token" in data:
            return data["access_token"]

        error = data.get("error", "")
        if error == "authorization_pending":
            continue
        elif error == "slow_down":
            interval += 5
            continue
        elif error == "expired_token":
            _say(
                event_sink,
                "failed",
                "Device code expired. Run again.",
                reason="expired",
            )
            if event_sink is not None:
                raise RuntimeError("device_code_expired")
            sys.exit(1)
        elif error == "access_denied":
            _say(event_sink, "failed", "User denied access.", reason="denied")
            if event_sink is not None:
                raise RuntimeError("access_denied")
            sys.exit(1)
        else:
            _say(
                event_sink,
                "failed",
                f"Unexpected error: {error}",
                reason="unexpected",
                detail=error,
            )
            if event_sink is not None:
                raise RuntimeError(f"unexpected:{error}")
            sys.exit(1)

    _say(event_sink, "failed", "Timed out waiting for authorization.", reason="timeout")
    if event_sink is not None:
        raise RuntimeError("timeout")
    sys.exit(1)


def _verify_copilot_access(token: str) -> bool:
    """Verify token by hitting GET /models."""
    try:
        r = httpx.get(
            _COPILOT_MODELS_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": _HEADERS["User-Agent"],
                "Accept": "application/json",
            },
            timeout=10.0,
        )
        if r.status_code == 200:
            data = r.json()
            models = data.get("data", [])
            enabled = [m for m in models if m.get("model_picker_enabled")]
            print(f"  Copilot OK — {len(enabled)} models available\n")
            for m in enabled:
                endpoints = m.get("supported_endpoints", [])
                ep_str = ", ".join(endpoints) if endpoints else "?"
                print(f"    {m['id']:30s}  [{ep_str}]")
            return True
        else:
            print(f"  Copilot verification failed: {r.status_code}")
            print(f"  Response: {r.text[:200]}")
            return False
    except Exception as e:
        print(f"  Copilot verification error: {e}")
        return False


# -- Public login function ----------------------------------------------------


def login(
    oauth_path: Path | None = None, *, event_sink: EventSink | None = None
) -> None:
    """Run the full GitHub Copilot device-flow login.

    When ``event_sink`` is ``None`` (the CLI default), prints user-visible
    messages to stdout. When supplied, emits structured events via the
    callback so the HTTP/SSE route can render a live login modal.
    """
    oauth_path = oauth_path or _default_oauth_file()

    _say(event_sink, "started", "=== GitHub Copilot Device Login ===\n")

    # Me check if already logged in
    existing = CopilotOAuth.load(oauth_path)
    if existing:
        _say(event_sink, "checking_existing", f"Existing token found in {oauth_path}")
        if _verify_copilot_access(existing.github_token.get_secret_value()):
            _say(
                event_sink,
                "success",
                "Existing token still valid. No action needed.",
                already_authenticated=True,
            )
            return
        _say(
            event_sink,
            "reauthenticating",
            "Existing token invalid. Re-authenticating...",
        )

    # Step 1: get device code
    _say(event_sink, "requesting_device_code", "Requesting device code...")
    data = _request_device_code()
    device_code = data["device_code"]
    user_code = data["user_code"]
    verification_uri = data["verification_uri"]
    interval = data.get("interval", 5)
    expires_in = data.get("expires_in", 900)

    _say(
        event_sink,
        "device_code",
        f"Open: {verification_uri}  Code: {user_code}",
        verification_uri=verification_uri,
        user_code=user_code,
        expires_in=expires_in,
    )

    # Step 2: poll for token
    token = _poll_for_token(device_code, interval, expires_in, event_sink=event_sink)
    _say(
        event_sink,
        "token_acquired",
        f"GitHub token acquired: {token[:8]}...{token[-4:]}",
    )

    # Step 3: verify Copilot access
    _say(event_sink, "verifying", "Verifying Copilot access...")
    ok = _verify_copilot_access(token)
    if not ok:
        _say(
            event_sink,
            "warning",
            "Token obtained but Copilot access failed. "
            "Make sure you have an active GitHub Copilot subscription. "
            "Saving token anyway — you can retry later.",
            copilot_access_ok=False,
        )

    # Step 4: save
    oauth = CopilotOAuth(github_token=SecretStr(token))
    oauth.save(oauth_path)
    _say(
        event_sink,
        "success",
        f"Saved to {oauth_path}. Use model: copilot:gpt-5.4-mini",
        oauth_path=str(oauth_path),
        suggested_model="copilot:gpt-5.4-mini",
    )
