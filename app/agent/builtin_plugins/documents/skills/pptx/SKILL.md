---
name: pptx
description: Create, redesign, render, and verify high-fidelity or selectively editable PowerPoint presentations through Artifact Fabric. Use when PPTX, PowerPoint, slides, a presentation, or a pitch deck is the requested input/output; do not use for a static poster, prose-only memo, or theme-only change to an otherwise complete artifact.
---

# Author a high-fidelity PowerPoint presentation

Use the deferred `artifact` tool with `format: "pptx"`. Produce one
communication job per slide and verify every rendered HTML preview. Do not
load unrelated bundled references or examples when this skill activates; load
the mandatory format contract below and the lane-specific resources only when
their lane is selected.

After framing the request, always read
[references/slide-dna-contract.md](references/slide-dna-contract.md) and
[templates/powerpoint-slide-dna.json](templates/powerpoint-slide-dna.json).
Instantiate a project-local `slide-dna.json` before authoring. This PowerPoint
format DNA is mandatory for new and inherited decks; a style-specific DNA may
extend it but never replace its representation and render-fidelity gates.

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
Merge that style DNA over the PowerPoint baseline instead of treating it as a
complete format contract.

For a technical research or academic engineering deck that specifically calls
for the compact Office-like blue-and-white diagram language, read
[references/academic-engineering-blueprint-style.md](references/academic-engineering-blueprint-style.md)
and [templates/academic-engineering-blueprint-dna.json](templates/academic-engineering-blueprint-dna.json).
Prefer this measured ten-archetype system over the looser paper briefing style
when the reference uses numbered rails, dense architecture panels, and a fixed
takeaway band.

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

Copy and adapt the bundled
[project-local Slide DNA example](examples/slide-dna.json); do not invent the
top-level DNA structure from memory. Also copy
[the six-dimension QA ledger example](examples/qa-ledger.json), keep every
evidence path project-local, and leave `canvas-and-geometry` plus
`reopened-render-parity` unverified for the runtime to score from actual
renders. If the `artifact` tool is unavailable,
authoring may continue only as a local draft that passes the supported schema
validator:
`python scripts/validate_slide_project.py /absolute/path/to/project.json`.
Do not claim a preview, reopened-render score, publication, or deliverable PPTX
until Artifact Fabric and its desktop WebView are available.

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
source, but it is not proof of exported PPTX fidelity. Read and execute
[references/pptx-fidelity-checklist.md](references/pptx-fidelity-checklist.md).
Inspect the 2× flattened shell and editable-element manifest before publishing.
Structural OpenXML round-trip is required but earns no visual-fidelity credit.
Mark unsupported or unrendered Office behavior as `unverified` rather than
silently passing it.

### 5. Publish

Call `artifact(action="publish", job_id=..., output="...pptx")` only after the
pre-publication checklist gates pass. Publish reuses the exact immutable bytes
already reviewed. Then call `artifact(action="inspect", format="pptx",
source_path="...pptx")` on that exact output and compare every returned slide
preview with the accepted HTML preview. Require the DNA score of at least
90/100 as the runtime-computed `observedScore`, not merely the declared target,
and resolve every hard failure. If the reopened render fails, do not
deliver it—author and publish a new immutable revision. Report the native
editable object count without implying that flattened visual details are
semantically editable.

## Stop conditions

Stop when narrative and visual direction are coherent, every slide has been
rendered and inspected, no error remains, template lineage is intact where
required, the reopened PPTX render meets the 90/100 DNA gate, and the final
PPTX passed structural round-trip.
