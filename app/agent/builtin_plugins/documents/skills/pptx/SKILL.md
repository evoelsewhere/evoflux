---
name: pptx
description: Create, edit, inspect, redesign, or verify Microsoft PowerPoint .pptx presentations through a research-to-design-to-HTML/SVG-to-PPTX workflow with explicit visual-fidelity and editability checks. Use when a PPTX or PowerPoint file is an input or required output; do not trigger for prose-only writing, static graphics, PDFs, or theme advice without a presentation file.
---

# Build high-fidelity editable PowerPoint presentations

Use `research → design → HTML/SVG → PPTX → verify` for new decks and major
redesigns. Treat HTML/CSS as the layout and preview source, SVG as vector art,
and PowerPoint Open XML as the delivery format. Compile a hybrid deck: keep
ordinary text, simple shapes, eligible images, tables, and charts native;
keep effects that PowerPoint cannot reproduce in a visual shell.

Never claim that embedded SVG paths or a raster shell are internally editable.
An SVG inserted into PowerPoint is normally one vector-picture object. Read
[the HTML/SVG-to-PPTX pipeline](references/html-svg-pptx-pipeline.md) before
creating or substantially redesigning a deck.

EvoFlux no longer provides a presentation-authoring tool, durable preview job,
or publish step, and it does not provide an HTML-rendering API.
Confirm `python-pptx`, an HTML renderer, an SVG rasterizer or embedder, and any
chart/image dependencies are already available. Do not silently install them.
Keep deterministic task-local authoring code and generated source files
together so the exact deck can be regenerated. Never overwrite an uploaded
presentation.

## Required reference gate

Before the first authoring write, read every reference required by the selected
route through the skill resource tool. Do not infer their contents from names or
from this summary.

- **New deck or major redesign, always:**
  `references/html-svg-pptx-pipeline.md`,
  `references/content-derived-design-grammar.md`,
  `references/slide-quality-gate.md`, and `references/vision-qa.md`.
- **No supplied visual direction, or a named library style:** also read
  `references/style-library.md` and inspect the selected local preview.
- **Image-led content, supplied images, screenshots, or named brands/products:**
  also read `references/image-intelligence.md`.
- **Uploaded PPTX used as a template:** also read
  `references/template-layout-use.md`.
- **Focused edit or read-only task:** read only the references needed for that
  narrow route; the full new-deck set is not required.

Write the chosen route and exact reference paths to task-local `workflow.txt`.
If a required reference cannot be read, stop before authoring and report the
missing resource.

## Non-negotiable execution gates

For a new deck or major redesign, perform these stages in order and keep the
named evidence files task-local:

1. **Research gate:** write `research.txt` and `sources.json` with audience,
   outcome, constraints, claims, provenance, and unresolved assumptions.
2. **Design gate:** write `design.txt` and `outline.json` with the selected
   style, visual tokens, layout families, slide roles, and takeaway titles.
3. **HTML/SVG gate:** write project JSON, one HTML source per slide, shared or
   local CSS, and declared local assets. Run the bundled project validator,
   render complete source previews and glyph-free shells, and inspect showcase
   slides before batching.
4. **Compile gate:** only after gate 3 passes, write a compiler adapter that
   consumes project JSON and browser-derived geometry. The adapter may use
   `python-pptx` or another available authoring library only to materialize the
   reviewed HTML/SVG representation.
5. **Delivery gate:** reopen the exact PPTX, write the editability and vision
   ledgers, run structural checks, and return the final path plus QA status.

A direct `build_deck.py`-style program that hardcodes slide copy, positions, or
visual design into `python-pptx` is non-compliant for new decks and redesigns.
Do not write the PPTX compiler before validated HTML/SVG sources and rendered
evidence exist. If the HTML/SVG compiler path is unavailable, stop and report
the blocker instead of falling back to direct PowerPoint authoring.

## Choose the path

- **New deck or major redesign:** run the full research-to-HTML/SVG pipeline.
- **Uploaded PPTX used as a template:** inspect and preserve its master/layout
  lineage. Read [template and layout use](references/template-layout-use.md).
  Use HTML/SVG to prototype or populate redesigned content regions, not to
  replace inherited template chrome with a full-slide shell.
- **Uploaded PPTX used only for content:** extract and verify its facts, then
  build a new HTML/SVG-source deck.
- **Focused edit:** make the smallest safe native edit. Do not rebuild an
  unchanged deck merely to force it through the new-deck pipeline.
- **Read or review only:** inspect all relevant slides, notes, and objects;
  answer without modifying or exporting unless asked.
- **Ambiguous uploaded PPTX:** ask once whether it is a template or a content
  source when that choice materially changes the result.

## Required pipeline for create or redesign

### 1. Research

Define the audience, decision or narrative outcome, setting, duration or slide
count, language, editability expectation, brand constraints, and filename.
Verify externally sourced claims and assets. Keep a source ledger and put
slide-specific provenance in `[Sources]` speaker-note blocks.

### 2. Design

Read [content-derived design grammar](references/content-derived-design-grammar.md).
Read [image intelligence](references/image-intelligence.md) when supplied
images, screenshots, a named brand/product, or image-led content are involved.
Use [the visual style library](references/style-library.md) when the user names
a style or no strong brand/reference direction exists; in that route, reading
the library and inspecting the selected preview are mandatory. Treat a style
as a coherent system, not a fixed layout. Inspect the selected preview, derive
HTML/SVG tokens and 4–5 role-specific layout families, then draft takeaway
titles and a slide sequence. For decks of five or more slides, render two
structurally different showcase slides before batching.

### 3. Author HTML and SVG

Create one deterministic 1280×720 HTML slide per output slide unless the source
deck requires another aspect ratio. Use local CSS and assets only. Use semantic
HTML for audience copy and inline or local SVG for icons, geometric structure,
and data illustration. Do not use remote URLs, executable scripts, iframe,
video, audio, canvas, or time-dependent state.

Annotate intended native objects with `data-pptx-editable` and stable
`data-pptx-name` values. Mark intentionally flattened art with
`data-pptx-mode="art"`. The [schema-v8 project example](examples/project.example.json)
demonstrates the compiler contract only; do not treat it as the visual-quality
target. Validate each task-specific project with the
[bundled validator](scripts/validate_html_svg_project.py):

```bash
python3 /absolute/path/to/pptx/scripts/validate_html_svg_project.py \
  /absolute/path/to/project.json
```

Validation proves only the static project contract; it does not prove browser
rendering, PowerPoint fidelity, or editability.

### 4. Compile a hybrid PPTX

Render a complete source preview, then create a glyph-free visual shell by
hiding every object that will be emitted natively without changing layout.
Place that shell first on the slide and add native objects above it in DOM
z-order. Prefer a PowerPoint-compatible SVG shell or vector-picture object only
when it contains no unsupported `foreignObject`, filter, mask, external font,
or browser-only CSS; otherwise use a high-resolution PNG shell.

Map browser pixels at 96 DPI: `inch = px / 96` and `point = px × 0.75`.
Recreate eligible text, simple shapes, raster pictures, tables, and charts as
native PowerPoint objects. Keep complex gradients, masks, filters, textures,
clipped imagery, decorative SVG, and stylized text in the shell. Do not leave a
second baked-in copy of native text under the overlay.

### 5. Verify source, shell, editability, and reopened output

Read [the slide quality gate](references/slide-quality-gate.md) and
[vision QA protocol](references/vision-qa.md). Render full-size Chromium
evidence for every slide before compilation:

1. the complete HTML source preview;
2. the shell after native objects are removed;
3. a deck contact sheet for pacing only.

Reopen the exact saved PPTX with `python-pptx`; verify slide count, size,
relationships, notes, placeholders, object bounds, required text, and the
editability ledger. When the active model can inspect images, use vision to
inspect every complete source slide and shell individually. Fix the task-local
source/compiler and repeat until the vision ledger passes. If pixels rendered
from the exact final PPTX are already available, inspect them too; do not add an
office-suite dependency solely for QA. When vision input is unavailable, skip
only vision judgment, complete structural and editability checks, and report
`vision QA: skipped (capability unavailable)`. Never imply that source-image
review proves Microsoft PowerPoint-specific fidelity.

## Editability contract

Report three separate counts instead of one vague “editable” claim:

- **native editable:** text, shapes, pictures, tables, and charts represented
  by separate PowerPoint objects;
- **vector-picture editable:** SVG that can be moved, resized, or replaced as
  one object, but whose internal paths/text are not promised editable;
- **flattened:** shell content intentionally preserved as pixels or one
  composite visual.

`python-pptx` cannot safely author or preserve every animation, transition,
SmartArt, embedded object, chart feature, SVG extension, or custom XML part.
Preserve unsupported source objects by minimizing edits to their package parts.
Disclose unsupported behavior instead of flattening or silently dropping it.

## Stop conditions

Stop only when the narrative is coherent, the visual grammar is consistent,
every slide passes individual source/shell inspection when vision is available,
editability coverage accounts for all visible text and intended objects,
template lineage is intact where applicable, and the exact final package
reopens. If vision is unavailable, record the skipped visual gate without
blocking otherwise valid structural delivery. Return the absolute final PPTX
path, vision-QA status, and the three editability counts.
