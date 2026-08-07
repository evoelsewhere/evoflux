---
name: pptx
description: Create, redesign, render, and verify editable PowerPoint presentations through EvoFlux's new-deck and inherited-template pipelines. Use when PPTX, PowerPoint, slides, a presentation, or a pitch deck is the requested input/output; do not use for a static poster, prose-only memo, or theme-only change to an otherwise complete artifact.
---

# Author a PowerPoint presentation

Produce one communication job per slide and verify the rendered deck, not just
the project schema. Do not load bundled references or examples when this skill
activates.

## Choose one path

- **New deck or image/screenshot reference:** use deferred `pptx_html`.
- **Uploaded PPTX explicitly used as the visual template:** use deferred
  `pptx_template`; the source deck itself confirms the visual direction.
- **Uploaded PPTX with ambiguous purpose:** ask whether it is the visual
  template or only a content source before authoring.

Never fall back to blank slides, `python-pptx`, or `pptx_html` when the user
requires preservation of an uploaded template's masters and layouts. Never
overwrite the uploaded source.

## Required state machine

### 1. FRAME

Identify audience, decision or narrative outcome, supplied facts, required
slide count or time, source/citation needs, editability expectations, brand
assets, and final filename. Draft a slide-by-slide story whose titles state the
takeaway rather than a topic label.

### 2. RESOLVE VISUAL DIRECTION

Treat the user's visual direction as confirmed whenever the request supplies a
recognizable design language through colors, typography, tone, density,
audience, layout references, brand rules, an image, or phrases such as
“enterprise technology.” Map it to the closest internal preset, preserve the
stated constraints, set `style_confirmed: true`, and continue without asking
the user to approve the internal mapping.

Only when meaningful direction is absent or two interpretations would
materially change the deck, call the `ask_user` tool once with a short,
job-aware set of options in the user's language. Batch any other blocking
presentation question into that call. After it returns, resume outline,
authoring, rendering, and composition in the same run. Never send a plain
assistant message asking the user to choose a style or end the run waiting for
a separate chat reply.

Use `scientific-defense` first for research, technical, thesis, or
evidence-heavy decks. Other common directions include clean professional,
McKinsey-style consulting, data dashboard, teaching courseware, and creative
magazine. Set an exact `style_preset` and `style_confirmed: true`; do not use a
silent default.

### 3A. INHERITED TEMPLATE

Load `pptx_template`, call `catalog`, then `inspect` the source and review every
source-slide preview and object manifest. Read
[references/inherited-template-contract.md](references/inherited-template-contract.md)
only after inspection returns the manifest. Use exact source hash, slide
numbers, object IDs, names, types, and locators from that result. Validate,
render, visually inspect, and compose only after lineage and placeholder QA
pass.

### 3B. NEW DECK

Load `pptx_html` and call `catalog` for the current schema, templates, editable
markers, and visual systems. Read
[references/new-deck-contract.md](references/new-deck-contract.md) only after
choosing the style and before writing the project. Start from
[examples/project.example.json](examples/project.example.json) only when a
starter is useful; use a more specific example only for the matching deck type.

Write and validate the UTF-8 JSON project. Render one representative slide,
inspect the returned image, and fix it before producing the full deck. Then
render every slide and resolve all error-severity QA findings before compose.
Warnings require deliberate review rather than automatic acceptance.

### 4. VISUAL AND ROUND-TRIP QA

Inspect all rendered slides for hierarchy, clipping, accidental overlap,
broken assets, repeated silhouettes, unreadable density, weak contrast, and
content outside the 1600×900 canvas. Verify sources and speaker notes when
required. Treat the written deck as unverified unless round-trip rendering
completed; if unavailable, report that limitation rather than interpreting an
absence of warnings as proof.

### 5. COMPOSE

Compose exactly one final PPTX after structural and visual gates pass. Preserve
inherited master/layout lineage in template mode. In new-deck mode, preserve
the intended split between editable native objects and pixel-stable complex
background effects.

## Stop conditions

Stop when narrative and visual direction are coherent, every slide has been
rendered and inspected, no error-severity QA issue remains, source/template
lineage is intact where required, and the final PPTX is independently opened or
round-trip checked when the environment supports it.

## Deliverable

Return the PPTX path first. Report slide count, selected path and style, QA and
warning status, editable text/shape/image counts, editability coverage and
preserved rich-text runs, source/template preservation, which effects remain
rasterized, and whether round-trip verification completed or was skipped.
