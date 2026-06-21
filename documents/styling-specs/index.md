---
title: EvoFlux Styling
description: Design-system reference for EvoFlux brand assets, tokens, components, interaction, and motion
status: stable
updated: 2026-05-09
---

# EvoFlux Styling

Design-system reference for EvoFlux. Brand assets, tokens, components, interaction, motion.

---

## At a glance

| | |
|---|---|
| **Aesthetic** | Warm paper notebook — cream surfaces, hand-drawn headlines, calm utility chrome |
| **Palette** | EvoFlux brand pigments on a warm `#FFFFFF` paper background; pastel agent chips for role identity |
| **Type** | Inter (UI/body) + JetBrains Mono (code) + Inter (handwritten headlines) |
| **Modes** | Light-first paper, dark-equal — both rendered with equal care |
| **Motion** | Motion is information; every animation conveys state, progress, or causality |
| **Token prefix** | `--color-*`, `--accent-*`, `--bg-*`, `--fg-*`, `--font-*`, `--radius-*` |

---

## Pages

| | |
|---|---|
| [Colors](./colors.md) | Paper palette, agent-chip palette, semantic tokens, marker palette for charts, light/dark theme variables |
| [Typography](./typography.md) | Inter, JetBrains Mono, Inter hand-drawn headlines, type scale, font-weight transitions |
| [Motion](./motion.md) | Motion tokens, spring presets, choreography patterns, reduced-motion fallbacks |
| [Interaction](./interaction.md) | Hover / focus / active model, keyboard shortcuts, state choreography |
| [Layout](./layout.md) | 4px grid, breakpoints, radius scale, depth, accessibility |
| [Logo](./logo.md) | Source-faithful EvoFlux mascot, lockups, sizing, asset delivery |
| [Imagery](./imagery.md) | EvoFlux mascot usage, icons (lucide), charts, screenshots, patterns |
| [Applications](./applications.md) | Component guidelines — agent chips, sidebar, input bar, tool call rows, modals, topbar, popovers, empty states |

---

## What changed in this revision

The styling system was previously specified for a cool zinc/Geist neutral aesthetic with reserved EvoFlux gold accents. The pencil source design has since converged on a **minimal monochrome notebook** language — cream surfaces (`#FFFFFF`), Inter handwritten screen headlines, Inter UI, and a four-color **agent chip palette** that gives each agent role a recognizable pastel identity (mint for `EvoFlux`, blue for `executor`, orange for `consultant`, pink for `explorer`).

Codebase migration from previous token names (`--color-jb-*`, zinc neutrals) to the paper tokens is tracked separately.
