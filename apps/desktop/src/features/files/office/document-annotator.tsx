// DeckAnnotator: select part of a slide or sheet in the Files viewer and tell
// the agent what to change there (docs/features/office-v3-parity/spec.md,
// FR-10; port of v3 web/src/components/document-annotator.tsx).
//
// While annotating, hovering a slide outlines the shape under the pointer
// (native render: every shape carries `data-shape-id`), a click selects it and
// a drag selects a free area — the only option on exact pages, which are
// pictures with a text layer. On a workbook's cell grid a click selects a cell
// and a drag a range of cells (`B3:D8`), sent with the sheet's name. A popover
// takes the instruction: send it now, or add it to the composer's batch and
// keep selecting. Batched selections stay pinned with their number; sent ones
// shimmer until the agent's turn ends (60 s if it never starts).
//
// All drawing happens inside the preview, positioned in percent of the slide
// so zoom, fit and scroll never skew it.
//
// ── Mounting it (the viewer) ────────────────────────────────────────────────
//
//   <div className="relative min-h-0 flex-1">        ← positioned: the popover sits in it
//     <iframe ref={frameRef} srcDoc={html} sandbox="allow-same-origin" … />
//     {canAnnotate && (
//       <DeckAnnotator frameRef={frameRef} frameKey={html} chatId={activeId}
//         file={path} active={annotating} onExit={() => setAnnotating(false)} />
//     )}
//   </div>
//
// Props (DeckAnnotatorProps below):
// - `frameRef`  the preview: an `<iframe>` whose document is same-origin
//               (`sandbox="allow-same-origin"`, no scripts), or an element of
//               this document that holds the pages (exact pages drawn here).
//               The annotator must be its sibling inside one positioned box.
// - `frameKey`  changes whenever the frame's document or the pages are
//               replaced (the HTML string, or the PDF path + mtime).
// - `chatId`    the chat whose composer collects the batch (engine-store
//               `activeId`; the engine calls go to that chat).
// - `file`      the document, absolute or relative to the chat's working
//               folder; annotations carry it relative to that folder.
// - `kind`      optional: "slides" | "pages" | "cells"; detected from the
//               markup when omitted (v3 rules).
// - `active`    annotate mode: the pointer selects instead of scrolling text.
// - `agentWorking` optional: whether the chat's turn runs (ends the shimmer);
//               defaults to the chat's `transcript.busy`.
// - `onExit`    "Done annotating" in the popover.
//
// The markup it reads (v3 contract): items `[data-preview-item]` (with
// `data-preview-label` for sheet names), surfaces `.slide` (not
// `.slide-skeleton`), `.pdf-page-surface` (with `.pdf-text-layer span` text)
// and `.sheet .grid-stage` (with `td[data-cell]`), shapes `[data-shape-id]`
// with `data-shape-name` / `data-qa-label` / `data-source-layer`. Surfaces
// must be positioned (`position: relative`): boxes are absolute children.

import * as React from "react";
import { ArrowUpIcon, MessageSquarePlusIcon, XIcon } from "lucide-react";
import {
  areaOf,
  cellRange,
  cleanText,
  describeAnnotation,
  overlapShare,
  parseCell,
  workspacePath,
  type AnnotationArea,
  type DocumentAnnotation,
} from "@/lib/document-annotations";
import { cn } from "@/lib/utils";
import { MAX_BATCH_ANNOTATIONS, useAnnotationsStore, usePendingAnnotations } from "@/stores/annotations-store";
import { useEngineStore } from "@/stores/engine-store";

// A slide, an exact page, or a sheet's cell grid.
const SURFACE = ".slide:not(.slide-skeleton), .pdf-page-surface, .sheet:not(.sheet-skeleton) .grid-stage";
const MAX_RANGE_TEXT_CELLS = 40;
const DRAG_THRESHOLD_PX = 4;
const MAX_AREA_SHAPES = 12;
/** Sent selections stop shimmering if the turn never starts. */
const SHIMMER_CAP_MS = 60_000;

/**
 * Boxes and cursors, injected into the preview. v3 used a fixed blue
 * (#1a73e8); evo has one accent, so the boxes take `--brand` (resolved here,
 * since the preview's document does not inherit the app's variables).
 */
function annotatorCss(accent: string, onAccent: string): string {
  const a = (percent: number) => `color-mix(in srgb,${accent} ${percent}%,transparent)`;
  return `
[data-evo-annotating] .slide,[data-evo-annotating] .pdf-page-surface{cursor:crosshair;user-select:none;-webkit-user-select:none}
[data-evo-annotating] .grid-stage{cursor:cell;user-select:none;-webkit-user-select:none}
[data-evo-anno]{position:absolute;pointer-events:none;box-sizing:border-box;z-index:2147483000;border-radius:3px}
[data-evo-anno="hover"]{outline:2px solid ${accent};background:${a(7)}}
[data-evo-anno="selection"]{outline:2px solid ${accent};box-shadow:0 0 0 4px ${a(18)};background:${a(5)}}
[data-evo-anno="drag"]{border:1.5px dashed ${accent};background:${a(10)}}
[data-evo-anno="pin"]{outline:1.5px solid ${a(70)};background:${a(4)}}
[data-evo-anno="pin"]::before,[data-evo-anno="working"]::before{content:attr(data-n);position:absolute;top:-9px;left:-9px;min-width:18px;height:18px;padding:0 5px;border-radius:9px;background:${accent};color:${onAccent};font:600 11px/18px Arial,sans-serif;text-align:center;box-shadow:0 1px 4px #0004}
[data-evo-anno="working"]{outline:2px solid ${accent};background:linear-gradient(100deg,transparent 30%,${a(30)} 50%,transparent 70%) 0 0/250% 100%;animation:evo-anno-work 1.8s ease-in-out infinite}
@keyframes evo-anno-work{0%{background-position:120% 0;box-shadow:0 0 0 0 ${a(40)}}50%{box-shadow:0 0 0 7px ${a(0)}}100%{background-position:-120% 0;box-shadow:0 0 0 0 ${a(0)}}}
@media (prefers-reduced-motion:reduce){[data-evo-anno="working"]{animation:none}}
`;
}

function appAccent(): { accent: string; onAccent: string } {
  const style = getComputedStyle(document.documentElement);
  return {
    accent: style.getPropertyValue("--brand").trim() || "#0072f5",
    onAccent: style.getPropertyValue("--brand-foreground").trim() || "#ffffff",
  };
}

interface Selection {
  slide: number;
  shapes: Array<{ id: number; name: string }>;
  area: AnnotationArea;
  text: string;
  /** Workbooks: the sheet's name and the selected cells ("B3" or "B3:D8"). */
  sheet?: string;
  range?: string;
}

interface Box {
  kind: "hover" | "selection" | "drag" | "pin" | "working";
  slide: number;
  area: AnnotationArea;
  n?: number;
}

/**
 * Where the preview lives: an iframe's own document, or an element of this
 * one. `root` is what is searched and listened to; `host` carries
 * `data-evo-annotating`; `frame` is the iframe whose box offsets coordinates.
 */
interface Scope {
  doc: Document;
  win: Window;
  root: Document | HTMLElement;
  host: HTMLElement;
  frame: HTMLIFrameElement | null;
}

function scopeOf(target: HTMLIFrameElement | HTMLElement | null): Scope | null {
  if (!target) return null;
  if (target.tagName === "IFRAME") {
    const frame = target as HTMLIFrameElement;
    const doc = frame.contentDocument;
    const win = frame.contentWindow;
    if (!doc?.body || !win) return null;
    return { doc, win, root: doc, host: doc.documentElement, frame };
  }
  const doc = target.ownerDocument;
  const win = doc.defaultView;
  return win ? { doc, win, root: target, host: target, frame: null } : null;
}

/** Frame elements belong to the frame's realm, so `instanceof Element` fails. */
function asElement(target: EventTarget | null): Element | null {
  return target && typeof (target as Element).closest === "function" ? (target as Element) : null;
}

/** An editable shape of the slide itself (not its layout or master). */
function slideShape(element: Element | null, surface: HTMLElement): HTMLElement | null {
  const shape = element?.closest<HTMLElement>("[data-shape-id]") ?? null;
  if (!shape || !surface.contains(shape)) return null;
  const layer = shape.dataset.sourceLayer;
  return !layer || layer === "slide" ? shape : null;
}

/** A line of text on an exact page (its invisible, positioned text layer). */
function textLine(element: Element | null, surface: HTMLElement): HTMLElement | null {
  const span = element?.closest<HTMLElement>(".pdf-text-layer span") ?? null;
  return span && surface.contains(span) && cleanText(span.textContent) ? span : null;
}

function shapeRef(shape: HTMLElement) {
  return {
    id: Number(shape.dataset.shapeId),
    name: shape.dataset.shapeName || shape.dataset.qaLabel || `Shape ${shape.dataset.shapeId}`,
  };
}

function slideNumber(root: Scope["root"], surface: HTMLElement): number {
  const item = surface.closest("[data-preview-item]");
  return Array.from(root.querySelectorAll("[data-preview-item]")).indexOf(item as Element) + 1;
}

function surfaceFor(root: Scope["root"], slide: number): HTMLElement | null {
  const item = root.querySelectorAll("[data-preview-item]")[slide - 1];
  return item?.querySelector<HTMLElement>(SURFACE) ?? null;
}

// ── Workbook cells ──────────────────────────────────────────────────────────

function isGrid(surface: HTMLElement): boolean {
  return surface.classList.contains("grid-stage");
}

/** The rendered cell (`td[data-cell="B3"]`) at an element, inside `surface`. */
function gridCell(element: Element | null, surface: HTMLElement): HTMLElement | null {
  const cell = element?.closest<HTMLElement>("td[data-cell]") ?? null;
  return cell && surface.contains(cell) ? cell : null;
}

function cellAt(doc: Document, x: number, y: number, surface: HTMLElement): HTMLElement | null {
  return gridCell(asElement(doc.elementFromPoint(x, y)), surface);
}

function unionRect(a: DOMRect, b: DOMRect): DOMRect {
  const left = Math.min(a.left, b.left);
  const top = Math.min(a.top, b.top);
  return new DOMRect(left, top, Math.max(a.right, b.right) - left, Math.max(a.bottom, b.bottom) - top);
}

function sheetName(surface: HTMLElement): string {
  const label = surface.closest<HTMLElement>("[data-preview-item]")?.dataset.previewLabel ?? "";
  return label.replace(/ \(hidden\)$/, "");
}

function cellSelection(root: Scope["root"], surface: HTMLElement, from: HTMLElement, to: HTMLElement): Selection | null {
  const range = cellRange(from.dataset.cell ?? "", to.dataset.cell ?? "");
  if (!range) return null;
  const text = Array.from(surface.querySelectorAll<HTMLElement>("td[data-cell]"))
    .filter((cell) => {
      const at = parseCell(cell.dataset.cell ?? "");
      return at && at.column >= range.left && at.column <= range.right && at.row >= range.top && at.row <= range.bottom;
    })
    .slice(0, MAX_RANGE_TEXT_CELLS)
    .map((cell) => cleanText(cell.textContent))
    .filter(Boolean)
    .join(" · ");
  return {
    slide: slideNumber(root, surface),
    shapes: [],
    area: areaOf(unionRect(from.getBoundingClientRect(), to.getBoundingClientRect()), surface.getBoundingClientRect()),
    text: cleanText(text),
    sheet: sheetName(surface),
    range: range.name,
  };
}

function nextId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export interface DeckAnnotatorProps {
  /** The preview: a same-origin iframe, or an element of this document holding the pages. */
  frameRef: React.RefObject<HTMLIFrameElement | HTMLElement | null>;
  /** Changes whenever the preview's document or pages are replaced. */
  frameKey: string | number | undefined;
  /** The chat whose composer collects the batch (engine-store `activeId`). */
  chatId: string;
  /** The document, absolute or relative to the chat's working folder. */
  file: string;
  /** What the preview shows; detected from its markup when omitted. */
  kind?: "slides" | "pages" | "cells";
  /** Annotate mode: the pointer selects instead of scrolling text. */
  active: boolean;
  /** Whether the chat's turn runs (ends the shimmer); defaults to the chat's state. */
  agentWorking?: boolean;
  onExit(): void;
}

export function DeckAnnotator({ frameRef, frameKey, chatId, file, kind, active, agentWorking, onExit }: DeckAnnotatorProps) {
  const [selection, setSelection] = React.useState<Selection | null>(null);
  const [hover, setHover] = React.useState<Box | null>(null);
  const [drag, setDrag] = React.useState<Box | null>(null);
  const [instruction, setInstruction] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [sent, setSent] = React.useState<DocumentAnnotation[]>([]);
  const [frameTick, setFrameTick] = React.useState(0);
  const [position, setPosition] = React.useState<{ left: number; top: number; above: boolean } | null>(null);
  // Exact pages are pictures with a text layer: no shapes to click.
  const [detectedPages, setExactPages] = React.useState(false);
  // A workbook's sheets are cell grids: a click picks a cell, a drag a range.
  const [detectedCells, setWorkbook] = React.useState(false);
  const exactPages = kind ? kind === "pages" : detectedPages;
  const workbook = kind ? kind === "cells" : detectedCells;
  const selectionRef = React.useRef<Selection | null>(null);
  const cwd = useEngineStore((s) => s.runtimes[chatId]?.cwd);
  const chatBusy = useEngineStore((s) => s.runtimes[chatId]?.transcript.busy ?? false);
  const filePath = React.useMemo(() => workspacePath(file, cwd), [file, cwd]);

  // Place the popover next to the selection's box: its bottom edge just above
  // the box when there is room (CSS lifts it by its own height), else below.
  const placePopover = React.useCallback(
    (next: Selection | null) => {
      selectionRef.current = next;
      const target = frameRef.current;
      const scope = scopeOf(target);
      const surface = next && scope ? surfaceFor(scope.root, next.slide) : null;
      if (!next || !target || !scope || !surface) {
        setPosition(null);
        return;
      }
      // Surface boxes are in the frame's viewport, or in this one.
      const origin = scope.frame ? scope.frame.getBoundingClientRect() : { left: 0, top: 0 };
      const containerRect = (target.offsetParent as HTMLElement | null)?.getBoundingClientRect() ?? target.getBoundingClientRect();
      const rect = surface.getBoundingClientRect();
      const boxTop = rect.top + (rect.height * next.area.y) / 100;
      const boxLeft = rect.left + (rect.width * next.area.x) / 100;
      const boxBottom = boxTop + (rect.height * next.area.h) / 100;
      const width = 340;
      const roughHeight = 120;
      const offsetX = origin.left - containerRect.left;
      const offsetY = origin.top - containerRect.top;
      const above = offsetY + boxTop - 8 >= roughHeight;
      const top = above
        ? offsetY + boxTop - 8
        : Math.max(4, Math.min(offsetY + boxBottom + 8, containerRect.height - roughHeight - 4));
      const left = Math.max(4, Math.min(offsetX + boxLeft, containerRect.width - width - 4));
      setPosition({ left, top, above });
    },
    [frameRef],
  );

  const select = React.useCallback(
    (next: Selection | null) => {
      setSelection(next);
      placePopover(next);
    },
    [placePopover],
  );
  const pending = usePendingAnnotations(chatId);
  const pins = React.useMemo(() => pending.filter((annotation) => annotation.file === filePath), [pending, filePath]);
  const working = agentWorking ?? chatBusy;
  const sawWorkingRef = React.useRef(false);

  // Sent selections shimmer while the agent works on them.
  React.useEffect(() => {
    if (sent.length === 0) {
      sawWorkingRef.current = false;
      return;
    }
    if (working) {
      sawWorkingRef.current = true;
      return;
    }
    if (!sawWorkingRef.current) {
      // The turn has not started yet; give up if it never does.
      const timer = window.setTimeout(() => setSent([]), SHIMMER_CAP_MS);
      return () => window.clearTimeout(timer);
    }
    sawWorkingRef.current = false;
    const timer = window.setTimeout(() => setSent([]), 0);
    return () => window.clearTimeout(timer);
  }, [sent.length, working]);

  // Redraw boxes whenever anything shown changes (and after frame reloads).
  React.useLayoutEffect(() => {
    const scope = scopeOf(frameRef.current);
    if (!scope) return;
    const { doc, root, host } = scope;
    const { accent, onAccent } = appAccent();
    const css = annotatorCss(accent, onAccent);
    let style = doc.querySelector<HTMLStyleElement>("style[data-evo-annotator]");
    if (!style) {
      style = doc.createElement("style");
      style.dataset.evoAnnotator = "";
      doc.head?.appendChild(style);
    }
    if (style.textContent !== css) style.textContent = css;
    host.toggleAttribute("data-evo-annotating", active);
    root.querySelectorAll("[data-evo-anno]").forEach((element) => element.remove());
    const boxes: Box[] = [
      ...sent
        .filter((a) => a.file === filePath)
        .map((a, index): Box => ({ kind: "working", slide: a.slide, area: a.area, n: index + 1 })),
      ...pins.map((a, index): Box => ({ kind: "pin", slide: a.slide, area: a.area, n: pending.indexOf(a) + 1 || index + 1 })),
    ];
    if (active && hover && !drag) boxes.push(hover);
    if (selection) boxes.push({ kind: "selection", slide: selection.slide, area: selection.area });
    if (drag) boxes.push(drag);
    for (const box of boxes) {
      const surface = surfaceFor(root, box.slide);
      if (!surface) continue;
      const element = doc.createElement("div");
      element.dataset.evoAnno = box.kind;
      if (box.n) element.dataset.n = String(box.n);
      Object.assign(element.style, {
        left: `${box.area.x}%`,
        top: `${box.area.y}%`,
        width: `${box.area.w}%`,
        height: `${box.area.h}%`,
      });
      surface.appendChild(element);
    }
  }, [active, drag, filePath, frameRef, frameKey, frameTick, hover, pending, pins, selection, sent]);

  // Boxes leave with the annotator (an element preview outlives it).
  React.useEffect(
    () => () => {
      const scope = scopeOf(frameRef.current);
      if (!scope) return;
      scope.host.removeAttribute("data-evo-annotating");
      scope.root.querySelectorAll("[data-evo-anno]").forEach((element) => element.remove());
    },
    [frameRef],
  );

  // Pointer handling inside the preview.
  React.useEffect(() => {
    const target = frameRef.current;
    if (!target) return;
    let detach = () => {};
    const attach = () => {
      detach();
      const scope = scopeOf(target);
      if (!scope) return;
      const { doc, win, root } = scope;
      setFrameTick((tick) => tick + 1);
      setExactPages(Boolean(root.querySelector('[data-preview-renderer^="libreoffice-"], .pdf-page-surface')));
      setWorkbook(Boolean(root.querySelector(".sheet .grid-stage")));
      // A reloaded frame has new slide elements; re-anchor the popover.
      placePopover(selectionRef.current);
      let start: { surface: HTMLElement; x: number; y: number; target: Element | null } | null = null;
      let dragging = false;

      const onMove = (event: PointerEvent) => {
        if (!active) return;
        const at = asElement(event.target);
        if (start) {
          if (!dragging && Math.hypot(event.clientX - start.x, event.clientY - start.y) < DRAG_THRESHOLD_PX) return;
          dragging = true;
          const rect = start.surface.getBoundingClientRect();
          if (isGrid(start.surface)) {
            // A drag across cells selects whole cells, from the first to the one under the pointer.
            const from = gridCell(start.target, start.surface);
            const to = cellAt(doc, event.clientX, event.clientY, start.surface) ?? from;
            if (from && to) {
              setDrag({
                kind: "drag",
                slide: slideNumber(root, start.surface),
                area: areaOf(unionRect(from.getBoundingClientRect(), to.getBoundingClientRect()), rect),
              });
            }
            return;
          }
          const left = Math.min(start.x, event.clientX);
          const top = Math.min(start.y, event.clientY);
          setDrag({
            kind: "drag",
            slide: slideNumber(root, start.surface),
            area: areaOf(new DOMRect(left, top, Math.abs(event.clientX - start.x), Math.abs(event.clientY - start.y)), rect),
          });
          return;
        }
        const surface = at?.closest<HTMLElement>(SURFACE) ?? null;
        const hit = !surface || !root.contains(surface)
          ? null
          : isGrid(surface)
            ? gridCell(at, surface)
            : (slideShape(at, surface) ?? textLine(at, surface));
        setHover(
          surface && hit
            ? { kind: "hover", slide: slideNumber(root, surface), area: areaOf(hit.getBoundingClientRect(), surface.getBoundingClientRect()) }
            : null,
        );
      };

      const onDown = (event: PointerEvent) => {
        if (!active || event.button !== 0) return;
        const at = asElement(event.target);
        const surface = at?.closest<HTMLElement>(SURFACE) ?? null;
        if (!surface || !root.contains(surface)) return;
        event.preventDefault();
        // Keep receiving the drag even when it strays out of the preview, so it
        // never ends up resizing or selecting anything beside the viewer.
        try {
          (at as Element & { setPointerCapture?: (id: number) => void }).setPointerCapture?.(event.pointerId);
        } catch {
          // Synthetic events carry no active pointer.
        }
        start = { surface, x: event.clientX, y: event.clientY, target: at };
        dragging = false;
      };

      const onUp = (event: PointerEvent) => {
        if (!start) return;
        const { surface, target: from } = start;
        const surfaceRect = surface.getBoundingClientRect();
        const slide = slideNumber(root, surface);
        if (isGrid(surface)) {
          const first = gridCell(from, surface);
          const last = dragging ? (cellAt(doc, event.clientX, event.clientY, surface) ?? first) : first;
          select(first && last ? cellSelection(root, surface, first, last) : null);
        } else if (dragging) {
          const bounds = {
            left: Math.min(start.x, event.clientX),
            top: Math.min(start.y, event.clientY),
            right: Math.max(start.x, event.clientX),
            bottom: Math.max(start.y, event.clientY),
          };
          const area = areaOf(
            new DOMRect(bounds.left, bounds.top, bounds.right - bounds.left, bounds.bottom - bounds.top),
            surfaceRect,
          );
          const inside = Array.from(surface.querySelectorAll<HTMLElement>("[data-shape-id]")).filter(
            (shape) => slideShape(shape, surface) === shape && overlapShare(shape.getBoundingClientRect(), bounds) > 0.5,
          );
          // Keep the outermost shape of a nested group.
          const outermost = inside.filter((shape) => !inside.some((other) => other !== shape && other.contains(shape)));
          const text =
            outermost.length > 0
              ? outermost
                  .map((shape) => cleanText(shape.textContent))
                  .filter(Boolean)
                  .join(" · ")
              : Array.from(surface.querySelectorAll<HTMLElement>(".pdf-text-layer span"))
                  .filter((span) => overlapShare(span.getBoundingClientRect(), bounds) > 0.5)
                  .map((span) => span.textContent ?? "")
                  .join(" ");
          select({ slide, shapes: outermost.slice(0, MAX_AREA_SHAPES).map(shapeRef), area, text: cleanText(text) });
        } else {
          const shape = slideShape(from, surface);
          if (shape) {
            select({
              slide,
              shapes: [shapeRef(shape)],
              area: areaOf(shape.getBoundingClientRect(), surfaceRect),
              text: cleanText(shape.textContent),
            });
          } else {
            const line = textLine(from, surface);
            select(
              line
                ? { slide, shapes: [], area: areaOf(line.getBoundingClientRect(), surfaceRect), text: cleanText(line.textContent) }
                : null,
            );
          }
        }
        setInstruction("");
        setError(null);
        setDrag(null);
        start = null;
        dragging = false;
      };

      const onLeave = () => setHover(null);
      const onScroll = () => placePopover(selectionRef.current);
      const onKey = (event: Event) => {
        if ((event as KeyboardEvent).key === "Escape") select(null);
      };

      const events = root as EventTarget;
      events.addEventListener("pointermove", onMove as EventListener);
      events.addEventListener("pointerdown", onDown as EventListener);
      events.addEventListener("pointerup", onUp as EventListener);
      events.addEventListener("pointerleave", onLeave);
      events.addEventListener("keydown", onKey);
      // In a frame its window scrolls; in this document any scroller may.
      const scroller: EventTarget = scope.frame ? win : doc;
      scroller.addEventListener("scroll", onScroll, { passive: true, capture: !scope.frame });
      win.addEventListener("resize", onScroll);
      detach = () => {
        events.removeEventListener("pointermove", onMove as EventListener);
        events.removeEventListener("pointerdown", onDown as EventListener);
        events.removeEventListener("pointerup", onUp as EventListener);
        events.removeEventListener("pointerleave", onLeave);
        events.removeEventListener("keydown", onKey);
        scroller.removeEventListener("scroll", onScroll, { capture: !scope.frame });
        win.removeEventListener("resize", onScroll);
      };
    };
    attach();
    target.addEventListener("load", attach);
    return () => {
      target.removeEventListener("load", attach);
      detach();
    };
  }, [active, frameKey, frameRef, placePopover, select]);

  // Leaving annotate mode drops the unsent selection.
  React.useEffect(() => {
    if (active) return;
    const timer = window.setTimeout(() => {
      select(null);
      setHover(null);
      setDrag(null);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [active, select]);

  const commit = (sendNow: boolean) => {
    if (!selection) return;
    const annotation: DocumentAnnotation = {
      id: nextId(),
      file: filePath,
      slide: selection.slide,
      ...(selection.range ? { sheet: selection.sheet, range: selection.range } : {}),
      shapes: selection.shapes,
      area: selection.area,
      text: selection.text,
      instruction: instruction.trim(),
      label: describeAnnotation(selection),
    };
    const store = useAnnotationsStore.getState();
    if (!store.add(chatId, annotation)) {
      setError(`A message carries up to ${MAX_BATCH_ANNOTATIONS} annotations. Send these first.`);
      return;
    }
    // Capture the file as it is now, so this edit can be undone.
    void useEngineStore
      .getState()
      .request("document_versions_act", {
        path: filePath,
        action: "checkpoint",
        label: annotation.instruction || annotation.label,
      })
      .catch(() => undefined);
    if (sendNow) {
      const batch = useAnnotationsStore.getState().pending[chatId] ?? [];
      setSent(batch.filter((item) => item.file === filePath));
      store.requestSubmit(chatId);
    }
    select(null);
    setInstruction("");
  };

  if (!selection || !position) {
    if (!active) return null;
    return (
      <div
        role="status"
        className="pointer-events-none absolute top-2 left-1/2 z-30 max-w-[calc(100%-16px)] -translate-x-1/2 rounded-full bg-popover/95 px-3 py-1 text-[11px] text-muted-foreground shadow-border-small"
      >
        {exactPages
          ? "Click a line of text or drag across an area to select it"
          : workbook
            ? "Click a cell or drag across cells to select them"
            : "Click a shape or drag across an area to select it"}
      </div>
    );
  }
  return (
    <div
      role="dialog"
      aria-label="Annotate selection"
      className="absolute z-30 w-[340px] max-w-[calc(100%-8px)] rounded-lg bg-popover p-2 text-popover-foreground shadow-menu"
      style={{
        left: position.left,
        top: position.top,
        transform: position.above ? "translateY(-100%)" : undefined,
      }}
      data-testid="annotation-popover"
    >
      <div className="mb-1 flex items-center gap-2 px-1 text-[11px] text-muted-foreground">
        <span className="min-w-0 flex-1 truncate">{describeAnnotation(selection)}</span>
        {pending.length > 0 && <span className="shrink-0">{pending.length} in batch</span>}
        <button
          type="button"
          onClick={() => select(null)}
          aria-label="Cancel selection"
          className="flex size-5 shrink-0 items-center justify-center rounded hover:bg-accent hover:text-foreground"
        >
          <XIcon className="size-3" />
        </button>
      </div>
      <div className="flex items-end gap-1.5">
        <textarea
          autoFocus
          rows={2}
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              select(null);
            } else if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              commit(true);
            }
          }}
          placeholder="Edit or ask; leave empty to quote only"
          aria-label="Instruction for the selection"
          className="min-h-10 flex-1 resize-none rounded-md bg-transparent px-2 py-1.5 text-sm outline-none placeholder:text-muted-foreground"
        />
        <div className="flex shrink-0 flex-col gap-1">
          <button
            type="button"
            onClick={() => commit(true)}
            title="Send now (Enter)"
            aria-label="Send annotation now"
            className="flex size-7 items-center justify-center rounded-md bg-brand text-brand-foreground transition-opacity hover:opacity-90"
          >
            <ArrowUpIcon className="size-3.5" />
          </button>
          <button
            type="button"
            onClick={() => commit(false)}
            title="Add to batch and keep selecting"
            aria-label="Add annotation to batch"
            className={cn(
              "flex size-7 items-center justify-center rounded-md text-muted-foreground shadow-border transition-colors hover:bg-accent hover:text-foreground",
            )}
          >
            <MessageSquarePlusIcon className="size-3.5" />
          </button>
        </div>
      </div>
      {error && <p className="px-1 pt-1 text-[11px] text-destructive">{error}</p>}
      <p className="px-1 pt-1 text-[10px] text-muted-foreground">
        Esc cancels ·{" "}
        <button type="button" className="underline hover:text-foreground" onClick={onExit}>
          Done annotating
        </button>
      </p>
    </div>
  );
}
