# Template and layout use

Use this lane only after the source PPTX has been inspected and every source
slide preview and object manifest is available. The source deck—not a generic
style preset—is the visual authority.

## Inspect before mapping

Record the source hash, slide size, masters, child layouts, placeholders,
themes, fonts, colors, inherited backgrounds, recurring chrome, and high-risk
native objects. Review every source slide at full size and as a contact sheet.

Build a source-slide → output-slide map. For each output slide, record its
communication job, selected source slide or layout, reuse mode, verified edit
targets, and any source slide intentionally omitted. Use
[`examples/template-following.example.json`](../examples/template-following.example.json)
as a starter, never as evidence for slide numbers or object IDs.

## Choose layouts by fit

Prefer the existing layout whose placeholders and safe content frame best fit:

- narrative role and required title/subtitle hierarchy;
- text, image, chart, or comparison regions;
- expected density and reading order;
- image aspect ratio and focal-point needs;
- inherited footer, numbering, logo, and source-note anchors.

Do not choose a layout only to create superficial variety. Reuse a strong
layout when the communication job repeats, while varying the content
silhouette inside its intended frame. Preserve the source aspect ratio; never
coerce a 4:3, portrait, or custom template to 16:9.

## Use the live template operations

Keep master/layout chrome and reusable template objects native. Choose
`use-layout` to create a fresh slide from the inspected source slide's actual
layout, then fill text and picture placeholders by the exact inspected
`placeholder_idx + placeholder_type`. Choose `duplicate-slide` when an
existing populated composition should be cloned and edited by verified shape
ID.

Do not cover inherited headers, footers, logos, numbering, or background art
with an unnecessary full-slide raster. Do not inject an arbitrary HTML shell
into a native layout or claim support for an edit that `python-pptx` cannot
preserve safely.

## Edit semantics

- Prefer substring `replace_text` when surrounding rich text must survive.
- Use `set_text` only for a complete verified target.
- For `use-layout`, use `placeholder_fills` rather than shape-ID `edits`.
- Replace an image without changing its frame, crop, fit, geometry, rotation,
  flips, or aspect lock unless the user requests a layout change.
- Use typed native chart, table, and placeholder operations exposed by the
  live catalog.
- Treat an empty edit list as preserve-only; add no hidden overlays.
- Preserve transitions, animations, relationships, custom XML, unsupported
  native objects, and untouched content.

## Verify lineage and rendering

Pass the completed inspect job and exact source hash to validation and preview.
Fail rather than silently losing master → layout → slide lineage, resolving an
unknown object ID, or leaving an unresolved placeholder. After publication,
reopen the exact output and confirm source mapping, slide count, size,
inherited chrome, native object behavior, and visual parity for every slide.
