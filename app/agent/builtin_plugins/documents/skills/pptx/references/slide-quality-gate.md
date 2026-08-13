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

Render every slide and inspect each image at full-slide size. Use a contact
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
- consistent palette, typography, spacing, recurring anchors, and source-note
  treatment.

Shorten copy or choose another layout before shrinking text. Fix the authoring
script, regenerate, reopen, and render the exact final bytes. If a renderer is
unavailable, disclose that only structural QA was completed.
