# Inherited PPTX template contract

Read this only after `pptx_template(action="inspect")` returns the source
manifest and previews.

## Required sequence

1. Review every source slide and object.
2. Choose source frames and write a source-slide → output-slide map.
3. Copy the manifest's exact `sourceSha256` into the project.
4. Declare `output_slide`, `source_slide`, `narrative_role`,
   `reuse_mode: "duplicate-slide"`, and `edits` for every output slide.
5. List every unused source slide in `omitted_source_slides`.
6. Validate source hash, mapping completeness, object types, and edit targets.
7. Render the inherited preview and inspect it before composition.

Use [examples/template-following.example.json](examples/template-following.example.json)
only as a schema starter. Never invent source slide numbers or target IDs.

## Edit semantics

- Prefer `replace_text` when changing a substring inside a textbox so
  surrounding rich-text runs remain intact.
- Use `set_text` only when the complete verified target should be replaced.
- `replace_image` must preserve frame, crop, fit, geometry, rotation, flips,
  and aspect lock.
- Use typed native table-cell and chart-series operations for those objects.
- Add `speaker_notes` only when the request requires them.
- Treat `edits: []` as preserve-only: do not add overlays, hidden replacements,
  or new objects to that slide.

Reusing one source frame several times is allowed; each duplicate needs its own
explicit edit list. Composition must fail rather than silently losing source
master/layout lineage or leaving unresolved placeholders.
