# HTML/Tailwind new-deck contract
Read this after `artifact(action="catalog", format="pptx")` and visual-direction
selection. The live catalog is authoritative.

## Tool sequence

1. Create one project directory containing JSON, HTML, CSS, and local assets.
2. Call `validate` to enforce schema, path, asset, HTML, CSS, and network safety.
3. Call `preview` while the EvoFlux desktop WebView is connected.
4. Inspect every immutable PNG preview and resolve all errors.
5. Publish the accepted preview job to the final `.pptx` path.

## Project schema

Use schema version 4:

```json
{
  "schema_version": 4,
  "title": "Deck title",
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

Every path stays inside the project directory. HTML/CSS references declared
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

The desktop WebView produces the immutable visual preview and the flattened
shell. A thin OpenXML packer adds explicitly editable overlays and verifies the
PPTX can be opened with the expected slide count. There is no native-shape or
headless browser fallback.
