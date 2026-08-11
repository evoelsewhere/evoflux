# PowerPoint slide DNA contract

Read this contract for every PPTX authoring or redesign task after framing the
request. Use
[`templates/powerpoint-slide-dna.json`](../templates/powerpoint-slide-dna.json)
as the format baseline, then instantiate a project-local `slide-dna.json` before
writing slide HTML or template edits. Treat this file as a design and
representation contract, not as audience-facing content.

## Build the deck DNA

Record these deck-level decisions:

1. `communication_job`: audience, decision, narrative outcome, language, and
   presentation duration;
2. `visual_signature`: mood, palette roles, type roles, spacing rhythm, image
   treatment, and motion policy;
3. `canvas`: aspect ratio, source dimensions, safe area, and export mapping;
4. `layout_family`: the finite set of silhouettes allowed in this deck and the
   reason each exists;
5. `representation_policy`: which object classes remain native, hybrid,
   flattened, preserved from a template, unsupported, or unverified;
6. `fidelity_target`: the required score, hard failures, render surfaces, and
   evidence paths;
7. `known_gaps`: every requested Office feature the current lane cannot create
   or verify faithfully.

For every slide, record at least:

```json
{
  "id": "decision-proof",
  "narrative_role": "evidence",
  "takeaway": "Retention improves after the activation milestone",
  "archetype": "data-story",
  "dominant_object": "comparison-chart",
  "reading_order": ["title", "chart", "annotation", "takeaway"],
  "density": "standard",
  "editable_intent": ["title", "annotation"],
  "flattened_intent": ["chart", "decorative-rule"],
  "source_ids": ["analysis-01"],
  "risk_flags": ["font-metric-drift"]
}
```

Keep one communication job and one dominant visual hierarchy per slide. Select
an archetype because it fits the reasoning job; never force content into a
layout merely to vary the deck.

## Preserve PowerPoint geometry

Use a 1280 × 720 CSS canvas for a 16:9 new deck. Map it to PowerPoint's
13.333333 × 7.5 inch slide at 96 CSS px per inch and 914400 EMU per inch. Map
CSS font pixels to points with `pt = px × 0.75`. Do not mix CSS pixels,
PowerPoint points, inches, and EMU without recording the conversion.

Keep critical content inside the DNA safe area. Preserve source slide size for
an inherited deck; never silently coerce 4:3, A4-like, portrait, or custom
slides to 16:9. Treat a wrong aspect ratio, off-canvas object, or background
that does not cover the complete slide as a hard failure.

## Choose the representation per object

Use the capability matrix in the baseline JSON. Apply these lane-specific
rules:

- **New HTML hybrid deck:** keep the complete visual composition in the shell.
  Make only uniform solid-color text and plain rectangular raster images native.
  Flatten rich text, semantic bullets, charts, tables, equations, SmartArt,
  SVG, masks, and effects unless the live artifact catalog explicitly adds a
  faithful native mapping.
- **Inherited template deck:** preserve native masters, layouts, themes,
  transitions, animations, object IDs, crops, relationships, and unsupported
  objects in place. Apply only typed edits declared by the live catalog. Do not
  rebuild an inherited slide as HTML to imitate it.

An editability request never overrides visual fidelity. Do not label an object
native or editable because it merely looks similar in one preview. Record the
degradation in `known_gaps` when PowerPoint semantics, accessibility, or
round-trip behavior cannot be retained.

## Resolve typography before layout

Declare the actual font files or an export-safe installed font stack. Record a
fallback for every role. Test representative Latin, Vietnamese, CJK, Arabic,
numeric, and symbol runs when those scripts occur in the deck. Preserve line
break intent without inserting manual breaks merely to disguise a metric
mismatch.

Use the baseline minimums unless a confirmed source template overrides them.
Shorten copy or change the layout before shrinking text. Treat title wrapping,
missing glyphs, clipped descenders, shifted bullets, changed line count, and a
font fallback that changes hierarchy as fidelity failures.

## Make the visual system complete

Define all semantic colors, not just a palette: canvas, primary ink, muted ink,
structure, emphasis, positive, warning, negative, data series, gridline, and
focus. Define type roles, spacing steps, radii, border weights, image crops,
chart grammar, table grammar, and source-note treatment.

Use at least three compatible slide silhouettes for decks longer than five
slides, while keeping common title, grid, footer, and source-note anchors.
Avoid repeated card grids, decorative controls, and dashboard chrome unless
the audience is explicitly reviewing a software interface.

## Close the render loop

Keep four distinct render surfaces in the QA ledger:

1. `source-preview`: the complete WebView render used to approve composition;
2. `flattened-shell`: the 2× shell with editable objects removed;
3. `reopened-plugin-preview`: the generated PPTX reopened and rendered by the
   built-in Documents preview engine;
4. `powerpoint-reference`: an optional Microsoft PowerPoint render when that
   application is available.

Do not call structural OpenXML round-trip a visual check. Compare the reopened
PPTX against the accepted source preview slide by slide. Read
[`pptx-fidelity-checklist.md`](pptx-fidelity-checklist.md) before accepting or
delivering a revision. Keep the six weighted assessments in a separate
project-local QA ledger; the runtime, not the author, awards the canvas and
reopened-render-parity points and enforces the observed score against the DNA
target.

## Extend, never replace, this baseline

When a style DNA such as the research-paper briefing applies, merge its visual
tokens, layouts, and density rules over this PowerPoint baseline. Keep this
contract's coordinate, representation, render-surface, scorecard, and failure
rules intact. For inherited templates, derive visual tokens from the inspected
source instead; the source master/layout/theme hierarchy remains authoritative.
