---
name: algorithmic-art
description: Create original interactive generative art with p5.js, seeded randomness, and meaningful parameter exploration. Use for algorithmic art, flow fields, particle systems, procedural compositions, or browser-based generative sketches; do not use for static poster design, ordinary product UI, or photorealistic image generation.
---

# Create algorithmic art

Build one self-contained browser artwork whose visual character emerges from a
coherent system, not a stack of unrelated random effects. Do not load bundled
templates when this skill activates.

## State machine

### 1. FRAME

Extract the subject, intended mood, output constraints, interaction needs, and
one conceptual relationship the algorithm will express. If the brief leaves an
axis open, choose it deliberately instead of asking for generic preferences.

Define a compact generative system:

- entities and initial state;
- forces, rules, or mathematical relationships;
- evolution and termination behavior;
- color and composition logic;
- parameters that change the system rather than merely decorate it.

Do not imitate a living artist or reproduce a recognizable artwork. Translate
references into non-exclusive attributes such as density, rhythm, geometry,
palette, motion, or material quality.

### 2. PLAN

Choose a deterministic seed strategy and a small parameter set. State what each
parameter controls and the visual range it must preserve. Prefer a few
high-leverage controls over exposing every constant.

Read [templates/viewer.html](templates/viewer.html) only now, immediately before
implementation. Preserve its working shell, seed navigation, control layout,
reset/regenerate actions, and download behavior; replace the artwork-specific
algorithm and controls. Read
[templates/generator_template.js](templates/generator_template.js) only when
the planned system needs an implementation example for seeded state, animation
lifecycle, or parameter wiring.

### 3. BUILD

Create a single HTML file with inline CSS and JavaScript. The p5.js CDN may be
the only external runtime dependency. Ensure:

- identical seed and parameters produce identical initial output;
- every visible control updates the intended parameter;
- previous, next, random, jump-to-seed, reset, regenerate, and PNG download work;
- the composition remains intentional across representative seeds;
- animation stays responsive and bounds particle, history, and allocation work;
- keyboard focus, labels, reduced motion, and usable contrast are present.

Do not create a separate manifesto file unless the user asks for process notes.
Keep conceptual explanation short and let the artifact carry the idea.

### 4. VERIFY

Open the HTML in a browser and inspect it visually. Exercise the full seed and
parameter controls, reset behavior, resize behavior, and download. Revisit at
least three materially different seeds and one extreme value for each control.
Fix blank frames, unstable initialization, runaway work, clipped controls,
illegible text, accidental collisions, and seeds that collapse the composition.

## Stop conditions

Stop when the requested artifact works without setup, seed reproduction is
proven, controls are meaningful, representative variations retain the visual
system, and no unresolved browser or visual defect remains.

## Deliverable

Return the HTML artifact first, followed by the seed used for the preview,
available controls, and verification performed. Mention any external runtime
dependency or performance boundary.
