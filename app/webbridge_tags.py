"""Dependency-neutral WebBridge session tag constants.

Only provenance lives in tags: a session the extension created carries the
browser-origin tag. Whether an agent drives the user's browser is live
state (``webbridge_manager.agent_browsing_ready``), never a session tag.
"""

WEBBRIDGE_BROWSER_ORIGIN_TAG = "webbridge_origin:browser"
