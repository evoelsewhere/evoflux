---
title: Typography
description: Inter (UI/body), JetBrains Mono (code), Inter (handwritten headlines), type scale, font-weight transitions
status: stable
updated: 2026-05-09
---

# Typography

Three families, three jobs. Inter does the work, JetBrains Mono renders code and structured data, Inter carries the handwritten "this is a notebook" voice on a small set of headlines.

---

## Three families, three jobs

| Family | Token | Job |
|---|---|---|
| **Inter** | `--font-sans` | Every UI surface — body, labels, buttons, nav, prose |
| **JetBrains Mono** | `--font-mono` | Code blocks, terminal output, file paths, agent IDs, structured data |
| **Inter** | `--font-hand` / `--font-script` | Hand-drawn screen titles and reflective callouts only — not body |

Anything that isn't code and isn't a hand-drawn title is Inter. Inter is reserved — overuse breaks the spell.

---

## Primary typeface: Inter

- **Usage**: All UI text — headings, body copy, labels, buttons, prose
- **Weights in use**: 400 (Regular), 500 (Medium), 600 (SemiBold), 700 (Bold)
- **Source**: `@fontsource-variable/inter` (open source)
- **Character**: Highly legible humanist sans, built for screens. Reads as calm utility against the minimal monochrome.
- **Token**: `--font-sans`

```css
font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
```

---

## Secondary typeface: JetBrains Mono

- **Usage**: Code blocks, terminal output, file paths, agent IDs (`g_abc123`), token meters, anything monospaced or structured
- **Weights**: 400 (Regular), 500 (Medium), 600 (SemiBold)
- **Character**: Humanist monospace designed for code. Distinguishes `0O`, `1lI`, `{}()` clearly.
- **Token**: `--font-mono`

```css
font-family: 'JetBrains Mono', ui-monospace, 'SF Mono', 'Courier New', monospace;
```

---

## Hand-drawn typeface: Inter

- **Usage**: Screen titles in design (`empty room.`, `first stream`, `queue armed.`, `idle.`), reflective callouts, the mascot's "what's on your mind?" prompt
- **Weights**: 400 (Regular), 700 (Bold)
- **Character**: Casual handwritten script. Carries the notebook voice — a person wrote this, not a system.
- **Tokens**: `--font-hand` and `--font-script` (alias)

```css
font-family: 'Inter', 'Bradley Hand', cursive;
```

### When to use Inter

Use Inter for:

- Top-of-canvas screen labels in design files (typically *outside* production UI — they label the design context).
- One reflective prompt on an empty state ("what's on your mind?").
- Personality moments in marketing surfaces — tagline, hero pull-quote.

Do not use Inter for:

- Body text. Ever.
- Buttons, labels, nav items, form fields.
- Anything a screen reader must read clearly. Inter is decorative chrome; pair it with an accessible Inter equivalent or mark it `aria-hidden`.
- Multi-line paragraphs.
- Headings inside dense product chrome.

The "design canvas labels" in the pencil source (`empty room.`, etc.) are reference labels for the design file itself; production app headings stay in Inter.

---

## Type hierarchy

| Level | Size | Weight | Line height | Letter spacing | Family | Usage |
|---|---|---|---|---|---|---|
| **Hand callout** | 36–48px | 400 | 1.10 | 0 | Inter | Marketing-only handwritten moment |
| **Display** | 32px | 700 | 1.25 | -0.5px | Inter | Hero titles, marketing page headers |
| **Heading 1** | 28px | 700 | 1.30 | -0.3px | Inter | Page titles, section headers |
| **Heading 2** | 24px | 600 | 1.35 | -0.2px | Inter | Subsection headers |
| **Heading 3** | 20px | 600 | 1.40 | 0 | Inter | Component titles |
| **Body** | 16px | 400 | 1.50 | 0 | Inter | Main content, UI text, paragraphs |
| **Small** | 14px | 400 | 1.50 | 0.1px | Inter | Secondary info, labels, captions, message metadata |
| **Tiny** | 12px | 400 | 1.50 | 0.2px | Inter | Timestamps, footnotes, token counts |
| **Code inline** | 14px (0.92em in prose) | 400 | 1.50 | 0 | JetBrains Mono | `inline_code`, file paths |
| **Code block** | 14px | 400 | 1.55 | 0 | JetBrains Mono | Multi-line code, terminal output |

**Line-height rule**: tighter for display, looser for body. Never go below 1.4 for body text. Inter sets tighter (1.10) because handwritten letters already imply rhythm.

---

## Font-weight transitions (signature interaction)

Weight shifts on hover and active states are a signature of the EvoFlux interaction language. Text feels *alive* under the cursor without changing color or position.

### The rule

| State | Body/label | Interactive (button, link, nav item) |
|---|---|---|
| Idle | 400 | 400 |
| Hover | 400 | 500 |
| Active / pressed | 400 | 600 |
| Selected / current | 500 | 500 |

### CSS implementation

Inter is a variable font, so weight transitions are smooth rather than stepped. Use `font-variation-settings` for sub-weight precision, or `font-weight` with a transition if you don't need in-between values.

```css
/* Smooth weight shift on interactive elements */
.interactive {
  font-weight: 400;
  transition: font-weight 200ms cubic-bezier(0.4, 0, 0.2, 1);
}

.interactive:hover  { font-weight: 500; }
.interactive:active { font-weight: 600; }

/* Or with variation settings for finer control */
.interactive {
  font-variation-settings: 'wght' 400;
  transition: font-variation-settings 200ms cubic-bezier(0.4, 0, 0.2, 1);
}

.interactive:hover { font-variation-settings: 'wght' 500; }
```

### Anti-patterns

- Weight shift on idle/static text. Only interactive elements shift.
- Weight shift without a transition. The result is a layout jump that feels broken.
- Shift beyond 600. Weight 700 (Bold) is reserved for permanent headings, not hover states.
- Different shift amounts within a group. A nav where some items go 400→500 and others go 400→600 reads as inconsistent.
- Weight shift on Inter. Script weights are not perceptually distinct the way Inter weights are; let Inter sit.

### When NOT to use weight transitions

- Body paragraph links — too much motion in a reading flow
- Table rows with many cells — shifts the whole row, causes reflow
- Icon-only buttons — there's no text weight to shift
- Inter headlines — the hand-drawn aesthetic doesn't support it

See [interaction.md](./interaction.md) for the full hover/focus/active state model.

---

## Implementation tokens

The web app exposes typography through the `@theme` inline block in `src/index.css`:

```css
@theme inline {
  /* Families */
  --font-sans:    'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-mono:    'JetBrains Mono', ui-monospace, 'SF Mono', 'Courier New', monospace;
  --font-hand:    'Inter', 'Bradley Hand', cursive;
  --font-script:  var(--font-hand);
  --font-heading: var(--font-sans);

  /* Sizes */
  --text-display: 32px;
  --text-h1:      28px;
  --text-h2:      24px;
  --text-h3:      20px;
  --text-body:    16px;
  --text-sm:      14px;
  --text-xs:      12px;
  --text-hand:    44px;

  /* Weights */
  --weight-regular:  400;
  --weight-medium:   500;
  --weight-semibold: 600;
  --weight-bold:     700;

  /* Motion — shared with interaction.md */
  --motion-weight-shift: 200ms cubic-bezier(0.4, 0, 0.2, 1);
}
```

---

## Tailwind utility usage

```tsx
// Body — Inter, default weight
<p className="text-base">Body copy in Inter.</p>

// Heading — Inter, semibold
<h2 className="text-h2 font-semibold">Section heading</h2>

// Code — JetBrains Mono
<code className="font-mono text-sm bg-(--bg-key) px-1.5 py-0.5 rounded">
  app/agent/mode/chat.py
</code>

// Hand callout — Inter
<span className="font-hand text-[44px] leading-none text-(--color-text)">
  what's on your mind?
</span>
```

---

## Web implementation notes

- Inter loads from `@fontsource-variable/inter` — single variable font, no per-weight imports needed
- JetBrains Mono is loaded via `@fontsource-variable/jetbrains-mono`
- Inter is loaded via `@fontsource/inter` (400 + 700)
- Code syntax highlighting uses `highlight.js` with the EvoFlux theme (see [colors.md](./colors.md#syntax-highlighting--code))
- All UI text inherits `font-family: var(--font-sans)` from the root; code elements (`<code>`, `<pre>`, `.font-mono`) opt into the mono stack; Inter is opt-in only via `.font-hand` or the `--font-hand` variable
- Font-weight transitions are defined on `<button>`, `<a>`, and `[role="button"]` elements, plus an explicit `.interactive` utility for custom controls

---

## Accessibility

- **Minimum body size**: 16px. Never smaller for paragraph text.
- **Minimum small size**: 14px for secondary info; 12px only for non-essential metadata (timestamps, byte counts)
- **Inter is decorative** — every Inter callout must have an accessible Inter equivalent in the DOM (or be marked `aria-hidden="true"` if it's purely visual). Screen readers should not depend on script-rendering for meaning.
- **Line length**: aim for 60–75 characters per line in reading contexts. Use `max-width: 65ch` on prose containers.
- **Weight + contrast**: thin weights (300 or below) are not used; they fail WCAG on low-DPI screens even when contrast math passes
- **`prefers-reduced-motion`**: font-weight transitions honor reduced-motion (disable the 200ms transition, snap directly to final weight)

```css
@media (prefers-reduced-motion: reduce) {
  .interactive {
    transition: none;
  }
}
```
