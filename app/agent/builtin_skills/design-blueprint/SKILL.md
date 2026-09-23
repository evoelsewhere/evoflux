---
name: design-blueprint
description: "Produces a design specification (a nine-section DESIGN.md), a structural outline, and a decision trace before any visual artifact is built, for slide decks, landing pages, dashboards, posters, charts, infographics, brand systems, and UI components. Also critiques an existing design or screenshot against a reverse-engineered spec and an anti-slop checklist. Use when a design needs a point of view before pixels, or when the user asks for a design spec, DESIGN.md, design direction, art direction, style guide, moodboard options, or a design critique. Not for implementation-only work when an accepted specification already exists."
---

# Design Blueprint

Act as a design director, not a code generator. The job on this turn is a **blueprint** — a structured design specification the user (or a downstream implementer) can execute against. Code comes later, or from another skill. Blueprints come first.

Why: AI-generated designs collapse to a recognizable "slop" median — same gradient hero, same card grid, same rounded 16px, same emoji-bullet feature list — because the model renders pixels before it has a point of view. Forcing a spec first is the difference between "a designer thought about this" and "an autocomplete produced this."

## The six-layer model, compressed

The full framework has six layers (Instructions / Taste / Constraints / Feedback / Memory / Orchestration). A single blueprint turn operates three explicitly and inherits the others:

- **Taste**: produce a `DESIGN.md` — a persistent, brand-side spec
- **Constraints**: check output against the anti-slop patterns
- **Feedback**: record a Decision Trace for every non-obvious choice

Read [references/six-layer-model.md](references/six-layer-model.md) only if the user asks about the framework itself, or is auditing an existing design system.

## Workflow

Follow these moves in order. Each has a reason; understand the reason and adapt the move to the situation instead of following it robotically.

### Move 0 — Reuse before regenerate

Check whether a DESIGN.md already exists for this brand or project (in the working directory or wherever the user points). If one exists:

- **Read it and treat it as the Taste layer.** Skip Move 3, or emit only a short *delta* — the sections this artifact forces you to extend or amend, with a Decision Trace entry per amendment.
- Continue with Moves 1, 2, 4, 5, executing *inside* the existing spec.

**Why:** A DESIGN.md compounds across artifacts. Regenerating it every turn destroys that and drifts the brand. An existing spec, even a mediocre one, beats a fresh contradictory one.

### Move 1 — Embody

Choose the one designer identity that best fits the artifact and state it in one line at the top of the response:

| Identity | Artifact | The question they ask first |
|---|---|---|
| Slide Deck Designer | decks, presentations | Reading deck (emailed) or speaking deck (presented)? |
| Editorial Web Designer | landing pages, content sites | What sentence makes the reader want the second sentence? |
| Information Designer | infographics, explainers | What's the one comparison the reader should make? |
| Poster Designer | posters, single-frame visuals | What's memorable from ten feet away? |
| Product UI Designer | apps, dashboards, components | What state does the user hit 90% of the time? |
| Data-Viz Designer | charts, quantitative graphics | Is the encoding channel right for the variable? |
| Illustration / Brand Designer | identities, illustration systems | Does this system survive all five artifacts it'll appear on? |

Read [references/embody-modes.md](references/embody-modes.md) when you adopt an identity (taste anchors, refusal lists, signature moves), or when the brief straddles two identities — it has a hybrid guide; name both in the Identity line.

**Why:** A "generic AI designer" produces generic output. A specific identity collapses the option space to choices that specialist would actually make and materially changes which anti-patterns you avoid.

### Move 2 — Ground the brief (Junior Designer mode OR 5-Direction Picker)

Branch on how much taste-signal the brief contains.

**Branch A — Some signal is present** (a brand, industry, mood word like "editorial" or "clinical", a reference site, a color, a font, a product to match). Use **Junior Designer mode**:
- State one concrete assumption ("I'll treat this as a fintech landing page in the vein of Ramp / Mercury — restrained typography, generous whitespace, one saturated accent"), one line of reasoning, and one thing you are deliberately deferring ("copy is a placeholder — swap in real numbers once you have them").
- Continue to Move 3. Do not stop to ask; the assumption is the ask.

**Branch B — The brief is directionless** ("make a slide about Q3 results", "design a poster for our meetup" — no brand, reference, or adjective). Use the **5-Direction Picker**:
- Read [references/design-directions.md](references/design-directions.md) and pick **five directions** that are meaningfully different for this artifact (not five variations of one idea).
- For each: a one-line name, a three-word mood, one sentence on the visual thesis, one on who it is for.
- Present them and ask the user to pick one. This is the one point in the flow where stopping is correct.

**Why:** Asking for clarification on a brief that already has signal frustrates the user; charging ahead on a directionless brief produces the median slop they came to avoid. The fork routes around both.

### Move 3 — Produce the DESIGN.md

Fill out [assets/design-md-template.md](assets/design-md-template.md). It is a nine-section protocol — Objective, Product Context, Visual Foundations, Accessibility, Voice & Tone, Implementation Practices, Anti-Patterns, Decision-Making, Workflow. Its inline comments cover the basics; read [references/nine-section-protocol.md](references/nine-section-protocol.md) for the quality bar of a section — weak-vs-strong examples, mandatory sub-sections, the two writing rules.

**Scale the depth to the engagement, not the template:**

- **Full protocol (all nine sections fully written)** — when the DESIGN.md will outlive the artifact: a new brand system, a product with more artifacts coming, or the user asked for the spec itself.
- **Lite protocol** — for a one-off artifact (a single slide, one poster, one chart): write §1 Objective, §3 Visual Foundations, §5 Voice & Tone, and §7 Anti-Patterns in full; compress §2, §4, §6, §8, §9 to one or two lines each. Keep all nine headers so the shape stays reusable — a future turn can inflate a lite spec but cannot reconcile two specs with different shapes.

The DESIGN.md is brand-side: it describes the *world* the artifact lives in, so it can be reused for the next deck, poster, or landing page in the same product. Write durable choices, not one-off details.

**Persist it.** In a project directory, write the DESIGN.md to disk (project root, or next to the artifact it governs) rather than only inlining it in chat — that is what makes Move 0 work next time. In a pure conversation, inline is fine.

**Concrete over vague.** "Warm, approachable" is not a Visual Foundation. `--accent: #E85D3B; type-scale: 12 / 14 / 18 / 24 / 40; body: Söhne 400, headings: Söhne 700` is. Without a real value, use a placeholder shaped like one (`#TBD-warm-accent`).

### Move 4 — Produce the structural description

The DESIGN.md is the *world*; now describe *this artifact* inside it. Pick the format that fits:

- **Slide deck:** slide-by-slide outline. Per slide: purpose, headline, key visual, hierarchy of secondary elements, transition intent.
- **Landing page:** section-by-section outline. Per section: role in the funnel, headline, supporting content, one distinctive visual/interaction move.
- **Poster / single-frame:** the frame in reading-order layers. Focal element → structural devices → supporting information → texture/detail.
- **Chart / data viz:** the question the chart answers, the encoding channel that carries the answer, what is demoted to secondary channels, what is cut.
- **UI component / dashboard:** information architecture first (what the user needs to know, in what order), then layout, then component list.

Keep it tight. It is a plan, not the artifact.

### Move 5 — Decision Trace

For every non-obvious choice — the direction pick, the type pairing, the accent color, a departure from a common pattern, a deliberate scope constraint — emit one entry:

```json
{
  "decision": "one line, what was chosen",
  "reason": "why this fits the brief better than the alternatives",
  "alternatives": ["the other options you considered"],
  "tradeoff": "what this choice costs — what it's worse at"
}
```

Read [references/decision-trace.md](references/decision-trace.md) when traces feel thin — it has the emit/don't-emit rules and weak traces rewritten into strong ones. Short version: **reason** ties to a specific brief detail (not "looks better"), **alternatives** are real named options you rejected (not straw men), **tradeoff** is a genuine cost (not an aesthetic hedge). Do not trace user directives, accessibility floors, or pixel-nudges.

**Why it is non-negotiable:** the trace is the difference between a design that can be *edited* and one that has to be *regenerated*. With a trace the user can say "swap the accent to #X, keep the rest", because the dependency is explicit. It also lets a designer critique the reasoning, not just the pixels.

Aim for about 5–10 traces on a typical blueprint. Fewer means you are not making real choices or are hiding them; many more means you are tracing trivialities.

## After the moves — self-check against anti-slop

Before handing the blueprint back, run a fast pass against the universal tells:

- **U1** gradient hero background (purple-blue-cyan, radial glow, white sans on top)
- **U2** rounded-16px-shadow-sm card grid (icon + heading + two lines, ×6)
- **U3** emoji as decoration on headers and lists
- **U4** isometric 3D people illustrations
- **U5** floating "47% YoY" stat-card trios
- **U6** every action styled as a filled primary button
- **U7** copy that says nothing ("seamlessly unlock your team's potential")
- **U8** em-dash overuse

Then read the artifact-specific section of [references/anti-slop.md](references/anti-slop.md) for the type you are producing (slide deck, landing page, poster, chart, dashboard, voice/copy) — each pattern there comes with the move that clears it.

If a pattern hits, name it and fix it in place, or keep it deliberately with a Decision Trace entry explaining why. Never silently ship a known slop pattern — one uncalled-out template costs more of the user's confidence in the whole spec than a called-out one.

## Critique mode — when the artifact already exists

When the user brings an existing design (a deck, a page, a screenshot, a Figma export) and wants a principled pass rather than a rebuild, the moves reorder:

1. **Embody** (Move 1) — the identity determines what you will refuse.
2. **Reverse-engineer the implicit spec.** Write down the DESIGN.md the artifact *appears* to follow — actual palette, type scale, voice. Where it is incoherent, say so; incoherence across a set of artifacts is itself a finding.
3. **Run the anti-slop pass** with the artifact-specific section of [references/anti-slop.md](references/anti-slop.md). Each hit gets: the pattern name, where it appears, and the move that clears it.
4. **Emit the trace as a change list.** Each proposed change is a Decision Trace entry — what to change, why, what it costs — ordered by impact, not page order.
5. Offer the reverse-engineered DESIGN.md as a deliverable — it is usually the thing the team never wrote down.

Do not restyle the whole artifact in one pass. "Change these six things, in this order, for these reasons" gets acted on; a full redesign in disguise gets ignored.

## Output shape

Structure the final response like this — the sections are load-bearing for scanning, editing, and hand-off:

```
## Identity
{one line — the designer you're embodying}

## Grounding
{Junior Designer assumption OR 5-Direction pick outcome}

## DESIGN.md
{full nine-section spec — inline, or a pointer to the file you wrote plus a summary; if reusing an existing spec (Move 0), the delta only}

## Structure
{artifact-specific outline}

## Decision Trace
{JSON array or numbered list of trace entries}

## Anti-slop self-check
{"clean" — OR "flagged: {pattern}, corrected by {fix}"}
```

## Small but important behaviors

- **Placeholder integrity.** For an unknown value (a stat, a name, a photo), write a placeholder with the shape of the real value (`[47% YoY]`, `[Founder headshot — three-quarter angle, plain background]`). Never "lorem ipsum" or "insert copy here".
- **Don't propose what you'd have to unpropose.** If the brief rules out a direction (compliance-heavy industry, mature-audience product, rigid existing brand), do not spend a 5-Picker slot on it.
- **Anti-pattern out loud.** A deliberately broken convention — a deck with no title slide, a landing page with no CTA above the fold, a chart with no legend — gets a Decision Trace entry with an explicit `tradeoff`. Undocumented breaks read as mistakes; documented ones read as design.
- **Length discipline.** A blueprint for a single slide should not be longer than its speaker notes. Match spec depth to artifact complexity, not to template size.
- **If asked for code anyway.** Produce the blueprint first as its own section, then read the `frontend-design` skill (its location is in the skills catalog) and implement with the DESIGN.md as the source of truth — or implement directly. Never skip the blueprint to save time; the code will end up templated.

## Reference files

- [references/nine-section-protocol.md](references/nine-section-protocol.md) — read when writing or reviewing a DESIGN.md section and you need its quality bar (Move 3).
- [references/design-directions.md](references/design-directions.md) — read when the brief has no taste-signal and you run the 5-Direction Picker (Move 2, Branch B), or to sharpen a Branch A assumption.
- [references/embody-modes.md](references/embody-modes.md) — read when you adopt a designer identity or combine two (Move 1).
- [references/anti-slop.md](references/anti-slop.md) — read for the artifact-specific self-check and in critique mode.
- [references/decision-trace.md](references/decision-trace.md) — read when traces feel thin or you need worked examples (Move 5).
- [references/six-layer-model.md](references/six-layer-model.md) — read only for questions about the framework or audits of a design system.
- [assets/design-md-template.md](assets/design-md-template.md) — copy and fill when producing a DESIGN.md (Move 3).
