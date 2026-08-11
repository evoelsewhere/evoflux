# Academic engineering blueprint style

Use this style for technical research briefings, engineering architecture
reviews, thesis defenses, and paper walkthroughs when the requested direction
is the measured blue-and-white Office-like montage: dense diagrams, numbered
reading rails, compact evidence panels, and one explicit takeaway per slide.
For a looser editorial research deck, use the research-paper briefing style
instead.

## Required resources

Merge
[`templates/academic-engineering-blueprint-dna.json`](../templates/academic-engineering-blueprint-dna.json)
over the mandatory
[`templates/powerpoint-slide-dna.json`](../templates/powerpoint-slide-dna.json)
baseline. Copy
[`templates/academic-engineering-blueprint.css`](../templates/academic-engineering-blueprint.css)
into the project and adapt the
[`architecture example`](../templates/academic-engineering-blueprint.example.html).
The style file is an overlay, not a complete project-local Slide DNA.

The project itself remains schema version 6 and points at merged, project-local
DNA and QA files:

```json
{
  "schema_version": 6,
  "dna_path": "slide-dna.json",
  "qa_ledger_path": "qa-ledger.json",
  "width": 1280,
  "height": 720
}
```

## Measured frame

- Canvas: `1280 × 720`, white.
- Title anchor: `x=28, y=18`; one line in navy `#002E7E`.
- Rule: `x=28, y=66, w=1224, h=2`.
- Evidence field: `x=28, y=78, w=1224, h=560`; it ends at `y=638`.
- Takeaway band: `x=28, y=650, w=1224, h=54`; it ends at `y=704`.
- Pale fill: `#EDF3FB`; border: `#C8D6EC`; semantic red:
  `#D71920`.

The screenshot is confirmed visual direction, so its compact typography may
override generic minimums. Keep content titles at 32–38 px, panel titles at
17–21 px, body at 14–18 px, and annotations at 12–15 px only when the full
1280 × 720 render remains legible. Test every language used in the deck,
especially Vietnamese and CJK glyphs.

## Ten archetypes

1. `hero-architecture-triad`: identity, signature architecture, three proofs.
2. `problem-funnel-question`: three limitations, evidence, central question.
3. `four-contribution-evidence`: four compact contribution panels with proof.
4. `architecture-main-reading-rail`: system diagram plus numbered rail.
5. `dual-mechanism-numbered-rail`: two mechanism views plus interpretation.
6. `sequence-information-flow`: input, central flow, supporting mechanisms.
7. `comparison-table-conclusions`: dominant table plus numbered conclusions.
8. `metric-scoreboard-method`: headline metrics, experiment table, conditions.
9. `evidence-gallery-observations`: dominant figure, evidence, observations.
10. `synthesis-defense`: three-lens summary, conceptual model, discussion.

Use the canonical sequence for a ten-slide technical briefing, but choose an
archetype by communication job rather than slide number. Do not repeat one on
adjacent slides, and do not run more than two dense evidence slides in a row.

## Visual grammar

- Navy carries titles, rules, section headers, numbers, and connectors.
- Red is semantic only: one central answer, displaced assumption, or decisive
  result; use at most two red phrases on a slide.
- Panels use one-pixel blue-gray borders, four-pixel radii, white or pale-blue
  fills, and no visible dashboard shadow.
- Architecture modules may use pale blue, green, yellow, and lilac. Use one red
  path at most. Number the reading order outside dense figures.
- Tables use a navy header and restrained alternating rows. Charts saturate
  one focal series and directly label values.
- The footer must add an implication. It may not restate the title.

Keep one dominant technical object and at most four supporting evidence units.
Compact panels still need distinct roles: premise, mechanism, evidence, and
implication. A wall of equal cards is not this style.

## Representation and QA

The complete HTML/CSS composition remains the visual source. Mark only
uniform, solid-color text and plain rectangular raster images as editable.
Flatten complex diagrams, equations, charts, tables, connectors, and icons for
fidelity. Put claims and visual sources in `[Sources]` speaker notes.

Validate the schema-v6 project, inspect every source preview, inspect the 2×
flattened shell, publish, and reopen the exact PPTX in the built-in renderer.
The runtime-observed DNA score must reach at least 90/100; wrong geometry,
title wrapping, content outside the measured bands, missing glyphs, and an
unrendered reopened slide are hard failures.
