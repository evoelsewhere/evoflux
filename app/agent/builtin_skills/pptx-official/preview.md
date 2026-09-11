# Visual preview before build

Use `show_widget` to let users see themes and slide layouts before any .pptx
file is written. This phase sits between Phase 2 (outline) and Phase 3 (prepare
assets). It is optional: skip when the user says "just build it", the deck is
small and straightforward, or `show_widget` is unavailable.

## When to preview

| Condition | Action |
|-----------|--------|
| User asks to see options ("preview", "show me", "xem truoc") | Preview |
| Deck > 10 slides, complex or contested material | Preview |
| Deck goes to board, customer, regulator, public audience | Preview |
| User says "just build it", "tao nhanh", delegates fully | Skip |
| Deck is <= 5 slides and straightforward | Skip |
| Non-interactive run (scheduled task) | Skip |
| `show_widget` tool is unavailable | Skip (fall back to text approval) |

## Setup

Before any `show_widget` call, load the design modules:

```
visualize_read_me(modules=["interactive", "mockup"])
```

This returns the HTML/CSS/JS guidelines required by `show_widget`. The
`i_have_seen_read_me` parameter must be `true` in every subsequent call.

## Preview type 1: Theme picker

Show 2-3 recommended themes as clickable cards. Each card contains:

- Theme name and suitability note
- Color swatches: bg, surface, accent, positive, negative
- Typography sample: title line (bold, ~22px) + body line (~14px)
- WCAG contrast badge
- "Select" button that sends `Theme: <name>` to chat

### Template

```html
<style>
  :root { --bg: #0F1B2A; --surface: #17263A; --title: #F5F7FA; --body: #D5DEE9; --muted: #9FB0C4; --accent: #4F9CF9; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--body); }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; padding: 16px; }
  .card { background: var(--surface); border-radius: 12px; padding: 20px; border: 2px solid transparent; transition: border-color 0.2s; }
  .card:hover { border-color: var(--accent); }
  .swatches { display: flex; gap: 6px; margin: 12px 0; }
  .swatch { width: 28px; height: 28px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.1); }
  .title-sample { font-size: 22px; font-weight: 700; color: var(--title); margin: 8px 0 4px; }
  .body-sample { font-size: 14px; color: var(--body); line-height: 1.5; }
  .label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
  .badge { display: inline-block; font-size: 10px; padding: 2px 8px; border-radius: 4px; background: rgba(255,255,255,0.08); color: var(--muted); margin-top: 8px; }
  .select-btn { margin-top: 12px; width: 100%; padding: 10px; background: var(--accent); color: #fff; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; }
  .select-btn:hover { opacity: 0.85; }
</style>

<div class="grid">
  <!-- One card per recommended theme. Override CSS variables per card. -->
  <div class="card" style="--bg:#0F1B2A; --surface:#17263A; --title:#F5F7FA; --body:#D5DEE9; --muted:#9FB0C4; --accent:#4F9CF9;">
    <div class="label">Boardroom</div>
    <div class="title-sample">Revenue grew 34%</div>
    <div class="body-sample">Every product line beat plan; hiring stayed flat.</div>
    <div class="swatches">
      <div class="swatch" style="background:#0F1B2A" title="bg"></div>
      <div class="swatch" style="background:#17263A" title="surface"></div>
      <div class="swatch" style="background:#4F9CF9" title="accent"></div>
      <div class="swatch" style="background:#3FBF8F" title="+"></div>
      <div class="swatch" style="background:#E4695E" title="-"></div>
    </div>
    <div class="badge">Dark, projector-safe, executive</div>
    <button class="select-btn" onclick="sendPrompt('Theme: Boardroom')">Select Boardroom</button>
  </div>

  <div class="card" style="--bg:#FBFAF7; --surface:#F1EEE7; --title:#1C2430; --body:#2E3947; --muted:#5C6878; --accent:#1F5C8B;">
    <div class="label">Ledger</div>
    <div class="title-sample">Revenue grew 34%</div>
    <div class="body-sample">Every product line beat plan; hiring stayed flat.</div>
    <div class="swatches">
      <div class="swatch" style="background:#FBFAF7" title="bg"></div>
      <div class="swatch" style="background:#F1EEE7" title="surface"></div>
      <div class="swatch" style="background:#1F5C8B" title="accent"></div>
      <div class="swatch" style="background:#1C7A55" title="+"></div>
      <div class="swatch" style="background:#B03A2E" title="-"></div>
    </div>
    <div class="badge">Warm paper, prints clean, finance</div>
    <button class="select-btn" onclick="sendPrompt('Theme: Ledger')">Select Ledger</button>
  </div>
</div>

<script>
function sendPrompt(p) {
  window.parent.postMessage({ type: 'widget_send_prompt', prompt: p }, '*');
}
</script>
```

### Agent call

```
show_widget(
  title="theme_picker",
  loading_messages=["Loading theme previews...", "Rendering color palettes..."],
  widget_code=<html above>,
  i_have_seen_read_me=True,
  width=900,
  height=700,
)
```

### Handling the selection

The user's click sends a message like `"Theme: Boardroom"` to chat. The agent
parses the theme name and continues the pipeline with that theme. If the
message is ambiguous or the user types a different theme name, treat their
text as the selection.

---

## Preview type 2: Slide preview grid

Show all slides as compact cards after the outline is finalized and the theme
is selected (or confirmed).

Each card shows:
- Slide number + layout label in header bar
- Action title (the thesis sentence)
- Visual form indicator (chart, table, stat callout, image placeholder, etc.)
- Body content preview (first 2 lines or structural description)

A summary footer shows total count and ghost deck test result.

### Template

```html
<style>
  :root { --bg: #FBFAF7; --surface: #F1EEE7; --title: #1C2430; --body: #2E3947; --muted: #5C6878; --accent: #1F5C8B; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--body); padding: 16px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 10px; }
  .slide { background: var(--surface); border-radius: 8px; overflow: hidden; border: 1px solid rgba(0,0,0,0.06); }
  .slide-hdr { background: var(--accent); color: #fff; padding: 5px 10px; font-size: 11px; font-weight: 600; display: flex; justify-content: space-between; }
  .slide-bd { padding: 10px; min-height: 80px; }
  .slide-title { font-size: 12px; font-weight: 700; color: var(--title); margin-bottom: 4px; line-height: 1.3; }
  .slide-visual { font-size: 10px; color: var(--accent); font-style: italic; margin-top: 4px; }
  .slide-meta { font-size: 9px; color: var(--muted); margin-top: 4px; }
  .summary { margin-top: 14px; padding: 10px 14px; background: var(--surface); border-radius: 8px; font-size: 12px; color: var(--body); display: flex; justify-content: space-between; align-items: center; }
  .pass { color: #2E7D32; font-weight: 600; }
  .fail { color: #C62828; font-weight: 600; }
</style>

<div class="grid">
  <!-- One card per slide. Populate from the approved outline. -->
  <div class="slide">
    <div class="slide-hdr"><span>1</span><span>cover</span></div>
    <div class="slide-bd">
      <div class="slide-title">Q3 Revenue grew 34% on 22% headcount</div>
      <div class="slide-visual">[stat callout + accent bar]</div>
      <div class="slide-meta">layout: title-only</div>
    </div>
  </div>

  <div class="slide">
    <div class="slide-hdr"><span>2</span><span>content</span></div>
    <div class="slide-bd">
      <div class="slide-title">Growth came from enterprise, not SMB</div>
      <div class="slide-visual">[column chart: revenue by segment]</div>
      <div class="slide-meta">layout: title+content</div>
    </div>
  </div>
</div>

<div class="summary">
  <span>10 slides &middot; <span class="pass">Ghost deck: PASS</span></span>
  <span>Theme: Ledger &middot; Mode: argument-first</span>
</div>
```

### Agent call

```
show_widget(
  title="slide_preview",
  loading_messages=["Rendering slide grid...", "Applying theme colors..."],
  widget_code=<html above>,
  i_have_seen_read_me=True,
  width=1100,
  height=800,
)
```

### Handling feedback

After the slide grid renders, the user may:
- **Confirm** ("OK", "looks good", "duyet") -- proceed to Phase 3
- **Request changes** ("slide 3 needs a table not a chart") -- adjust outline,
  rebuild preview, show again
- **Skip** ("just build it") -- proceed to Phase 3 directly

---

## Preview type 3: Style comparison (optional)

Use when the deck topic fits multiple visual approaches. Shows 2-3 miniature
slide samples (cover + one content slide) with different styles applied.

### Template

```html
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: #f5f5f5; padding: 16px; }
  .row { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
  .approach { background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
  .approach-hdr { padding: 14px 16px 8px; font-size: 14px; font-weight: 700; color: #1a1a1a; }
  .approach-desc { padding: 0 16px 10px; font-size: 12px; color: #666; }
  .mini-slide { margin: 0 16px 12px; border-radius: 6px; padding: 16px; min-height: 100px; }
  .mini-title { font-weight: 700; margin-bottom: 6px; }
  .mini-body { font-size: 11px; line-height: 1.4; }
  .pick-btn { display: block; width: calc(100% - 32px); margin: 0 16px 16px; padding: 10px; border: none; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; }
</style>

<div class="row">
  <div class="approach">
    <div class="approach-hdr">Argument-first</div>
    <div class="approach-desc">Light ground, one accent, no decorative imagery</div>
    <div class="mini-slide" style="background:#FBFAF7; color:#1C2430;">
      <div class="mini-title" style="color:#1C2430;">Q3 Revenue grew 34%</div>
      <div class="mini-body" style="color:#2E3947;">Every product line beat plan; hiring stayed flat.</div>
    </div>
    <div class="mini-slide" style="background:#F1EEE7; color:#1C2430;">
      <div class="mini-title" style="color:#1C2430; font-size:12px;">Growth by segment</div>
      <div class="mini-body" style="color:#5C6878;">[chart placeholder: clean, data-forward]</div>
    </div>
    <button class="pick-btn" style="background:#1F5C8B; color:#fff;" onclick="sendPrompt('Style: argument-first')">Use argument-first</button>
  </div>

  <div class="approach">
    <div class="approach-hdr">Visual-first</div>
    <div class="approach-desc">Hero imagery, bold typography, dark accents</div>
    <div class="mini-slide" style="background:#0B0A14; color:#FFFFFF;">
      <div class="mini-title" style="color:#FFFFFF;">Q3 Revenue grew 34%</div>
      <div class="mini-body" style="color:#DCD7EC;">[hero image placeholder behind text]</div>
    </div>
    <div class="mini-slide" style="background:#181528; color:#FFFFFF;">
      <div class="mini-title" style="color:#FFFFFF; font-size:12px;">Growth by segment</div>
      <div class="mini-body" style="color:#A199C0;">[chart on dark bg + accent glow]</div>
    </div>
    <button class="pick-btn" style="background:#B57BFF; color:#fff;" onclick="sendPrompt('Style: visual-first')">Use visual-first</button>
  </div>
</div>

<script>
function sendPrompt(p) {
  window.parent.postMessage({ type: 'widget_send_prompt', prompt: p }, '*');
}
</script>
```

---

## HTML size budget

Keep total HTML under 8KB for responsive streaming (500-char chunks).

| Component | Size estimate |
|-----------|--------------|
| Theme card (1 card) | ~1.5 KB |
| Theme picker (3 cards) | ~4.5 KB |
| Slide card (1 card) | ~400 B |
| Slide grid (12 slides) | ~5 KB |
| Style approach (1 card) | ~1.2 KB |
| Style comparison (2 cards) | ~2.5 KB |

## Constraints

- `show_widget` width: 200-1200px. Height: 150-900px (initial, auto-grows).
- Max rendered content height: 2400px (WidgetRenderer clamp).
- HTML must not include `<!DOCTYPE>`, `<html>`, `<head>`, `<body>` tags.
- CSS variables for dark mode: use `var(--color-*)` or card-level overrides.
- JavaScript only via `sendPrompt()` for widget-to-chat communication.
- Streaming-first: `<style>` first, content middle, `<script>` last.

## Fallback

When `show_widget` is unavailable or the user skips preview, the pipeline
continues with the existing text-based `ask_user` flow from `interview.md`.
No regression in capability.
