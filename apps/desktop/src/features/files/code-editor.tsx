// The Files tool's editor: CodeMirror 6 with the app's colours, the language
// picked from the file name, search, and an editor state kept per file (undo
// history and selection survive switching tabs).

import * as React from "react";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { HighlightStyle, bracketMatching, foldGutter, indentOnInput, LanguageDescription, syntaxHighlighting } from "@codemirror/language";
import { languages } from "@codemirror/language-data";
import { highlightSelectionMatches, search, searchKeymap } from "@codemirror/search";
import { Compartment, EditorSelection, EditorState, StateEffect, StateField, type Extension } from "@codemirror/state";
import {
  Decoration,
  EditorView,
  crosshairCursor,
  drawSelection,
  highlightActiveLine,
  highlightActiveLineGutter,
  highlightSpecialChars,
  keymap,
  lineNumbers,
  rectangularSelection,
  type DecorationSet,
} from "@codemirror/view";
import { tags as t } from "@lezer/highlight";
import { hasMod, isMac } from "@/lib/platform";

/** Token colours come from CSS variables (index.css), so light and dark follow the theme. */
const highlight = HighlightStyle.define([
  { tag: [t.keyword, t.operatorKeyword, t.modifier, t.controlKeyword], color: "var(--syn-keyword)" },
  { tag: [t.string, t.special(t.string), t.regexp, t.character], color: "var(--syn-string)" },
  { tag: [t.number, t.bool, t.null, t.atom], color: "var(--syn-number)" },
  { tag: [t.comment, t.lineComment, t.blockComment, t.docComment], color: "var(--syn-comment)", fontStyle: "italic" },
  { tag: [t.function(t.variableName), t.function(t.propertyName), t.macroName], color: "var(--syn-function)" },
  { tag: [t.typeName, t.className, t.namespace, t.definition(t.typeName)], color: "var(--syn-type)" },
  { tag: [t.propertyName, t.attributeName], color: "var(--syn-property)" },
  { tag: [t.tagName, t.angleBracket], color: "var(--syn-tag)" },
  { tag: [t.heading, t.strong], fontWeight: "600", color: "var(--syn-heading)" },
  { tag: t.emphasis, fontStyle: "italic" },
  { tag: [t.link, t.url], color: "var(--syn-string)", textDecoration: "underline" },
  { tag: [t.meta, t.processingInstruction, t.annotation], color: "var(--syn-comment)" },
  { tag: t.invalid, color: "var(--destructive)" },
]);

const theme = EditorView.theme({
  "&": { height: "100%", fontSize: "12.5px", backgroundColor: "transparent", color: "var(--foreground)" },
  "&.cm-focused": { outline: "none" },
  ".cm-scroller": { fontFamily: "var(--app-font-mono)", lineHeight: "1.6" },
  ".cm-content": { caretColor: "var(--foreground)", paddingBottom: "40vh" },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--foreground)" },
  ".cm-gutters": { backgroundColor: "transparent", border: "none", color: "var(--muted-foreground)" },
  ".cm-lineNumbers .cm-gutterElement": { padding: "0 10px 0 12px", minWidth: "3ch" },
  ".cm-activeLine": { backgroundColor: "color-mix(in oklab, var(--foreground) 4%, transparent)" },
  ".cm-activeLineGutter": { backgroundColor: "transparent", color: "var(--foreground)" },
  "&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, ::selection":
    { backgroundColor: "color-mix(in oklab, var(--brand) 26%, transparent) !important" },
  ".cm-searchMatch": { backgroundColor: "#ffb22440", outline: "1px solid #ffb22480" },
  ".cm-searchMatch.cm-searchMatch-selected": { backgroundColor: "#ffb224a0" },
  ".cm-selectionMatch": { backgroundColor: "color-mix(in oklab, var(--brand) 12%, transparent)" },
  ".cm-matchingBracket": { backgroundColor: "color-mix(in oklab, var(--brand) 20%, transparent)", outline: "none" },
  ".cm-foldGutter .cm-gutterElement": { padding: "0 4px", cursor: "pointer" },
  ".cm-panels": { backgroundColor: "var(--popover)", color: "var(--popover-foreground)", fontSize: "12px" },
  ".cm-panels.cm-panels-bottom": { borderTop: "1px solid var(--border)" },
  ".cm-panel.cm-search": { padding: "6px 8px" },
  ".cm-panel.cm-search input, .cm-panel.cm-search button": { fontSize: "12px" },
  ".cm-textfield": {
    backgroundColor: "var(--background)",
    border: "1px solid var(--border)",
    borderRadius: "6px",
    padding: "2px 6px",
  },
  ".cm-button": {
    backgroundImage: "none",
    backgroundColor: "var(--muted)",
    border: "1px solid var(--border)",
    borderRadius: "6px",
    padding: "2px 8px",
  },
  ".cm-revealed-line": { backgroundColor: "color-mix(in oklab, var(--brand) 16%, transparent)", transition: "background-color 1s" },
});

/** A line marked after "open at line", fading after a moment. */
const markLine = StateEffect.define<number | null>();
const markedLine = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(marks, tr) {
    marks = marks.map(tr.changes);
    for (const effect of tr.effects) {
      if (!effect.is(markLine)) continue;
      if (effect.value === null) return Decoration.none;
      const line = tr.state.doc.line(Math.min(Math.max(1, effect.value), tr.state.doc.lines));
      return Decoration.set([Decoration.line({ class: "cm-revealed-line" }).range(line.from)]);
    }
    return marks;
  },
  provide: (field) => EditorView.decorations.from(field),
});

const states = new Map<string, EditorState>();
/** Forget a closed file's editor state. */
export const dropEditorState = (path: string) => states.delete(path);

interface Props {
  path: string;
  text: string;
  /** Bumped when `text` was (re)loaded from disk. */
  revision: number;
  readOnly: boolean;
  onChange(text: string, dirty: boolean): void;
  onSave(text: string): void;
  /** 1-based line to scroll to and mark. */
  revealLine?: number | null;
  revealNonce?: number;
  onCursor?(line: number, column: number): void;
}

export function CodeEditor({ path, text, revision, readOnly, onChange, onSave, revealLine, revealNonce, onCursor }: Props) {
  const host = React.useRef<HTMLDivElement>(null);
  const view = React.useRef<EditorView | null>(null);
  const language = React.useRef(new Compartment());
  const editable = React.useRef(new Compartment());
  const saved = React.useRef(text);
  const loadedRevision = React.useRef(revision);
  const callbacks = React.useRef({ onChange, onSave, onCursor });
  callbacks.current = { onChange, onSave, onCursor };

  const extensions = React.useCallback(
    (): Extension[] => [
      lineNumbers(),
      foldGutter(),
      highlightActiveLineGutter(),
      highlightSpecialChars(),
      history(),
      drawSelection(),
      EditorState.allowMultipleSelections.of(true),
      indentOnInput(),
      bracketMatching(),
      rectangularSelection(),
      crosshairCursor(),
      highlightActiveLine(),
      highlightSelectionMatches(),
      search({ top: false }),
      syntaxHighlighting(highlight),
      markedLine,
      theme,
      keymap.of([
        { key: "Mod-s", preventDefault: true, run: (v) => (callbacks.current.onSave(v.state.doc.toString()), true) },
        ...searchKeymap,
        ...defaultKeymap,
        ...historyKeymap,
        indentWithTab,
      ]),
      language.current.of([]),
      editable.current.of([EditorState.readOnly.of(readOnly), EditorView.editable.of(!readOnly)]),
      EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          const doc = update.state.doc.toString();
          callbacks.current.onChange(doc, doc !== saved.current);
        }
        if (update.selectionSet || update.docChanged) {
          const head = update.state.selection.main.head;
          const line = update.state.doc.lineAt(head);
          callbacks.current.onCursor?.(line.number, head - line.from + 1);
        }
      }),
    ],
    // `readOnly` is reconfigured below; the rest never changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  // One view per mounted file; its state is kept when another file shows.
  React.useLayoutEffect(() => {
    if (!host.current) return;
    const kept = states.get(path);
    const state =
      kept && kept.doc.toString() === text ? kept : EditorState.create({ doc: text, extensions: extensions() });
    saved.current = text;
    loadedRevision.current = revision;
    const editor = new EditorView({ state, parent: host.current });
    view.current = editor;
    // Syntax: the language for this file name, loaded on demand.
    const description = LanguageDescription.matchFilename(languages, path.split(/[\\/]/).pop() ?? path);
    if (description) {
      void description.load().then((support) => {
        if (view.current === editor) editor.dispatch({ effects: language.current.reconfigure(support) });
      });
    }
    return () => {
      states.set(path, editor.state);
      editor.destroy();
      view.current = null;
    };
    // Recreate only for another file.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);

  // Reloaded from disk (or saved): take the text as the new saved version.
  React.useEffect(() => {
    const editor = view.current;
    saved.current = text;
    if (!editor || revision === loadedRevision.current) return;
    loadedRevision.current = revision;
    const current = editor.state.doc.toString();
    if (current === text) return;
    const head = Math.min(editor.state.selection.main.head, text.length);
    editor.dispatch({
      changes: { from: 0, to: editor.state.doc.length, insert: text },
      selection: EditorSelection.cursor(head),
    });
    callbacks.current.onChange(text, false);
  }, [text, revision]);

  React.useEffect(() => {
    view.current?.dispatch({
      effects: editable.current.reconfigure([EditorState.readOnly.of(readOnly), EditorView.editable.of(!readOnly)]),
    });
  }, [readOnly]);

  // Open at line: scroll it to the middle, put the cursor there and mark it briefly.
  React.useEffect(() => {
    const editor = view.current;
    if (!editor || !revealLine) return;
    const line = editor.state.doc.line(Math.min(Math.max(1, revealLine), editor.state.doc.lines));
    editor.dispatch({
      selection: EditorSelection.cursor(line.from),
      effects: [EditorView.scrollIntoView(line.from, { y: "center" }), markLine.of(revealLine)],
    });
    editor.focus();
    const timer = setTimeout(() => {
      if (view.current === editor) editor.dispatch({ effects: markLine.of(null) });
    }, 1600);
    return () => clearTimeout(timer);
  }, [revealLine, revealNonce]);

  return (
    <div
      ref={host}
      className="h-full min-h-0 overflow-hidden"
      onKeyDown={(event) => {
        // Editing keys stay in the editor; the app keeps its own shortcuts.
        if (!hasMod(event) || event.altKey) return;
        const key = event.key.toLowerCase();
        const appKey = ["p", "j", ",", "n", "o", "=", "+", "-", "0", "`", ";", "tab"].includes(key);
        if (!appKey || (isMac && key === "`")) event.stopPropagation();
      }}
    />
  );
}
