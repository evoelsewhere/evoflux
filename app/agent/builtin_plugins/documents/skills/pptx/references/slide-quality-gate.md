# Slide quality gate

Use this reference for the final QA pass of every created or edited PPTX.

## Structural inspection

Reopen the exact exported file. Verify slide count and size, master/layout
lineage, notes, relationships, required text, object bounds, chart and table
sources, image relationships, and inherited placeholders. Empty structural
placeholders still count even when a renderer hides their edit-mode prompts;
fill or remove them intentionally.

For template work, compare each output slide with its mapped source pattern and
review every changed package part. Unplanned loss of brand chrome, logos,
footers, numbering, notes, or unsupported objects is a failure.

## Visual inspection

For HTML/SVG-source work, create the complete source preview and glyph-free
shell in Chromium. When the active model accepts image input, follow
`vision-qa.md` and inspect each surface at full size. If pixels rendered from
the exact final PPTX already exist, inspect them as additional evidence. For
focused native edits, inspect available before/after renders. Use a contact
sheet only to evaluate flow, pacing, repeated silhouettes, and consistency; it
does not replace individual inspection.

Check every slide for:

- one clear narrative job, primary claim, and reading order;
- audience-facing copy with no production notes or timing scaffolds;
- title wrapping, clipped or overflowing text, missing glyphs, and type that is
  too small for the presentation setting;
- unintended overlap, uneven margins, weak alignment, crowding, or excessive
  empty space;
- correct image identity, aspect ratio, focal point, crop, resolution, and
  source note;
- legible charts and tables with correct labels, units, categories, series,
  scales, and source data;
- connector endpoints and semantics, unresolved placeholders, duplicated
  objects, and off-slide content;
- duplicate baked-in/native text, shifted overlays, SVG fallback loss, wrong
  z-order, and font-metric wrap or baseline drift;
- consistent palette, typography, spacing, recurring anchors, and source-note
  treatment.

Shorten copy or choose another layout before shrinking text. Fix the authoring
script, regenerate, reopen, and render the exact final bytes. If vision input is
unavailable, skip only the visual judgment and record that capability gap;
structural and editability checks remain required.

## Editability inspection

Read the per-slide editability ledger. Confirm that every visible text block is
either a native text object or has an explicit flattening reason. Confirm that
every annotated object exists at the expected bounds and z-order after reopen.
Count native editable objects, SVG vector-picture objects, and flattened
objects separately. Never infer path-level SVG editability from the fact that
PowerPoint can move or resize the SVG picture.

Inspect the PPTX package when the authoring library exposes ambiguous output:
native shapes and text appear as separate shape/text nodes, while an inserted
SVG normally appears as one picture relationship with an SVG payload and a
raster fallback. Package structure is editability evidence, not visual proof.

## Fidelity verification

Use Chromium source previews as the required visual surface. If vision is
available, inspect every slide independently and save the vision ledger. The
glyph-free shell verifies that native overlays were removed without shifting
layout. An exact final-PPTX render is optional evidence when a trustworthy
renderer is already present; do not introduce an office-suite dependency only
to obtain it. Pixel similarity is secondary evidence and is meaningful only
for a calibrated renderer pair. A valid ZIP/OpenXML package proves structure,
while source-image vision QA judges design quality; neither alone proves
Microsoft PowerPoint-specific fidelity.
