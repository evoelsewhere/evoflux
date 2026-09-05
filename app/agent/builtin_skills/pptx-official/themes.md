# Colour themes by subject

Pick the theme from what the deck is *about* and where it will be read, then
name the choice in the plan so the user can reject it before generation. Never
mix two themes in one deck.

Every palette below was checked against WCAG: on both its background and its
surface, title and accent roles clear 3:1 and body and muted text clear 4.5:1.
The weakest pair in each theme is listed so you know where the margin is thin.

## The roles

| Role | What it paints |
|---|---|
| `bg` | The slide background |
| `surface` | Cards, table fills, callout blocks sitting on `bg` |
| `title` | Slide titles and stat numbers |
| `body` | Body copy, table cells |
| `muted` | Captions, footnotes, axis labels, source lines |
| `accent` | One emphasis colour: rules, active states, the single figure that matters |
| `positive` / `negative` | Direction in data only — never decoration |

Use exactly one accent. A second accent has to earn itself by encoding a second
variable, and a deck with three is a deck with none.

## The themes

### Boardroom — executive, board, quarterly review
Dark, low-chroma, projector-safe. Reads as institutional rather than styled.

`bg #0F1B2A` · `surface #17263A` · `title #F5F7FA` · `body #D5DEE9` ·
`muted #9FB0C4` · `accent #4F9CF9` · `positive #3FBF8F` · `negative #E4695E`
Weakest pair 4.71:1 (negative on surface).

### Ledger — finance, audit, budget
Warm paper, ink body, one restrained blue. Prints without burning toner and
survives being photocopied.

`bg #FBFAF7` · `surface #F1EEE7` · `title #1C2430` · `body #2E3947` ·
`muted #5C6878` · `accent #1F5C8B` · `positive #1C7A55` · `negative #B03A2E`
Weakest pair 4.57:1 (positive on surface).

### Lab Notebook — research, methods, scientific results
Neutral white, no personality competing with the figures. The right choice
when charts and equations carry the argument.

`bg #FFFFFF` · `surface #F4F6F8` · `title #111827` · `body #26303D` ·
`muted #5A6675` · `accent #2F5FAF` · `positive #1B7F4F` · `negative #A63232`
Weakest pair 4.62:1 (positive on surface).

### Terminal — engineering, architecture, incident review
Near-black with a green accent that reads as a console without cosplaying one.
Good behind code blocks and system diagrams.

`bg #12141A` · `surface #1C1F27` · `title #EDEFF3` · `body #C9CFD9` ·
`muted #8B94A3` · `accent #7BD88F` · `positive #7BD88F` · `negative #F2777A`
Weakest pair 5.38:1 (muted on surface).

### Launch — product launch, brand, keynote
The only theme here allowed to be loud. Violet accent on near-black. Use it
when the deck's job includes making an impression, not when it reports numbers.

`bg #0B0A14` · `surface #181528` · `title #FFFFFF` · `body #DCD7EC` ·
`muted #A199C0` · `accent #B57BFF` · `positive #4FD1A5` · `negative #FF7A7A`
Weakest pair 6.15:1 (accent on surface).

### Clinic — healthcare, clinical, patient-facing
Calm teal on white. Avoids the red/green pairing that clinical audiences read
as triage status.

`bg #FFFFFF` · `surface #EFF5F4` · `title #12312C` · `body #234840` ·
`muted #4F6E67` · `accent #0E7A6B` · `positive #12795C` · `negative #9E3B34`
Weakest pair 4.74:1 (accent on surface).

### Classroom — teaching, onboarding, workshops
Warm and unintimidating, for material read slowly rather than presented fast.
Its accent has the thinnest margin here — keep accent text large.

`bg #FFFDF8` · `surface #F6EFE2` · `title #2B2113` · `body #3E3220` ·
`muted #6B5B44` · `accent #B26A1F` · `positive #2F7A3E` · `negative #A63A2B`
Weakest pair 3.69:1 (accent on surface) — display sizes only.

### Dashboard — analytics, KPI review, operating metrics
White cards on light grey, so many small tables and charts stay separable
without borders everywhere.

`bg #F7F8FA` · `surface #FFFFFF` · `title #151A21` · `body #2B333D` ·
`muted #5B6673` · `accent #3A6EA5` · `positive #1E7A4C` · `negative #B23A34`
Weakest pair 5.00:1 (accent on bg).

### Statute — legal, policy, compliance, governance
Quiet warm greys with a brown accent. Deliberately undesigned: nothing here
should look like it is selling.

`bg #FCFCFA` · `surface #EFEEE9` · `title #1A1A17` · `body #2D2D28` ·
`muted #5E5E56` · `accent #6B4E2E` · `positive #2C6E49` · `negative #96331F`
Weakest pair 5.26:1 (positive on surface).

### Field — sustainability, environment, operations
Deep green ground for material about physical places and systems.

`bg #0E1A14` · `surface #17281F` · `title #F2F7F3` · `body #D2E2D7` ·
`muted #9BB3A3` · `accent #5FCF8E` · `positive #5FCF8E` · `negative #E88A6A`
Weakest pair 6.09:1 (negative on surface).

## Choosing

Match the theme to the room, not only the topic. A projected deck in a bright
room wants a light theme; a dark theme is for screens and dimmed rooms, and it
is where a bright accent earns its place.

An existing template or brand overrides every palette here. Extract the real
colours from the template first and match them; introducing a second visual
language into a customer's deck is worse than a plain one.

When the subject is not on this list, take the nearest neighbour rather than
inventing a palette. The point of a fixed set is that a deck looks decided
rather than assembled.

## Applying it

Define the palette once as named constants at the top of the generator, then
reference the names. A hex literal repeated across forty slides is a theme
change that cannot be made.

Keep charts inside the same palette: series take accent, then muted, then
positive/negative only where direction is the point. A default chart palette
from the library is the fastest way to make a themed deck look untouched.

Check the result rather than trusting these numbers: run `document_preview`
after generating and confirm the text you expect is present and inside its
box. Contrast holds by construction, but only if the palette was applied.
