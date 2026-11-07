// Document annotations: parts of a document the person selected in the Files
// viewer, each with an instruction, sent to the agent as one message
// (docs/features/office-v3-parity/spec.md, FR-10; port of v3
// web/src/lib/document-annotations.ts).
//
// The wire format is plain message text, so a message queues, replays and is
// edited like any other. It is a skill command, the way evo runs any skill
// from the composer: `/skill:office-annotation-edit <the person's text>`, then
// the JSON block the skill documents. The engine expands the command into the
// skill's instructions with the rest as its arguments (a replayed message
// shows as `/office-annotation-edit …`). v3 used a `$office-annotation-edit`
// mention line instead; old messages still parse. The chat hides the command
// and the block and shows an "Annotations: N" chip. No React, no DOM.

export interface AnnotationArea {
  /** Percent of the slide/page, origin top-left. */
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface DocumentAnnotation {
  /** Client id, for removing one from a batch; not sent. */
  id: string;
  /** The file, relative to the chat's working folder (forward slashes). */
  file: string;
  /** 1-based slide (or, in a workbook, sheet) number. */
  slide: number;
  /** Workbooks: the sheet's name and the selected cells, e.g. "B3:D8". */
  sheet?: string;
  range?: string;
  /** Shapes the person clicked; empty for a dragged box. */
  shapes: Array<{ id: number; name: string }>;
  area: AnnotationArea;
  /** Visible text inside the selection, for orientation. */
  text: string;
  instruction: string;
  /** Short human label, e.g. "Slide 7 · Chart 3". */
  label: string;
}

export const ANNOTATION_SKILL = "office-annotation-edit";
/** Characters of a selection's text sent with it. */
export const MAX_ANNOTATION_TEXT = 300;
const OPEN_TAG = "<evo-annotations>";
const CLOSE_TAG = "</evo-annotations>";
/** v3 wrote `<evoflux-annotations>`; old messages still parse. */
const LEGACY_OPEN_TAG = "<evoflux-annotations>";
const BLOCK_RE = /\n*(?:\$office-annotation-edit\s*\n)?<(evo|evoflux)-annotations>\n([\s\S]*?)\n<\/\1-annotations>\s*$/;
/** The leading skill command: as sent (`/skill:name`) or as replayed (`/name`). */
const COMMAND_RE = /^\/(?:skill:)?office-annotation-edit(?=\s|$)/;

const round = (value: number) => Math.round(value * 10) / 10;

/** Append the annotation block to the message text. */
export function composeAnnotatedMessage(text: string, annotations: DocumentAnnotation[]): string {
  if (annotations.length === 0) return text;
  const payload = annotations.map((annotation, index) => ({
    n: index + 1,
    file: annotation.file,
    slide: annotation.slide,
    ...(annotation.range ? { sheet: annotation.sheet ?? "", range: annotation.range } : {}),
    shapes: annotation.shapes,
    area: {
      x: round(annotation.area.x),
      y: round(annotation.area.y),
      w: round(annotation.area.w),
      h: round(annotation.area.h),
    },
    text: annotation.text.slice(0, MAX_ANNOTATION_TEXT),
    instruction: annotation.instruction,
  }));
  const block = `${OPEN_TAG}\n${JSON.stringify(payload)}\n${CLOSE_TAG}`;
  // The space after the command matters: the engine splits the skill name
  // from its arguments at the first space.
  const body = text.trim() ? `${text.trim()}\n\n${block}` : block;
  return `/skill:${ANNOTATION_SKILL} ${body}`;
}

export interface ParsedAnnotation {
  n: number;
  file: string;
  slide: number;
  sheet?: string;
  range?: string;
  shapes: Array<{ id: number; name: string }>;
  text: string;
  instruction: string;
}

/** Split a sent message into its visible text and its annotations; `null` when it carries none. */
export function parseAnnotatedMessage(raw: string): { text: string; annotations: ParsedAnnotation[] } | null {
  if (!raw.includes(OPEN_TAG) && !raw.includes(LEGACY_OPEN_TAG)) return null;
  // Line breaks may arrive as CRLF.
  const content = raw.replace(/\r\n?/g, "\n");
  const match = BLOCK_RE.exec(content);
  if (!match) return null;
  try {
    const items = JSON.parse(match[2]) as unknown;
    if (!Array.isArray(items)) return null;
    const annotations = items.flatMap((item: Partial<ParsedAnnotation>, index): ParsedAnnotation[] =>
      item && typeof item === "object"
        ? [
            {
              n: typeof item.n === "number" ? item.n : index + 1,
              file: String(item.file ?? ""),
              slide: Number(item.slide ?? 0),
              ...(typeof item.range === "string" && item.range ? { sheet: String(item.sheet ?? ""), range: item.range } : {}),
              shapes: Array.isArray(item.shapes) ? item.shapes : [],
              text: String(item.text ?? ""),
              instruction: String(item.instruction ?? ""),
            },
          ]
        : [],
    );
    return { text: content.slice(0, match.index).trim().replace(COMMAND_RE, "").trim(), annotations };
  } catch {
    return null;
  }
}

/** "Slide 7 · Chart 3", "Slide 2 · “Revenue…”", "Model · B3:D8". */
export function describeAnnotation(
  annotation: Pick<ParsedAnnotation, "slide" | "shapes" | "sheet" | "range"> & { text?: string },
): string {
  if (annotation.range) return `${annotation.sheet || `Sheet ${annotation.slide}`} · ${annotation.range}`;
  const quoted = annotation.text?.trim();
  const target =
    annotation.shapes.length > 0
      ? annotation.shapes.map((shape) => shape.name).join(", ")
      : quoted
        ? `“${quoted.length > 40 ? `${quoted.slice(0, 40)}…` : quoted}”`
        : "Selected area";
  return `Slide ${annotation.slide} · ${target}`;
}

/**
 * `path` relative to the chat's working folder `cwd`, with forward slashes —
 * what an annotation's `file` holds. A path outside the folder stays absolute.
 */
export function workspacePath(path: string, cwd?: string | null): string {
  const slashed = path.replace(/\\/g, "/");
  const absolute = /^([A-Za-z]:)?\//.test(slashed);
  if (!absolute) return slashed.replace(/^(\.\/)+/, "");
  if (!cwd) return slashed;
  const root = cwd.replace(/\\/g, "/").replace(/\/+$/, "");
  // Drive paths (Windows) compare without case.
  const fold = (value: string) => (/^[A-Za-z]:/.test(root) ? value.toLowerCase() : value);
  return fold(slashed).startsWith(`${fold(root)}/`) ? slashed.slice(root.length + 1) : slashed;
}

// ── Geometry (pure helpers of the annotator) ────────────────────────────────

/** Keep an area inside its slide: 0–100 %, and never past the right or bottom edge. */
export function clampArea(area: AnnotationArea): AnnotationArea {
  const x = Math.max(0, Math.min(100, area.x));
  const y = Math.max(0, Math.min(100, area.y));
  return { x, y, w: Math.max(0, Math.min(100 - x, area.w)), h: Math.max(0, Math.min(100 - y, area.h)) };
}

interface Bounds {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** `rect` in percent of `surface` (both in the same coordinates), clamped. */
export function areaOf(rect: Bounds, surface: Bounds): AnnotationArea {
  return clampArea({
    x: ((rect.left - surface.left) / surface.width) * 100,
    y: ((rect.top - surface.top) / surface.height) * 100,
    w: (rect.width / surface.width) * 100,
    h: (rect.height / surface.height) * 100,
  });
}

/** Share of `inner` that lies inside `outer` (0–1). */
export function overlapShare(
  inner: { left: number; top: number; right: number; bottom: number; width: number; height: number },
  outer: { left: number; top: number; right: number; bottom: number },
): number {
  const width = Math.min(inner.right, outer.right) - Math.max(inner.left, outer.left);
  const height = Math.min(inner.bottom, outer.bottom) - Math.max(inner.top, outer.top);
  if (width <= 0 || height <= 0 || inner.width <= 0 || inner.height <= 0) return 0;
  return (width * height) / (inner.width * inner.height);
}

/** Collapse whitespace and cap at 300 characters. */
export function cleanText(text: string | null | undefined): string {
  return (text ?? "").replace(/\s+/g, " ").trim().slice(0, MAX_ANNOTATION_TEXT);
}

/** "B3" → column 2, row 3. */
export function parseCell(name: string): { column: number; row: number } | null {
  const match = /^([A-Z]+)(\d+)$/.exec(name);
  if (!match) return null;
  const column = [...match[1]].reduce((total, letter) => total * 26 + letter.charCodeAt(0) - 64, 0);
  return { column, row: Number(match[2]) };
}

/** 1 → "A", 27 → "AA". */
export function columnName(column: number): string {
  let name = "";
  for (let value = column; value > 0; value = Math.floor((value - 1) / 26)) {
    name = String.fromCharCode(65 + ((value - 1) % 26)) + name;
  }
  return name;
}

/** The cells `a` and `b` span, as an A1 range ("B3" or "B3:D8"), with its bounds. */
export function cellRange(a: string, b: string) {
  const start = parseCell(a);
  const end = parseCell(b);
  if (!start || !end) return null;
  const left = Math.min(start.column, end.column);
  const right = Math.max(start.column, end.column);
  const top = Math.min(start.row, end.row);
  const bottom = Math.max(start.row, end.row);
  const first = `${columnName(left)}${top}`;
  const last = `${columnName(right)}${bottom}`;
  return { name: first === last ? first : `${first}:${last}`, left, right, top, bottom };
}
