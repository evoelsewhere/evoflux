from __future__ import annotations

from app.plugin_platform.models import PluginInstallation, PluginInstallationOrigin


def test_legacy_installation_origin_stays_unknown_instead_of_inferred() -> None:
    legacy = PluginInstallation.model_validate(
        {
            "id": "a" * 32,
            "name": "old-plugin",
            "root": "/plugins/old-plugin",
            "source_type": "installed",
            "source_ref": "/plugins/old-plugin",
            "content_sha256": "b" * 64,
            "installed_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )
    assert legacy.origin is None


def test_origin_kind_contract_is_explicit() -> None:
    origin = PluginInstallationOrigin(
        kind="marketplace",
        marketplace_id="0123456789abcdef",
        marketplace_name="Test marketplace",
        source_ref="marketplace:0123456789abcdef/example@main",
    )
    assert origin.kind == "marketplace"
    assert origin.marketplace_id == "0123456789abcdef"
    assert origin.marketplace_name == "Test marketplace"
