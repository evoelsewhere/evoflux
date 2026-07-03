"""SSL verification patch for corporate proxy environments.

When ``SSL_VERIFY=false``, disables certificate verification for all
httpx clients. This is needed on corporate networks where an
SSL-inspecting proxy presents certificates that Python 3.14+ rejects.
"""

from __future__ import annotations

import ssl

from app.core.config import settings


def apply_ssl_patch() -> None:
    """Disable SSL verification globally when ``SSL_VERIFY`` is ``False``."""
    if settings.SSL_VERIFY:
        return

    import httpcore

    _orig = httpcore.HTTPConnection._connect

    def _patched_connect(self, *args, **kwargs):
        if hasattr(self, "_ssl_context") and self._ssl_context is not None:
            self._ssl_context.check_hostname = False
            self._ssl_context.verify_mode = ssl.CERT_NONE
        return _orig(self, *args, **kwargs)

    httpcore.HTTPConnection._connect = _patched_connect  # type: ignore[assignment]

    _orig_async = httpcore.AsyncHTTPConnection._connect

    async def _patched_async_connect(self, *args, **kwargs):
        if hasattr(self, "_ssl_context") and self._ssl_context is not None:
            self._ssl_context.check_hostname = False
            self._ssl_context.verify_mode = ssl.CERT_NONE
        return await _orig_async(self, *args, **kwargs)

    httpcore.AsyncHTTPConnection._connect = _patched_async_connect  # type: ignore[assignment]
