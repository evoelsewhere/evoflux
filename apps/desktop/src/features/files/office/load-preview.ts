// Fetch one preview of an Office file from the engine (RPC `office_preview`,
// crates/evo-engine/src/office.rs; docs/features/office-v3-parity/plan.md §3.3)
// and turn it into the HTML document the viewer shows: the engine's cached
// native render as it is, or its exact-pages PDF turned into v3's exact-pages
// document (exact-pages.ts).

import { readBytes } from "../fs";
import { useEngineStore } from "@/stores/engine-store";
import { previewItems } from "./document-thumbnail";
import type { OfficeKind } from "./kinds";
import type { PageLabel } from "./exact-pages";

/** v3 `MAX_PREVIEW_RESPONSE_BYTES`. */
const MAX_PREVIEW_BYTES = 36 * 1024 * 1024;
const TOO_LARGE = "This preview is too large for the in-app viewer. Open the file in its app to inspect it.";

export type PreviewMode = "native" | "exact" | "auto";

type PreviewReply =
  | { kind: "html"; path: string; renderer: string; live?: boolean; fallback?: boolean }
  | { kind: "pdf"; path: string; renderer: string };

/** The engine predates `office_preview`: the viewer falls back to LibreOffice pages. */
export class PreviewUnsupported extends Error {}

const request = (path: string, mode: PreviewMode) =>
  useEngineStore.getState().request<PreviewReply>("office_preview", { path, mode });

async function readHtml(path: string): Promise<string> {
  const bytes = await readBytes(path);
  if (bytes.byteLength > MAX_PREVIEW_BYTES) throw new Error(TOO_LARGE);
  return new TextDecoder().decode(bytes);
}

function slideNotes(element: HTMLElement): string {
  const inline = element.dataset.previewNotes?.trim();
  if (inline) return inline;
  return element.querySelector<HTMLElement>("[data-preview-notes]")?.textContent?.trim() ?? "";
}

/**
 * Page labels for exact pages (v3 `_office_page_labels`): slide titles and
 * notes for a deck, sheet names for a workbook, read from the native render.
 * `null` when they cannot be had (the pages are then "Page N").
 */
async function pageLabels(path: string, kind: OfficeKind): Promise<PageLabel[] | null> {
  if (kind === "docx") return null;
  try {
    const reply = await request(path, "native");
    if (reply.kind !== "html") return null;
    const document = new DOMParser().parseFromString(await readHtml(reply.path), "text/html");
    const items = previewItems(document).filter((item) => item !== document.body);
    return items.map((item, index) => [
      item.dataset.previewLabel || `${kind === "pptx" ? "Slide" : "Sheet"} ${index + 1}`,
      kind === "pptx" ? slideNotes(item) : "",
    ]);
  } catch {
    return null;
  }
}

/** Exact-pages documents already built, by PDF (the engine names its cached PDFs by content). */
const exactCache = new Map<string, string>();
const EXACT_CACHE_ENTRIES = 4;

export interface LoadedPreview {
  html: string;
  /** "native", "native-live" or "libreoffice-<version>". */
  renderer: string;
}

/** The preview document for `path` in `mode`. Rejects with the engine's message (or `PreviewUnsupported`). */
export async function loadPreview(path: string, kind: OfficeKind, mode: PreviewMode, title: string): Promise<LoadedPreview> {
  let reply: PreviewReply;
  try {
    reply = await request(path, mode);
  } catch (error) {
    if (/unknown command type/i.test(String(error))) throw new PreviewUnsupported(String(error));
    throw error;
  }
  if (reply.kind === "html") return { html: await readHtml(reply.path), renderer: reply.renderer };

  const cached = exactCache.get(reply.path);
  if (cached) return { html: cached, renderer: reply.renderer };
  const [pdf, labels] = await Promise.all([readBytes(reply.path), pageLabels(path, kind)]);
  const { exactPagesHtml } = await import("./exact-pages");
  const itemName = kind === "pptx" ? "Slide" : kind === "xlsx" ? "Sheet" : "Page";
  const html = await exactPagesHtml(pdf, { title, renderer: reply.renderer, labels, itemName });
  if (html.length > MAX_PREVIEW_BYTES) throw new Error(TOO_LARGE);
  exactCache.set(reply.path, html);
  while (exactCache.size > EXACT_CACHE_ENTRIES) exactCache.delete(exactCache.keys().next().value as string);
  return { html, renderer: reply.renderer };
}
