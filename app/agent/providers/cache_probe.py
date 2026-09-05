"""Diagnostic: where does the prompt prefix stop matching the previous call?

Prefix caching (OpenAI, MiMo, Codex, and every other automatic-prefix
provider) reuses exactly the leading byte-run a request shares with an
earlier one. A single edited character anywhere in the system prompt, the
tool list, or an old message throws away everything after it — the usage
block then reports a cache-read count well below the replayed history, and
nothing in the response says which segment moved.

This probe answers that question. Enable it with ``EVOFLUX_CACHE_PROBE=1``
and every outbound request is split into ordered segments (tools, system,
one per message), compared against the previous request on the same
conversation, and the first divergent segment is logged with the character
offset inside it and the share of the prompt it invalidates.

It is off unless the environment variable is set, allocates nothing when
off, and never changes the request.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from loguru import logger

_ENV_FLAG = "EVOFLUX_CACHE_PROBE"
_ENV_PATH = "EVOFLUX_CACHE_PROBE_PATH"

_lock = threading.Lock()
#: Recent requests per conversation key. A provider's cache matches a new
#: request against *any* prefix it still holds, not only the immediately
#: preceding call, so the probe keeps a short history and reports the best
#: match — otherwise interleaved callers (title generation, sub-agents) on
#: the same model look like total invalidations that the provider never sees.
_history: dict[str, list[list[tuple[str, str]]]] = {}
_counter: dict[str, int] = {}
_HISTORY_DEPTH = 24


def enabled() -> bool:
    return os.environ.get(_ENV_FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _segments(body: dict[str, Any]) -> list[tuple[str, str]]:
    """Split a request body into ordered, comparable prompt segments."""
    out: list[tuple[str, str]] = []
    if body.get("tools"):
        out.append(("tools", _dumps(body["tools"])))
    for field in ("instructions", "system"):
        if body.get(field):
            out.append((field, _dumps(body[field])))
    items = body.get("messages") or body.get("input") or []
    if isinstance(items, list):
        for index, item in enumerate(items):
            role = (
                item.get("role") or item.get("type") or "?"
                if isinstance(item, dict)
                else "?"
            )
            out.append((f"{index:03d}:{role}", _dumps(item)))
    return out


def _stable_chars(
    previous: list[tuple[str, str]], current: list[tuple[str, str]]
) -> int:
    total = 0
    for index, segment in enumerate(current):
        if index >= len(previous) or previous[index] != segment:
            return total
        total += len(segment[1])
    return total


def _best_match(
    history: list[list[tuple[str, str]]], current: list[tuple[str, str]]
) -> list[tuple[str, str]] | None:
    """The cached request this one shares the longest prefix with."""
    best: list[tuple[str, str]] | None = None
    best_chars = -1
    for candidate in history:
        chars = _stable_chars(candidate, current)
        if chars > best_chars:
            best, best_chars = candidate, chars
    return best


def _common_prefix_chars(a: str, b: str) -> int:
    limit = min(len(a), len(b))
    for i in range(limit):
        if a[i] != b[i]:
            return i
    return limit


def record(body: dict[str, Any], *, provider: str | None, model: str) -> None:
    """Log how much of this request's prefix still matches the previous one."""
    if not enabled():
        return
    try:
        _record(body, provider=provider, model=model)
    except Exception as exc:  # diagnostics must never break a run
        logger.debug("cache_probe_failed error={}", exc)


def _record(body: dict[str, Any], *, provider: str | None, model: str) -> None:
    key = f"{provider or '?'}:{model}:{body.get('prompt_cache_key') or '-'}"
    segments = _segments(body)
    total = sum(len(text) for _, text in segments)

    with _lock:
        history = _history.setdefault(key, [])
        previous = _best_match(history, segments)
        history.append(segments)
        del history[:-_HISTORY_DEPTH]
        _counter[key] = _counter.get(key, 0) + 1
        call = _counter[key]

    if previous is None:
        logger.info(
            "cache_probe call={} key={} segments={} chars={} (first call, no baseline)",
            call,
            key,
            len(segments),
            total,
        )
        _append_jsonl(
            {
                "call": call,
                "key": key,
                "segments": len(segments),
                "chars": total,
                "stable_chars": 0,
                "first_divergent": None,
            }
        )
        return

    stable = 0
    divergent_index: int | None = None
    for index, (name, text) in enumerate(segments):
        if index < len(previous) and previous[index] == (name, text):
            stable += len(text)
            continue
        divergent_index = index
        break

    if divergent_index is None:
        detail: dict[str, Any] = {"reason": "identical prefix (request is a superset)"}
    else:
        name, text = segments[divergent_index]
        old_name, old_text = (
            previous[divergent_index]
            if divergent_index < len(previous)
            else ("<absent>", "")
        )
        offset = _common_prefix_chars(old_text, text)
        detail = {
            "segment": name,
            "previous_segment": old_name,
            "char_offset_in_segment": offset,
            "was": old_text[offset : offset + 220],
            "now": text[offset : offset + 220],
            "is_new_tail": divergent_index >= len(previous),
        }

    share = (stable / total * 100.0) if total else 0.0
    logger.info(
        "cache_probe call={} key={} stable_chars={}/{} ({:.1f}%) first_divergent={} detail={}",
        call,
        key,
        stable,
        total,
        share,
        divergent_index,
        _dumps(detail),
    )
    _append_jsonl(
        {
            "call": call,
            "key": key,
            "segments": len(segments),
            "chars": total,
            "stable_chars": stable,
            "stable_percent": round(share, 2),
            "first_divergent": divergent_index,
            "sizes": [[name, len(text)] for name, text in segments],
            "detail": detail,
        }
    )


def record_usage(*, provider: str | None, model: str, usage: Any) -> None:
    """Log what the provider actually cached, next to what we sent it.

    The probe's own numbers say how much of the prefix we *kept identical*;
    this says how much the provider chose to reuse. A wide gap between the
    two means the miss is upstream (routing, eviction, TTL), not in how the
    request was assembled.
    """
    if not enabled():
        return
    try:
        prompt = getattr(usage, "prompt_tokens", None) or 0
        cached = getattr(usage, "cached_tokens", None) or 0
        share = (cached / prompt * 100.0) if prompt else 0.0
        logger.info(
            "cache_probe_usage key={}:{} prompt_tokens={} cached_tokens={} ({:.1f}%)",
            provider,
            model,
            prompt,
            cached,
            share,
        )
        _append_jsonl(
            {
                "kind": "usage",
                "key": f"{provider}:{model}",
                "prompt_tokens": prompt,
                "cached_tokens": cached,
                "cached_percent": round(share, 2),
            }
        )
    except Exception as exc:
        logger.debug("cache_probe_usage_failed error={}", exc)


def _append_jsonl(row: dict[str, Any]) -> None:
    target = os.environ.get(_ENV_PATH)
    if not target:
        return
    path = Path(target)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(_dumps(row) + "\n")
    except OSError as exc:
        logger.debug("cache_probe_write_failed path={} error={}", path, exc)


__all__ = ["enabled", "record", "record_usage"]
