# New PPTX deck contract

Read this after `pptx_html(action="catalog")` and visual-direction selection.
Treat the live catalog as authoritative when it differs from examples here.

## Tool sequence

1. Query the selected `style_preset` and any selected `base_template` through
   `catalog` for exact palette and content contracts.
2. Write the project JSON inside the workspace and call `validate`.
3. Call `render` for one representative slide and inspect the image.
4. Correct the project, render all slides, and resolve `qa.json` errors.
5. Call `compose` only after full render and QA succeed.

## Authoring rules

Each slide contains the inner content of a fixed 1600×900 canvas. Prefer
`template + content` over raw HTML when a base template fits; the live catalog
lists current IDs and item bounds. Do not supply both a template and raw HTML
for one slide.

Keep one deck-level visual system. Vary narrative archetypes across adjacent
slides rather than repeating the same card grid. Use one communication job,
one takeaway title, and normally no more than three major content groups per
slide.

Use **Evoflux** for any generator/edition branding visible in the design. Never
emit Codex logos, watermarks, edition labels, or generator credits; the upstream
repository name may appear only in source attribution or when it is the actual
subject of the presentation.

Use `editable_mode: "max"` unless a supplied visual requires unusual CSS.
Semantic headings, paragraphs, list items, table cells, images, panels, steps,
rules, and `data-box` regions become native where supported. Use explicit
`data-pptx-native` markers for custom editable objects and `data-pptx-raster`
for gradients, clipping, filters, transformed compounds, text strokes, or
effects that cannot round-trip faithfully.

Native text preserves inline runs for font family, size, weight, italic,
underline, strike, color, tracking, explicit line breaks, and list markers.
Review `qa.json.editability`: investigate any `editable_coverage_low` warning,
and rasterize only effects whose CSS cannot be represented faithfully.

Use explicit `<br>` in display titles when the line break is part of the art
direction. Editable text must use export-safe fonts or be deliberately
rasterized; treat `font_not_export_safe` as a real reflow risk.

Use `data-box` for peer structural regions so collision QA and native-shape
promotion can reason about them. Mark intentional overlap explicitly. Never
use QA-ignore markers to hide text overflow.

Workspace images and SVG files must use `asset://relative/path`. Reject remote
URLs, scripts, iframes, forms, imported CSS, executable attributes, and
filesystem URLs. Prefer inline SVG or CSS geometry for sharp diagrams.

## Visual quality

- Use composition, scale, whitespace, and contrast before adding boxes.
- Avoid dashboard grids unless the content is genuinely a dashboard.
- Keep body text generally 18–24 px or larger and titles 44–72 px.
- Build diagrams with a clear reading order and meaningful edges.
- Use inline SVG, CSS shapes, or workspace assets instead of emoji icons.
- Never accept clipped text, broken images, accidental overlap, or off-canvas
  content.

Put presenter guidance in `speaker_notes` and traceable URLs/labels in
`sources`; do not scatter raw citations over the visual surface unless the
audience needs them there.

When LibreOffice round-trip comparison runs, inspect any `round_trip_drift`
warning against both named images. Without a completed round trip, report that
the final PowerPoint render remains environment-unverified.
