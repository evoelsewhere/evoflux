---
name: evoflux-product-ui
description: >-
  EvoFlux product UI map for Forge, Coding, AIM chat, and Settings. Shared
  shell primitives, Settings design language, and anti-patterns. Use when
  editing web UI in evoflux, polishing Forge/Coding/Settings, or aligning
  panels with AppShell/SidePanel/SettingsLayout.
---

# EvoFlux Product UI

## Shell

- Frame: `web/src/components/shell/AppShell.tsx` — `sidebar`, `header`, `trailing`, `fullHeightTrailing`, `overlay`
- Side panels: `web/src/components/shell/SidePanel.tsx` (`useMotionPreset`)
- Mode root: `web/src/components/TeamChatView/index.tsx`
- Forge sidebar: `Sidebar.tsx` · Coding: `CodingWorkspacePanel` / `CodingSidebar.tsx`
- Coding workspace + file viewer mount in **`fullHeightTrailing`** (Forge-style corner), not body `trailing`

## Settings language

Primitives in `web/src/components/settings/SettingsLayout.tsx`:

- `SettingsPage` / `SettingsPageHeader` / `SettingsGroup` / `SettingsRow` / `SettingsCallout`
- Lists: `SettingsListView.tsx`
- Nav: `SettingsSidebar.tsx` (Models / Team / Machine / Application)
- Controls: `ui/discrete-slider.tsx`, `ui/segmented-control.tsx`

Shape scale: containers `rounded-lg`, controls `rounded-md`, chips `rounded-full`. Prefer hairline `divide-y` groups over stacked `Card`s.

## Composer

- `InputBar.tsx` + `SessionPillsRow.tsx` — model picker, thinking (`DiscreteSlider`), speed
- Do not reintroduce per-tick focus rings on thinking marks

## Motion

Always follow skill `design-motion-product`. Appearance intensity must affect real transitions.

## Anti-patterns

- Negative-margin hacks to fake full-height panels
- `EditorSubHeader` (removed) — use `SettingsPage` + `EditorHeaderActions`
- Hardcoded `transition={{ duration: 0.15 }}` on chrome
- Purple glow / decorative particle spam without `motion-ambient`
- Dead no-op controls left clickable (hide or disable)
