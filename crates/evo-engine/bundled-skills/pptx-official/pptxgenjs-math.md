# Math formulas in PptxGenJS (MathJax → PNG)

Use `mathjax-full` to render LaTeX formulas to SVG, then rasterize to PNG via
`sharp` and place the PNG with `slide.addImage`. Install project-locally with
`bun add mathjax-full sharp`, run the generator with `bun run build_deck.ts`,
and type-check with `bun tsc --noEmit`.

```typescript
import { mathjax } from "mathjax-full/js/mathjax.js";
import { TeX } from "mathjax-full/js/input/tex.js";
import { SVG } from "mathjax-full/js/output/svg.js";
import { liteAdaptor } from "mathjax-full/js/adaptors/liteAdaptor.js";
import { RegisterHTMLHandler } from "mathjax-full/js/handlers/html.js";
import sharp from "sharp";

const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);

const mjDoc = mathjax.document("", {
  InputJax: new TeX(),
  OutputJax: new SVG({ fontCache: "none" }),
});

async function texToPng(latex: string, scale = 2): Promise<{ data: string; w: number; h: number }> {
  const node = mjDoc.convert(latex, { display: true });
  const svgStr = adaptor.innerHTML(node);  // NOT outerHTML — wraps in <mjx-container>
  const density = 72 * scale;
  const pngBuf = await sharp(Buffer.from(svgStr), { density }).png().toBuffer();
  const meta = await sharp(pngBuf).metadata();
  return {
    data: "image/png;base64," + pngBuf.toString("base64"),
    w: (meta.width ?? 100) / density,   // pixels ÷ render density = inches
    h: (meta.height ?? 20) / density,
  };
}

// Usage
const { data, w: imgW, h: imgH } = await texToPng("E = mc^2", 3);
const imgX = 0.5 + (9.0 - imgW) / 2;  // center horizontally
slide.addImage({ data, x: imgX, y: 1.5, w: imgW, h: imgH });
```

**Key notes:**
- Use `adaptor.innerHTML()`, not `adaptor.outerHTML()` — outerHTML wraps the SVG in a `<mjx-container>` element that sharp cannot parse.
- Use `density` option in sharp to scale SVGs: `sharp(buf, { density: 72 * scale })`. Do NOT use `resize({ scale })` — sharp's `ResizeOptions` has no `scale` property.
- Get actual pixel dimensions from PNG metadata via `sharp(buf).metadata()` — don't parse SVG viewBox (those are internal coordinate units, not pixels).
- Divide pixel dimensions by the same density used for rendering to get inches: `meta.width / density`. This keeps `scale` as a pure sharpness knob without changing the on-slide size.
- `scale=3` (density 216) produces crisp formulas for projection. `scale=2` (density 144) is sufficient for screen viewing.
