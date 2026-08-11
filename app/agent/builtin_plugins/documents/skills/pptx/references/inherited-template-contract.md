# Inherited PPTX template contract

Read this only after `artifact(action="inspect", format="pptx",
source_path=...)` returns a completed inspect job, source manifest, and
previews.

## Required sequence

1. Review every source slide and object.
2. Choose source frames and write a source-slide → output-slide map.
3. Copy the manifest's exact `sourceSha256` into the project.
4. Declare `output_slide`, `source_slide`, `narrative_role`,
   `reuse_mode: "duplicate-slide"`, and `edits` for every output slide.
5. List every unused source slide in `omitted_source_slides`.
6. Validate source hash, mapping completeness, object types, and edit targets.
7. Pass the inspect job ID to `validate` and `preview` so the durable manifest
   is reused.
8. Inspect every rendered slide before publishing the accepted revision.

Use [../examples/template-following.example.json](../examples/template-following.example.json)
only as a schema starter. Never invent source slide numbers or target IDs.

## Edit semantics

- Prefer `replace_text` for a substring so surrounding rich-text runs survive.
- Use `set_text` only when the complete verified target should be replaced.
- `replace_image` must preserve frame, crop, fit, geometry, rotation, flips,
  and aspect lock.
- Use typed native table-cell and chart-series operations for those objects.
- Add `speaker_notes` only when required.
- Treat `edits: []` as preserve-only; add no overlays or hidden replacements.

Reusing one source frame is allowed; each duplicate needs its own explicit edit
list. Preview must fail rather than silently losing master/layout lineage or
leaving unresolved placeholders.
