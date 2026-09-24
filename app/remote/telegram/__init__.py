"""Telegram Bot API transport and adapter lifecycle.

Everything that knows the Telegram wire format — request/response models,
the HTTP client, and the polling adapter — lives in this package. Generic
remote-access code (``app/remote/contracts.py``, a later
``RemoteService``) never imports from here; only this package imports the
provider-neutral types in ``app/remote/contracts.py``.
"""

from __future__ import annotations
