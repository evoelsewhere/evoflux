// Changed-line markers in the Files editor: the open document is diffed
// against its text at HEAD in the browser (no git call per keystroke), and the
// gutter marks added, modified and removed lines. Clicking a marker peeks at
// the committed text of that hunk. Design: docs/features/files-git/sdd.md.

import { RangeSet, StateEffect, StateField, type EditorState, type Extension } from "@codemirror/state";
import { Decoration, EditorView, GutterMarker, ViewPlugin, WidgetType, gutter, type DecorationSet, type ViewUpdate } from "@codemirror/view";

/** A changed region: base lines `[baseFrom, baseTo)` became document lines `[docFrom, docTo)` (0-based). */
export interface Hunk {
  baseFrom: number;
  baseTo: number;
  docFrom: number;
  docTo: number;
}

/** Past this many edits the whole changed middle is one hunk (keeps the diff cheap). */
const MAX_EDITS = 2000;
/** Documents larger than this get no markers. */
const MAX_CHARS = 1_000_000;
const DEBOUNCE_MS = 300;

/** Lines of `text`, line endings normalised (a CRLF checkout does not mark every line). */
export const splitLines = (text: string) => text.split(/\r\n|\r|\n/);

/** Myers line diff of `base` against `doc`, as hunks in document order. */
export function diffLines(base: string[], doc: string[]): Hunk[] {
  // Shared head and tail first: the usual edit touches a few lines.
  let start = 0;
  while (start < base.length && start < doc.length && base[start] === doc[start]) start++;
  let endBase = base.length;
  let endDoc = doc.length;
  while (endBase > start && endDoc > start && base[endBase - 1] === doc[endDoc - 1]) {
    endBase--;
    endDoc--;
  }
  if (start === endBase && start === endDoc) return [];
  if (start === endBase || start === endDoc) return [{ baseFrom: start, baseTo: endBase, docFrom: start, docTo: endDoc }];

  // Lines as numbers so the inner loop compares integers.
  const ids = new Map<string, number>();
  const id = (line: string) => {
    let n = ids.get(line);
    if (n === undefined) ids.set(line, (n = ids.size));
    return n;
  };
  const a = base.slice(start, endBase).map(id);
  const b = doc.slice(start, endDoc).map(id);
  const edits = myers(a, b);
  if (!edits) return [{ baseFrom: start, baseTo: endBase, docFrom: start, docTo: endDoc }];

  const hunks: Hunk[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    if ((i < a.length && edits.deleted[i]) || (j < b.length && edits.inserted[j])) {
      const from = { i, j };
      while ((i < a.length && edits.deleted[i]) || (j < b.length && edits.inserted[j])) {
        if (i < a.length && edits.deleted[i]) i++;
        else j++;
      }
      hunks.push({ baseFrom: start + from.i, baseTo: start + i, docFrom: start + from.j, docTo: start + j });
    } else {
      i++;
      j++;
    }
  }
  return hunks;
}

/** Which lines of `a` are deleted and which of `b` inserted; `null` past `MAX_EDITS`. */
function myers(a: number[], b: number[]): { deleted: Uint8Array; inserted: Uint8Array } | null {
  const n = a.length;
  const m = b.length;
  const max = Math.min(n + m, MAX_EDITS);
  const offset = max + 1;
  const v = new Int32Array(2 * max + 3);
  // trace[d] holds V for k in [-d, d] after step d.
  const trace: Int32Array[] = [];
  let found = -1;
  for (let d = 0; d <= max && found < 0; d++) {
    for (let k = -d; k <= d; k += 2) {
      let x = k === -d || (k !== d && v[offset + k - 1] < v[offset + k + 1]) ? v[offset + k + 1] : v[offset + k - 1] + 1;
      let y = x - k;
      while (x < n && y < m && a[x] === b[y]) {
        x++;
        y++;
      }
      v[offset + k] = x;
      if (x >= n && y >= m) found = d;
    }
    trace.push(v.slice(offset - d, offset + d + 1));
  }
  if (found < 0) return null;

  const deleted = new Uint8Array(n);
  const inserted = new Uint8Array(m);
  let x = n;
  let y = m;
  for (let d = found; d > 0; d--) {
    const prev = trace[d - 1];
    const at = (k: number) => prev[k + d - 1];
    const k = x - y;
    const down = k === -d || (k !== d && at(k - 1) < at(k + 1));
    const prevK = down ? k + 1 : k - 1;
    const prevX = at(prevK);
    const prevY = prevX - prevK;
    if (down) inserted[prevY] = 1;
    else deleted[prevX] = 1;
    x = prevX;
    y = prevY;
  }
  return { deleted, inserted };
}

// ── CodeMirror ──────────────────────────────────────────────────────────────

type MarkKind = "added" | "modified" | "removed-above" | "removed-below";

class ChangeMarker extends GutterMarker {
  constructor(readonly kind: MarkKind) {
    super();
  }
  eq(other: ChangeMarker) {
    return other.kind === this.kind;
  }
  toDOM() {
    const el = document.createElement("div");
    // Tailwind classes (scanned from this file): the status tokens are not CSS variables.
    const colour =
      this.kind === "added" ? "bg-status-ok" : this.kind === "modified" ? "bg-brand" : "border-l-status-error";
    el.className = `cm-git-mark cm-git-${this.kind} ${colour}`;
    return el;
  }
}

const markers: Record<MarkKind, ChangeMarker> = {
  added: new ChangeMarker("added"),
  modified: new ChangeMarker("modified"),
  "removed-above": new ChangeMarker("removed-above"),
  "removed-below": new ChangeMarker("removed-below"),
};

/** Set the HEAD text to compare with (`null`: no markers). */
export const setGitBase = StateEffect.define<string | null>();
const setHunks = StateEffect.define<Hunk[]>();
const setPeek = StateEffect.define<Hunk | null>();

const baseField = StateField.define<string | null>({
  create: () => null,
  update: (value, tr) => {
    for (const effect of tr.effects) if (effect.is(setGitBase)) value = effect.value;
    return value;
  },
});

interface Marks {
  hunks: Hunk[];
  set: RangeSet<GutterMarker>;
}

function markSet(state: EditorState, hunks: Hunk[]): RangeSet<GutterMarker> {
  const ranges = [];
  const lines = state.doc.lines;
  for (const hunk of hunks) {
    if (hunk.docFrom === hunk.docTo) {
      // Removed lines sit between two document lines.
      const below = hunk.docFrom > 0;
      const line = state.doc.line(Math.min(below ? hunk.docFrom : 1, lines));
      ranges.push(markers[below ? "removed-below" : "removed-above"].range(line.from));
      continue;
    }
    const kind = hunk.baseFrom === hunk.baseTo ? markers.added : markers.modified;
    for (let n = hunk.docFrom; n < hunk.docTo && n < lines; n++) ranges.push(kind.range(state.doc.line(n + 1).from));
  }
  return RangeSet.of(ranges, true);
}

const marksField = StateField.define<Marks>({
  create: () => ({ hunks: [], set: RangeSet.empty }),
  update(marks, tr) {
    for (const effect of tr.effects) {
      if (effect.is(setHunks)) return { hunks: effect.value, set: markSet(tr.state, effect.value) };
      if (effect.is(setGitBase) && effect.value === null) return { hunks: [], set: RangeSet.empty };
    }
    // Until the next diff, markers move with the text.
    return tr.docChanged ? { hunks: marks.hunks, set: marks.set.map(tr.changes) } : marks;
  },
});

/** The committed lines of one hunk, shown under it. */
class PeekWidget extends WidgetType {
  constructor(
    readonly lines: string[],
    readonly hunk: Hunk,
  ) {
    super();
  }
  eq(other: PeekWidget) {
    return other.hunk.baseFrom === this.hunk.baseFrom && other.lines.join("\n") === this.lines.join("\n");
  }
  toDOM() {
    const box = document.createElement("div");
    box.className = "cm-git-peek";
    const head = document.createElement("div");
    head.className = "cm-git-peek-head";
    head.textContent =
      this.lines.length === 0
        ? "Not in HEAD — added lines"
        : `HEAD · ${this.lines.length} ${this.lines.length === 1 ? "line" : "lines"} (Esc to close)`;
    box.append(head);
    for (const line of this.lines) {
      const row = document.createElement("div");
      row.className = "cm-git-peek-line";
      row.textContent = line || "​";
      box.append(row);
    }
    return box;
  }
  ignoreEvent() {
    return false;
  }
}

const peekField = StateField.define<{ hunk: Hunk; deco: DecorationSet } | null>({
  create: () => null,
  update(peek, tr) {
    for (const effect of tr.effects) {
      if (!effect.is(setPeek)) continue;
      const hunk = effect.value;
      const base = tr.state.field(baseField);
      if (!hunk || base === null) return null;
      const lines = splitLines(base).slice(hunk.baseFrom, hunk.baseTo);
      const doc = tr.state.doc;
      // Under the hunk's last line; removed lines above the line they precede.
      const above = hunk.docTo === 0;
      const line = doc.line(Math.min(Math.max(hunk.docTo, 1), doc.lines));
      const deco = Decoration.widget({ widget: new PeekWidget(lines, hunk), block: true, side: above ? -1 : 1 });
      return { hunk, deco: Decoration.set([deco.range(above ? line.from : line.to)]) };
    }
    // Edits move the text under the peek: close it.
    return tr.docChanged ? null : peek;
  },
  provide: (field) => EditorView.decorations.from(field, (peek) => peek?.deco ?? Decoration.none),
});

/** The hunk drawn on document line `n` (0-based). */
function hunkAt(hunks: Hunk[], n: number): Hunk | null {
  return (
    hunks.find((h) =>
      h.docFrom === h.docTo ? n === Math.max(h.docFrom - 1, 0) : n >= h.docFrom && n < h.docTo,
    ) ?? null
  );
}

/** Re-diff a moment after the last edit, or at once when the base changes. */
const differ = ViewPlugin.fromClass(
  class {
    timer: ReturnType<typeof setTimeout> | undefined;
    constructor(readonly view: EditorView) {
      this.schedule(0);
    }
    update(update: ViewUpdate) {
      const baseChanged = update.transactions.some((tr) => tr.effects.some((e) => e.is(setGitBase)));
      if (baseChanged) this.schedule(0);
      else if (update.docChanged) this.schedule(DEBOUNCE_MS);
    }
    schedule(delay: number) {
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.run(), delay);
    }
    run() {
      const state = this.view.state;
      const base = state.field(baseField);
      if (base === null) return;
      const hunks = state.doc.length > MAX_CHARS || base.length > MAX_CHARS ? [] : diffLines(splitLines(base), state.doc.toJSON());
      this.view.dispatch({ effects: setHunks.of(hunks) });
    }
    destroy() {
      clearTimeout(this.timer);
    }
  },
);

const gitTheme = EditorView.baseTheme({
  ".cm-git-gutter": { width: "4px", marginRight: "2px" },
  ".cm-git-gutter .cm-gutterElement": { position: "relative", cursor: "pointer" },
  ".cm-git-mark": { position: "absolute", left: "0", width: "3px", top: "0", bottom: "0", borderRadius: "1px" },
  ".cm-git-removed-below, .cm-git-removed-above": {
    width: "0",
    height: "0",
    borderTop: "4px solid transparent",
    borderBottom: "4px solid transparent",
    borderLeftWidth: "5px",
    borderLeftStyle: "solid",
    borderRadius: "0",
  },
  ".cm-git-removed-below": { top: "auto", bottom: "-4px" },
  ".cm-git-removed-above": { top: "-4px", bottom: "auto" },
  ".cm-git-peek": {
    margin: "2px 0 4px",
    borderTop: "1px solid var(--border)",
    borderBottom: "1px solid var(--border)",
    backgroundColor: "color-mix(in oklab, var(--muted) 70%, transparent)",
    fontFamily: "var(--app-font-mono)",
  },
  ".cm-git-peek-head": { padding: "2px 8px", fontSize: "11px", color: "var(--muted-foreground)", fontFamily: "var(--app-font-sans)" },
  ".cm-git-peek-line": { padding: "0 8px", whiteSpace: "pre", color: "var(--muted-foreground)", textDecoration: "line-through" },
});

/** The changed-line gutter; feed it the HEAD text with `setGitBase`. */
export function gitGutter(): Extension {
  return [
    baseField,
    marksField,
    peekField,
    differ,
    gutter({
      class: "cm-git-gutter",
      markers: (view) => view.state.field(marksField).set,
      domEventHandlers: {
        mousedown(view, line) {
          const n = view.state.doc.lineAt(line.from).number - 1;
          const hunk = hunkAt(view.state.field(marksField).hunks, n);
          if (!hunk) return false;
          const open = view.state.field(peekField);
          const same = open && open.hunk.baseFrom === hunk.baseFrom && open.hunk.docFrom === hunk.docFrom;
          view.dispatch({ effects: setPeek.of(same ? null : hunk) });
          return true;
        },
      },
    }),
    EditorView.domEventHandlers({
      keydown(event, view) {
        if (event.key !== "Escape" || !view.state.field(peekField)) return false;
        view.dispatch({ effects: setPeek.of(null) });
        return true;
      },
    }),
    gitTheme,
  ];
}
