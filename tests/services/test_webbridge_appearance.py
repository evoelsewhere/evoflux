from __future__ import annotations

from app.services.webbridge_appearance import (
    WebBridgeAppearanceSnapshot,
    WebBridgeAppearanceStore,
)


def test_default_snapshot() -> None:
    store = WebBridgeAppearanceStore()

    assert store.get() == WebBridgeAppearanceSnapshot(
        schema_version=1,
        theme_preference="system",
        resolved_theme="light",
        accent="default",
        font_family="system",
        font_scale=1.0,
        motion_intensity="standard",
        synced=False,
        revision=0,
    )


def test_update_increments_revision_and_dedupes_identical_snapshot() -> None:
    store = WebBridgeAppearanceStore()

    first = store.update(
        theme_preference="system",
        resolved_theme="light",
        accent="default",
        font_family="system",
        font_scale=1.0,
        motion_intensity="standard",
    )
    duplicate = store.update(
        theme_preference="system",
        resolved_theme="light",
        accent="default",
        font_family="system",
        font_scale=1.0,
        motion_intensity="standard",
    )
    changed = store.update(
        theme_preference="system",
        resolved_theme="dark",
        accent="default",
        font_family="system",
        font_scale=1.0,
        motion_intensity="standard",
    )

    assert first.synced is True
    assert first.revision == 1
    assert duplicate is first
    assert duplicate.revision == 1
    assert changed.revision == 2
    assert store.get() is changed


def test_update_preserves_all_appearance_fields() -> None:
    store = WebBridgeAppearanceStore()

    updated = store.update(
        theme_preference="dark",
        resolved_theme="dark",
        accent="purple",
        font_family="anthropic-sans",
        font_scale=1.2,
        motion_intensity="cinematic",
    )

    assert updated == WebBridgeAppearanceSnapshot(
        schema_version=1,
        theme_preference="dark",
        resolved_theme="dark",
        accent="purple",
        font_family="anthropic-sans",
        font_scale=1.2,
        motion_intensity="cinematic",
        synced=True,
        revision=1,
    )
    assert store.get() is updated
