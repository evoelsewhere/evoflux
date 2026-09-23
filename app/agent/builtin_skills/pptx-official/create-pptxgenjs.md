# Creating a .pptx with PptxGenJS

PptxGenJS is a JavaScript/TypeScript API that emits PPTX files. Use it for
design-heavy custom layouts that need more shape and chart primitives than
python-pptx exposes.

## Contents

- Project setup and running
- Skeleton
- Text
- Shapes and shadows
- Images
- Icons (react-icons → PNG)
- Charts
- Tables: border tuples, three-line academic table
- Slide masters
- PptxGenJS pitfalls (things that silently corrupt the file)
- Quick reference (PptxGenJS enums)
- After you generate

## Project setup and running

Work in a Bun project in the user's workspace (`bun init -y` when there is no
`package.json`; the full setup, including `tsconfig.json`, is in `setup.md`).
Add the libraries project-locally:

```bash
bun add pptxgenjs
# for icon rasterization:
bun add react-icons react react-dom sharp
# for math formulas (sharp is shared with the icon pipeline above):
bun add mathjax-full
```

Run the generator with `bun run build_deck.ts`, and type-check after every
change with `bun tsc --noEmit` — it catches outdated PptxGenJS signatures
before runtime.

## Skeleton

```typescript
import pptxgen from "pptxgenjs";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";          // 13.33" × 7.5" (16:9)
pres.author = "Your Name";
pres.title = "Q3 Product Review";

const slide = pres.addSlide();
slide.background = { color: "1F3A5F" };
slide.addText("Revenue grew 34% on 22% headcount", {
  x: 0.5, y: 3.0, w: 12.3, h: 1.5,
  fontSize: 40, bold: true, color: "FFFFFF", align: "left",
});

await pres.writeFile({ fileName: "review.pptx" });
```

Available `pres.layout` values: `LAYOUT_16x9` (10 × 5.625), `LAYOUT_WIDE`
(13.333 × 7.5), `LAYOUT_16x10` (10 × 6.25), `LAYOUT_4x3` (10 × 7.5). Use
`LAYOUT_WIDE` for anything modern.

## Text

```typescript
// simple
slide.addText("Body copy", {
  x: 0.5, y: 1.5, w: 8, h: 1,
  fontSize: 18, color: "1F1F1F", align: "left", valign: "top",
  fontFace: "Calibri",
});

// rich text with mixed formatting
slide.addText([
  { text: "Growth: ", options: { bold: true } },
  { text: "34% YoY", options: { color: "0D9488" } },
  { text: " on flat headcount.", options: {} },
], { x: 0.5, y: 2.6, w: 12, h: 0.6, fontSize: 20 });

// multi-line text (requires breakLine: true)
slide.addText([
  { text: "Line 1", options: { breakLine: true } },
  { text: "Line 2", options: { breakLine: true } },
  { text: "Line 3" },
], { x: 0.5, y: 3.5, w: 12, h: 2, fontSize: 18 });

// character spacing (use charSpacing, not letterSpacing which is silently ignored)
slide.addText("SPACED TEXT", { x: 1, y: 1, w: 8, h: 1, charSpacing: 6 });

// text box margin (internal padding)
slide.addText("Title", {
  x: 0.5, y: 0.3, w: 9, h: 0.6,
  margin: 0,  // Use 0 when aligning text with other elements like shapes or icons
});
```

**Tip:** Text boxes have internal margin by default. Set `margin: 0` when
you need text to align precisely with shapes, lines, or icons at the same
x-position.

Never mix a hard-coded bullet glyph (`"• Item"`) with `bullet: true`. The
result is two bullets — and see the pitfalls below for why `bullet: true` is
best avoided altogether.

## Shapes and shadows

```typescript
slide.addShape(pres.ShapeType.rect, {
  x: 0.5, y: 0.5, w: 3, h: 1.5,
  fill: { color: "F7F5F0" },
  line: { color: "1F3A5F", width: 1 },
});

slide.addShape(pres.ShapeType.roundRect, {
  x: 0.5, y: 2.5, w: 3, h: 1.5,
  fill: { color: "FFFFFF" },
  line: { type: "none" },
  rectRadius: 0.1,
});

slide.addShape(pres.ShapeType.ellipse, {
  x: 4.5, y: 2.5, w: 1.2, h: 1.2,
  fill: { color: "0D9488" },
});

// with transparency
slide.addShape(pres.ShapeType.rect, {
  x: 1, y: 1, w: 3, h: 2,
  fill: { color: "0088CC", transparency: 50 },
});

// with shadow
slide.addShape(pres.ShapeType.rect, {
  x: 1, y: 1, w: 3, h: 2,
  fill: { color: "FFFFFF" },
  shadow: { type: "outer", color: "000000", blur: 6, offset: 2, angle: 135, opacity: 0.15 },
});
```

Shadow options:

| Property | Type | Range | Notes |
|----------|------|-------|-------|
| `type` | string | `"outer"`, `"inner"` | |
| `color` | string | 6-char hex (e.g. `"000000"`) | No `#` prefix, no 8-char hex — see pitfalls |
| `blur` | number | 0-100 pt | |
| `offset` | number | 0-200 pt | **Must be non-negative** — negative values corrupt the file |
| `angle` | number | 0-359 degrees | Direction the shadow falls (135 = bottom-right, 270 = upward) |
| `opacity` | number | 0.0-1.0 | Use this for transparency, never encode in color string |

To cast a shadow upward (e.g. on a footer bar), use `angle: 270` with a
positive offset — do **not** use a negative offset.

## Images

```typescript
// from disk
slide.addImage({ path: "chart.png",  x: 0.5, y: 1.5, w: 6, h: 4 });

// from URL (fetched at generate time — needs network)
slide.addImage({ path: "https://example.com/logo.png",
                 x: 12, y: 0.3, w: 1, h: 0.5 });

// from base64 (fastest, no I/O)
slide.addImage({ data: "image/png;base64,iVBORw0KGg...", x: 0.5, y: 1.5, w: 5, h: 3 });

// sized to fit inside a box, preserving aspect
slide.addImage({ path: "photo.jpg", x: 1, y: 1, sizing: { type: "contain", w: 6, h: 4 } });

// sized to cover a box, cropping if needed
slide.addImage({ path: "photo.jpg", x: 1, y: 1, sizing: { type: "cover",   w: 6, h: 4 } });
```

Formats that render everywhere: PNG, JPG, GIF. SVG works in modern
PowerPoint but not consistently in older LibreOffice — rasterize to PNG
if the deck has to survive every viewer.

**Always check image dimensions before inserting.** Setting both `w` and `h`
without matching the source aspect ratio will stretch or squash the image.
Either use `sizing: { type: "contain" }` / `"cover"`, or compute the correct
dimensions from the source:

```typescript
import sharp from "sharp";

// maxW, maxH in inches — matches PptxGenJS coordinate system
async function fitImage(imagePath: string, maxW: number, maxH: number) {
  const meta = await sharp(imagePath).metadata();
  const srcW = meta.width ?? 1;
  const srcH = meta.height ?? 1;
  const scale = Math.min(maxW / srcW, maxH / srcH);
  return { w: srcW * scale, h: srcH * scale };
}

// Usage: preserve aspect ratio within a 6" × 4" box
const { w, h } = await fitImage("photo.png", 6, 4);
slide.addImage({ path: "photo.png", x: 1, y: 1, w, h });
```

## Icons (react-icons → PNG)

```typescript
import React from "react";
import ReactDOMServer from "react-dom/server";
import sharp from "sharp";
import { FaCheckCircle, FaChartLine } from "react-icons/fa";

async function iconPng(
  Icon: React.ComponentType<{ color?: string; size?: string }>,
  color = "0D9488",
  pixelSize = 256,
): Promise<string> {
  const svg = ReactDOMServer.renderToStaticMarkup(
    React.createElement(Icon, { color: "#" + color, size: String(pixelSize) })
  );
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

// Usage
const okData = await iconPng(FaCheckCircle, "0D9488", 256);
slide.addImage({ data: okData, x: 0.5, y: 3, w: 0.5, h: 0.5 });
```

`pixelSize` controls rasterization sharpness, not the on-slide display size.
Use 256 or higher; the on-slide size is `w`/`h` in inches.

Install: `bun add react-icons react react-dom sharp`

## Charts

```typescript
slide.addChart(pres.ChartType.bar, [{
  name: "Revenue",
  labels: ["Q1", "Q2", "Q3", "Q4"],
  values: [3.1, 3.9, 4.6, 5.4],
}], {
  x: 0.5, y: 1, w: 12, h: 5,
  barDir: "col",
  showTitle: true, title: "Revenue by quarter",
  chartColors: ["0D9488"],
  showLegend: false,
  catAxisLabelColor: "64748B",
  valAxisLabelColor: "64748B",
  valGridLine: { color: "E2E8F0", size: 0.5 },
  catGridLine: { style: "none" },
  showValue: true,
  dataLabelPosition: "outEnd",
});
```

Supported chart families: `pres.ChartType.bar`, `.line`, `.pie`,
`.doughnut`, `.scatter`, `.bubble`, `.radar`, `.area`.

## Tables

```typescript
slide.addTable([
  [
    { text: "Metric", options: { bold: true, fill: { color: "1F3A5F" }, color: "FFFFFF" } },
    { text: "Q2",     options: { bold: true, fill: { color: "1F3A5F" }, color: "FFFFFF" } },
    { text: "Q3",     options: { bold: true, fill: { color: "1F3A5F" }, color: "FFFFFF" } },
  ],
  ["Revenue",       "$4.2M", "$5.6M"],
  ["Gross margin",  "62%",   "65%"],
  ["Headcount",     "48",    "51"],
], {
  x: 0.5, y: 1.5, w: 12, colW: [6, 3, 3],
  fontSize: 14, border: { pt: 1, color: "E5E7EB" },
});
```

### Border tuple order

When using per-side borders, the tuple order is **`[top, right, bottom, left]`** (clockwise from top):

```typescript
const bNone = { pt: 0, color: "FFFFFF" };
type Border = { pt: number; color: string };
const bTuple = (...args: Border[]) => args as [Border, Border, Border, Border];

// Header row: thick top, thin bottom
{
  border: bTuple(
    { pt: 1.5, color: "333333" },  // top — thick
    bNone,                          // right — none
    { pt: 0.5, color: "333333" },  // bottom — thin
    bNone,                          // left — none
  )
}
```

### Three-line table (academic style)

A common academic/benchmark table style with only three horizontal lines:

```typescript
const bNone = { pt: 0, color: "FFFFFF" };
type Border = { pt: number; color: string };
const bTuple = (...args: Border[]) => args as [Border, Border, Border, Border];

// 1. Header: thick top + thin bottom
const hdrOpts = () => ({
  bold: true, fontSize: 11, fontFace: "Calibri", color: "333333",
  align: "center" as const, valign: "middle" as const,
  border: bTuple({ pt: 1.5, color: "333333" }, bNone, { pt: 0.5, color: "333333" }, bNone),
});

// 2. Body cells: no borders
const cellOpts = () => ({
  fontSize: 11, fontFace: "Calibri", color: "555555",
  align: "center" as const, valign: "middle" as const,
  border: bTuple(bNone, bNone, bNone, bNone),
});

// 3. Last row: thick bottom
const lastOpts = () => ({
  fontSize: 11, fontFace: "Calibri", color: "555555",
  align: "center" as const, valign: "middle" as const,
  border: bTuple(bNone, bNone, { pt: 1.5, color: "333333" }, bNone),
});
```

**Pattern**: Top line (thick) → header bottom line (thin) → body with no lines → bottom line (thick).

Usage:

```typescript
const rows = [
  [{ text: "Method", options: hdrOpts() }, { text: "Acc (%)", options: hdrOpts() }],
  [{ text: "Ours",   options: cellOpts() }, { text: "94.2",   options: cellOpts() }],
  [{ text: "Baseline", options: lastOpts() }, { text: "89.1", options: lastOpts() }],
];
slide.addTable(rows, { x: 1, y: 1.5, w: 8, colW: [5, 3] });
```

## Slide masters

Define once, apply repeatedly:

```typescript
pres.defineSlideMaster({
  title: "SECTION_DIVIDER",
  background: { color: "1F3A5F" },
  objects: [
    { placeholder: { options: { name: "title", type: "title",
                                x: 0.5, y: 3, w: 12.3, h: 1.5,
                                fontSize: 44, bold: true, color: "FFFFFF" },
                     text: "" } },
  ],
});

const s = pres.addSlide({ masterName: "SECTION_DIVIDER" });
s.addText("Part 2 — What's Next", { placeholder: "title" });
```

## PptxGenJS pitfalls (things that silently corrupt the file)

- **`#` prefix on hex colors** — `color: "#FF0000"` corrupts the file.
  Always use bare hex: `"FF0000"`.
- **8-character hex to fake alpha** — corrupts the file. Use the
  `transparency: 0-100` property on `fill`, or the `opacity: 0.0-1.0`
  property on shadow.
- **Reusing option objects across calls** — PptxGenJS mutates option
  objects in-place (converting inches to EMU, hex to Office xml). Sharing
  one `{ shadow: {...} }` between two calls corrupts the second call.
  Factory the object:
  ```typescript
  const makeShadow = () => ({ type: "outer", color: "000000", blur: 6, offset: 2, angle: 135, opacity: 0.15 });
  slide.addShape(pres.ShapeType.rect, { x:1, y:1, w:3, h:2, fill:{color:"FFFFFF"}, shadow: makeShadow() });
  slide.addShape(pres.ShapeType.rect, { x:5, y:1, w:3, h:2, fill:{color:"FFFFFF"}, shadow: makeShadow() });
  ```
- **Do NOT use `bullet: true`** — PptxGenJS's built-in bullet adds
  excessive, uncontrollable spacing between the bullet character and text,
  especially with mixed CJK/Latin content. Instead, create small filled
  circles as custom bullet shapes:
  ```typescript
  function addBulletItem(
    slide: pptxgen.Slide, pres: pptxgen,
    text: string, x: number, y: number, w: number, h: number,
    fontSize = 12,
  ) {
    const dotSize = 0.1;
    slide.addShape(pres.ShapeType.ellipse, {
      x, y: y + (h - dotSize) / 2, w: dotSize, h: dotSize,
      fill: { color: "8C1515" },  // your accent color
    });
    slide.addText(text, {
      x: x + 0.18, y, w: w - 0.18, h,
      fontSize, fontFace: "Arial", color: "2D2D2D",
      valign: "middle", margin: 0,
    });
  }
  ```
- **Avoid `lineSpacing` with bullets** — causes excessive gaps between
  items. Use `paraSpaceAfter` instead for controlled spacing.
- **`ROUNDED_RECTANGLE` with accent borders** — rectangular overlay bars
  (used as left-side accents) won't cover rounded corners. Use `RECTANGLE`
  instead when you need accent-bar overlays:
  ```typescript
  // WRONG: accent bar doesn't cover rounded corners
  slide.addShape(pres.ShapeType.roundRect, { x: 1, y: 1, w: 3, h: 1.5, fill: { color: "FFFFFF" } });
  slide.addShape(pres.ShapeType.rect, { x: 1, y: 1, w: 0.08, h: 1.5, fill: { color: "0891B2" } });

  // CORRECT: use RECTANGLE for clean alignment
  slide.addShape(pres.ShapeType.rect, { x: 1, y: 1, w: 3, h: 1.5, fill: { color: "FFFFFF" } });
  slide.addShape(pres.ShapeType.rect, { x: 1, y: 1, w: 0.08, h: 1.5, fill: { color: "0891B2" } });
  ```
- **Unicode bullet glyphs with `bullet: true`** — you get a double bullet.
  Pick one.
- **`rectRadius` on `RECTANGLE`** — ignored silently. Use
  `ROUNDED_RECTANGLE` (`pres.ShapeType.roundRect`).
- **Negative shadow `offset`** — corrupts the file. Cast the shadow upward
  with `angle: 270` and a **positive** offset.
- **Each presentation needs a fresh instance** — don't reuse `pptxgen()`
  objects across multiple decks.

## Quick reference (PptxGenJS enums)

- **Shapes**: `pres.ShapeType.rect`, `.ellipse`, `.line`, `.roundRect`
- **Charts**: `pres.ChartType.bar`, `.line`, `.pie`, `.doughnut`, `.scatter`, `.bubble`, `.radar`, `.area`
- **Layouts**: `LAYOUT_16x9` (10"×5.625"), `LAYOUT_WIDE` (13.333"×7.5"), `LAYOUT_16x10`, `LAYOUT_4x3`
- **Table border tuple**: `[top, right, bottom, left]` (clockwise from top)
- **Math formulas**: `mathjax-full` → `mjDoc.convert(latex)` → `adaptor.innerHTML()` → sharp PNG (full recipe in `pptxgenjs-math.md`)
- **SVG scaling**: `sharp(buf, { density: 72 * scale })` — don't use `resize({ scale })`

## After you generate

Always run the QA checklist from `SKILL.md` — even three-slide decks fail QA
more often than you'd think. Assume something is wrong; find it.
