# High-fidelity new-deck contract

Read this after `artifact(action="catalog", format="pptx")` and visual-direction
selection. Treat the live catalog as authoritative.

## Tool sequence

1. Select `fidelity`, `hybrid`, or `native`; use `fidelity` unless the user asks
   for semantic editability.
2. Write the schema-version 3 project and required local SVG/assets inside one
   project directory, then call `validate`.
3. Call `preview`; inspect every slide image, layout finding, and visual-parity
   metric.
4. Correct the project and create a new preview until QA succeeds.
5. Call `publish` with the accepted preview job ID and final `.pptx` path.

## Static SVG contract

For `fidelity`, each slide's `visual_shell.svg_path` is the complete visual
composition. Use an exact `1280 × 720` viewBox unless the project declares
another size. SVG must be static, self-contained, and project-local. Use SVG
gradients, filters, paths, text, and data URLs; do not reference scripts,
network URLs, remote fonts, HTML, canvas, video, or audio.

The bundled Rust SVG renderer rasterizes the shell at the declared project
size. It is embedded as one full-slide image in PowerPoint. This is a deliberate
quality-first representation: do not claim that its internal text, charts, or
shapes are semantically editable.

For `hybrid`, `svg_path` contains only the non-editable visual shell. Add native
objects in `elements`, and put the desired complete composition in
`reference_svg_path`. The backend renders the reference independently and
rejects the PPTX if changed-pixel ratio or mean absolute error exceeds the
declared thresholds. Do not duplicate visible labels in both the shell and
native overlay.

For `native`, omit `visual_shell` and use native `text`, `shape`, `image`,
`table`, and `chart` elements only.

## Authoring rules

Use one canvas size and visual system for the deck. Keep important content
inside consistent safe margins. Use one communication job, one takeaway title,
and normally no more than three major content groups per slide. Vary narrative
archetypes instead of repeating a card grid.

Prefer `fidelity` for gradients, complex typography, shadows, layered vector
art, clipping, and compositions that already look correct in SVG. Use
export-safe typefaces and meaningful alt text for every visual shell and image.

Use **EvoFlux** for any generator/edition branding visible in the design. Never
emit Codex logos, watermarks, edition labels, or generator credits; an upstream
repository name may appear only in attribution or when it is the subject.

## Visual quality

- Use composition, scale, whitespace, and contrast before adding boxes.
- Avoid dashboard grids unless the content is genuinely a dashboard.
- Keep body text generally 18–24 px or larger and titles 40–64 px.
- Build diagrams with clear reading order and meaningful edges.
- Use project assets or SVG paths instead of emoji icons.
- Never accept clipped text, broken images, accidental overlap, off-slide
  content, or failed parity evidence.

Put presenter guidance in `speaker_notes`. The bundled renderer renders every
slide, emits layout evidence, and compares the accepted preview to its SVG
reference before candidate acceptance. Round-trip open the final PPTX with an
independent OOXML reader; report if that verification was skipped.
