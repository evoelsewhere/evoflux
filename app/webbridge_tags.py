"""Dependency-neutral WebBridge session tag constants and helpers."""

WEBBRIDGE_SESSION_TAG = "webbridge"
WEBBRIDGE_BROWSER_ORIGIN_TAG = "webbridge_origin:browser"
WEBBRIDGE_TARGET_TAG_PREFIX = "webbridge_target:"


def webbridge_target_tag(extension_id: str) -> str:
    """Return the server-managed tag that pins a chat to one browser."""
    return f"{WEBBRIDGE_TARGET_TAG_PREFIX}{extension_id}"


def webbridge_target_from_tags(tags: tuple[str, ...] | frozenset[str]) -> str | None:
    """Read the one browser target carried by a session's feature tags."""
    targets = [tag.removeprefix(WEBBRIDGE_TARGET_TAG_PREFIX) for tag in tags if tag.startswith(WEBBRIDGE_TARGET_TAG_PREFIX)]
    return targets[0] if len(targets) == 1 and targets[0] else None
