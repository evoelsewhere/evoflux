# HTML shell and editable text

Use this lane for a new deck or a deck derived from images or screenshots.
HTML/CSS owns composition; PowerPoint editability is added without rebuilding
the visual design as native shapes.

## Project contract

Start from [`examples/project.example.json`](../examples/project.example.json).
The project uses schema version 7, a 1280×720 canvas, one HTML fragment per
slide, optional project-local CSS, and declared local assets.

Each HTML file must have exactly one `data-slide-root`. Do not use scripts,
event handlers, remote or protocol-relative URLs, `@import`, forms, canvas,
iframe, video, or audio. Use static HTML/CSS, curated Tailwind utilities, SVG,
and `asset://<name>` URLs for declared assets.

## Representation model

The runtime produces two layers:

1. a high-resolution raster shell containing backgrounds, images, gradients,
   SVG, charts, diagrams, texture, masks, borders, shadows, and decoration;
2. native PowerPoint text frames for eligible DOM text.

During shell capture, editable glyphs are removed without changing layout.
The resulting text overlays must occupy the same bounds and must not expose a
second baked-in copy underneath. This keeps HTML/CSS fidelity while making the
copy practical to edit.

## Automatic editable text

```html
<h1
  data-pptx-name="Takeaway title"
  style="font-family: Arial, sans-serif"
>
  Activation predicts long-term retention
</h1>
```

The WebView automatically extracts eligible ordinary visible HTML text—such
as headings, paragraphs, list items, table cells, captions, and simple labels—
into native PowerPoint text frames when its styling can be reproduced. Do not
annotate every text node. Keep a logical paragraph in one DOM element, use an
export-safe available font, and avoid manual line breaks used only to conceal
font-metric mismatch. Safe inline run styling, bullets/numbering, padding,
alignment, and letter spacing are retained. `data-pptx-name` and
`data-pptx-role` are optional stable metadata for the generated overlay.

`data-pptx-editable="text"` is only an optional compatibility or selection hint
for text in a non-structural container; it is not required for ordinary text:

```html
<div
  data-pptx-editable="text"
  data-pptx-name="Metric label"
  style="font-family: Arial, sans-serif"
>42% retained</div>
```

Use the explicit art fallback when a text treatment belongs in the shell:

```html
<h1 data-pptx-text-mode="art" class="gradient-display">Signal, amplified</h1>
```

Retain text in the shell when its identity depends on gradient fill, clipping,
blend mode, path layout, extreme transform, complex shadow, or another effect
that the current catalog cannot reproduce. Mark that exception with
`data-pptx-text-mode="art"` and report it. Do not convert complex graphics,
charts, diagrams, tables, or icons to native PowerPoint primitives merely to
raise an editability count.

The runtime also keeps text flattened when it contains an embedded graphic or
is covered by a foreground element. Native text is painted above the shell, so
converting either case would change stacking or remove part of the artwork.
Every such fallback must appear in the automatic text-coverage ledger.

## Geometry and assets

For standard 16:9 output, 1280 CSS px maps to 13.333333 inches and 720 CSS px
maps to 7.5 inches. The runtime maps CSS font pixels to points at `pt = px ×
0.75`. Keep every editable box inside the canvas and allow width for font
metric differences.

Use CSS `object-fit` and `object-position` for image art direction in the
shell. The shell preserves crops, masks, radii, filters, alpha, and blend
effects exactly as rendered. Declare an image as a native editable object only
when the live artifact catalog explicitly supports its complete treatment.
At present, `data-pptx-editable="image" data-pptx-asset="<declared-key>"` is
limited to an uncropped declared raster using fill sizing with no mask, radius,
filter, transform, opacity, or blend effect; other imagery stays in the shell.

Before accepting a preview, ensure fonts have loaded, raster images decode,
assets resolve, and no animation or time-dependent state changes the render.

## Render loop

1. `validate` the schema-v7 project and its local paths.
2. `preview` every slide and inspect each at full size.
3. Inspect the shell with editable glyphs removed; it must be complete without
   gaps, duplicate text, or removal halos.
4. Inspect editable text names, bounds, font choices, line breaks, and layer
   order.
5. Publish the accepted immutable revision.
6. Reopen the exact PPTX through `artifact(action="inspect", format="pptx",
   source_path=...)` and compare every slide with its HTML preview.

A successful OpenXML reopen proves package structure only. Reject visible
baseline drift, fallback fonts, changed wrapping, duplicate shell text,
clipping, wrong z-order, or missing glyphs.
