---
name: canvas-design
description: Create original static visual artwork as PNG or print-ready PDF, including posters, covers, wall art, editorial compositions, and one-page visual pieces. Use when the deliverable is a static canvas rather than product UI, a slide deck, a document, or interactive generative art.
---

# Create static canvas artwork

Deliver the requested visual artifact, not a prose manifesto. Build an original
composition from the subject, audience, viewing distance, physical or digital
format, and one deliberate visual thesis. Do not load the bundled font library
when this skill activates.

## State machine

### 1. FRAME

Confirm canvas size, orientation, output format, required text, brand or legal
constraints, and whether the work is primarily expressive or informational.
Infer non-blocking choices from the brief. Ask only when missing dimensions,
copy, or brand assets would materially change the deliverable.

### 2. DIRECT

Define a compact visual system before production:

- one compositional idea and focal point;
- palette with functional roles;
- type roles and hierarchy when text is required;
- grid, margins, rhythm, and intended negative space;
- one signature element tied to the subject.

Translate artist references into general visual attributes; do not copy a
recognizable work or imitate a living artist. Use text as content, not filler,
and never invent event, legal, pricing, or contact details.

### 3. BUILD

Create only the formats requested. Use vector or code-native geometry where it
improves print quality. Inspect `canvas-fonts/` only after choosing required type
roles, then load the minimum matching font files and retain their license files.
Keep all content inside safe margins and make typography readable at the
intended viewing size.

### 4. VERIFY

Render the final PNG/PDF and inspect the actual image. Check dimensions,
resolution, crop/bleed requirements, contrast, text accuracy, font rendering,
alignment, clipping, unintended overlap, and export artifacts. Make a second
pass that removes or refines weak elements instead of adding decoration.

## Stop conditions

Stop when the composition has a clear focal hierarchy, all required copy is
accurate, the rendered output is clean at normal and zoomed viewing, and the
delivered files match the requested dimensions and formats.

## Deliverable

Return the final PNG or PDF first. Briefly state dimensions, fonts used,
print/export assumptions, and visual verification performed. Provide design
notes only when requested.
