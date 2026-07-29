---
name: pptx
description: "Create, inspect, or edit PPTX presentations with a narrative-first, design-token, native OpenXML workflow. Trigger whenever a slide deck, presentation, PowerPoint template, speaker notes, charts, or .pptx file is an input or deliverable."
---

# PPTX

Create PowerPoint decks with `python-pptx`, native charts/tables/shapes, and
targeted OOXML patches. The quality target is a designed presentation, not a
document split across slides. Use only the bundled Python toolchain.

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

`replace_image` is also supported with `file`; the replacement must use the
same media format. The editor patches only selected slide/media parts and
rejects changes to masters, layouts, and themes. Use `python-pptx` only when a
requested structural change cannot be expressed by this editor, and then
compare the before/after package and render every slide.

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
4. Assign every slide one explicit silhouette before writing slide copy:
   `hero`, `split`, `visual-left`, `comparison`, or `statement`. Declare which
   content belongs in each region and a maximum line count. Do not place
   arbitrary shapes first and try to make the content fit afterward.
5. Define design tokens: slide ratio, margins/grid, title/body sizes, fonts,
   background, primary/accent colors, chart palette, footer, and image style.
6. Build one reproducible Python script in a temporary directory. Use
   `layout_plan`, `LayoutGuard`, and strict `add_text` from
   `scripts/stylekit.py`; collision or text-fit errors require a layout/copy
   change, not an overlap exception.
7. Run structural QA and render every slide. Inspect every slide individually,
   repair issues, rerender, and deliver only the final PPTX.

Minimal layout-first pattern:

```python
plan = layout_plan(prs, "split", theme=theme)
guard = LayoutGuard(plan)
add_title(slide, takeaway, theme=theme, guard=guard)

text_region = plan.region("text")
add_text(
    slide,
    body,
    left=text_region.left,
    top=text_region.top,
    width=text_region.width,
    height=text_region.height,
    font=theme.body_font,
    size=theme.body_pt,
    color=theme.ink,
    max_lines=6,
    guard=guard,
)
visual_region = plan.region("visual")
add_image_cover(
    slide,
    image_path,
    left=visual_region.left,
    top=visual_region.top,
    width=visual_region.width,
    height=visual_region.height,
    guard=guard,
)
```

## Narrative and layout rules

- The title slide is minimal: title, concise subtitle, and only necessary
  metadata.
- Each slide has one job and one clear takeaway. Write audience-facing copy;
  never expose planning notes or generation instructions.
- Use an assertion as the title when possible ("Renewals drive 70% of growth"),
  not a generic label ("Revenue").
- Prefer fewer, stronger elements. If text does not fit, shorten it or change
  the layout before shrinking the type.
- Build the spatial skeleton before adding copy: reserve the title, content,
  visual, and footer zones; then fill only those zones.
- A slide is one composition, not a dashboard. Use flat alignment, whitespace,
  scale, imagery, and typography for hierarchy. Rounded rectangles are not the
  default container.
- Use at most two rounded shapes on a slide, and only when the rounded boundary
  has semantic meaning. Four or more rounded rectangles fail QA.
- Titles and banner copy must remain on one line. If they wrap, shorten the
  assertion or select another silhouette.
- Never solve overflow by stacking text boxes, placing copy over a chart/image,
  or reducing body text below 16 pt. Use `[allow-overlap]` in a shape name only
  for a visually inspected, intentional composition such as a labeled image
  overlay.
- Default floors for a new 16:9 deck: 38–44 pt slide titles, 22–28 pt
  subheads, 17–22 pt body, 11–13 pt notes/footers. Match a supplied template
  instead when one exists.
- Use consistent left/right margins and align shapes to a deliberate grid.
- Avoid repetitive card dashboards, ornamental pills, and dense UI styling.
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

Run:

```bash
python "{SKILL_DIR}/scripts/qa.py" output.pptx --render-dir /tmp/pptx-render
```

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
- slides with too many independent shapes or text blocks.

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
