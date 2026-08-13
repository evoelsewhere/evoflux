---
name: pptx
description: Create, redesign, render, and verify editable PowerPoint presentations. Use when PPTX, PowerPoint, slides, a presentation, or a pitch deck is the requested input/output; do not use for a static poster or prose-only memo.
---

# Author an editable PowerPoint presentation

Work directly with PPTX files from the workspace using Python and
`python-pptx`. Keep the authoring logic in a task-local script so the deck can
be regenerated. Never overwrite an uploaded presentation.

## Frame the communication job

Identify the audience, decision or narrative outcome, presentation setting,
duration or slide count, supplied facts, language, citation needs, editability
expectations, brand assets, and final filename. Draft takeaway titles so every
slide has one communication job.

Read [content-derived design grammar](references/content-derived-design-grammar.md).
Derive the palette, typography, density, image treatment, recurring anchors,
and 4–5 useful layout families from the content, brand, references, and
audience. Do not select a bundled style preset.

Read [image intelligence](references/image-intelligence.md) whenever the user
supplies images, screenshots, a brand/product, or image-led content. Inspect
semantic role, focal point, negative space, crop safety, technical quality,
provenance, and consistency before assigning an image to a slide.

## Choose the lane

- **New deck or image/screenshot reference:** create a new native deck with
  editable text, shapes, images, charts, and tables.
- **Uploaded PPTX used as the visual template:** inspect slide size, masters,
  layouts, placeholders, notes, and existing object geometry first. Read
  [template and layout use](references/template-layout-use.md), preserve the
  source master/layout lineage, and bind content to suitable layouts.
- **Uploaded PPTX used only for content:** extract its facts and build a new
  deck without claiming to preserve its design.
- **Ambiguous uploaded PPTX:** ask once whether it is a visual template or a
  content source before authoring.

## Required workflow

1. Inspect source assets and presentation structure before layout.
2. Write and run one task-local Python authoring script.
3. Reopen the exact saved PPTX with `python-pptx`; verify slide count, size,
   relationships, notes, placeholders, object bounds, and required text.
4. Render every slide to PNG with the bundled document renderer when it is
   available, then inspect every image at full size.
5. Fix clipping, unintended overlap, broken assets, title wrapping, missing
   glyphs, unreadable density, crop drift, and unresolved placeholders.
6. Run the authoring script again and repeat reopen/render verification on the
   exact final file before returning its workspace path.

Use native PowerPoint objects whenever practical so titles, body text, tables,
charts, and key images remain editable. Decorative background artwork may be
rasterized when necessary, but never imply that flattened details are editable.
Put externally sourced claims and visuals in a `[Sources]` speaker-notes block.

## Stop conditions

Stop only when the narrative is coherent, the visual grammar is consistent
without repetitive silhouettes, images have defensible roles and crops,
template lineage is intact where applicable, the exact final package reopens,
and every rendered slide passes visual review. Return the final PPTX path and
briefly state what was verified.
