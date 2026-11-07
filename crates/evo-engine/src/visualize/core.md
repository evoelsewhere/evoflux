
# evo Widget Design System

## Philosophy
Widgets are inline visualizations that enhance the conversation flow.
They are NOT deliverables (use artifacts for that) — they are explanatory
tools that help users understand concepts, data, and relationships.

## Streaming-First Architecture
Widgets must be structured for progressive rendering:
1. `<style>` blocks first (short, minimal CSS)
2. HTML content (structure appears as tokens stream)
3. `<script>` blocks last (activate after content loads)

This ensures useful content appears early, even before scripts execute.

## Critical Rules
- **NO gradients, shadows, or blur** — they flash during streaming DOM diffs
- **NO `<!-- comments -->`** — waste tokens and break streaming
- **Two font weights only**: 400 (regular) and 500 (medium) — never 600 or 700
- **Sentence case everywhere** — never Title Case or ALL CAPS
- **CSS variables for all colors** — ensures dark mode compatibility
- **Dark mode is mandatory** — every color must work in both themes

## Color System
Use CSS variables for all colors:
```css
:root {
  --color-text-primary: #1a1a1a;
  --color-text-secondary: #666666;
  --color-background: #ffffff;
  --color-background-secondary: #f5f5f5;
  --color-border: #e0e0e0;
  --color-accent: #534ab7;
  --color-success: #1d9e75;
  --color-warning: #d85a30;
  --color-error: #d85a30;
}

.dark {
  --color-text-primary: #f5f5f5;
  --color-text-secondary: #a0a0a0;
  --color-background: #1a1a1a;
  --color-background-secondary: #2a2a2a;
  --color-border: #3a3a3a;
  --color-accent: #7f77dd;
  --color-success: #5dcaa5;
  --color-warning: #f0997b;
  --color-error: #f0997b;
}
```

## Typography
- Font stack: `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`
- Base size: 14px
- Line height: 1.5
- Never use custom fonts unless absolutely necessary

## CDN Allowlist
Only load scripts from these CDNs:
- `cdnjs.cloudflare.com`
- `cdn.jsdelivr.net`
- `unpkg.com`
- `esm.sh`

## Widget Structure
```html
<style>
  /* Minimal CSS using variables */
  .widget { padding: 1rem; }
</style>

<div class="widget">
  <!-- HTML content -->
</div>

<script>
  // Scripts execute after content loads
</script>
```
