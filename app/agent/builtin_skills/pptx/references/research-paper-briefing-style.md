# Research paper briefing visual system

Use this system for academic papers, technical reports, thesis defenses, and
research briefings when the user wants a slide language like the supplied
Attention Is All You Need reference: information-rich, disciplined, and still
easy to scan.

## Design fingerprint

- White or warm-white canvas; deep research navy carries titles, rules,
  numbering, and section headers.
- Red is semantic, not decorative. Reserve it for the central result, the
  replaced assumption, or the one phrase the audience must remember.
- A 2 px navy title rule anchors every content slide. Titles are direct claims,
  not generic topic labels.
- Thin blue-gray borders organize evidence without creating heavy dashboard
  chrome. Shadows are optional and nearly invisible.
- The main paper figure, equation, table, or result is the visual center. Side
  panels explain premise, mechanism, evidence, and implication.
- A bottom takeaway strip closes the reasoning loop. It states what the
  audience should now believe, not another section label.
- Numbered navy circles and simple inline SVG icons provide navigation. Never
  use emoji.

Use the reusable CSS in
[`templates/research-paper-briefing.css`](../templates/research-paper-briefing.css).
Use the layout selector, component mapping, and density limits in
[`research-paper-briefing-dna.json`](../templates/research-paper-briefing-dna.json)
as the executable design contract.
Copy the CSS into the current project directory and link or embed it in each
static slide; keep all style references project-local.
The adjacent
[`research-paper-briefing.example.html`](../templates/research-paper-briefing.example.html)
shows the system applied to a real evidence-comparison slide; its JSON project
is in the same directory for end-to-end fidelity rendering.

## Canvas and typography

Design at 1280 × 720. Use a 30–36 px outer margin and an 8 px spacing unit.

- Cover title: 62–72 px, 1.0–1.05 line-height, maximum three lines.
- Content title: 38–44 px and normally one line.
- Section/panel title: 18–22 px, bold.
- Body: 18–21 px. Figure annotations may use 15–17 px only when the supplied
  source figure already has that density and remains legible at full-slide
  render.
- Metric: 44–60 px; caption 17–19 px.

Prefer Instrument Sans, Aptos, Arial, or another export-safe sans serif. Use a
serif face only for displayed equations. Never shrink body copy merely to fit
another fact; move secondary detail to notes or another slide.

## Spatial grammar

The reference deck uses a stable three-band frame with varied content
silhouettes inside it:

- `header`: 8–11% of the slide. One claim title plus a 2 px rule; no subtitle
  unless the slide is the cover.
- `evidence field`: 76–82%. Allocate 58–68% to the dominant figure, table,
  equation, or mechanism and 24–32% to a reading guide or implication rail.
- `conclusion`: 7–10%. Use a takeaway strip only when it advances the argument;
  do not repeat the title verbatim.

Maintain 32 px outer margins, 12–16 px internal gutters, and align unrelated
objects to the same 12-column grid. Within a panel, use 10–14 px padding. A
dominant visual should normally be at least twice the area of any supporting
unit. Asymmetry is deliberate: equal-width columns are reserved for true
comparisons, not used as a default.

## Claim-to-evidence grammar

Every content slide follows the same reasoning equation:

`claim title → evidence → reading guide → implication → takeaway`

- The title says what is now believed, not merely the section name.
- The evidence is concrete: a paper figure, equation, table, measured result,
  or explicit before/after mechanism.
- The reading guide tells the audience where to look, normally with two to four
  numbered observations.
- The implication connects the evidence to the paper's central thesis.
- The takeaway compresses the implication into one sentence with exactly one
  red semantic phrase.

Omit a stage only when the visual already performs its job. For example, a
directly labeled comparison chart may not need a separate reading rail.

## Density without clutter

This is an evidence-dense editorial system, not a generic card dashboard.
Every visible region must have a different reasoning role:

1. `premise`: what was true before this work;
2. `mechanism`: what the method changes or computes;
3. `evidence`: the figure, equation, table, or measured result;
4. `implication`: why the evidence changes the conclusion.

Use at most one dominant visual plus three supporting evidence units. Keep
visible prose around 60–100 words for Latin-script languages. A comparison
table may exceed that only when labels are short and the takeaway is explicit.
Do not repeat the same sentence in a panel, caption, and takeaway strip.

## Layout family

Choose the silhouette that matches the slide's communication job. Vary
adjacent silhouettes.

- `cover-split`: large title and citation on the left; signature paper figure
  or architecture preview on the right; three compact proof points along the
  bottom.
- `problem-funnel`: three numbered limitations or causal steps on the left;
  evidence diagrams in the center; one red research question on the right.
- `contribution-triptych`: three non-equal columns for architecture,
  efficiency, and result. Each column must contain evidence, not prose alone.
- `architecture-main-aside`: architecture figure occupies 60–70%; a numbered
  explanatory rail on the right resolves how to read it.
- `mechanism-two-plus-one`: two mechanism diagrams/equations plus one concise
  interpretation rail.
- `evidence-comparison`: comparison table or chart on the left; numbered
  interpretation on the right; conclusion strip below.
- `results-scoreboard`: two or three headline metrics above; experiment table
  and setup/method notes below.
- `interpretability-gallery`: one dominant evidence figure plus two or three
  smaller source figures, each with a claim caption.
- `synthesis-three-lens`: contribution, efficiency, and historical impact on
  the left; conceptual mechanism in the center; discussion questions on the
  right.
- `claim-evidence`: one provocative claim or research question against one
  dominant proof; use for the opening tension, limitation, or decisive result.
- `process-cascade`: three or four causal stages on one side and a mechanism
  comparison on the other; use when sequence or dependency is the argument.
- `equation-focus`: one governing equation plus term decomposition and a
  mechanism diagram; use when the math explains the visual rather than merely
  decorating it.
- `ablation-matrix`: a dominant ablation table or small-multiple chart plus a
  narrow interpretation and caveat rail.
- `timeline-impact`: four chronological milestones connected by one baseline;
  use only when the history or downstream influence changes the conclusion.

## Component DNA

### Figures and diagrams

- Preserve a paper figure's aspect ratio and crop only dead margin.
- Add a navy claim label above the figure and a one-line interpretation below;
  do not use generic captions such as “Architecture”.
- Architecture diagrams use pale green, yellow, blue, and lilac modules with
  navy outlines. Connectors stay navy or blue-gray. Use red for one traced path
  or failure point only.
- A diagram may contain at most three connector semantics: data flow, repeated
  block, and emphasized path. Label the legend directly beside the diagram.
- Number the reading order outside the figure rather than overprinting dense
  source artwork.

### Equations

- Show one governing equation per slide, 25–34 px, centered in a soft-blue
  field. Break it into two to four terms beneath or beside it.
- Explain what each term does to the computation, not only what the symbol
  stands for.
- Use serif only for the equation. Keep labels and interpretation in sans
  serif. Highlight one operator or denominator in red only when it is the
  actual conceptual hinge.

### Tables and charts

- A table must answer one comparison question. Highlight the proposed method's
  column or decisive cells; do not color every winner.
- Use a navy header, pale alternating rows, direct units, and no more than six
  visible rows unless the table is the dominant slide object.
- For bars, saturate the focal series and mute comparators. Put values on or
  above bars and remove the legend when direct labels are possible.
- Headline metrics belong above the experiment detail. Each metric needs a
  denominator, task, split, or training condition close enough to prevent a
  misleading reading.

### Reading rails and callouts

- Use two to four numbered observations. Each begins with a 3–7 word claim and
  one supporting sentence.
- The rail is narrower and visually quieter than the evidence. Avoid large
  icons, badges, or nested cards.
- Caveats use muted ink on pale yellow, never the same red used for the central
  conclusion.

## Deck rhythm

Alternate spatial energy so adjacent slides do not look templated:

1. broad composition (`cover-split` or `claim-evidence`);
2. directional composition (`problem-funnel` or `process-cascade`);
3. comparative composition (`contribution-triptych` or
   `evidence-comparison`);
4. deep-focus composition (`architecture-main-aside` or `equation-focus`);
5. evidence composition (`results-scoreboard`, `ablation-matrix`, or
   `interpretability-gallery`);
6. synthesis composition (`synthesis-three-lens` or `timeline-impact`).

Do not repeat the same silhouette on consecutive slides. Use no more than two
dense evidence slides in a row; follow them with a synthesis, mechanism, or
claim-focused slide.

## Density budgets

- Cover: 25–45 visible words plus citation and three proof points.
- Mechanism/architecture: 45–80 visible words outside the figure.
- Table/chart: 35–65 words outside labels and cells.
- Synthesis/discussion: 70–110 words across three distinct reasoning roles.
- Reading rail: maximum four items and roughly 18–28 words per item.

If the content exceeds its budget, split the argument or move detail into
speaker notes. Never shrink the title, body, or figure labels to rescue an
overloaded composition.

## Recommended paper narrative

For a 9–11 slide paper briefing, use this cumulative sequence:

1. Paper identity, central claim, citation, and signature visual.
2. Prior limitation and the exact research question.
3. Claimed contributions and why each matters.
4. Overall architecture and reading guide.
5. Core mechanism and governing equation.
6. Supporting mechanisms or representation choices.
7. Complexity/efficiency comparison and implication.
8. Training setup, headline results, and fair-comparison caveats.
9. Interpretability, ablation, or qualitative evidence.
10. Synthesis, limitations, and productive discussion questions.

Do not force every paper into ten slides. Preserve the logic above while
dropping sections unsupported by the source.

## Evidence and sourcing

Recreate a figure only when it improves readability and all values remain
faithful. Otherwise use a high-resolution crop from the paper with a concise
claim caption. Put the paper URL, figure/table number, and any external visual
source in the slide's `[Sources]` speaker-notes block. Distinguish reported
results from the presenter's interpretation.

## Paper-to-deck extraction

Extract content in evidence order rather than document order:

1. `central claim`: abstract conclusion plus the exact problem displaced;
2. `novelty`: contribution statements from the introduction, deduplicated;
3. `mechanism`: signature architecture figure and governing equations;
4. `efficiency`: complexity table, training cost, or scaling evidence;
5. `effectiveness`: main result table with fair-comparison conditions;
6. `trust`: ablation, qualitative evidence, error analysis, or limitations;
7. `implication`: what later systems, decisions, or research directions change.

For each extracted item, record `claim`, `evidence locator`, `interpretation`,
`caveat`, and `source`. Do not design a slide until all five fields are known or
explicitly marked unsupported.

## PPTX representation

Author the complete slide in HTML/CSS. Mark solid-color titles, panel headers,
body copy, metrics, numbered observations, and takeaway text editable only when
they use export-safe fonts and no transform, filter, shadow, mask, or gradient.
Keep paper figures, complex equations, charts, attention maps, icons, and
decorative detail in the visual shell. Raster source figures may be editable
images when replacement is genuinely useful.

The immutable WebView render is the visual reference. Accept the candidate
only when every preview is complete, legible, and free of overflow and the
generated PPTX passes structural OpenXML round-trip.
