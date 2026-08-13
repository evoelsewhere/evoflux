---
name: pptx
description: Create, redesign, render, and verify high-fidelity PowerPoint presentations through Artifact Fabric. Use when PPTX, PowerPoint, slides, a presentation, or a pitch deck is the requested input/output; do not use for a static poster, prose-only memo, or theme-only change to an otherwise complete artifact.
---

# Author a high-fidelity PowerPoint presentation

Use the deferred `artifact` tool with `format: "pptx"`. HTML/CSS is the visual
source of truth for new composition. The exported deck combines a glyph-free
raster shell for visual fidelity with native text overlays for practical
editing. Do not reconstruct the complete design from miscellaneous PowerPoint
primitives.

Load only the references required by the selected lane. Keep generated HTML,
CSS, images, and project JSON inside one project directory.

## Choose the lane

- **New deck or image/screenshot reference:** author an HTML-shell deck.
- **Uploaded PPTX used as the visual template:** inspect it first, preserve its
  master → layout → slide lineage, and bind new content to suitable layouts.
- **Uploaded PPTX used only for content:** extract its facts and build a new
  HTML-shell deck.
- **Ambiguous uploaded PPTX:** ask once whether it is a visual template or a
  content source before authoring.

## Required workflow

### 1. Frame the communication job

Identify the audience, decision or narrative outcome, presentation setting,
duration or slide count, supplied facts, language, citation needs,
editability expectations, brand assets, and final filename. Verify current or
external claims before using them. Draft takeaway titles so every slide has
one communication job.

Read [content-derived design grammar](references/content-derived-design-grammar.md).
Derive the palette, typography, density, image treatment, recurring anchors,
and 4–5 useful layout families from the content, brand, references, and
audience. Do not select a bundled style preset.

Treat explicit colors, typography, tone, density, brand rules, template
lineage, or visual references as confirmed direction. Only when missing
direction would materially change the result, call `ask_user` once with short
options in the user's language. Resume outline, authoring, preview, and
publication in the same run; never send a plain assistant message asking for
an avoidable style choice.

### 2. Understand images before layout

Read [image intelligence](references/image-intelligence.md) whenever the user
supplies images, screenshots, a brand/product, or image-led content. Inspect
semantic role, focal point, negative space, crop safety, technical quality,
provenance, and consistency before assigning an image to a slide. Real product
images, UI captures, logos, charts, and evidence outrank decorative stock.

### 3A. Author a new HTML-shell deck

Call `artifact(action="catalog", format="pptx")`, then read
[HTML shell and editable text](references/html-shell-editable-text.md). Copy
and adapt [the schema-v7 project example](examples/project.example.json).
Author one deterministic 1280×720 HTML fragment and optional CSS file per
slide. Use only project-local assets declared in project JSON. Do not use
scripts, remote URLs, CDN assets, canvas, iframe, video, or audio.

Eligible ordinary visible HTML text is extracted by the WebView by default and
exported as native PowerPoint text when its styling is supported. Do not
annotate every text node. `data-pptx-editable="text"` remains an optional
compatibility or selection hint, while `data-pptx-name` can give an overlay a
stable name. Use `data-pptx-text-mode="art"` when stylized text must remain in
the shell. Keep gradients, SVG, charts, diagrams, clipped imagery, texture,
shadows, masks, and decorative composition in the shell; do not lower the
whole deck's visual quality or build a fully native substitute.

Write UTF-8 project JSON, call `validate`, then call `preview` while the
EvoFlux desktop WebView remains connected. Inspect every returned slide at
full size; for decks longer than the returned preview page, call `status` on
the job with successive `preview_offset` values until every slide has been
seen. Iterate with a new immutable preview job. If Artifact Fabric is
unavailable, authoring may continue only as a local draft that passes:

```bash
python scripts/validate_slide_project.py /absolute/path/to/project.json
```

Do not claim a preview, publication, or deliverable PPTX until Artifact Fabric
and its desktop WebView are available.

### 3B. Follow a PPTX template or layout library

Call `artifact(action="catalog", format="pptx")`, then inspect the source deck
and review every preview and object manifest. Read
[template and layout use](references/template-layout-use.md). Prefer an
existing source layout whose placeholders and content frame fit the
communication job. Preserve slide size, masters, layouts, themes, inherited
chrome, untouched objects, and source relationships.

Use [the template-following example](examples/template-following.example.json)
only as a schema starter. Copy the exact inspected source hash and use verified
slide numbers and object IDs. Do not invent edit targets or flatten an
inherited template into a generic 16:9 screenshot.

### 4. Verify visual and editable parity

For every candidate revision, inspect:

1. the complete HTML source preview;
2. the high-resolution shell with editable glyphs removed;
3. the editable-text manifest and overlay bounds;
4. the exact published PPTX reopened by the built-in renderer.

Reject blank or wrong-ratio slides, clipping, unintended overlap, broken
assets, title wrapping, missing glyphs, unreadable density, duplicate shell
text, font substitution, shifted overlays, crop drift, and unresolved
placeholders. A successful OpenXML reopen is structural evidence, not visual
proof. Put every externally sourced claim and visual in a `[Sources]` speaker
notes block.

### 5. Publish and reopen the exact bytes

Call `artifact(action="publish", job_id=..., output="...pptx")` only after the
accepted preview has no error-severity findings. Publication must reuse the
reviewed immutable revision. Then call
`artifact(action="inspect", format="pptx", source_path="...pptx")` on that
exact output and compare every reopened slide with the accepted HTML preview.
If the reopened deck drifts materially, author and publish a new revision.

## Stop conditions

Stop only when the narrative is coherent, the design grammar is consistent
without repetitive silhouettes, images have defensible roles and crops, every
slide has accepted source and reopened previews, inherited template lineage is
intact where applicable, and the final package passes structural round-trip.
Report native editable text counts and any text intentionally retained in the
visual shell without implying that flattened details are editable.
