---
name: pptx
description: Create, redesign, render, and verify high-fidelity or selectively editable PowerPoint presentations through Artifact Fabric. Use when PPTX, PowerPoint, slides, a presentation, or a pitch deck is the requested input/output; do not use for a static poster, prose-only memo, or theme-only change to an otherwise complete artifact.
---

# Author a high-fidelity PowerPoint presentation

Use the deferred `artifact` tool with `format: "pptx"`. Produce one
communication job per slide and verify every rendered HTML preview. Do not
load bundled references or examples when this skill activates.

## Choose one path

- **New deck or image/screenshot reference:** use the HTML/Tailwind hybrid lane.
- **Uploaded PPTX used as the visual template:** inspect it, then use the
  inherited-template lane; the source deck confirms the visual direction.
- **Uploaded PPTX with ambiguous purpose:** ask whether it is the visual
  template or only a content source before authoring.

Never build a new deck from miscellaneous PowerPoint primitives. HTML is the
visual source of truth. Only simple text and raster images explicitly marked
editable become native PowerPoint objects; complex typography, charts,
diagrams, icons, gradients, texture, and decorative composition remain in the
visual shell.

## Required state machine

### 1. Frame

Identify audience, decision or narrative outcome, supplied facts, slide count
or time, citation needs, editability expectations, brand assets, and final
filename. Draft a slide-by-slide story whose titles state takeaways.

### 2. Resolve visual direction

Treat colors, typography, tone, density, audience, layout references, brand
rules, images, or recognizable design language as confirmed direction. Turn
them into one coherent editorial system. Avoid repeated card grids and generic
UI composition.

Only when direction is absent or two interpretations would materially change
the deck, call the `ask_user` tool once with short options in the user's
language. Never send a plain assistant message asking for a style choice.
After the answer, resume outline, authoring, preview, and publication in the
same run.

For a dense blue-and-white paper briefing, read
[references/research-paper-briefing-style.md](references/research-paper-briefing-style.md)
and [templates/research-paper-briefing-dna.json](templates/research-paper-briefing-dna.json).

### 3A. Inherited template

Call `artifact(action="catalog", format="pptx")`, then inspect the source and
review every preview and object manifest. Read
[references/inherited-template-contract.md](references/inherited-template-contract.md)
after inspection. Preserve masters, layouts, themes, transitions, and untouched
objects.

### 3B. New HTML deck

Call `artifact(action="catalog", format="pptx")`, then read
[references/new-deck-contract.md](references/new-deck-contract.md). Author one
HTML fragment and optional CSS file per slide at 1280×720. Use only local
assets declared in the project JSON. Do not use scripts, remote URLs, CDN
Tailwind, canvas, iframe, video, or audio.

Use `data-pptx-editable="text"` only for solid-color text with export-safe
fonts and no CSS transform, filter, text shadow, letter spacing, text transform,
opacity, clipping, blend mode, or mixed inline styling. Use
`data-pptx-editable="image" data-pptx-asset="..."` only for declared raster
images without crop, mask, radius, filter, transform, opacity, or blend effects.
Do not mark stylized text or SVG icons editable merely to increase an editability
count.

Write the UTF-8 project JSON and call `validate`. Call `preview` while the
EvoFlux desktop window remains open, inspect every returned slide, and resolve
all error-severity findings. Iterate with a new preview job; never mutate an
accepted revision.

### 4. Visual and round-trip QA

Inspect all rendered slides for hierarchy, clipping, broken assets, repeated
silhouettes, unreadable density, weak contrast, and off-slide content. Verify
sources and speaker notes. Reject blank/wrong-ratio previews and any editable
element that overflows the canvas. The accepted HTML preview is the visual
evidence; the generated PPTX must also pass structural OpenXML round-trip.

### 5. Publish

Call `artifact(action="publish", job_id=..., output="...pptx")` only after QA
passes. Publish reuses the exact immutable bytes already reviewed. Report the
native editable object count without implying that flattened visual details
are semantically editable.

## Stop conditions

Stop when narrative and visual direction are coherent, every slide has been
rendered and inspected, no error remains, template lineage is intact where
required, and the final PPTX passed structural round-trip.
