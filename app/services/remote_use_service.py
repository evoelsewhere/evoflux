"""Embedded Tailscale and external Serve support for remote use.

Three responsibilities, all deliberately free of route and UI concerns:

1. **Provider control** — packaged desktop builds supervise the bundled
   ``evoflux-tailnet`` tsnet helper through a token-protected loopback API.
   Source/server runs fall back to the optional ``tailscale`` CLI.
2. **State and serving** — both providers expose one response contract and
   distinct user-facing states. External CLI calls use literal argv; embedded
   mode persists its own node identity and enabled preference.
3. **Single-device session lock** — one live row in ``remote_use_sessions``
   at a time. :func:`claim` refreshes the caller's own session or raises
   :class:`RemoteUseConflict` (HTTP 409 body) when another live session
   holds the lock; idle-expired sessions never block the next claim.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import col, select

import app.core.db as db_module
from app.core.config import settings
from app.models.remote_use import RemoteUseSession

#: The serve target is this machine's loopback: tailscaled terminates the
#: tailnet HTTPS connection and forwards to the sidecar locally.
SERVE_TARGET_HOST = "127.0.0.1"

#: A remote session is released once no heartbeat arrived for this long.
IDLE_WINDOW = timedelta(minutes=30)
IDLE_WINDOW_MINUTES = int(IDLE_WINDOW.total_seconds() // 60)

#: Overrides CLI discovery (custom installs and the stub used by tests).
TAILSCALE_BIN_ENV = "EVOFLUX_TAILSCALE_BIN"

#: Bundled Go helper containing an embedded tsnet node. Tauri sets this only
#: for packaged/bundled runs; source servers retain the external CLI provider.
EMBEDDED_TAILNET_BIN_ENV = "EVOFLUX_TSNET_BIN"

#: Explicit provider override for development and managed deployments.
REMOTE_USE_PROVIDER_ENV = "EVOFLUX_REMOTE_USE_PROVIDER"

_CLI_TIMEOUT_SECONDS = 15.0
_EMBEDDED_HANDSHAKE_PREFIX = "EVOFLUX_TAILNET_HANDSHAKE "
_EMBEDDED_START_TIMEOUT_SECONDS = 10.0
_EMBEDDED_REQUEST_TIMEOUT_SECONDS = 12.0


class RemoteUseConflict(Exception):
    """Another live remote session already holds the single-device lock."""

    def __init__(self, current: RemoteUseSession) -> None:
        self.current = current
        label = current.device_label or "unknown device"
        super().__init__(
            f"remote session lock is held by {current.user_login} ({label})"
        )

    def body(self) -> dict[str, Any]:
        """The HTTP 409 body returned to the blocked device."""
        return {
            "detail": str(self),
            "current": session_lock_payload(self.current),
            "live_window_minutes": IDLE_WINDOW_MINUTES,
        }


def session_lock_payload(session: RemoteUseSession | None) -> dict[str, Any] | None:
    """Serialize a lock holder into the shared ``lock`` response shape."""
    if session is None:
        return None
    return {
        "user_login": session.user_login,
        "device_label": session.device_label,
        "claimed_at": session.claimed_at.isoformat(),
        "last_seen_at": session.last_seen_at.isoformat(),
    }


# --------------------------------------------------------------------------
# tailscale CLI plumbing (subprocess only — never call inside a transaction)
# --------------------------------------------------------------------------


def tailscale_binary() -> str | None:
    """Locate the tailscale CLI, or ``None`` when it is not installed."""
    override = os.environ.get(TAILSCALE_BIN_ENV)
    if override:
        return override
    return shutil.which("tailscale")


def embedded_tailnet_binary() -> str | None:
    """Configured embedded helper path, unless external mode is forced."""
    if os.environ.get(REMOTE_USE_PROVIDER_ENV, "").strip().lower() == "external":
        return None
    value = os.environ.get(EMBEDDED_TAILNET_BIN_ENV, "").strip()
    return value or None


def _use_embedded_provider() -> bool:
    forced = os.environ.get(REMOTE_USE_PROVIDER_ENV, "").strip().lower()
    if forced == "embedded":
        return True
    return embedded_tailnet_binary() is not None


def _embedded_error_status(detail: str) -> dict[str, Any]:
    return {
        "tailscale": {
            "provider": "embedded",
            "installed": embedded_tailnet_binary() is not None,
            "logged_in": False,
            "https_certs": None,
            "auth_url": None,
            "error": detail,
        },
        "serve": {"enabled": False, "url": None},
    }


def _normalize_embedded_status(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("embedded tailnet returned an invalid response")
    tailscale = payload.get("tailscale")
    serve = payload.get("serve")
    if not isinstance(tailscale, dict) or not isinstance(serve, dict):
        raise ValueError("embedded tailnet response is missing status sections")
    tailscale.setdefault("provider", "embedded")
    tailscale.setdefault("installed", True)
    tailscale.setdefault("logged_in", False)
    tailscale.setdefault("https_certs", None)
    tailscale.setdefault("auth_url", None)
    tailscale.setdefault("error", None)
    serve.setdefault("enabled", False)
    serve.setdefault("url", None)
    return {"tailscale": tailscale, "serve": serve}


class _EmbeddedTailnetManager:
    """Own one bundled ``evoflux-tailnet`` process and its loopback API."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._control_url: str | None = None
        self._control_token: str | None = None
        self._target_port: int | None = None

    async def ensure_started(self, port: int | None) -> None:
        if port is None or not (0 < port < 65536):
            raise RuntimeError("cannot start embedded tailnet: backend port unknown")
        async with self._lock:
            if (
                self._process is not None
                and self._process.returncode is None
                and self._control_url is not None
                and self._target_port == port
            ):
                return
            await self._stop_locked()
            binary = embedded_tailnet_binary()
            if binary is None:
                raise RuntimeError("embedded tailnet helper is not bundled")
            path = Path(binary).expanduser()
            if not path.is_file():
                raise RuntimeError(f"embedded tailnet helper not found at {path}")

            state_dir = Path(settings.EVOFLUX_STATE_DIR) / "tailnet"
            state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            control_token = secrets.token_urlsafe(32)
            from app.core.desktop_auth import embedded_remote_proxy_secret

            env = os.environ.copy()
            env["EVOFLUX_TAILNET_CONTROL_TOKEN"] = control_token
            env["EVOFLUX_TAILNET_PROXY_TOKEN"] = embedded_remote_proxy_secret()
            process = await asyncio.create_subprocess_exec(
                str(path),
                "--state-dir",
                str(state_dir),
                "--hostname",
                "evoflux",
                "--target",
                f"http://{SERVE_TARGET_HOST}:{port}",
                "--parent-pid",
                str(os.getpid()),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            assert process.stdout is not None
            try:
                raw = await asyncio.wait_for(
                    process.stdout.readline(), _EMBEDDED_START_TIMEOUT_SECONDS
                )
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith(_EMBEDDED_HANDSHAKE_PREFIX):
                    raise RuntimeError(
                        "embedded tailnet exited without a valid handshake"
                    )
                handshake = _parse_json_object(line[len(_EMBEDDED_HANDSHAKE_PREFIX) :])
                control_port = int((handshake or {}).get("port", 0))
                if not (0 < control_port < 65536):
                    raise RuntimeError("embedded tailnet handshake has no control port")
            except Exception:
                process.kill()
                await process.communicate()
                raise

            self._process = process
            self._control_url = f"http://127.0.0.1:{control_port}"
            self._control_token = control_token
            self._target_port = port
            self._stderr_task = asyncio.create_task(
                self._drain_stderr(process), name="embedded-tailnet-logs"
            )
            logger.info(
                "embedded_tailnet_started pid={} control_port={} target_port={}",
                process.pid,
                control_port,
                port,
            )

    async def _drain_stderr(self, process: asyncio.subprocess.Process) -> None:
        if process.stderr is None:
            return
        while True:
            line = await process.stderr.readline()
            if not line:
                return
            logger.info(
                "embedded_tailnet {}", line.decode("utf-8", errors="replace").rstrip()
            )

    async def request(self, method: str, path: str, port: int | None) -> dict[str, Any]:
        await self.ensure_started(port)
        control_url = self._control_url
        control_token = self._control_token
        if control_url is None or control_token is None:
            raise RuntimeError("embedded tailnet control API is unavailable")
        async with httpx.AsyncClient(
            timeout=_EMBEDDED_REQUEST_TIMEOUT_SECONDS
        ) as client:
            response = await client.request(
                method,
                f"{control_url}{path}",
                headers={"Authorization": f"Bearer {control_token}"},
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"embedded tailnet returned HTTP {response.status_code}"
            ) from exc
        if response.is_error and not (
            isinstance(payload, dict)
            and isinstance(payload.get("tailscale"), dict)
            and isinstance(payload.get("serve"), dict)
        ):
            detail = payload.get("detail") if isinstance(payload, dict) else None
            raise RuntimeError(
                str(detail or f"embedded tailnet HTTP {response.status_code}")
            )
        return _normalize_embedded_status(payload)

    async def _stop_locked(self) -> None:
        process = self._process
        control_url = self._control_url
        control_token = self._control_token
        self._process = None
        self._control_url = None
        self._control_token = None
        self._target_port = None
        if process is None:
            return
        if process.returncode is None and control_url and control_token:
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    await client.post(
                        f"{control_url}/v1/shutdown",
                        headers={"Authorization": f"Bearer {control_token}"},
                    )
                await asyncio.wait_for(process.wait(), 4.0)
            except (httpx.HTTPError, TimeoutError):
                process.terminate()
        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), 3.0)
            except TimeoutError:
                process.kill()
                await process.wait()
        task = self._stderr_task
        self._stderr_task = None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def shutdown(self) -> None:
        async with self._lock:
            await self._stop_locked()


_embedded_manager = _EmbeddedTailnetManager()


async def _run_tailscale(
    *args: str, timeout: float = _CLI_TIMEOUT_SECONDS
) -> tuple[int | None, str, str]:
    """Run ``tailscale <args>`` with a literal argv — never a shell string.

    Returns ``(returncode, stdout, stderr)``; ``returncode`` is ``None`` when
    the process could not be started or timed out, with the reason in
    ``stderr``. Never raises.
    """
    binary = tailscale_binary()
    if binary is None:
        return None, "", "tailscale CLI not found on PATH"
    try:
        process = await asyncio.create_subprocess_exec(
            binary,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        return None, "", f"failed to start tailscale: {exc}"
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        await process.communicate()
        return None, "", f"tailscale {' '.join(args)} timed out after {timeout:g}s"
    return (
        process.returncode,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _first_error_line(*texts: str) -> str | None:
    for text in texts:
        for line in text.splitlines():
            if line.strip():
                return line.strip()[:300]
    return None


# --------------------------------------------------------------------------
# state detection
# --------------------------------------------------------------------------


def _status_logged_in(status: dict[str, Any]) -> bool:
    return status.get("BackendState") == "Running"


def _status_https_certs(status: dict[str, Any]) -> bool | None:
    """Best-effort HTTPS-certs signal from ``tailscale status --json``.

    A non-empty ``CertDomains`` list means the tailnet hands out certs; a
    ``Health`` entry saying HTTPS/TLS is disabled, expired, or unavailable
    is a negative signal. Everything else stays ``None`` ("unknown"): the UI
    treats unknown as "not confirmed" and ``serve enable`` surfaces the
    authoritative error when it fails.
    """
    cert_domains = status.get("CertDomains")
    if isinstance(cert_domains, list) and cert_domains:
        return True
    health = status.get("Health")
    if isinstance(health, list):
        for entry in health:
            if not isinstance(entry, str):
                continue
            lowered = entry.lower()
            mentions_tls = "https" in lowered or "tls" in lowered or "cert" in lowered
            says_broken = any(
                marker in lowered
                for marker in (
                    "not enabled",
                    "disabled",
                    "unavailable",
                    "expired",
                    "failed",
                    "not yet",
                )
            )
            if mentions_tls and says_broken:
                return False
    return None


async def detect_tailscale_state() -> dict[str, Any]:
    """Probe ``tailscale status --json`` for the user-facing CLI state."""
    if tailscale_binary() is None:
        return {
            "installed": False,
            "logged_in": False,
            "https_certs": None,
            "error": "tailscale CLI not found on PATH",
        }
    returncode, stdout, stderr = await _run_tailscale("status", "--json")
    if returncode != 0:
        detail = (
            _first_error_line(stderr, stdout)
            or f"tailscale status exited with {returncode}"
        )
        return {
            "installed": True,
            "logged_in": False,
            "https_certs": None,
            "error": detail,
        }
    status = _parse_json_object(stdout)
    if status is None:
        return {
            "installed": True,
            "logged_in": False,
            "https_certs": None,
            "error": "tailscale status --json returned unparseable output",
        }
    return {
        "installed": True,
        "logged_in": _status_logged_in(status),
        "https_certs": _status_https_certs(status),
        "error": None,
    }


def _web_entry_active(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return bool(entry)
    handlers = entry.get("Handlers", entry)
    return isinstance(handlers, dict) and bool(handlers)


def _normalize_serve_url(url: str) -> str:
    # Tailscale serve status returns bare hostnames like
    # "host.tailnet.ts.net:443" - normalise to a scannable HTTPS URL.
    if not url.startswith(("https://", "http://")):
        url = f"https://{url}"
    if url.startswith("https://") and url.endswith(":443"):
        return url[: -len(":443")]
    if url.startswith("http://") and url.endswith(":80"):
        return url[: -len(":80")]
    return url


def _serve_state_from_config(config: dict[str, Any]) -> dict[str, Any]:
    web = config.get("Web")
    if isinstance(web, dict):
        active = [str(key) for key, value in web.items() if _web_entry_active(value)]
    else:
        active = []
    if not active:
        return {"enabled": False, "url": None}
    preferred = next((url for url in active if url.startswith("https://")), active[0])
    return {"enabled": True, "url": _normalize_serve_url(preferred)}


async def _serve_state() -> tuple[dict[str, Any], str | None]:
    """``(serve state, error)`` parsed from ``tailscale serve status --json``."""
    disabled = {"enabled": False, "url": None}
    if tailscale_binary() is None:
        return disabled, "tailscale CLI not found on PATH"
    returncode, stdout, stderr = await _run_tailscale("serve", "status", "--json")
    if returncode != 0:
        detail = (
            _first_error_line(stderr, stdout)
            or f"tailscale serve status exited with {returncode}"
        )
        return disabled, detail
    config = _parse_json_object(stdout)
    if config is None:
        return disabled, "tailscale serve status --json returned unparseable output"
    return _serve_state_from_config(config), None


async def _get_cli_status() -> dict[str, Any]:
    """Tailscale + serve state (the two non-lock sections of the response)."""
    tailscale = await detect_tailscale_state()
    serve, serve_error = await _serve_state()
    if tailscale["error"] is None and serve_error is not None:
        tailscale["error"] = serve_error
    if tailscale["https_certs"] is None and str(serve.get("url") or "").startswith(
        "https://"
    ):
        tailscale["https_certs"] = True
    return {"tailscale": tailscale, "serve": serve}


def _looks_like_https_error(detail: str) -> bool:
    lowered = detail.lower()
    return "https" in lowered or "cert" in lowered or "tls" in lowered


async def _enable_cli_serve(port: int | None) -> dict[str, Any]:
    """Run ``tailscale serve --bg http://127.0.0.1:<port>`` (outside the DB)."""
    status = await _get_cli_status()
    tailscale = status["tailscale"]
    if not tailscale["installed"] or tailscale["error"] is not None:
        return status
    if not tailscale["logged_in"]:
        tailscale["error"] = "tailscale is not logged in"
        return status
    if port is None or not (0 < port < 65536):
        tailscale["error"] = "cannot enable tailscale serve: backend port unknown"
        return status
    target = f"http://{SERVE_TARGET_HOST}:{port}"
    returncode, stdout, stderr = await _run_tailscale("serve", "--bg", target)
    if returncode != 0:
        detail = (
            _first_error_line(stderr, stdout)
            or f"tailscale serve --bg exited with {returncode}"
        )
        tailscale["error"] = detail
        if _looks_like_https_error(detail):
            tailscale["https_certs"] = False
        return status
    logger.info("remote_use_serve_enabled target={}", target)
    return await _get_cli_status()


async def _disable_cli_serve() -> dict[str, Any]:
    """Run ``tailscale serve reset`` (outside the DB)."""
    status = await _get_cli_status()
    tailscale = status["tailscale"]
    if not tailscale["installed"] or tailscale["error"] is not None:
        return status
    returncode, stdout, stderr = await _run_tailscale("serve", "reset")
    if returncode != 0:
        detail = (
            _first_error_line(stderr, stdout)
            or f"tailscale serve reset exited with {returncode}"
        )
        tailscale["error"] = detail
        return status
    logger.info("remote_use_serve_reset")
    return await _get_cli_status()


async def get_status(port: int | None = None) -> dict[str, Any]:
    """Return the active provider's tailnet and serving state."""
    if not _use_embedded_provider():
        return await _get_cli_status()
    try:
        return await _embedded_manager.request("GET", "/v1/status", port)
    except (OSError, RuntimeError, httpx.HTTPError) as exc:
        logger.warning("embedded_tailnet_status_failed error={}", exc)
        return _embedded_error_status(str(exc))


async def connect_tailnet(port: int | None) -> dict[str, Any]:
    """Start or refresh the embedded interactive login flow."""
    if not _use_embedded_provider():
        status = await _get_cli_status()
        if not status["tailscale"]["logged_in"]:
            status["tailscale"]["error"] = (
                "Open the Tailscale app or run `tailscale up` to sign in"
            )
        return status
    try:
        return await _embedded_manager.request("POST", "/v1/login", port)
    except (OSError, RuntimeError, httpx.HTTPError) as exc:
        logger.warning("embedded_tailnet_login_failed error={}", exc)
        return _embedded_error_status(str(exc))


async def enable_serve(port: int | None) -> dict[str, Any]:
    """Enable phone access through embedded tsnet or external Serve."""
    if not _use_embedded_provider():
        return await _enable_cli_serve(port)
    try:
        return await _embedded_manager.request("POST", "/v1/enable", port)
    except (OSError, RuntimeError, httpx.HTTPError) as exc:
        logger.warning("embedded_tailnet_enable_failed error={}", exc)
        return _embedded_error_status(str(exc))


async def disable_serve(port: int | None = None) -> dict[str, Any]:
    """Disable phone access through embedded tsnet or external Serve."""
    if not _use_embedded_provider():
        return await _disable_cli_serve()
    try:
        return await _embedded_manager.request("POST", "/v1/disable", port)
    except (OSError, RuntimeError, httpx.HTTPError) as exc:
        logger.warning("embedded_tailnet_disable_failed error={}", exc)
        return _embedded_error_status(str(exc))


async def bootstrap_embedded_tailnet(port: int | None) -> dict[str, Any]:
    """Start the bundled helper early so persisted phone access auto-restores."""
    if not _use_embedded_provider():
        return await _get_cli_status()
    return await get_status(port)


async def shutdown_embedded_tailnet() -> None:
    """Stop the helper during FastAPI shutdown; safe when it never started."""
    await _embedded_manager.shutdown()


# --------------------------------------------------------------------------
# single-device session lock
# --------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _device_label(value: str | None) -> str | None:
    label = (value or "").strip()
    if not label:
        return None
    return label[:128]


def _label_clause(label: str | None):
    if label is None:
        return col(RemoteUseSession.device_label).is_(None)
    return col(RemoteUseSession.device_label) == label


async def _find_live(db: AsyncSession, now: datetime) -> RemoteUseSession | None:
    result = await db.exec(
        select(RemoteUseSession)
        .where(
            col(RemoteUseSession.released_at).is_(None),
            col(RemoteUseSession.idle_expires_at) > now,
        )
        .order_by(col(RemoteUseSession.claimed_at).desc())
        .limit(1)
    )
    return result.first()


async def _sweep_expired(db: AsyncSession, now: datetime) -> int:
    """Release live rows whose idle window elapsed (the idle sweep)."""
    result = await db.exec(
        select(RemoteUseSession).where(
            col(RemoteUseSession.released_at).is_(None),
            col(RemoteUseSession.idle_expires_at) <= now,
        )
    )
    rows = result.all()
    for row in rows:
        row.released_at = now
        db.add(row)
    if rows:
        await db.commit()
        logger.info("remote_use_sessions_idle_released count={}", len(rows))
    return len(rows)


async def _touch(
    db: AsyncSession, row: RemoteUseSession, now: datetime
) -> RemoteUseSession:
    row.last_seen_at = now
    row.idle_expires_at = now + IDLE_WINDOW
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def claim(
    user_login: str, device_label: str | None, *, now: datetime | None = None
) -> RemoteUseSession:
    """Acquire the single-device lock for one remote session.

    Re-claiming with the same ``(user_login, device_label)`` refreshes the
    heartbeat; a live holder with a different identity raises
    :class:`RemoteUseConflict`. Idle-expired rows are swept first, so a
    lapsed session never blocks the next claim.
    """
    login = user_login.strip()
    if not login:
        raise ValueError("user_login is required")
    label = _device_label(device_label)
    now = now or _utcnow()
    async with db_module.async_session_factory() as db:
        await _sweep_expired(db, now)
        holder = await _find_live(db, now)
        if holder is not None:
            if holder.user_login == login and holder.device_label == label:
                return await _touch(db, holder, now)
            raise RemoteUseConflict(holder)
        row = RemoteUseSession(
            user_login=login,
            device_label=label,
            claimed_at=now,
            last_seen_at=now,
            idle_expires_at=now + IDLE_WINDOW,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        logger.info("remote_use_session_claimed login={} device={}", login, label)
        return row


async def heartbeat(
    user_login: str, device_label: str | None, *, now: datetime | None = None
) -> RemoteUseSession | None:
    """Refresh ``last_seen_at`` for the caller's own live session, if any."""
    login = user_login.strip()
    if not login:
        raise ValueError("user_login is required")
    label = _device_label(device_label)
    now = now or _utcnow()
    async with db_module.async_session_factory() as db:
        result = await db.exec(
            select(RemoteUseSession)
            .where(
                col(RemoteUseSession.user_login) == login,
                _label_clause(label),
                col(RemoteUseSession.released_at).is_(None),
                col(RemoteUseSession.idle_expires_at) > now,
            )
            .order_by(col(RemoteUseSession.claimed_at).desc())
            .limit(1)
        )
        row = result.first()
        if row is None:
            return None
        return await _touch(db, row, now)


async def release(
    user_login: str, device_label: str | None, *, now: datetime | None = None
) -> RemoteUseSession | None:
    """Release the caller's own live session, if any. Returns the row."""
    login = user_login.strip()
    if not login:
        raise ValueError("user_login is required")
    label = _device_label(device_label)
    now = now or _utcnow()
    async with db_module.async_session_factory() as db:
        result = await db.exec(
            select(RemoteUseSession)
            .where(
                col(RemoteUseSession.user_login) == login,
                _label_clause(label),
                col(RemoteUseSession.released_at).is_(None),
                col(RemoteUseSession.idle_expires_at) > now,
            )
            .order_by(col(RemoteUseSession.claimed_at).desc())
            .limit(1)
        )
        row = result.first()
        if row is None:
            return None
        row.released_at = now
        db.add(row)
        await db.commit()
        await db.refresh(row)
        logger.info("remote_use_session_released login={} device={}", login, label)
        return row


async def force_release(*, now: datetime | None = None) -> int:
    """Desktop force-release: retire every live session. Returns the count."""
    now = now or _utcnow()
    async with db_module.async_session_factory() as db:
        result = await db.exec(
            select(RemoteUseSession).where(col(RemoteUseSession.released_at).is_(None))
        )
        rows = result.all()
        for row in rows:
            row.released_at = now
            db.add(row)
        if rows:
            await db.commit()
            logger.info("remote_use_sessions_force_released count={}", len(rows))
        return len(rows)


async def sweep_idle(*, now: datetime | None = None) -> int:
    """Release sessions whose idle window elapsed. Returns the count."""
    now = now or _utcnow()
    async with db_module.async_session_factory() as db:
        return await _sweep_expired(db, now)


async def get_lock_holder(*, now: datetime | None = None) -> RemoteUseSession | None:
    """Current live lock holder after an opportunistic idle sweep."""
    now = now or _utcnow()
    async with db_module.async_session_factory() as db:
        await _sweep_expired(db, now)
        return await _find_live(db, now)
