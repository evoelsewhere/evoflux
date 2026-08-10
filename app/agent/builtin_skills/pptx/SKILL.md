---
name: pptx
description: Create, redesign, render, and verify high-fidelity or editable PowerPoint presentations through Artifact Fabric. Use when PPTX, PowerPoint, slides, a presentation, or a pitch deck is the requested input/output; do not use for a static poster, prose-only memo, or theme-only change to an otherwise complete artifact.
---

# Author a high-fidelity PowerPoint presentation

Use the deferred `artifact` tool with `format: "pptx"`. Produce one
communication job per slide and verify rendered slides, not only the project
schema. Do not load bundled references or examples when this skill activates.

## Choose one path

- **New deck or image/screenshot reference:** use the new-deck schema and select
  a quality profile below.
- **Uploaded PPTX used as the visual template:** inspect it, then use the
  inherited-template lane; the source deck confirms the visual direction.
- **Uploaded PPTX with ambiguous purpose:** ask whether it is the visual
  template or only a content source before authoring.

Never use Desktop WebView capture or browser screenshots. Artifact Fabric owns
the OpenXML writes and uses static project-local SVG for fidelity shells. Never
overwrite an uploaded source.

## New-deck quality profiles

- **`fidelity` (default):** author each complete slide as static SVG. This
  preserves vector typography, gradients, shadows, and composition exactly;
  the PowerPoint slide contains one full-slide visual object.
- **`hybrid`:** use a decorative SVG shell plus native editable overlays. Also
  author a complete reference SVG for each slide; Artifact Fabric pixel-diffs
  the composed PPTX against that reference and rejects drift.
- **`native`:** use only native text, shape, image, table, and chart objects when
  full semantic editability matters more than CSS-level fidelity.

## Required state machine

### 1. Frame

Identify audience, decision or narrative outcome, supplied facts, slide count
or time, citation needs, editability expectations, brand assets, and final
filename. Draft a slide-by-slide story whose titles state takeaways.

### 2. Resolve visual direction

Treat the user's visual direction as confirmed when supplied colors,
typography, tone, density, audience, layout references, brand rules, images, or
recognizable design language are sufficient. Translate them into one explicit
system for palette, type, spacing, geometry, charts, and images, and
continue without asking the user to approve an internal mapping.

Only when direction is absent or two interpretations would materially change
the deck, call the `ask_user` tool once with short, job-aware options in the
user's language. Batch other blocking presentation questions into that call.
After it returns, resume outline, authoring, preview, and publication in the
same run. Never send a plain assistant message asking the user to choose a
style or end the run waiting for a separate chat reply.

When the source is an academic paper, technical report, thesis, or research
defense—and the requested direction is a dense blue-and-white evidence
briefing—read
[references/research-paper-briefing-style.md](references/research-paper-briefing-style.md)
and the machine-readable
[templates/research-paper-briefing-dna.json](templates/research-paper-briefing-dna.json),
then reuse those tokens and layout primitives in project-local SVG. Do not
fetch a web theme.

### 3A. Inherited template

Call `artifact(action="catalog", format="pptx")`, then `inspect` the source and
review every source-slide preview and object manifest. Read
[references/inherited-template-contract.md](references/inherited-template-contract.md)
only after inspection. Use exact source hash, slide numbers, object IDs, names,
types, and locators. Pass the completed inspect job as `inspect_job_id` when
calling `validate` and `preview`.

### 3B. New deck

Call `artifact(action="catalog", format="pptx")` for the live fidelity, hybrid,
native element, and visual-shell schema. Read
[references/new-deck-contract.md](references/new-deck-contract.md) after choosing
the visual direction and before writing the project. Use
[examples/project.example.json](examples/project.example.json) only when a
starter is useful.

Write the UTF-8 JSON project and call `validate`. Call `preview`, inspect every
returned slide image, and resolve all error-severity findings. Iterate by
creating a new preview job; never mutate an accepted revision.

### 4. Visual and round-trip QA

Inspect all rendered slides for hierarchy, clipping, accidental overlap,
broken assets, repeated silhouettes, unreadable density, weak contrast, and
off-slide content. Verify sources and speaker notes when required. Treat a deck
as unverified unless rendering completed; report limitations explicitly.

### 5. Publish

Call `artifact(action="publish", job_id=..., output="...pptx")` only after
structural and visual gates pass. Publish reuses the immutable bytes already
rendered and reviewed. Preserve master/layout lineage in template mode. In
new-deck mode, report whether the accepted deck is fidelity, hybrid, or native
and do not overstate editability.

## Stop conditions

Stop when narrative and visual direction are coherent, every slide has been
rendered and inspected, no error remains, template lineage is intact where
required, and the final PPTX is independently opened or round-trip checked
when the environment supports it.

## Deliverable

Return the PPTX path first. Report slide count, quality profile, visual
direction, QA and visual-parity status, semantic editable object count,
template preservation, and whether round-trip verification completed or was
skipped.
