---
name: pptx
description: Create, redesign, render, and verify presentation decks with EvoFlux's HTML-first hybrid PowerPoint pipeline. Triggers on PPTX, PowerPoint, slide, slides, presentation, or pitch deck.
---

# PowerPoint authoring

Use this skill whenever the deliverable is a presentation. It adapts the useful
workflow discipline from `ningzimu/codex-ppt-skill`—outline, visual direction,
representative sample, per-slide production, assembly, and verification—but it
does not depend on an image-generation model. The visual source of truth is
controlled HTML/CSS rendered by the EvoFlux Desktop WebView.

For a new deck, the result is an editable-first hybrid PPTX:

- complex backgrounds, diagrams, SVG, gradients, and decoration are rendered
  pixel-stably into each slide background;
- semantic text, common cards, rules, and images are automatically exported as
  individual editable PowerPoint objects in the default `max` mode;
- explicit `data-pptx-native="text|shape|line|image"` markers cover custom
  elements, while `data-pptx-raster` keeps complex effects pixel-stable;
- speaker notes and source URLs stay in the PowerPoint file;
- Desktop WebView geometry checks must pass before the PPTX is written.

For an uploaded PPTX that the user explicitly identifies as the visual
template, use the separate inherited-template workflow below. It edits a copy
of that actual deck and does not route through HTML.

## Choose the authoring path first

- New deck or a screenshot/image reference: use `pptx_html` and resolve the
  visual direction using the style rule below.
- Uploaded PPTX explicitly requested as the visual template: use
  `pptx_template`. The chosen PPTX itself is the style confirmation, so do not
  ask the generic style question.
- Uploaded PPTX with an ambiguous role: ask whether it is a visual template or
  only a content source before authoring.

Never use `pptx_html`, python-pptx, or fresh blank slides as a fallback for an
uploaded-template request. If inherited editing cannot preserve the source
master/layout, fail clearly and ask for a different template or narrower edit.

## Required workflow

Keep this checklist in the working context:

```text
Presentation workflow
- [ ] 1. Understand the communication job and audience
- [ ] 2. Honor the supplied visual direction, or call `ask_user` once if absent
- [ ] 3. Draft a slide-by-slide story outline
- [ ] 4. Create the JSON project and validate it
- [ ] 5. Render one representative sample slide
- [ ] 6. Inspect the sample image and correct it
- [ ] 7. Render all slides and resolve QA errors
- [ ] 8. Compose the PPTX and hand off preview/download
```

Do not jump straight from the request to a full deck unless the user explicitly
asks to skip the sample gate. If the user supplied a reference slide, infer its
design language but improve hierarchy and density instead of tracing every box.

## Visual-direction rule for new decks

Treat the user's visual direction as confirmed whenever the request describes
a recognizable design language, even if it does not use a built-in preset ID.
Colors, typography, tone, density, audience, layout references, brand rules, a
reference image, or phrases such as "enterprise technology" are valid style
direction. Map that direction to the closest `style_preset`, preserve the
user's stated constraints, set `style_confirmed: true`, and continue without
asking the user to approve your internal preset mapping. Never ask the user to
repeat or reconfirm style information already present in the request.

Only ask about style when the request contains no meaningful visual direction,
or when two genuinely different interpretations would materially change the
deck. In that case, call the `ask_user` tool, offer a short,
job-aware set of options in the user's current language, and await its result.
Batch any other blocking presentation questions, such as missing brand assets,
into the same `ask_user` call. After the tool returns, resume outline,
authoring, rendering, and composition in the same run.

Never send a plain assistant message asking the user to choose a style, never
end the run while waiting for a separate chat reply, and never replace
`ask_user` with prose such as "please confirm". Put `scientific-defense` first
as the recommended general option for research, technical, thesis, or
evidence-heavy decks; other useful options include Clean Professional,
McKinsey-style Consulting, Data Dashboard, Teaching Courseware, and Creative
Magazine.

Once the direction is supplied either in the original request or through
`ask_user`, set both `style_preset` and `style_confirmed: true` at the project
root. The schema intentionally has no silent style default and rejects projects
that omit either field.

## Uploaded PPTX template workflow

Keep this checklist in the working context when the user says to use an
uploaded PPTX as the template:

```text
Inherited template workflow
- [ ] 1. Confirm the upload is the visual template (the user's request may do this)
- [ ] 2. Inspect every source slide and object
- [ ] 3. Review the source previews and choose source slide frames
- [ ] 4. Write the source-slide → output-slide map with exact edit targets
- [ ] 5. Validate source hash, omitted slides, and object types
- [ ] 6. Render the inherited preview and inspect it visually
- [ ] 7. Compose only after lineage and placeholder QA pass
```

First load and call the deferred `pptx_template` tool.

1. `pptx_template(action="catalog")` returns the project schema and invariants.
2. `pptx_template(action="inspect", source_pptx="<upload>.pptx")` imports the
   actual deck, renders every source slide, and writes `template-manifest.json`
   plus `template-inspect.ndjson`. Review all source previews. Use object IDs,
   names, text, and slide numbers from the manifest; never invent target IDs.
3. Write a JSON map using the manifest's `sourceSha256`. Every output slide must
   declare `output_slide`, `source_slide`, `narrative_role`,
   `reuse_mode: "duplicate-slide"`, and `edits`. Explicitly list every unused
   source slide in `omitted_source_slides`. A starter is in
   `examples/template-following.example.json`.
4. `pptx_template(action="validate", source_pptx="...", project_path="...",
   manifest_path="...")` checks the immutable source hash, complete mapping,
   and type-safe targets.
5. `pptx_template(action="render", ...)` duplicates the selected source slides,
   applies the edits to inherited objects, and returns preview images. Inspect
   them before publishing.
6. `pptx_template(action="compose", ..., output="...pptx")` exports only if
   every output slide still inherits the source master/layout and no unresolved
   placeholder remains.

Prefer `replace_text` over `set_text` when changing only part of a textbox; it
retains surrounding rich-text runs. `replace_image` preserves the existing
frame, crop, fit, geometry, rotation, flips, and aspect lock. Native table cells
and chart series remain editable through their typed operations. Set
`speaker_notes` on an output slide only when the request requires it.

`edits: []` means preserve-only. Do not add text, charts, images, panels,
overlays, or hidden replacements to that slide. Reusing one source frame
multiple times is allowed: each duplicate receives its own edit list.

## New-deck tool contract

First load and call the deferred `pptx_html` tool.

1. `pptx_html(action="catalog")` returns the JSON schema, built-in classes,
   markers, 21 editable base templates, restrictions, and the 12 built-in visual
   systems. After choosing a direction, call
   `pptx_html(action="catalog", style_preset="...")` for its exact palette and
   `pptx_html(action="catalog", base_template="...")` for one template's content
   contract and editable features.
2. Write a UTF-8 JSON project inside the workspace. A working starter lives at
   `examples/project.example.json` in this skill.
3. `pptx_html(action="validate", project_path="...")` validates structure and
   security before browser work.
4. `pptx_html(action="render", project_path="...", slide_numbers=[N])` returns
   the sample as an image. Visually inspect it; never assume render success means
   design success.
5. After the sample is sound, render all slides. Fix every `error` in `qa.json`.
   Warnings require judgment; acknowledge any warning deliberately retained.
6. `pptx_html(action="compose", project_path="...", output="...pptx")` performs
   full render + QA and only writes the PPTX if error-free.

## Project authoring rules

Each slide's `html` is the inner content of a fixed 1600×900 `.slide` element.
Use absolute positioning when the composition needs art direction; use the
built-in grid/flex classes for predictable editorial layouts.

Set one confirmed deck-level `style_preset`; never infer it silently. Built-ins adapted from the upstream style
library are: `clean-professional`, `creative-magazine`, `e-ink-magazine`,
`data-dashboard`, `retro-flat-illustration`, `handdrawn-technical`,
`handdrawn-whiteboard`, `warm-handmade`, `scientific-defense`, `mckinsey`,
`party-government-red`, and `teaching-courseware`. Use slide-level overrides
only for an intentional diagnostic gallery; a normal deck keeps one identity.

Presets are visual systems, not fixed masters. Choose a different recommended
archetype for each narrative role and avoid repeating one silhouette on adjacent
slides. Reusable preset classes include `preset-tag`, `preset-display`,
`preset-stage`, `preset-panel`, `preset-note`, `preset-number`, `preset-rule`,
and `preset-grid`.

### Base templates first

Prefer `template + content` over raw `html`. The base renderer escapes text,
validates item counts, chooses bounded geometry, and emits native-object markers
consistently. Use raw HTML only when no base template fits the slide's narrative
job.

Built-in template IDs are: `cover-split`, `section-divider`,
`typographic-statement`, `metric-story`, `process-flow`, `comparison`,
`timeline`, `architecture-layers`, `decision-matrix`, `bar-chart`, `data-table`,
`quote`, `image-story`, and `closing-actions`.

For research and technical-defense decks, use the specialized editable family:
`research-paper-overview`, `research-problem-chain`,
`research-contribution-grid`, `research-architecture-annotated`,
`research-mechanism`, `research-equation-explainer`, and
`research-results-summary`. These layouts reproduce the compact navy/white
academic grammar—numbered reasoning, technical structures, evidence columns,
equations, tables, and restrained red conclusions—without rasterizing the
common content objects. See
`examples/scientific-defense-gallery.example.json` for all seven contracts.

```json
{
  "id": "metrics",
  "title": "Three measures explain the result",
  "kind": "data",
  "template": "metric-story",
  "content": {
    "kicker": "Performance",
    "metrics": [
      {"label": "Activation", "value": "68%", "detail": "+8 pts"},
      {"label": "Time to value", "value": "2.3d", "detail": "-1.7 days"},
      {"label": "Retention", "value": "91%", "detail": "Stable"}
    ],
    "insight": "The intervention improved speed without reducing retention."
  }
}
```

Template slides must not also provide `html`. The validator rejects unknown
fields, invalid item counts, malformed tables, negative chart values, remote
image URLs, and content that exceeds the bounded project contract. A complete
14-slide general example lives at `examples/template-gallery.example.json`.

Set `editable_mode` at the project root. Use `"max"` unless a supplied visual
must be preserved with unusual CSS. `"balanced"` auto-promotes text and images
but requires explicit shape markers; `"explicit"` preserves the old marker-only
behavior.

In `max` mode, semantic elements (`h1`–`h6`, `p`, `li`, `blockquote`, table
cells), `<img>` elements, `.panel`, `.step`, `.rule`, and regions carrying
`data-box` become native automatically. Explicit markers are still useful when
an element has no recognized semantic class:

```html
<h1 class="title" data-pptx-role="title">
  A clear assertion, not a topic label
</h1>
<div data-box data-pptx-shape="roundRect">Editable card</div>
<div data-pptx-native="line"></div>
<svg data-pptx-native="image" viewBox="0 0 100 100">...</svg>
```

The exporter removes promoted objects during background capture and recreates
them at browser-computed coordinates. Solid fills, borders, rounded rectangles,
ellipses, rules, raster images, and captured SVG elements stay individually
selectable. CSS gradients, clipping, filters, transformed shapes, text strokes,
and decorative compounds should use `data-pptx-raster`; they stay in the visual
background instead of being approximated badly.

For large display titles, use explicit `<br>` elements when the line break is
part of the art direction. Browser and PowerPoint font metrics can differ; an
explicit break preserves the intended rhythm across both renderers.

Editable text keeps its font *name*, not its rendered pixels, so a family the
reader's PowerPoint lacks gets substituted and reflows over a background that was
rendered with the original. QA warns with `font_not_export_safe` when promoted
text uses a family outside the export-safe set (Aptos, Calibri, Cambria, Segoe
UI, Arial, Times New Roman, Georgia, Tahoma, Trebuchet MS, Verdana, Consolas,
Courier New). Either switch families or mark the element `data-pptx-raster` to
keep a distinctive face as pixels.

Add `data-box` to peer-level structural regions such as panels, columns, cards,
and diagram nodes. In `max` mode this both enables collision QA and makes a
supported solid region an editable PowerPoint shape. For intentional overlap,
add `data-overlap="allow"` to one region. Use `data-qa-ignore` only for purely
decorative objects and never to hide real text overflow.

Workspace images and SVG files must use `asset://relative/path`. Remote URLs,
scripts, iframes, forms, imported CSS, executable attributes, and filesystem URLs
are rejected. Prefer inline SVG and CSS geometry for diagrams; they remain sharp
in the rendered background and need no image model.

## Visual quality bar

- One communication job per slide. Titles should state the takeaway.
- Use composition, scale, whitespace, and contrast before adding boxes.
- Avoid dashboard-like grids unless the content is genuinely a dashboard.
- Use at most three major content groups on a normal slide.
- Body copy should generally be 18–24 px or larger; titles 44–72 px.
- Keep text concise. The configured word limit is a warning threshold, not a
  target to fill.
- Vary the rhythm across the deck: cover, assertion, process, evidence,
  comparison, architecture, and closing slides should not share one repeated
  card template.
- Build diagrams with a clear reading order and meaningful relationships.
- Do not use emoji as icons. Use inline SVG, CSS shapes, or workspace assets.
- Never deliver a slide with clipped text, broken images, accidental overlaps,
  or content outside the 1600×900 canvas.

## Sources and notes

Put presenter guidance in `speaker_notes`. Put traceable URLs or source labels in
the slide's `sources` array. The exporter appends them to notes under `[Sources]`.
Do not place raw citations across the visual surface unless the audience needs
them there.

## Round-trip verification

Every other check inspects the HTML before export. When LibreOffice is available,
`build` additionally rasterises the written deck and compares each slide against
the preview the WebView produced, recording the measured difference per slide in
`qa.json` under `round_trip`. A `round_trip_drift` warning means the exported
slide no longer matches its design: open both images named in the message and
look before shipping. A substituted font or a displaced native object is the
usual cause. Without LibreOffice the step reports `skipped` and the deck still
builds, so treat the absence of drift warnings as evidence only when
`round_trip.status` is `completed`.

## Final handoff

Report the output path, slide count, QA status, warning count, and editable
object counts split by text, shape, and image. State plainly which complex
effects remain in the pixel-stable background, and whether round-trip
verification ran or was skipped.
