# Template and layout use

Use this reference only when an uploaded PPTX is the visual template. The
source deck—not a generic style preset—is the visual authority.

## Inspect before mapping

Record the source file hash, slide size, masters, layouts, placeholders,
themes, fonts, colors, inherited backgrounds, recurring chrome, notes, and
high-risk native objects. Render and review every source slide when a renderer
is available.

Build a source-slide-to-output-slide map. For each output slide, record its
communication job, selected source slide or layout, reuse mode, verified edit
targets, and any source slide intentionally omitted. Derive this map from the
actual deck; do not invent slide numbers, shape IDs, or placeholder indices.

## Choose layouts by fit

Prefer the existing layout whose placeholders and safe content frame best fit:

- narrative role and required title/subtitle hierarchy;
- text, image, chart, or comparison regions;
- expected density and reading order;
- image aspect ratio and focal-point needs;
- inherited footer, numbering, logo, and source-note anchors.

Do not choose a layout only for superficial variety. Reuse a strong layout when
the communication job repeats, while varying the content silhouette inside its
intended frame. Preserve the source aspect ratio; never coerce a 4:3, portrait,
or custom template to 16:9.

## Work within authoring-library limits

Create a slide from an actual source layout and fill verified placeholders by
`placeholder_format.idx` and placeholder type. Duplicate an existing populated
slide only when the package relationships and unsupported objects can be
preserved safely; `python-pptx` has no complete public clone API.

Keep master/layout chrome and reusable template objects native. Do not cover
inherited headers, footers, logos, numbering, or background art with an
unnecessary full-slide raster. Do not replace inherited template chrome with a
full-slide HTML shell. HTML/SVG may prototype or populate a redesigned content
region only when its shell stays inside the verified placeholder or content
frame. Do not claim support for an edit that the authoring library cannot
preserve.

## Edit conservatively

- Prefer targeted run or paragraph edits when surrounding rich text must stay.
- Replace an image without changing its frame, crop, geometry, rotation, or
  aspect behavior unless the user requests a layout change.
- Use native chart, table, text, and picture APIs only after inspecting the
  actual object and confirming the API supports the requested change.
- Treat transitions, animations, SmartArt, embedded objects, custom XML, and
  unsupported chart features as preserve-only package content.
- Snapshot package-part hashes and relationships before editing; review every
  changed part after saving.

## Verify lineage and rendering

Reopen the exact output and confirm slide count, size, master/layout lineage,
placeholder identity, inherited chrome, notes, and required text. Render every
slide with an available renderer and compare it with the source mapping. A
semantic render is useful evidence but not proof of PowerPoint fidelity. Fail
or disclose the limitation rather than silently losing an unsupported object,
resolving an unknown target, or leaving an unresolved placeholder.
