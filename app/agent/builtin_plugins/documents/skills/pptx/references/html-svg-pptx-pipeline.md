# HTML/SVG to hybrid editable PPTX

Use this reference for new presentations and major redesigns. HTML/CSS owns
layout and review. PowerPoint owns the deliverable. The compiler preserves
visual fidelity by flattening only unsupported art and preserves practical
editability by recreating eligible objects natively.

## Contents

1. Project contract
2. Representation rules
3. HTML and SVG authoring rules
4. Compilation sequence
5. Editability ledger
6. Fidelity verification

## Project contract

Start from [the schema-v8 project example](../examples/project.example.json).
Use one project directory containing the JSON manifest, one HTML fragment per
slide, optional CSS, and local assets.
The default canvas is 1280×720 CSS pixels. Every HTML fragment must contain
exactly one `data-slide-root` element.

Use these annotations:

| Annotation | Meaning |
| --- | --- |
| `data-pptx-editable="text"` | Recreate as a native PowerPoint text box. |
| `data-pptx-editable="shape"` | Recreate a simple rectangle, rounded rectangle, ellipse, line, or connector. |
| `data-pptx-editable="image"` | Recreate a declared raster image as a native picture. |
| `data-pptx-editable="svg"` | Insert the SVG as one vector-picture object; do not promise internal editability. |
| `data-pptx-editable="table"` | Recreate a native table from a declared structured-data asset. |
| `data-pptx-editable="chart"` | Recreate a native chart from a declared structured-data asset. |
| `data-pptx-name="..."` | Stable, unique PowerPoint object name. Required on every intended native object. |
| `data-pptx-role="..."` | Optional semantic role such as title, body, source-note, or hero-visual. |
| `data-pptx-mode="art"` | Keep the element in the visual shell intentionally. |

Add `data-pptx-shape="rect|roundRect|ellipse|line|connector"` to editable
shapes. Add `data-pptx-source="asset://<declared-key>"` to native table and
chart frames; the declared asset must contain the structured source data used
by the PowerPoint object.

Use `asset://<declared-key>` for local assets named in project JSON. Inline
assets before browser rendering. Forbid network URLs, protocol-relative URLs,
scripts, event handlers, `@import`, iframe, object, embed, form controls, video,
audio, and canvas.

## Representation rules

Choose the richest PowerPoint representation that preserves the reviewed look:

| Source | PPTX representation | Editability |
| --- | --- | --- |
| Solid-color heading, paragraph, list, label | Native text box with paragraphs/runs | Full text editing within supported styles |
| Rect, rounded rect, ellipse, simple line/connector | Native shape | Fill, line, size, position, and text editable |
| Declared PNG/JPEG without browser-only effects | Native picture | Move, resize, crop, or replace |
| Pure SVG icon or illustration | SVG picture plus fallback | Move, resize, or replace as one object; internal paths are not guaranteed editable |
| Table or chart backed by structured data | Native PowerPoint table/chart | Data and formatting editable within library limits |
| Complex CSS, shadows, filters, masks, texture, blend modes, clipped art | Visual shell | Not internally editable |
| Stylized text using gradient fill, path layout, clipping, or text stroke | Visual shell | Not editable; record the reason |

Raw HTML is never embedded as editable PowerPoint content. Converting HTML to
SVG with `<foreignObject>` preserves browser appearance but is not a dependable
PowerPoint representation. Rasterize that content or materialize supported DOM
objects as native PowerPoint objects.

## HTML and SVG authoring rules

- Use semantic HTML for copy and SVG for vector art, not for hiding all slide
  text inside one picture.
- Use available, export-safe fonts. Test Vietnamese and CJK glyphs when used.
- Keep editable text free of transform, filter, blend mode, mask, clip path,
  text stroke, gradient text, and non-solid color.
- Give editable text enough width for PowerPoint font-metric differences. Do
  not force browser-only line breaks to conceal a wrapping mismatch.
- Keep inline SVG self-contained. Avoid `foreignObject`, scripts, animation,
  external CSS/fonts, remote images, filters, and masks when the SVG will be
  inserted as a vector picture.
- Do not put audience copy inside an SVG when that copy must remain editable.
- Build native charts and tables from structured data. SVG previews may guide
  their design but must not replace the editable data object.

## Compilation sequence

1. Validate project JSON, local paths, HTML safety, unique slide IDs, unique
   object names, declared assets, and canvas bounds.
2. Render the complete HTML source preview at the declared canvas size after
   fonts and images finish loading.
3. Read `getBoundingClientRect()` and computed styles for every annotated
   object. Reject off-slide or zero-area native candidates.
4. Classify each object as native, vector picture, or flattened. Record every
   fallback reason before export.
5. Hide native text glyphs with transparent text color and no text shadow;
   preserve the element's box, background, border, and layout. Hide extracted
   image/SVG pixels while preserving geometry.
6. Capture the visual shell at 2× resolution when raster output is required.
   Prefer one shell per slide, placed at `(0, 0)` behind all native overlays.
7. Convert geometry using `inch = px / 96`. Convert font size using
   `point = CSS px × 0.75`.
8. Recreate native objects in DOM z-order. Use one PowerPoint text box per
   logical text block, not per word. Preserve paragraphs, runs, bullets,
   alignment, padding, line spacing, rotation, and stable object names when the
   authoring library supports them.
9. Insert PowerPoint-compatible SVG with a raster fallback when the library can
   author the required SVG extension. Otherwise keep that SVG inside the shell
   and record the fallback.
10. Add `[Sources]` notes, save, reopen, render, and compare the exact bytes.

Do not use a full-slide shell on top of native template chrome. For a template
deck, keep the master/layout background and inherited objects native and limit
the shell to the redesigned content frame.

## Editability ledger

Write a machine-readable ledger next to the task-local source. At minimum,
record per slide:

```json
{
  "slide": 1,
  "visible_text_blocks": 4,
  "native_text_blocks": 3,
  "native_shape_objects": 2,
  "native_image_objects": 1,
  "vector_picture_objects": 1,
  "flattened": [
    {"name": "gradient-wordmark", "reason": "gradient text"}
  ]
}
```

Every visible text block must be native or listed under `flattened`. Every
annotated object must be emitted or have a fallback reason. Report deck totals
for native editable objects, vector-picture objects, and flattened objects.

## Fidelity verification

Verify these surfaces independently:

1. source HTML preview;
2. glyph-free shell;
3. vision inspection of the full-size surfaces when the active model accepts
   image input;
4. exact final-PPTX pixels only when a trustworthy renderer is already
   available.

Do not introduce an office-suite dependency solely for surface 4. When vision
is unavailable, skip surface 3 explicitly and retain all structural and
editability evidence.

Compare source and reopened previews at identical dimensions. Pixel similarity
is secondary evidence: use a target of at least 0.90 per slide and 0.95 median
only after confirming the metric is calibrated for the renderer pair. Always
inspect full-slide images for text baseline or wrap drift, duplicate glyphs,
font substitution, wrong z-order, clipped elements, crop changes, and missing
SVG details. A valid ZIP/OpenXML package proves structure, not visual parity.
