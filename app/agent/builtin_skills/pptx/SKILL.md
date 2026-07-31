---
name: pptx
description: "Create, inspect, or edit PowerPoint presentations (.pptx), including slide decks, templates, speaker notes, and charts, with a narrative-first, design-token, native OpenXML workflow. Triggers on PPTX, PowerPoint, or slide."
---

# PPTX

Create new PowerPoint decks through the declarative `pptx_engine` tool. It
compiles validated layout/slot specifications into native charts, tables,
images, text, groups, notes, and transitions, then runs structural and visual
QA. Use the package-preserving OOXML editor for supplied templates. The quality
target is a designed presentation, not a document split across slides.

## Declarative engine contract

For a new deck, call `pptx_engine(action="catalog")` once to inspect the
available layouts, slots, block types, and capability matrix. Then call
`pptx_engine(action="compose", path="...pptx", spec={...})`. The model owns the
narrative, content, layout selection, and asset choices; the engine owns exact
geometry, text floors, native-object construction, rendering, and QA.

Do not write a free-form `python-pptx` coordinate script for normal deck
creation. Low-level helpers under `scripts/` are engine internals and an escape
hatch for a structural feature that the declarative schema cannot yet express.
SmartArt, media/OLE, and complex animation remain template-first preserve-only
capabilities and must never be approximated with basic shapes.

## Template-first contract

If any PPTX is supplied, editing a copied deck is the default. Do not create a
new `Presentation()` and imitate the source. A supplied deck is an executable
design system: its masters, layouts, theme, placeholder geometry, typography,
brand marks, notes, and relationships are authoritative.

Use the package-preserving editor before any high-level save:

```bash
python "{SKILL_DIR}/scripts/template.py" inspect template.pptx \
  --out /tmp/template-manifest.json
python "{SKILL_DIR}/scripts/template.py" apply template.pptx output.pptx \
  --plan /tmp/template-edit-plan.json
python "{SKILL_DIR}/scripts/template.py" verify template.pptx output.pptx \
  --plan /tmp/template-edit-plan.json
```

The JSON plan is a mutation map. Every edit must target an inspected stable
`slide` + `shape_id`; everything absent from the plan is preserve-only:

```json
{
  "edits": [
    {
      "slide": 2,
      "shape_id": 7,
      "action": "replace_text",
      "text": "Audience-ready title"
    },
    {
      "slide": 3,
      "shape_id": 12,
      "action": "replace_table_cell",
      "row": 1,
      "column": 2,
      "text": "42%"
    }
  ]
}
```

The editor also supports:

- `fill_placeholder` for inspected native placeholders;
- `replace_rich_text` with paragraphs, runs, bullets, levels, alignment,
  spacing, font, size, color, bold, italic, and underline;
- `replace_chart_data` with `categories` and named `series`; this changes the
  existing chart cache and embedded workbook without rebuilding the slide;
- `replace_image` with `file`; the replacement must use the same media format.

The editor patches only the selected slide, chart, workbook, or media parts
and rejects changes to masters, layouts, and themes. Use `python-pptx` only
when a requested structural change cannot be expressed by this editor, and
then compare the before/after package and render every slide.

## Workflow

1. Classify inputs as `deck to edit`, `fillable template`, `structural base`,
   `visual reference`, or `content source`. Never overwrite a source.
2. If a PPTX/template exists, inspect slide size, masters, layouts,
   placeholders, theme fonts/colors, notes, charts, and every source slide.
   Produce a slide-frame map (`output slide -> source slide -> editTargets`).
   Reuse its hierarchy and edit inherited elements in place. `editTargets: []`
   means preserve the entire source slide.
3. If creating from scratch, plan the communication job before code:
   audience, decision/action, narrative arc, slide sequence, visual approach,
   and one-sentence takeaway per slide.
4. Assign every slide one explicit silhouette from the engine catalog before
   writing slide copy. Declare which content belongs in each named slot and a
   maximum line count. Do not place arbitrary shapes first and try to make the
   content fit afterward.
5. Define design tokens: slide ratio, margins/grid, title/body sizes, fonts,
   background, primary/accent colors, chart palette, footer, and image style.
6. Build one declarative `PresentationSpec` and submit it to `pptx_engine`.
   Collect all returned preflight issues and repair them as a batch; collision
   or text-fit errors require a layout/copy change, not an overlap exception.
7. For functional symbols, use the curated vector catalog in
  `scripts/icons.py`, not generated raster icons or mixed icon families.
  After choosing names, validate all of them in one pass with
  `scripts/icons.py` and its `--check <icon>...` option before running the
  generator.
8. Route evidence to Office-native objects with `scripts/office_features.py`.
   Quantitative evidence becomes an editable chart, structured comparisons
   become a real table, photos use native crop/focal controls, and navigation
   uses native hyperlinks. Do not rebuild these as collections of rectangles.
9. Keep `render=true` for the final compose/validate call. Inspect every
   returned slide image individually, repair issues, rerender, and deliver only
   the final PPTX.

Minimal layout-first spec:

```json
{
  "title": "Decision-ready update",
  "layout": "split",
  "slots": {
    "text": {
      "type": "bullets",
      "items": ["Evidence first", "One clear decision"]
    },
    "visual": {
      "type": "image",
      "path": "assets/decision.jpg",
      "alt_text": "Team reviewing the decision"
    }
  }
}
```

Do not repair a generator with global regex substitutions. Helper signatures
must use their declared keyword names (`left`, `top`, `width`, `height`), and a
signature mismatch must be fixed at the specific call site. Never mass-rewrite
short parameter names such as `h` because they can also match inside `width`.

## Office-native feature routing

Use the richest editable PowerPoint primitive that matches the content:

- Trends, comparisons, distributions, and portfolio shares: `add_native_chart`.
  The chart keeps its embedded workbook, labels, axes, legend, and theme-aware
  series formatting. Do not draw bars or lines manually.
- Matrices, schedules, ownership, and status registers: `add_native_table`.
  Do not simulate a table with one rectangle and text box per cell.
- Photography, screenshots, and diagrams: `add_image_cover` with `focal_x`,
  `focal_y`, and `alt_text`; crop natively instead of stretching or baking the
  image into a slide screenshot.
- Repeated branded elements: edit the source master/layout/placeholders. Do not
  duplicate them as slide-level shapes.
- Rich editorial copy: `add_rich_text` for editable mixed-format runs, native
  bullets, hierarchy, and one-to-four text columns. Do not split every emphasis
  change into a separate text box.
- Simple processes: `add_grouped_process` creates an editable native group
  with connectors behind nodes. Complex topology: Graphviz or a sourced
  visual. Do not turn every concept into a card grid.
- Cross-slide pacing: `set_slide_transition` only when it improves continuity.
  For intentional object continuity, assign matching `set_morph_identity`
  values on adjacent slides and use the `morph` transition. Keep transitions
  restrained; never use animation to hide poor hierarchy.
- Interactive references: `set_shape_hyperlink`; accessibility:
  `set_accessibility` on meaningful charts, tables, images, and controls.
- Native gradients and restrained depth are available through
  `apply_gradient_fill` and `apply_soft_shadow`. They are accents, not a reason
  to add extra containers.

SmartArt, embedded video, complex animation timelines, and existing custom
chart features must be preserved through the template-first OOXML path. If
they already exist in a supplied deck, edit their data/text in place or leave
them untouched; never flatten or reconstruct them with basic shapes.

## PowerPoint capability matrix

Choose the route by editability and fidelity, not by whichever API is easiest:

| Capability | Create new | Edit supplied template | QA/preservation |
| --- | --- | --- | --- |
| Theme fonts/colors | `theme_from_presentation` or design tokens | inherit theme/master | inventory themes, masters, layouts |
| Placeholders | use source layout | `fill_placeholder` | report type/index and empty placeholders |
| Rich text/bullets/columns | `add_rich_text` | `replace_rich_text` | text fit, wrap, density |
| Charts + workbook | `add_native_chart` | `replace_chart_data` | chart/workbook inventory and series validation |
| Tables | `add_native_table` | `replace_table_cell` | native-table inventory |
| Photos/screenshots | `add_image_cover` with focal crop | `replace_image` | crop, clipping, media inventory |
| Groups/connectors | `add_grouped_process` | preserve/edit targeted child content | group/connector inventory |
| Hyperlinks/accessibility | native helpers | retain or patch target | hyperlink/alt-text counts |
| Gradients/shadows | native DrawingML helpers | preserve existing effects | OOXML inventory + Chromium preview |
| Transitions/Morph | `set_slide_transition`, `set_morph_identity` | preserve existing transition | transition/Morph inventory |
| SmartArt | start from a suitable template | preserve package parts | SmartArt-part inventory |
| Audio/video/OLE | insert only from a proven template workflow | preserve relationships/media | inventory; playback requires PowerPoint |
| Complex animations | author from a suitable template | preserve `p:timing` unchanged | animation-timeline inventory |

“Preserve” is a supported capability: for SmartArt, media, OLE, and complex
animation, structural fidelity is higher when EvoFlux leaves untargeted
package parts byte-identical than when it approximates them with shapes.

Example:

```python
from app.agent.builtin_skills.pptx.scripts.office_features import (
    add_native_chart,
    set_accessibility,
)

chart = add_native_chart(
    slide,
    ["Q1", "Q2", "Q3", "Q4"],
    {"Actual": [12, 18, 24, 31], "Plan": [14, 19, 23, 28]},
    left=visual_region.left,
    top=visual_region.top,
    width=visual_region.width,
    height=visual_region.height,
    kind="line",
    title="Actual growth moves ahead of plan",
    theme=theme,
    guard=guard,
)
set_accessibility(
    chart,
    title="Actual versus plan",
    description="Line chart comparing quarterly actual and planned growth.",
)
```

## Narrative and layout rules

- The title slide is minimal: title, concise subtitle, and only necessary
  metadata.
- Each slide has one job and one clear takeaway. Write audience-facing copy;
  never expose planning notes or generation instructions.
- Use an assertion as the title when possible ("Renewals drive 70% of growth"),
  not a generic label ("Revenue").
- Select a density profile before writing or laying out the slide:
  - `editorial`: keynote/storytelling slides with one dominant visual;
  - `executive-dense`: decision slides with several evidence blocks;
  - `operational`: plans, matrices, roadmaps, registers, and workstream views
    containing many atomic actions and metadata fields.
- Choose the profile from the content and audience, never by forcing all content
  into the editorial default. A supplied template or reference slide is the
  visual contract: infer its density, typography, grid, and repeated components.
- Build a content-completeness ledger before layout. Preserve every required
  workstream, action, KPI, owner/PIC, target, date, dependency, and status.
  Do not delete or collapse fields merely to create more whitespace.
- Prefer fewer, stronger elements only in the editorial profile. Dense profiles
  should preserve useful information atoms and create hierarchy through a
  micro-grid, repeated rows, dividers, labels, and compact semantic icons.
- Build the spatial skeleton before adding copy: reserve the title, content,
  visual, and footer zones; then fill only those zones.
- Editorial slides are one composition, not a dashboard. Operational slides may
  use structured repeated containers, but the container must encode hierarchy;
  avoid decorative card soup and oversized corner radii.
- Use rules, alignment, whitespace, grouping, and flat borders before adding a
  rounded container. Profile-aware QA allows repeated operational panels but
  still flags excessive corner treatments.
- Titles and banner copy must remain on one line. If they wrap, shorten the
  assertion or select another silhouette.
- Never solve overflow by stacking text boxes, placing copy over a chart/image,
  or shrinking below the selected profile's minimum. Use `[allow-overlap]` in a
  shape name only for a visually inspected, intentional composition such as a
  labeled image overlay.
- Default 16:9 typography:
  - `editorial`: 38–44 pt title, 22–28 pt subhead, 17–22 pt body;
  - `executive-dense`: 28–34 pt title, 14–18 pt section, 10–14 pt body,
    7.5–10 pt metadata;
  - `operational`: 24–30 pt title, 12–16 pt section, 8–11.5 pt body,
    7–9.5 pt metadata.
  Match a supplied template when one exists.
- Use consistent left/right margins and align shapes to a deliberate grid.
- Operational slides should use nested grids: pillar → objective → action row →
  metadata. Keep row heights, gutters, icon sizes, label positions, and
  baselines consistent across repeated components.
- Avoid ornamental pills and decorative UI styling.
- Use icons as semantic labels, not decoration. Profile-aware QA permits more
  icons in dense operational slides. Keep one icon family throughout the deck;
  compact glyphs may be 0.18–0.38 inch when their strokes remain legible.
- Use the built-in Lucide subset for UI/business symbols. It is a curated ISC
  vector catalog, recolorable before insertion and convertible to PowerPoint
  shapes in modern Office. Use image generation for illustrative imagery, not
  for icons, logos, arrows, badges, or interface glyphs.
- Use visual assets when they clarify the idea. Crop deliberately and do not
  stretch images.
- Use native PowerPoint charts and tables so the result stays editable. Chart
  titles, axes, units, labels, legends, and source notes must agree with data.
- Build connectors before nodes for diagrams so edges remain behind shapes.
- Put source URLs for researched claims and assets in speaker notes.

## Template and edit rules

- Preserve masters, layouts, placeholders, notes, animations, theme parts, and
  relationships unless the user explicitly asks to change them.
- Default every inherited object to `keep`. Rewrite, replace, or delete it only
  when the mutation map says so.
- Reuse an existing source slide/frame when possible. Never replace a branded
  template slide with a screenshot or a visually similar reconstruction.
- Keep inherited font family, size, weight, color, spacing, and alignment.
  Shorten or remap content before shrinking typography.
- Fill or deliberately remove every inherited content placeholder. Do not
  silently delete date, footer, or slide-number placeholders.
- Prefer changing text, data, and local formatting in a copied deck. Do not
  flatten the deck into screenshots.
- Re-render representative descendants after any master/layout change.
- For unsupported `python-pptx` features, patch only the smallest OOXML part
  and validate the package again.

## Required QA

For new decks, use `pptx_engine(action="validate", path="output.pptx",
render=true)`. The compose action already runs the same gate when `render=true`.

For a template edit, include the unmodified source:

```bash
python "{SKILL_DIR}/scripts/qa.py" output.pptx \
  --render-dir /tmp/pptx-render --compare-to template.pptx
```

The structural gate rejects missing slides, out-of-canvas objects, broken
charts, and placeholder residue. Visual QA uses the bundled Chromium OpenXML
renderer, not LibreOffice. It emits one PNG per slide, checks DOM clipping and
canvas overflow, and reports `engine: chromium-openxml` with `confidence:
medium`. Treat image diffs and overflow heuristics as prompts for full-size
visual inspection, not proof of Microsoft PowerPoint pixel parity.

The layout gate also reports:

- text boxes whose estimated copy exceeds their geometry;
- one-line titles likely to wrap;
- text or content shapes overlapping by at least 12% of the smaller item;
- excessive rounded-card/UI composition;
- mixed icon families, raster icons, illegibly small icons, or icon overload;
- slides with too many independent shapes or text blocks.

Decks of five or more slides must include at least one native chart, table, or
non-icon picture. Shape-only decks fail QA by default; use
`--allow-shape-only` only when that treatment is an explicit design decision
you can explain in the final response.

The report includes `office_feature_summary`, per-slide editable-object counts,
and a package-wide `powerpoint_features` inventory for masters, layouts,
themes, charts, embedded workbooks, SmartArt parts, audio/video, notes,
comments, OLE objects, transitions, Morph, animation timelines, placeholders,
gradients, shadows, hyperlinks, and groups. Embedded media is structurally
preserved; Chromium QA explicitly warns that it cannot validate playback. A
deck of five or more slides with no chart, table, or non-icon picture receives
a shape-only warning.

Search and insert the curated icon catalog:

```bash
python "{SKILL_DIR}/scripts/icons.py" "growth analytics"
```

Validate every selected icon together before building so one run reports all
unsupported names:

```bash
python "{SKILL_DIR}/scripts/icons.py" --check trending-up chart-line shield-check
```

```python
from app.agent.builtin_skills.pptx.scripts.icons import add_icon

add_icon(
    slide,
    "trending-up",
    left=Inches(8.5),
    top=Inches(2.1),
    size=Inches(0.7),
    color=theme.accent,
    guard=guard,
)
```

When `--compare-to` is supplied, unchanged template design debt is baselined;
new or worsened overlap, overflow, density, and rounded-card issues still fail.

For a template edit, both `template.py verify` and `qa.py` must pass. A valid
deck with unexplained master/layout/theme or non-target slide changes is still
a failed edit.

Inspect every rendered slide at full size and confirm:

- no unintended overlap, clipping, wrapping, or off-canvas content;
- no unresolved placeholders, empty slides, duplicated accidental titles, or
  inconsistent footers;
- images are sharp and cropped correctly;
- chart values, labels, colors, notes, and sources are correct;
- the deck tells a coherent story from first slide to final action.

If the bundled Chromium runtime is unavailable, the report explicitly falls
back to `engine: structural-only`; disclose that visual QA could not be
completed.
