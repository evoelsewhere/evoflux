# Vision QA protocol

Use this protocol on Chromium-rendered HTML/SVG evidence before final delivery.
Vision QA judges pixels; it does not replace structural or editability checks.

## Capability gate

- If the active model can inspect local images, run the complete protocol.
- If image input is unavailable, do not simulate visual inspection from XML,
  OCR, object coordinates, filenames, or similarity scores. Record `vision QA:
  skipped (capability unavailable)` and continue the non-visual gates.

## Evidence

For every slide, provide the model with the full-size source preview. Include
the glyph-free shell when checking overlay duplication or z-order. If pixels
rendered from the exact final PPTX already exist, provide them at the same
dimensions as optional comparison evidence. Inspect slides individually; use a
contact sheet only afterward for deck-level rhythm and consistency.

## Inspection order

1. Inspect the complete source slide independently for clipping, wrapping, overlap,
   unreadable text, broken hierarchy, poor spacing, wrong crop, missing glyphs,
   missing art, and chart/table legibility.
2. Compare the shell with the complete source for duplicate native/shell text
   and unintended layout movement. If exact final-PPTX pixels exist, compare
   them with the source for displacement, font-metric drift, z-order changes,
   SVG fallback loss, color or gradient drift, and missing objects.
3. Inspect the deck contact sheet for repeated silhouettes, pacing, visual
   inconsistency, and accidental style changes.
4. Record actionable findings, fix the task-local source/compiler, regenerate
   the exact PPTX, and re-run only after all affected slides are rendered again.

## Vision ledger

Keep a machine-readable record next to the rendered evidence:

```json
{
  "vision_qa": "passed",
  "model": "vision-capable model identifier",
  "slides": [
    {
      "slide": 1,
      "verdict": "pass",
      "issues": []
    }
  ]
}
```

For each issue record `severity`, `category`, `observation`, and a concrete
location or object label. Use `critical`, `major`, or `minor`; do not pass a
slide with critical or major findings. Do not claim PowerPoint-specific
fidelity from a vision pass unless the inspected pixels came from Microsoft
PowerPoint itself.
