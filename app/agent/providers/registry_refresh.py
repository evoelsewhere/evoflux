"""Background refresh for the models.dev-backed model registry.

``load_model_registry`` memoizes its merge for the life of the process and the
disk cache's TTL is only consulted on the first read, so nothing about the
static registry changes under a running server: a month of uptime serves the
catalog as it looked on boot, and a model released yesterday stays invisible
until a restart. This task closes that gap — it re-fetches on an interval and
invalidates the derived caches when the catalog actually moved.

Its first pass matters even when the catalog is unchanged, and even when
refreshing is disabled: it warms the merged registry on a worker thread. Left
to the first reader, that work runs wherever the reader happens to be — which
is normally an API handler on the event loop, where the fetch inside
``_load_models_dev_data`` blocks every other request for its whole duration.

Interval: ``EVOFLUX_MODEL_REGISTRY_REFRESH_INTERVAL_HOURS`` (24 h).
Toggle:   ``EVOFLUX_MODEL_REGISTRY_REFRESH=false`` fetches nothing; the task
          still warms the registry once, then exits.
"""

from __future__ import annotations

import asyncio

from loguru import logger

from app.agent.providers.model_registry import (
    load_model_registry,
    refresh_models_dev_cache,
)
from app.core.config import settings


_task: asyncio.Task[None] | None = None


def _interval_seconds() -> float:
    hours = settings.EVOFLUX_MODEL_REGISTRY_REFRESH_INTERVAL_HOURS
    return float(max(1, hours) * 3600)


def refresh_model_registry_once() -> bool:
    """Refresh the models.dev cache and warm the merged registry.

    Both halves block — a synchronous HTTP request, then a merge across a few
    thousand catalog rows — so this belongs on a worker thread.
    """
    changed = refresh_models_dev_cache()
    registry = load_model_registry()
    logger.debug("model_registry_refresh changed={} models={}", changed, len(registry))
    return changed


async def _refresh_loop() -> None:
    interval = _interval_seconds()
    while True:
        try:
            await asyncio.to_thread(refresh_model_registry_once)
        except Exception as exc:  # noqa: BLE001  never kill the scheduler
            logger.warning("model_registry_refresh_failed error={}", exc)
        if not settings.EVOFLUX_MODEL_REGISTRY_REFRESH:
            # Nothing left to poll: the static sources cannot change under a
            # hermetic deployment, and the registry is already warm.
            return
        await asyncio.sleep(interval)


def start_model_registry_refresh() -> None:
    """Launch the background refresh task. Idempotent."""
    global _task
    if _task is not None and not _task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No event loop — called from a sync context; skip silently.
        return
    _task = loop.create_task(_refresh_loop(), name="model-registry-refresh")
    if settings.EVOFLUX_MODEL_REGISTRY_REFRESH:
        logger.info(
            "model_registry_refresh_started interval_h={}",
            int(_interval_seconds() // 3600),
        )
    else:
        logger.info("model_registry_refresh_disabled warm_only=true")


async def stop_model_registry_refresh() -> None:
    """Cancel the background task, if any."""
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except (asyncio.CancelledError, Exception):
        pass
    _task = None
