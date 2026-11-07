// Exact pages: the engine converts an Office file to PDF with the LibreOffice
// runtime (`office_preview` → `{kind: "pdf"}`), and this turns the PDF into
// the same preview document v3's `_render_pdf_document`
// (app/services/document_preview/service.py) served: one
// `<article data-preview-item>` per page holding a `.pdf-page-surface` with
// the page image and a `.pdf-text-layer` of positioned, transparent text runs,
// so search, thumbnails and area selection work on exact pages as on native
// ones. v3 drew the pages with pdfium on the server; here pdf.js draws them,
// with v3's limits (120 dpi, 80 pages, 24 MB of images, 10 Mpx per page).

import * as pdfjs from "pdfjs-dist";
import type { PDFPageProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

const DPI = 120;
const MAX_PAGES = 80;
const MAX_RASTER_BYTES = 24 * 1024 * 1024;
const MAX_PIXELS_PER_PAGE = 10_000_000;
const MAX_CHARS_PER_PAGE = 40_000;

/** The CSP every preview document carries (v3 `DOCUMENT_PREVIEW_CSP`, crates/evo-office/src/preview/mod.rs). */
const DOCUMENT_PREVIEW_CSP =
  "default-src 'none'; base-uri 'none'; connect-src 'none'; font-src data:; form-action 'none'; frame-src 'none'; img-src data: blob:; media-src data: blob:; object-src 'none'; script-src 'none'; style-src 'unsafe-inline'";

const CSS = `
*{box-sizing:border-box}body{margin:0;padding:28px;background:#e5e7eb;
color:#242424;font-family:Arial,sans-serif}.pdf-page-wrap{position:relative;
width:min(960px,94vw);margin:0 auto 28px}.pdf-page-surface{position:relative;
container-type:inline-size;background:#fff;box-shadow:0 2px 14px #0003}
.pdf-page{display:block;width:100%;height:auto}.pdf-page-number{
position:absolute;right:calc(100% + 9px);top:0;color:#616161;font-size:12px}
.pdf-text-layer{position:absolute;inset:0;overflow:hidden;line-height:1}
.pdf-text-layer span{position:absolute;color:transparent;white-space:pre;
overflow:hidden;cursor:text}.pdf-text-layer ::selection{background:#2563eb44}
.pdf-text-layer mark{color:transparent;opacity:.55}
.slide-notes-metadata{display:none!important}
.pdf-preview-limit{max-width:720px;margin:20px auto;padding:14px 18px;border-radius:8px;
background:#fff4ce;color:#5c2e00;box-shadow:0 1px 4px #0002}
`;

const ESCAPES: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" };
const escape = (text: string) => text.replace(/[&<>"']/g, (c) => ESCAPES[c]);
const fixed = (value: number, digits: number) => (Number.isFinite(value) ? value : 0).toFixed(digits);

/** One page's label and speaker notes (v3 `_office_page_labels`). */
export type PageLabel = [label: string, notes: string];

interface TextRun {
  text: string;
  left: number;
  top: number;
  width: number;
  height: number;
  /** Percent of the page width (CSS `cqw`). */
  fontSize: number;
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error("could not read the page image"));
    reader.readAsDataURL(blob);
  });
}

async function pageImage(page: PDFPageProxy): Promise<Blob> {
  const base = page.getViewport({ scale: 1 });
  let scale = DPI / 72;
  const pixels = base.width * base.height * scale * scale;
  if (!Number.isFinite(pixels) || pixels <= 0) throw new Error("PDF page has invalid dimensions");
  if (pixels > MAX_PIXELS_PER_PAGE) scale *= Math.sqrt(MAX_PIXELS_PER_PAGE / pixels);
  const viewport = page.getViewport({ scale });
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.floor(viewport.width));
  canvas.height = Math.max(1, Math.floor(viewport.height));
  try {
    await page.render({ canvas, viewport }).promise;
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
    if (!blob) throw new Error("could not encode the page image");
    return blob;
  } finally {
    // Free the bitmap now rather than at the next garbage collection.
    canvas.width = 0;
    canvas.height = 0;
  }
}

/** Positioned text runs in percent of the page box (v3 `pdf_text_layers`), or `null` when unreadable. */
async function textLayer(page: PDFPageProxy): Promise<{ width: number; height: number; runs: TextRun[] } | null> {
  const viewport = page.getViewport({ scale: 1 });
  const { width, height } = viewport;
  if (width <= 0 || height <= 0) return null;
  try {
    const content = await page.getTextContent();
    const runs: TextRun[] = [];
    let budget = MAX_CHARS_PER_PAGE;
    for (const item of content.items) {
      if (!("str" in item)) continue;
      const text = item.str.replace(/\r/g, "").replace(/\n/g, " ");
      if (!text.trim()) continue;
      const tx = pdfjs.Util.transform(viewport.transform, item.transform) as number[];
      const boxHeight = Math.hypot(tx[2], tx[3]);
      const boxWidth = item.width * viewport.scale;
      if (boxHeight <= 0 || boxWidth <= 0) continue;
      budget -= text.length;
      if (budget < 0) break;
      // tx[5] is the baseline; the run's box rises one font height above it.
      const top = tx[5] - boxHeight;
      runs.push({
        text,
        left: (100 * tx[4]) / width,
        top: (100 * top) / height,
        width: (100 * boxWidth) / width,
        height: (100 * boxHeight) / height,
        fontSize: (100 * boxHeight * 0.86) / width,
      });
    }
    return { width, height, runs };
  } catch {
    // Pages still render; they just are not searchable or selectable.
    return null;
  }
}

/**
 * The exact-pages preview document for `pdf`. `renderer` lands on
 * `<main data-preview-renderer>` ("libreoffice-<version>"), which the viewer
 * and the area selection read to tell exact pages from the native render.
 */
export async function exactPagesHtml(
  pdf: ArrayBuffer,
  {
    title,
    renderer,
    labels,
    itemName = "Page",
  }: {
    title: string;
    renderer: string;
    /** Used only when there is one per page (v3); otherwise pages are "<itemName> N". */
    labels?: PageLabel[] | null;
    itemName?: string;
  },
): Promise<string> {
  const loading = pdfjs.getDocument({ data: new Uint8Array(pdf) });
  const doc = await loading.promise;
  try {
    const totalPages = doc.numPages;
    const named = labels && labels.length === totalPages ? labels : null;
    const rendered: string[] = [];
    let rasterBytes = 0;
    let shown = 0;
    for (let number = 1; number <= Math.min(totalPages, MAX_PAGES); number++) {
      const page = await doc.getPage(number);
      try {
        const image = await pageImage(page);
        if (rasterBytes + image.size > MAX_RASTER_BYTES) break;
        rasterBytes += image.size;
        const encoded = await blobToDataUrl(image);
        const layer = await textLayer(page);
        const [label, notes] = named ? named[number - 1] : [`${itemName} ${number}`, ""];
        const aspect = layer ? ` style="aspect-ratio:${fixed(layer.width, 2)}/${fixed(layer.height, 2)}"` : "";
        const textHtml = layer
          ? layer.runs
              .map(
                (run) =>
                  `<span style="left:${fixed(run.left, 3)}%;top:${fixed(run.top, 3)}%;width:${fixed(run.width, 3)}%;height:${fixed(run.height, 3)}%;font-size:${fixed(run.fontSize, 3)}cqw">${escape(run.text)}</span>`,
              )
              .join("")
          : "";
        const notesHtml = notes
          ? `<span class="slide-notes-metadata" hidden aria-hidden="true" data-preview-notes="${escape(notes)}">${escape(notes)}</span>`
          : "";
        rendered.push(
          `<article class="pdf-page-wrap" data-preview-item data-preview-label="${escape(label)}" data-page-index="${number - 1}">` +
            `<span class="pdf-page-number">${number}</span>` +
            `<div class="pdf-page-surface"${aspect}>` +
            `<img class="pdf-page" src="${encoded}" alt="${escape(label)}">` +
            `<div class="pdf-text-layer">${textHtml}</div></div>` +
            `${notesHtml}</article>`,
        );
        shown = number;
      } finally {
        page.cleanup();
      }
    }
    if (shown < totalPages) {
      rendered.push(
        `<p class="pdf-preview-limit" role="status">Preview shows ${shown} of ${totalPages} pages. ` +
          "Open the document in its app to inspect the remaining pages.</p>",
      );
    }
    return (
      '<!doctype html><html><head><meta charset="utf-8">' +
      `<meta http-equiv="Content-Security-Policy" content="${escape(DOCUMENT_PREVIEW_CSP)}">` +
      '<meta name="referrer" content="no-referrer">' +
      `<title>${escape(title)}</title><style>${CSS}</style></head>` +
      `<body><main data-preview-renderer="${escape(renderer)}">${rendered.join("")}</main></body></html>`
    );
  } finally {
    void loading.destroy();
  }
}
