// One xterm.js terminal bound to a pseudo-terminal. Instances live outside
// React: the panel can unmount (another tool tab, side panel closed) while the
// shell keeps running and the terminal keeps its screen and scrollback; the
// view moves the terminal's element into whatever container shows it.

import "@xterm/xterm/css/xterm.css";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { SearchAddon, type ISearchOptions } from "@xterm/addon-search";
import { Unicode11Addon } from "@xterm/addon-unicode11";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { openUrl } from "@tauri-apps/plugin-opener";
import { hasMod, isMac, isWindows } from "@/lib/platform";
import { useAppearanceStore } from "@/stores/appearance-store";
import { resizePty, writePty } from "./pty";
import { isDark, loadTerminalFont, themedOptions } from "./terminal-theme";

export interface InstanceCallbacks {
  /** The shell set the window title (OSC 0/2). */
  onTitle(title: string): void;
  /** Ctrl+Shift+F / ⌘F inside the terminal. */
  onFindRequest(): void;
}

const SEARCH_DECORATIONS = (): ISearchOptions["decorations"] => {
  const dark = isDark();
  return {
    matchBackground: dark ? "#ffb22440" : "#ffb22466",
    matchOverviewRuler: "#ffb224",
    activeMatchBackground: dark ? "#ffb224a6" : "#ffb224cc",
    activeMatchColorOverviewRuler: "#ff9500",
  };
};

/** Copy text through the async clipboard, falling back to a hidden textarea. */
export async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
}

export class TerminalInstance {
  readonly term: Terminal;
  readonly search: SearchAddon;
  private readonly fitAddon = new FitAddon();
  /** Our own wrapper, opened once and then moved between containers. */
  private readonly host: HTMLDivElement;
  private opened = false;
  private ptyId: number | null = null;
  private pending = "";
  private flushing = false;
  private fitFrame = 0;
  private disposed = false;
  private replaying = false;
  private focusOnOpen = false;
  private focusWanted = -Infinity;
  private focusRetry: ReturnType<typeof setTimeout> | undefined;

  constructor(private readonly callbacks: InstanceCallbacks) {
    this.host = document.createElement("div");
    this.host.className = "evo-terminal h-full w-full";
    this.term = new Terminal({
      ...themedOptions(),
      allowProposedApi: true,
      allowTransparency: true,
      fontSize: 13,
      lineHeight: 1.2,
      cursorBlink: true,
      cursorStyle: "bar",
      cursorInactiveStyle: "outline",
      scrollback: 10_000,
      macOptionIsMeta: true,
      rightClickSelectsWord: false,
      ...(isWindows ? { windowsPty: { backend: "conpty" as const } } : {}),
    });
    this.search = new SearchAddon();
    this.term.loadAddon(this.fitAddon);
    this.term.loadAddon(this.search);
    this.term.loadAddon(
      // Links open with Ctrl/⌘+click, like most terminals, so a stray click does not.
      new WebLinksAddon((event, uri) => {
        if (isMac ? event.metaKey : event.ctrlKey) void openUrl(uri).catch(() => undefined);
      }),
    );
    const unicode = new Unicode11Addon();
    this.term.loadAddon(unicode);
    this.term.unicode.activeVersion = "11";

    this.term.onData((data) => this.send(data));
    this.term.onBinary((data) => this.send(data));
    this.term.onResize(({ cols, rows }) => {
      if (this.ptyId !== null) void resizePty(this.ptyId, cols, rows).catch(() => undefined);
    });
    this.term.onTitleChange((title) => this.callbacks.onTitle(title));
    this.term.attachCustomKeyEventHandler((event) => this.onKey(event));
    instances.add(this);
  }

  /** The pty keys go to; queued input flushes once one is bound. */
  bind(ptyId: number) {
    this.ptyId = ptyId;
    void this.flush();
    // The pty may have started at a guessed size.
    void resizePty(ptyId, this.term.cols, this.term.rows).catch(() => undefined);
  }

  unbind() {
    this.ptyId = null;
    this.pending = "";
  }

  get boundPty() {
    return this.ptyId;
  }

  write(data: string) {
    this.term.write(data);
  }

  /**
   * Replay output saved while no window listened. Queries in it (cursor
   * position, device attributes) were answered back then; answering them again
   * would type stray escape sequences into the shell.
   */
  replay(data: string) {
    if (!data) return;
    this.replaying = true;
    this.term.write(data, () => {
      this.replaying = false;
    });
  }

  /** Keys and pastes go out in order, one write at a time, batched while one is in flight. */
  send(data: string) {
    if (this.ptyId === null || this.replaying) return;
    this.pending += data;
    void this.flush();
  }

  private async flush() {
    if (this.flushing) return;
    this.flushing = true;
    try {
      while (this.pending && this.ptyId !== null) {
        const chunk = this.pending;
        this.pending = "";
        await writePty(this.ptyId, chunk).catch(() => undefined);
      }
    } finally {
      this.flushing = false;
    }
  }

  /** Show the terminal in `container` (it must be in the document). */
  async attach(container: HTMLElement) {
    container.appendChild(this.host);
    // Moved right after a focus request (a remount): moving the element dropped its focus.
    if (this.opened && this.term.element && performance.now() - this.focusWanted < 1000) this.term.focus();
    if (!this.opened) {
      this.opened = true;
      await loadTerminalFont();
      if (this.disposed) return;
      this.term.open(this.host);
      if (this.focusOnOpen) {
        this.focusOnOpen = false;
        this.fit();
        this.term.focus();
      }
    }
    this.fit();
  }

  detach() {
    cancelAnimationFrame(this.fitFrame);
    this.host.remove();
  }

  /** Fit to the container on the next frame (resize observers fire in bursts). */
  scheduleFit() {
    cancelAnimationFrame(this.fitFrame);
    this.fitFrame = requestAnimationFrame(() => this.fit());
  }

  fit() {
    // Hidden or collapsed: keep the last size instead of shrinking to nothing.
    if (!this.opened || !this.host.isConnected || this.host.clientWidth < 40 || this.host.clientHeight < 20) return;
    try {
      this.fitAddon.fit();
    } catch {
      // Not measurable yet (fonts, layout); the next resize fits it.
    }
  }

  focus() {
    // Not opened yet (the font is loading): focus once it is.
    if (!this.opened || !this.term.element) {
      this.focusOnOpen = true;
      return;
    }
    this.focusWanted = performance.now();
    this.term.focus();
    // The side panel may still be sliding open (collapsed, not focusable): try again after it.
    clearTimeout(this.focusRetry);
    this.focusRetry = setTimeout(() => {
      if (this.host.isConnected && !this.host.contains(document.activeElement)) this.term.focus();
    }, 300);
  }

  applyAppearance() {
    this.term.options = themedOptions();
    this.scheduleFit();
  }

  findNext(query: string, options: ISearchOptions = {}) {
    return this.search.findNext(query, { ...options, decorations: SEARCH_DECORATIONS() });
  }

  findPrevious(query: string, options: ISearchOptions = {}) {
    return this.search.findPrevious(query, { ...options, decorations: SEARCH_DECORATIONS() });
  }

  async copySelection() {
    const text = this.term.getSelection();
    if (text) await copyText(text);
  }

  async paste() {
    try {
      const text = await navigator.clipboard.readText();
      if (text) this.term.paste(text);
    } catch {
      // Clipboard read was refused; Ctrl+V (⌘V) still pastes through the browser.
    }
    this.focus();
  }

  /**
   * Keys the terminal does not take: copy, paste and find, and the app's own
   * shortcuts (side panel, palette, settings, zoom, tabs). `false` leaves the
   * event to the browser and the window's hotkeys.
   */
  private onKey(event: KeyboardEvent): boolean {
    if (event.type !== "keydown") return true;
    const key = event.key.toLowerCase();
    const mod = hasMod(event);

    const copy = isMac
      ? mod && !event.shiftKey && key === "c"
      : event.ctrlKey && key === "c" && (event.shiftKey || this.term.hasSelection());
    if (copy && this.term.hasSelection()) {
      event.preventDefault();
      void this.copySelection();
      if (!isMac && !event.shiftKey) this.term.clearSelection();
      return false;
    }
    if (copy && event.shiftKey) {
      event.preventDefault();
      return false;
    }
    // Paste: let the browser fire its paste event, which xterm handles (bracketed paste included).
    if (isMac ? mod && key === "v" : event.ctrlKey && key === "v" && (event.shiftKey || isWindows)) return false;
    if (event.shiftKey && !event.ctrlKey && !event.metaKey && key === "insert") return false;

    if (isMac ? mod && !event.shiftKey && key === "f" : event.ctrlKey && event.shiftKey && key === "f") {
      event.preventDefault();
      event.stopPropagation();
      this.callbacks.onFindRequest();
      return false;
    }
    // ⌘K clears, as in Terminal.app and iTerm.
    if (isMac && mod && key === "k") {
      event.preventDefault();
      event.stopPropagation();
      this.term.clear();
      return false;
    }
    if (isMac) return !event.metaKey; // every ⌘ shortcut belongs to the app
    if (event.ctrlKey && !event.altKey) {
      if (event.code === "Backquote" || key === "tab" || key === "," || key === "j" || key === "p") return false;
      if (key === "=" || key === "+" || key === "-" || key === "0") return false;
      if (event.shiftKey && key === "i") return false;
    }
    return true;
  }

  dispose() {
    this.disposed = true;
    instances.delete(this);
    this.detach();
    this.unbind();
    this.term.dispose();
  }
}

/** Live instances, restyled together when the theme or the code font changes. */
const instances = new Set<TerminalInstance>();

function restyleAll() {
  for (const instance of instances) instance.applyAppearance();
}

if (typeof document !== "undefined") {
  new MutationObserver(restyleAll).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["class", "style"],
  });
  useAppearanceStore.subscribe((state, previous) => {
    if (state.codeFont !== previous.codeFont) void loadTerminalFont().then(restyleAll);
  });
}
