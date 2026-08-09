# High-fidelity new-deck contract

Read this after `artifact(action="catalog", format="pptx")` and visual-direction
selection. Treat the live catalog as authoritative.

## Tool sequence

1. Select `fidelity`, `hybrid`, or `native`; use `fidelity` unless the user asks
   for semantic editability.
2. Write the schema-version 2 project and required local HTML/assets inside one
   project directory, then call `validate`.
3. Call `preview`; inspect every slide image, layout finding, and visual-parity
   metric.
4. Correct the project and create a new preview until QA succeeds.
5. Call `publish` with the accepted preview job ID and final `.pptx` path.

## Static HTML contract

For `fidelity`, each slide's `visual_shell.html_path` is the complete visual
composition. Use an exact `1280px × 720px` viewport unless the project declares
another size. Set `html, body` to that size with zero margin and hidden
overflow. Use static HTML/CSS, inline SVG, data URLs, and project-relative local
images or fonts. Scripts, event handlers, iframes, forms, remote URLs, imports,
canvas, video, and audio are rejected. The backend uses bundled headless
Chromium with JavaScript and network access disabled.

Use `render_scale: 2` for final quality. The shell is embedded as one full-slide
PNG in PowerPoint. This is a deliberate quality-first representation: do not
claim that its internal text, charts, or shapes are semantically editable.

For `hybrid`, `html_path` contains only the non-editable visual shell. Add
native objects in `elements`, and put the desired complete composition in
`reference_html_path`. The backend renders the reference independently and
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

Prefer `fidelity` for gradients, complex typography, shadows, layered SVG,
glass effects, clipping, and compositions that already look correct in HTML.
Choose export-safe fonts from the bundled font pack; local font files must stay
inside the project directory. Use meaningful alt text for every visual shell
and image.

Use **EvoFlux** for any generator/edition branding visible in the design. Never
emit Codex logos, watermarks, edition labels, or generator credits; an upstream
repository name may appear only in attribution or when it is the subject.

## Visual quality

- Use composition, scale, whitespace, and contrast before adding boxes.
- Avoid dashboard grids unless the content is genuinely a dashboard.
- Keep body text generally 18–24 px or larger and titles 40–64 px.
- Build diagrams with clear reading order and meaningful edges.
- Use project assets or inline SVG instead of emoji icons.
- Never accept clipped text, broken images, accidental overlap, off-slide
  content, or failed parity evidence.

Put presenter guidance in `speaker_notes`. The backend renders every slide,
emits layout evidence, and compares the accepted preview to its HTML reference
before candidate acceptance. Without an independent PowerPoint/LibreOffice
round trip, report that limitation instead of treating structural success as
visual proof.
