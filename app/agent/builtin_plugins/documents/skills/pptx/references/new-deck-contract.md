# HTML/Tailwind new-deck contract
Read this after `artifact(action="catalog", format="pptx")` and visual-direction
selection. The live catalog is authoritative.

## Tool sequence

1. Create one project directory containing project JSON, `slide-dna.json`,
   `qa-ledger.json`, HTML, CSS, and local assets. Copy and adapt the complete
   bundled [Slide DNA example](../examples/slide-dna.json) and
   [QA ledger example](../examples/qa-ledger.json); the abbreviated project
   example below is not a substitute for either schema.
2. Call `validate` to enforce the project and Slide DNA schemas, paths, assets,
   HTML, CSS, representation policy, and network safety.
3. Call `preview` while the EvoFlux desktop WebView is connected.
4. Inspect every immutable PNG preview and resolve all errors.
5. Build the `.pptx`; publication succeeds only after the exact output is
   reopened, rendered, and passes the Slide DNA raster-parity thresholds.

If `artifact` or the desktop WebView is unavailable, stop at a locally
schema-valid draft. Run
`python scripts/validate_slide_project.py /absolute/path/to/project.json` from
the PPTX skill directory. Record every render surface as `unverified`; never
infer a visual score from OpenXML structure or an unofficial harness.

## Project schema

Use schema version 6 and point `dna_path` and `qa_ledger_path` at project-local
files:

```json
{
  "schema_version": 6,
  "title": "Deck title",
  "dna_path": "slide-dna.json",
  "qa_ledger_path": "qa-ledger.json",
  "width": 1280,
  "height": 720,
  "slides": [
    {
      "id": "opening",
      "html_path": "slide-01.html",
      "style_paths": ["slide-01.css"],
      "assets": { "hero": "assets/hero.jpg" },
      "speaker_notes": "[Sources]\n- https://example.com"
    }
  ]
}
```

Every path, including DNA, QA ledger, and QA evidence, stays inside the project
directory and must exist. The QA ledger contains each of the six baseline
scorecard dimensions exactly once. Only `verified` entries may award points.
The runtime replaces any declared canvas and reopened-parity scores with its
own render evidence and rejects an observed total below the DNA target. The DNA
must define all required deck and slide fields, match project slide IDs
one-to-one, declare the baseline token groups and representation statuses, and
set a fidelity target of at least 90. HTML/CSS references declared
assets as `asset://hero`; never use filesystem, HTTP, protocol-relative, or CDN
URLs. Each HTML file is a fragment with exactly one `data-slide-root` element.

## Tailwind and CSS

The renderer supplies a curated build-time Tailwind utility set for layout,
spacing, typography, borders, radius, shadows, opacity, filters, and blend
modes. Unknown utilities do not compile at runtime. Put custom art direction
in project-local static CSS. Inline style is allowed, but scripts, event
handlers, `@import`, executable URLs, forms, canvas, iframe, video, and audio
are rejected.

Use HTML/CSS for the complete visual composition: editorial typography,
gradients, clipping, photo crops, texture, charts rendered as static visuals,
and coherent SVG icon assets. Build one composition with hierarchy and scale;
do not default to repeated UI cards.

## Selective PowerPoint editability

HTML is always the visual source of truth. Mark only objects that PowerPoint
can reproduce without visible drift.

```html
<h1 data-pptx-editable="text" data-pptx-name="Title">
  A direct audience-facing claim
</h1>
<img
  src="asset://hero"
  data-pptx-editable="image"
  data-pptx-asset="hero"
  alt="Product photograph"
/>
```

Editable text must use a solid color, one uniform inline style, normal letter
spacing/case/opacity/blending, no transform/filter/text shadow/clipping, and an
export-safe font such as Arial or Aptos. Stylized display type, gradient text,
masks, rotated labels, SVG icons, charts, complex diagrams, and decorative
detail remain flattened. Raster images may be editable only when they use a
plain rectangular `object-fit: fill` frame without crop or effects; SVG stays in
the shell.

When an explicitly editable element uses unsupported CSS, the renderer keeps
it visually correct in the shell and emits a warning. Never duplicate the same
visible content in the shell and native overlay.

## Visual quality

- Design at exactly 1280×720.
- Use at least 50pt-equivalent deck titles, 35pt slide titles, 24pt subheads,
  and 16pt body text unless a confirmed template says otherwise.
- Keep one communication job and one takeaway title per slide.
- Vary adjacent slide silhouettes.
- Reject clipped content, broken assets, placeholder copy, unreadable contrast,
  and editable elements outside the canvas.
- Put externally sourced claims and assets in a `[Sources]` notes block.

The desktop WebView produces the accepted source preview and flattened shell.
A thin OpenXML packer adds explicitly editable overlays. The built-in PPTX
renderer then reopens the exact output into `reopened-previews`, compares each
slide with the accepted source preview, and records per-slide and deck-median
parity. The structural OpenXML reopen is recorded separately and never counts
as visual evidence. Microsoft PowerPoint reference rendering remains an
explicitly unverified fourth surface unless it is supplied independently.
