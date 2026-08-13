---
name: pptx
description: Create, edit, inspect, redesign, or verify editable Microsoft PowerPoint .pptx presentations. Use when a PPTX or PowerPoint file is an input or required output; do not trigger for prose-only writing, static graphics, PDFs, or theme advice without a presentation file.
---

# Author an editable PowerPoint presentation

Work directly with PPTX files using Python and `python-pptx`. Keep authoring
logic in a task-local script so the deck can be regenerated. Never overwrite
an uploaded presentation.

EvoFlux no longer provides a presentation-authoring tool, durable preview job,
or publish step. Confirm `python-pptx` and any image/chart dependencies are
available in the workspace environment. Do not silently install them.

## Frame the communication job

Identify the audience, decision or narrative outcome, presentation setting,
duration or slide count, supplied facts, language, citation needs, editability
expectations, brand assets, and final filename. Draft takeaway titles so every
slide has one communication job.

Read [content-derived design grammar](references/content-derived-design-grammar.md)
before choosing the visual system. Read
[image intelligence](references/image-intelligence.md) only when the request
uses supplied images, screenshots, a named brand/product, or image-led content.
Read the [slide quality gate](references/slide-quality-gate.md) before final
delivery.

## Choose the path

- **New deck or visual reference:** create a native deck with editable text,
  shapes, images, charts, and tables.
- **Uploaded PPTX used as a template:** inspect slide size, masters, layouts,
  placeholders, notes, and object geometry. Read
  [template and layout use](references/template-layout-use.md), preserve the
  source master/layout lineage, and bind content to suitable layouts.
- **Uploaded PPTX used only for content:** extract its facts and build a new
  deck without claiming to preserve its design.
- **Read or review only:** inspect all relevant slides, notes, and objects;
  answer without modifying or exporting the deck unless asked.
- **Ambiguous uploaded PPTX:** ask once whether it is a template or content
  source when that choice would materially change the result.

## Required workflow for create or edit

1. Inspect source assets and presentation structure before layout.
2. Write and run one deterministic task-local Python authoring script.
3. Reopen the exact saved PPTX with `python-pptx`; verify slide count, size,
   relationships, notes, placeholders, object bounds, and required text.
4. Render every slide with an available renderer and inspect every image at
   full size. Treat EvoFlux's semantic renderer as a QA approximation, not
   proof of Microsoft PowerPoint fidelity.
5. Fix clipping, unintended overlap, broken assets, title wrapping, missing
   glyphs, unreadable density, crop drift, and unresolved placeholders.
6. Rerun authoring and reopen/render checks on the exact final bytes.

Use native PowerPoint objects whenever practical so titles, body text, tables,
charts, and key images remain editable. Decorative artwork may be rasterized
when necessary, but never imply that flattened details are editable. Put
externally sourced claims and visuals in a `[Sources]` speaker-notes block.

`python-pptx` cannot safely author or preserve every animation, transition,
SmartArt, embedded object, chart feature, or custom XML extension. Preserve
unsupported source objects by minimizing edits to their package parts. If a
requested edit requires unsupported behavior, disclose it instead of flattening
or silently dropping the object.

## Stop conditions

Stop only when the narrative is coherent, the visual grammar is consistent,
images have defensible roles and crops, template lineage is intact where
applicable, the exact final package reopens, and every rendered slide passes
visual review. If no renderer is available, report that only structural QA was
completed. Return the absolute final PPTX path and state what was verified.
