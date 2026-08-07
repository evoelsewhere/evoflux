# HTML-first hybrid presentation pipeline

EvoFlux authors new presentations from a controlled JSON + HTML/CSS project,
not from a low-level collection of PowerPoint layout slots. The design follows
the strongest part of `ningzimu/codex-ppt-skill`—a gated outline → style → sample
→ production → verification workflow—while removing its dependency on an image
generation model.

## Data flow

```text
communication job + user-confirmed visual direction
             ↓
1600×900 controlled HTML/CSS project
             ↓
validated base-template renderer or bounded raw HTML
             ↓
EvoFlux Desktop WebView render + DOM geometry inspection
             ↓
full preview PNG + editable-object-free background PNG
             ↓
background image + native text/shapes/images + notes
             ↓
verified hybrid PPTX
```

## Why hybrid

HTML/CSS is substantially better than direct PowerPoint coordinate programming
for gradients, SVG diagrams, editorial composition, grids, and visual iteration.
A slide-sized rendered background preserves unsupported effects exactly. In the
default `editable_mode="max"`, semantic text, solid cards, rounded rectangles,
ellipses, rules, and images are extracted from the DOM and rebuilt as individual
PowerPoint objects. `balanced` limits automatic promotion to text and images;
`explicit` only exports elements carrying `data-pptx-native` markers.

Promoted text retains computed inline runs rather than flattening its containing
element. Font family, size, weight, italic, underline, strike, color, tracking,
explicit line breaks, and list markers are recreated as editable PowerPoint
runs. The QA report records eligible object count, promoted object count,
coverage percentage, and rich-text run count; coverage below 85% is surfaced for
review instead of silently accepting a largely raster slide.

Authors use `data-pptx-raster` for gradients, clipping, filters, transformed
objects, text strokes, and decorative compounds that PowerPoint cannot reproduce
faithfully. The project JSON remains authoritative for that residual visual
layer.

## Security boundary

The project format rejects scripts, event handlers, iframes, forms, remote URLs,
CSS imports, executable CSS, and filesystem URLs. Images must be embedded as
`data:image` values or referenced through `asset://relative/path`; asset paths
are resolved inside the active workspace before the renderer sees them. The
sanitized document is sent only to the active task's in-app WebView over a
session-scoped local WebSocket.

## Verification contract

The desktop WebView checks each slide for canvas overflow, text overflow, broken
images, font floors, copy density, structural density, and accidental overlap
among elements marked `data-box`. `modern-screenshot` captures the preview,
raster background, and editable images in an isolated frame using that frame's
own document/window context. Any error prevents PPTX
composition. Warnings remain visible in
`.evoflux/pptx-html/<deck>/qa.json` for deliberate review.

Promoted text is also checked against `EXPORT_SAFE_FONTS`. Because a native run
carries a font *name* rather than pixels, a family the reader's PowerPoint lacks
is substituted and reflows over a background rendered with the original, so the
hybrid split only holds while the two agree. The check warns rather than blocks:
the authoring machine cannot know what the reader has installed.

This renderer is intentionally desktop-only. There is no system-browser,
headless-browser, or remote-service fallback; a render request without the
matching EvoFlux Desktop task fails closed.

Python owns the render geometry (canvas size and the export/preview pixel
ratios) and sends it with each request. The WebView keeps no copy, because a
geometry constant that drifts between the two languages breaks coordinates
silently and no test would catch it. Slides render concurrently up to
`RENDER_CONCURRENCY`; results are ordered by slide number, not by completion.

The exporter writes atomically, reopens the final file with `python-pptx`, and
checks slide count before publishing the artifact.

### Round-trip verification

Every check above runs on the HTML, so none of them sees the effect of the export
itself — a displaced native object or a substituted font produces a clean QA pass
and a wrong deck. When LibreOffice is available, `build_html_presentation`
therefore rasterises the written deck through the shared
`app/services/office/rendering.py` and compares each slide against its preview.

The comparison is a coarse grayscale signature, not a pixel diff: LibreOffice and
Chromium hint and antialias text differently, so only low-frequency structure is
comparable between them. Text that moved, vanished, or overlapped changes the
signature; rasterisation does not. Deviations are reported as warnings and every
measurement lands in `qa.json` under `round_trip`, so the threshold can be
retuned against real decks rather than trusted blindly. Without LibreOffice the
step records `skipped` and the build proceeds, keeping a developer-machine
dependency out of the critical path.

## Editable base templates

Slides can declare `template + content` instead of authoring raw HTML. EvoFlux
ships 21 deterministic base templates covering covers, section transitions,
typographic statements, metrics, processes, comparisons, timelines,
architecture, matrices, bar charts, tables, quotes, image stories, and closing
actions, plus seven scientific-defense layouts for paper overviews, problem
chains, contribution grids, annotated architectures, mechanisms, equations, and
research results. Each template owns a bounded content contract, escapes audience-facing
copy, enforces safe item counts, and emits semantic text plus native object
markers.

This separates two independent decisions: `style_preset` selects the deck's
visual language, while `template` selects the content-fit composition. The same
template therefore works across all 12 style systems without cloning fixed
masters. Raw HTML remains available for exceptional art direction.

## Built-in style systems

Style selection is a hard gate. The project schema has no fallback preset and
requires both `style_preset` and `style_confirmed: true`. The presentation agent
must ask the user to choose or confirm a visual direction before authoring or
rendering. The catalog recommends `scientific-defense` first for research and
evidence-heavy work, but never applies it silently. The prompt is stored in
English and localized dynamically to the user's current language.

The runtime includes 12 deck-level style presets adapted from the style taxonomy
and public visual briefs in
[`ningzimu/codex-ppt-skill`](https://github.com/ningzimu/codex-ppt-skill/tree/f2ed80372f65bb05fe62dd07979b239a17ac065d/skills/codex-ppt/references):
clean professional, creative magazine, e-ink magazine, data dashboard, retro flat
illustration, hand-drawn technical explanation, hand-drawn whiteboard, warm
handmade, scientific defense, consulting, party/government red, and teaching
courseware.

They are implemented as deterministic CSS visual systems rather than copied
slide images. Each preset defines color, typography, surface treatment, density,
recommended layout archetypes, and an avoid-list. A normal deck chooses one
`style_preset`; each slide then chooses the archetype that fits its narrative job.
This retains upstream's most important rule: visual identity remains stable while
slide silhouettes vary with content.

## Uploaded PPTX templates are a separate pipeline

When the user explicitly chooses an uploaded PPTX as the visual template,
EvoFlux does not convert it to HTML and does not rebuild a lookalike deck. The
`pptx_template` tool imports the original through `@oai/artifact-tool`, renders
and inventories every source slide, and emits stable inspect anchors for native
textboxes, shapes, images, tables, and charts.

The authoring plan maps every output slide to a source slide. Selected source
slides are duplicated in output order; unselected source slides are listed
explicitly. The worker correlates inspect anchors from the immutable source to
the corresponding inherited object on each duplicate, then applies only the
declared typed edits. Empty edit lists are preserve-only. The uploaded file is
mounted read-only and the output is always a new workspace file.

Before export, the pipeline verifies the source SHA-256, output slide count,
unresolved placeholders, and each slide's source master/layout lineage. A
lineage mismatch fails the build; there is no HTML, python-pptx, or blank-slide
fallback for this path. This separation keeps the HTML-first engine optimized
for new visual composition while making real client templates maximally
editable and structurally faithful.

The template worker requires Node.js and a built `@oai/artifact-tool`
entrypoint. Production environments may configure these explicitly with
`EVOFLUX_NODE_BIN` and `EVOFLUX_ARTIFACT_TOOL_ENTRYPOINT`. When either runtime
is unavailable, the tool reports the missing dependency and stops instead of
silently producing a lower-fidelity deck. Discovery and the worker subprocess
protocol live in `app/services/office/runtime.py`, shared with the XLSX and
DOCX pipelines; see `editable-office-pipelines.md` for the lookup order.
