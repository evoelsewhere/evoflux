"""Connection-aware core for outbound-only remote access (e.g. Telegram).

Nothing in this package is imported unless a connection is configured and
enabled. Adapter-specific modules (``app/remote/telegram/``, added in a later
task) own provider payload translation; everything here is provider-neutral.
"""

from __future__ import annotations
