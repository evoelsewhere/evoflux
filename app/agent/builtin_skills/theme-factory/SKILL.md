---
name: theme-factory
description: Select, create, and apply a cohesive color-and-typography theme to an existing slide deck, document, report, workbook, or HTML artifact without changing its content hierarchy. Use when visual theming is the requested outcome; do not use to author the artifact's substantive content or redesign a product interface.
---

# Apply an artifact theme

Preserve the artifact's content, hierarchy, semantics, and editability. Change
only the visual system the user requested. Do not load the showcase or any
theme specification when this skill activates.

## Select the theme

- If the user names a bundled theme, read only its file in `themes/` and apply
  it without asking for reconfirmation.
- If the brief supplies a clear palette, tone, brand rule, or visual reference,
  map it to the closest bundled theme or create a compatible custom theme and
  continue without asking about internal preset names.
- If visual direction is genuinely absent and different choices would
  materially change the artifact, show `theme-showcase.pdf` and ask once for a
  choice. Do not show the showcase merely because it exists.

Bundled themes are Ocean Depths, Sunset Boulevard, Forest Canopy, Modern
Minimalist, Golden Hour, Arctic Frost, Desert Rose, Tech Innovation, Botanical
Garden, and Midnight Galaxy.

## Define the contract

Record background, surface, primary text, muted text, accent, success/warning
roles, heading/body/utility fonts, contrast requirements, and any brand-fixed
values. For a custom theme, give it a descriptive name and define the same
roles. Do not invent a logo, brand color, or font license.

## Apply

Use the artifact's native styling mechanism: masters/themes for slides, styles
for documents, cell styles for workbooks, or tokens/CSS variables for HTML.
Update repeated components consistently. Preserve charts, data encodings,
semantic status colors, template lineage, formulas, and accessible reading
order unless the user explicitly asks to change them.

## Verify

Render or preview the full artifact after applying the theme. Check contrast,
font availability/substitution, hierarchy, chart legibility, table density,
links, clipping, and consistency across representative and edge pages/slides/
sheets. Correct local overrides that accidentally retain the old theme.

## Stop conditions

Stop when the theme roles are applied consistently, the artifact remains
editable and semantically unchanged, and visual verification exposes no
unresolved contrast, substitution, clipping, or stale-style defect.

## Deliverable

Return the themed artifact first. Name the theme, fonts and key colors, state
what was intentionally preserved, and summarize rendering/preview verification.
