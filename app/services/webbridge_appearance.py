"""Process-local appearance handoff from EvoFlux Desktop to WebBridge.

Appearance remains a device-local UI preference in the desktop frontend.  The
browser extension cannot read the WebView's localStorage, so the frontend
publishes its resolved snapshot here and a paired Side Panel reads that narrow
projection.  No account data or browser data is stored in this service.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from threading import Lock
from typing import Literal

ThemePreference = Literal["system", "light", "dark"]
ResolvedTheme = Literal["light", "dark"]
AccentColor = Literal["default", "blue", "green", "orange", "pink", "purple", "red"]
FontFamily = Literal["inter", "system", "mono", "geist", "anthropic-sans"]
MotionIntensity = Literal["reduced", "subtle", "standard", "expressive", "cinematic"]


@dataclass(frozen=True, slots=True)
class WebBridgeAppearanceSnapshot:
    schema_version: Literal[1] = 1
    theme_preference: ThemePreference = "system"
    resolved_theme: ResolvedTheme = "light"
    accent: AccentColor = "default"
    font_family: FontFamily = "system"
    font_scale: float = 1.0
    motion_intensity: MotionIntensity = "standard"
    synced: bool = False
    revision: int = 0


class WebBridgeAppearanceStore:
    """Small thread-safe latest-value store for one desktop process."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._snapshot = WebBridgeAppearanceSnapshot()

    def get(self) -> WebBridgeAppearanceSnapshot:
        with self._lock:
            return self._snapshot

    def update(
        self,
        *,
        theme_preference: ThemePreference,
        resolved_theme: ResolvedTheme,
        accent: AccentColor,
        font_family: FontFamily,
        font_scale: float,
        motion_intensity: MotionIntensity,
    ) -> WebBridgeAppearanceSnapshot:
        with self._lock:
            current = self._snapshot
            candidate = WebBridgeAppearanceSnapshot(
                schema_version=1,
                theme_preference=theme_preference,
                resolved_theme=resolved_theme,
                accent=accent,
                font_family=font_family,
                font_scale=font_scale,
                motion_intensity=motion_intensity,
                synced=True,
                revision=current.revision,
            )
            if candidate == current:
                return current
            self._snapshot = replace(candidate, revision=current.revision + 1)
            return self._snapshot


webbridge_appearance_store = WebBridgeAppearanceStore()
