---
title: Imagery & Graphics
description: EvoFlux mascot, lucide icons, charts on the marker palette, agent chips, screenshots, patterns
status: stable
updated: 2026-05-09
---

# Imagery & Graphics

## Iconography

## Mascot and brand imagery

EvoFlux uses a geometric layered-hexagon mark from `logo.svg` as the canonical brand identity. The logo renders cleanly on both light and dark surfaces. Source vector lives at project root; rasterized exports live in `documents/assets/brand/` and `web/src/assets/brand/`.

Use the logo for:

- README and social headers
- Empty states and onboarding moments
- App icon, sidebar logo, and avatar-style surfaces
- Launch or release graphics

Avoid using the logo as decoration in dense product chrome. In the app UI, small repeated logo positions should use `evoflux-app-icon.png`.

### Library: lucide-react

Single icon library, no mixing. `lucide-react` ships with the web stack and provides consistent 24px-native outlined icons with 1.5–2px strokes. Don't blend in icons from another library — even tonally similar sets diverge on weight and proportion under close comparison, which makes the UI feel uneven.

### Sizing

| Size | Use case |
|------|----------|
| **16px** | Status indicators, inline icons, table cells, small metadata |
| **20px** | Dense lists, secondary buttons |
| **24px** | Default UI icons, nav, primary buttons |
| **32px** | Feature tiles, section headers |
| **48px** | Empty-state illustrations, hero moments |

### Color

| Context | Color |
|---------|-------|
| Default | `currentColor` (inherits from text) |
| Interactive hover | `var(--color-accent)` |
| Agent role indicator | matching `--accent-{role}` edge color (e.g. `--accent-green` for EvoFlux) |
| Status — success | `var(--color-success)` |
| Status — warning | `var(--color-warning)` |
| Status — error | `var(--color-error)` |
| Status — info | `var(--color-info)` |
| Disabled | `var(--color-text-subtle)` |

### Rules

- **Outlined only** — never mix outlined and filled icons in the same view
- **Stroke width**: default (stock lucide). Don't override unless the icon looks visually too thin at a specific size.
- **Icon + label pairing**: when an icon accompanies text, don't duplicate meaning (`<Delete />` + "Delete" is fine; `<Info />` + "Info" is redundant — use a visible text label or an icon-only button with `aria-label`)
- **Icon-only buttons**: require `aria-label` or a tooltip for accessibility

---

## Patterns & textures

### No decorative patterns, no gradients in chrome

Backgrounds are **solid warm neutrals**. No grid overlays, no dot patterns, no noise textures, no parallax layers. The paper aesthetic intentionally avoids gradients in UI chrome — the only gradients in the system live inside the mascot artwork itself.

| Context | Treatment |
|---|---|
| Page background | `var(--bg-page)` solid |
| Panel / sidebar | `var(--bg-sidebar)` solid |
| Card / popover | `var(--bg-card)` solid + `var(--shadow-depth)` |
| Elevated surface | `var(--color-surface)` solid + `var(--shadow-depth)` |
| Section tint (rare) | `var(--accent-{role}-soft)` — only for content tied to that agent role |

### Dividers & borders

- **Subtle divider**: 1px solid `var(--border-soft)` — between list rows
- **Default divider**: 1px solid `var(--color-border)` — between sections, on cards
- **Strong divider**: 1px solid `var(--color-border-strong)` — major section breaks
- **Never**: gradient borders, dashed borders for decoration (dashed is reserved for *drag-target* affordances and *queued* states)

### Drag-target highlight

```css
.drag-target {
  outline: 2px dashed color-mix(in srgb, var(--color-accent) 55%, transparent);
  outline-offset: 2px;
  background: color-mix(in srgb, var(--color-accent) 6%, transparent);
}
```

---

## Data visualization

### Tools

- **Primary**: Recharts (already in the web stack)
- **Secondary**: Chart.js for advanced visualizations that Recharts can't handle well
- **Not used**: custom hand-rolled SVG charts without accessibility review

### Color palette

Use the **marker palette** from [colors.md](./colors.md#marker-palette--charts-and-tints). Markers are slightly more saturated than agent chips because they need to read against busy chart backgrounds. Series 1 is the most prominent data, series 5 the least.

The fixed series order is: blue, mint, orange, pink, yellow. Resolve colors through CSS custom properties (`var(--color-marker-*)`) so values flip per mode automatically. Area fills use the matching low-alpha tint tokens (`--color-tint-*`).

Never use the EvoFlux brand gold/orange as a chart color unless the data explicitly represents EvoFlux itself. Never use the agent chip colors as chart series — chips are role-identity-reserved, and reusing them in charts will collide perceptually with chip badges on the same screen.

### Design rules

- **Minimize non-data ink** — remove gridlines where possible, lighten axis labels to `text-muted`
- **No rainbow palettes** — stick to 3–5 series max; if you need more, stack or facet the chart
- **No pie charts** — bar or donut charts communicate proportion more accurately
- **Always provide a legend** for multi-series charts
- **Accessibility**: never rely on color alone. Pair series with patterns, symbols, or direct labels.
- **Responsive**: scale axis labels down at `< 640px`; hide secondary axes on mobile

### Chart chrome

Whatever charting library renders the visualization, configure its chrome to consume the same tokens as the rest of the app:

- Gridlines: `--color-border`, dashed and faint.
- Axis labels: `--color-text-muted`, tiny text scale.
- Tooltips: `--color-surface` fill, 1px `--color-border` outline, the small radius. Same recipe as a tiny popover.
- Series strokes: marker tokens at full saturation; series fills use the matching tint at low alpha.

---

## Markdown & prose

The app uses a custom `.prose` class for rendered markdown.

| Element | Style |
|---|---|
| `h1`–`h3` | `--color-text`, 600–700 weight, large top margin |
| Body | `--color-text`, 1.6 line-height, `max-width: 65ch` |
| `code` (inline) | `--color-text` on `--bg-key`, 6px radius (`--radius-xs`), JetBrains Mono, 0.9em |
| `pre code` (block) | `--color-surface` background, 1px `--color-border`, JetBrains Mono, syntax highlighted |
| Links | `--color-accent` with underline at 2px offset; weight 400→500 on hover |
| Lists | 1.5em padding, disc (ul) / decimal (ol) |
| Blockquote | Left border 3px `--color-border-strong`, `--color-text-2`, 1em padding |
| Tables | 1px `--color-border`, `--color-surface-2` header background |
| `hr` | 1px `--color-border-subtle` |

---

## Empty states

The canonical empty state pairs the mascot with a Inter callout — the "what's on your mind?" moment from the empty room screen. See also [applications.md § Empty states](./applications.md#empty-states-hand-drawn-pattern).

The composition is layered top to bottom:

1. **Mascot** — `evoflux-agentd-source.png`, full color, sized at the moderate hero scale (around 64–96px). Use the mascot only on full-page empty states; skip it inside narrow popovers and inline empty rows.
2. **Callout** — Inter at the hand size, `--color-text` (or `--color-text-subtle` for less-prominent surfaces), lowercase, ends with a question mark or period. The callout is decorative; pair it with an accessible Inter equivalent or mark it `aria-hidden`.
3. **Optional description** — body Inter at `--color-text-muted`, capped to a comfortable measure (~40ch).
4. **Optional primary CTA** — only when there is a clear next action.

For utilitarian empty states (lists with no items, search with no results), drop the mascot and the Inter. Use a small lucide glyph at `--color-text-muted`, an h3-scale Inter heading, an explanation paragraph at `--color-text-muted`, and a single primary CTA. The voice is calmer here — "No sessions yet" is enough.

### Skeleton placeholders

For content that will load within a few hundred milliseconds:

- Background: `var(--bg-key)` (warmer than `--color-surface-2`, so skeleton blocks read as "paper waiting for ink")
- Pulse animation: opacity `0.6 ↔ 1.0` over 1400ms (honors `prefers-reduced-motion`)
- Shape: match the final content's dimensions to prevent layout shift

```css
@keyframes skeleton-pulse {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.6; }
}

.skeleton {
  background: var(--bg-key);
  border-radius: var(--radius-sm);
  animation: skeleton-pulse 1400ms ease-in-out infinite;
}
```

Skeletons longer than ~800ms should be replaced with progressive text (see [motion.md](./motion.md#principles)).

---

## Screenshots

### Mode choice

Light (paper) is the canonical mode and the default everywhere unless there's a specific reason to use dark.

| Context | Mode |
|---|---|
| Product marketing (hero, landing, social cards) | **Light (paper)** — the warm cream is the brand surface |
| Documentation | **Light** |
| API reference screenshots | **Light** |
| README | **Light** |
| Blog posts | Match the blog's theme (usually light for long-form reading) |
| Conference slides on dark stages | **Dark** — for legibility against a dark venue |
| "What it looks like at night" feature | **Dark** |

### Composition

- **Crop tight** — screenshots should show the feature, not the browser chrome (unless the chrome is part of the point)
- **Consistent chrome** — if multiple screenshots appear together, use the same window style across all of them
- **Real data** — never use "Lorem ipsum" placeholder text in screenshots. Use plausible session names, real file paths, believable agent output.
- **No annotations inside the screenshot** — if you need arrows or labels, add them as a layer *on top* of the screenshot at export time, not inside the UI

### Export

- **1× and 2×** PNG for web
- **SVG** when the screenshot is actually a vector mockup (rare)
- **Full-bleed** or framed with 24px padding on a `--bg-page` background — pick one convention per surface and stick to it
