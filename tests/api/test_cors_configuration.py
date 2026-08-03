"""CORS wiring in the app factory.

The default origin allowlist must stay closed (no ``*``) so a hostile page in
the user's browser cannot drive the local API with the user's credentials, and
``allow_credentials`` must be disabled if an operator ever widens it to ``*``
— that combination is rejected by browsers and silently breaks every request.
"""

from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware

from app.api.app import create_app
from app.core.config import settings


def _cors_options(app) -> dict:
    for middleware in app.user_middleware:
        if middleware.cls is CORSMiddleware:
            return middleware.kwargs
    raise AssertionError("CORSMiddleware is not installed")


class TestCorsDefaults:
    def test_default_origins_do_not_include_wildcard(self):
        assert "*" not in settings.CORS_ORIGINS

    def test_default_origins_are_loopback_or_tauri_only(self):
        for origin in settings.CORS_ORIGINS:
            assert origin.startswith(
                ("http://localhost", "http://127.0.0.1", "tauri://", "https://tauri.")
            ), origin

    def test_credentials_enabled_for_closed_allowlist(self):
        options = _cors_options(create_app())
        assert options["allow_credentials"] is True
        assert "*" not in options["allow_origins"]


class TestCorsWildcardFallback:
    def test_wildcard_origin_disables_credentials(self, monkeypatch):
        monkeypatch.setattr(settings, "CORS_ORIGINS", ["*"])
        options = _cors_options(create_app())
        assert options["allow_credentials"] is False

    def test_wildcard_mixed_with_explicit_origin_disables_credentials(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            settings, "CORS_ORIGINS", ["http://localhost:5173", "*"]
        )
        options = _cors_options(create_app())
        assert options["allow_credentials"] is False
