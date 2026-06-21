---
title: Logo Specifications
description: Geometric layered-hexagon mark with blue-purple gradient, sizing rules, asset delivery
status: stable
updated: 2026-06-21
---

# Logo Specifications

## Primary logo

- **Format**: Geometric layered-hexagon mark (3 stacked hexagonal layers with blue-purple gradient)
- **Source**: `logo.svg` (root)
- **Canonical assets**: `documents/assets/brand/`
- **App assets**: `web/src/assets/brand/`
- **Wordmark casing**: `EvoFlux`
- **Wordmark font**: Inter, 800 weight (`--font-sans`)

The logo is a modern geometric mark: three stacked hexagonal layers with a blue (`#00F0FF` → `#0078FF`) to purple (`#A855F7` → `#3B0764`) gradient, surrounded by radiating tick marks. It renders cleanly at all sizes on both light and dark surfaces.

---

## Logo variants

| Variant | File | Use |
|---------|------|-----|
| **App icon** | `evoflux-app-icon.png` | Sidebar logo, app chrome, favicon, tight UI logo spots |
| **Source SVG** | `logo.svg` | Canonical vector source for all exports |
| **Tauri icons** | `desktop/src-tauri/icons/` | Desktop app launcher icons (32–512px) |

---

## Palette

| Name | Hex | Usage |
|------|-----|-------|
| Cyan start | `#00F0FF` | Gradient start (top layer) |
| Blue end | `#0078FF` | Gradient end (top layer) |
| Indigo | `#6366F1` | Middle layer |
| Purple start | `#A855F7` | Bottom layer gradient start |
| Deep purple | `#3B0764` | Bottom layer gradient end |
| Ring blue | `#1E3A8A` | Outer ring stroke |

---

## Minimum Size

- **App icon**: 16px minimum, 32px+ preferred
- **In UI chrome**: 24px minimum

---

## Asset Delivery

| Format | Use Case | Specs |
|--------|----------|-------|
| **SVG** | Source, web, docs | `logo.svg` — canonical vector |
| **PNG** | Web, docs, app UI | Generated from SVG via sharp at target size |
| **ICO / ICNS** | Favicon, app launchers | Generated from SVG, multi-size |

Generated PNGs live in:
- `documents/assets/brand/` — documentation exports
- `web/src/assets/brand/` — app-imported assets
- `web/public/brand-assets/` — browser URL assets (favicon)
- `desktop/src-tauri/icons/` — Tauri launcher icons
