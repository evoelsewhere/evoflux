// Tools the app gives every chat's agent (RPC external tools): the in-app
// browser — the same tabs the person sees — and showing a file in the Files
// tool. engine-store.ts registers them and routes calls here.

import { invoke } from "@tauri-apps/api/core";
import { isWindows } from "@/lib/platform";
import { adoptTabs, agentTab, useBrowserStore, type BrowserTab } from "@/stores/browser-store";
import { useEngineStore } from "@/stores/engine-store";
import { openFile } from "@/stores/files-store";
import { useUiStore } from "@/stores/ui-store";
import { resolvePath } from "@/features/files/fs";
import { tabLabel as terminalLabel, terminalInstance, useTerminalStore } from "@/stores/terminal-store";

type Content = { type: "text"; text: string } | { type: "image"; data: string; mimeType: string };
export interface ToolResult {
  content: Content[];
  isError?: boolean;
}

const tabId = { tabId: { type: "string", description: "A tab id from browser_tabs; default: the active tab." } };

export const UI_TOOLS = [
  {
    name: "browser_navigate",
    description:
      "Open a URL in the app's built-in browser, which the user sees in the side panel (for previewing a local dev server, checking a page, reading docs). Also takes \"back\", \"forward\" or \"reload\". Opens a tab when none is open (or with newTab). Waits for the page to load and returns its title, URL and HTTP status, or an error when the page failed to load. Then use browser_read_page or browser_screenshot to see it.",
    inputSchema: {
      type: "object",
      properties: {
        url: { type: "string", description: "URL, host (localhost:3000), local file path, or back/forward/reload." },
        newTab: { type: "boolean", description: "Open in a new tab instead of the active one." },
        ...tabId,
      },
      required: ["url"],
      additionalProperties: false,
    },
  },
  {
    name: "browser_tabs",
    description: "List, select or close the built-in browser's tabs (shared with the user).",
    inputSchema: {
      type: "object",
      properties: {
        action: { type: "string", enum: ["list", "select", "close"], description: "Default list." },
        ...tabId,
      },
      additionalProperties: false,
    },
  },
  {
    name: "browser_screenshot",
    description: "A screenshot of the visible part of the page in the built-in browser.",
    inputSchema: { type: "object", properties: { ...tabId }, additionalProperties: false },
  },
  {
    name: "browser_read_page",
    description:
      "The page as an outline: URL, title, headings, text, and interactive elements (links, buttons, fields) each with a ref like [ref_12] to use with browser_click, browser_type, browser_form_input and browser_scroll. Links inside text show as [link text](ref_12). filter \"interactive\" lists only headings and elements.",
    inputSchema: {
      type: "object",
      properties: {
        filter: { type: "string", enum: ["all", "interactive"] },
        maxChars: { type: "number", description: "Default 30000." },
        ...tabId,
      },
      additionalProperties: false,
    },
  },
  {
    name: "browser_find",
    description: "Find elements on the page whose role, label or text contains the query; returns them with refs.",
    inputSchema: {
      type: "object",
      properties: { query: { type: "string" }, ...tabId },
      required: ["query"],
      additionalProperties: false,
    },
  },
  {
    name: "browser_click",
    description:
      "Click an element by ref (from browser_read_page / browser_find), or a point (x, y in CSS pixels of the screenshot). Returns the element's state afterwards (checked, focused, value) and the page.",
    inputSchema: {
      type: "object",
      properties: {
        ref: { type: "string" },
        x: { type: "number" },
        y: { type: "number" },
        doubleClick: { type: "boolean" },
        ...tabId,
      },
      additionalProperties: false,
    },
  },
  {
    name: "browser_type",
    description:
      "Type text into ref (focused first, text added at the end), or into the focused element. Returns which element got the text and its value. Date, time, color and range fields are set directly. submit presses Enter afterwards.",
    inputSchema: {
      type: "object",
      properties: { text: { type: "string" }, ref: { type: "string" }, submit: { type: "boolean" }, ...tabId },
      required: ["text"],
      additionalProperties: false,
    },
  },
  {
    name: "browser_key",
    description: "Press a key or combination in the page: Enter, Escape, Tab, Backspace, ArrowDown, PageDown, ctrl+a, shift+Tab…",
    inputSchema: {
      type: "object",
      properties: { key: { type: "string" }, ...tabId },
      required: ["key"],
      additionalProperties: false,
    },
  },
  {
    name: "browser_form_input",
    description: "Set a form field's value directly (text, select option by value or label, checkbox true/false).",
    inputSchema: {
      type: "object",
      properties: { ref: { type: "string" }, value: { type: "string", description: "Text, an option value or label, or true/false for a checkbox." }, ...tabId },
      required: ["ref", "value"],
      additionalProperties: false,
    },
  },
  {
    name: "browser_scroll",
    description:
      "Scroll the page: to an element (ref) or the first text matching text, or up/down (amount in screens, default 1), or to the top or bottom.",
    inputSchema: {
      type: "object",
      properties: {
        direction: { type: "string", enum: ["up", "down", "top", "bottom"] },
        amount: { type: "number" },
        ref: { type: "string", description: "Scroll this element to the middle of the view." },
        text: { type: "string", description: "Scroll the first visible text containing this (case-insensitive) into view." },
        ...tabId,
      },
      additionalProperties: false,
    },
  },
  {
    name: "browser_eval",
    description:
      "Run JavaScript in the page and return its value as JSON: an expression, or statements (the last one's value). A returned promise is awaited (up to 30s). Console messages it logs are shown too. For inspection and debugging.",
    inputSchema: {
      type: "object",
      properties: { expression: { type: "string" }, ...tabId },
      required: ["expression"],
      additionalProperties: false,
    },
  },
  {
    name: "browser_console",
    description: "The page's console messages and uncaught errors since it loaded.",
    inputSchema: {
      type: "object",
      properties: { onlyErrors: { type: "boolean" }, limit: { type: "number" }, ...tabId },
      additionalProperties: false,
    },
  },
  {
    name: "browser_network",
    description: "Requests the page made (URL, type, status, duration, size), from the browser's resource timing.",
    inputSchema: {
      type: "object",
      properties: { limit: { type: "number" }, ...tabId },
      additionalProperties: false,
    },
  },
  {
    name: "terminal_run",
    description:
      "Run a long-lived command (dev server, watcher, REPL) in a new tab of the app's terminal, which the user sees and can type into. It keeps running after your turn. Returns the tab id; read its output with terminal_read. For one-off commands use your shell tool instead.",
    inputSchema: {
      type: "object",
      properties: {
        command: { type: "string", description: "One line, typed into the shell and run." },
        cwd: { type: "string", description: "Folder to start in; default the working folder." },
      },
      required: ["command"],
      additionalProperties: false,
    },
  },
  {
    name: "terminal_read",
    description: "Read the last lines on screen of a tab of the app's terminal (the user's tabs too). Without tabId, lists the tabs.",
    inputSchema: {
      type: "object",
      properties: {
        tabId: { type: "string" },
        lines: { type: "number", description: "Default 80." },
        waitMs: { type: "number", description: "Wait this long for new output first (max 30000)." },
      },
      additionalProperties: false,
    },
  },
  {
    name: "show_file",
    description:
      "Show a file to the user in the app's Files panel, scrolled to a line. Use it to point the user at code you are talking about instead of pasting it.",
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string", description: "Absolute, or relative to the working folder." },
        line: { type: "number", description: "1-based line to scroll to." },
      },
      required: ["path"],
      additionalProperties: false,
    },
  },
];

export const isUiTool = (name: string) => UI_TOOLS.some((tool) => tool.name === name);

const text = (value: string, isError = false): ToolResult => ({ content: [{ type: "text", text: value }], ...(isError ? { isError } : {}) });

const evaluate = (tab: BrowserTab, script: string, statements = false) =>
  invoke<unknown>("browser_eval", { tab: tab.id, script, statements });
const cdp = (tab: BrowserTab, method: string, params: Record<string, unknown> = {}) =>
  invoke<Record<string, unknown>>("browser_cdp", { tab: tab.id, method, params });

/** What is loaded in the tab: its address, title, state, and a load error if any. */
interface PageInfo {
  href: string;
  title: string;
  ready: string;
  status?: number;
  error?: string;
}

const PAGE_INFO = `({
  href: location.href,
  title: document.title,
  ready: document.readyState,
  status: performance.getEntriesByType("navigation")[0]?.responseStatus || undefined,
  error: location.protocol === "chrome-error:"
    ? ((document.querySelector(".error-code")?.textContent || "") + " " + (document.querySelector("#main-message h1, h1")?.textContent || "")).trim() || document.body?.innerText.slice(0, 200) || "unknown error"
    : undefined,
})`;

async function pageInfo(tab: BrowserTab): Promise<PageInfo | null> {
  const info = (await evaluate(tab, PAGE_INFO).catch(() => null)) as PageInfo | null;
  if (!info || typeof info !== "object") return null;
  if (info.error) info.error = info.error.replace(/\s+/g, " ").trim();
  return info;
}

const nativeUrl = (tab: BrowserTab, fallback = tab.url) => invoke<string>("browser_url", { tab: tab.id }).catch(() => fallback);

/** Our page helper, or a clear error on pages without it (error pages, about:blank). */
async function helper<T>(tab: BrowserTab, call: string): Promise<T> {
  const ready = await evaluate(tab, "typeof window.__evo === 'object'").catch(() => false);
  if (!ready) {
    const info = await pageInfo(tab);
    if (info?.error) throw new Error(`The page failed to load: ${info.error}. Use browser_navigate to try again.`);
    throw new Error(`The page at ${info?.href ?? tab.url} cannot be read${info && info.ready !== "complete" ? " yet (still loading)" : ""}.`);
  }
  return (await evaluate(tab, `window.__evo.${call}`)) as T;
}

const KEYS: Record<string, [string, number]> = {
  enter: ["Enter", 13],
  escape: ["Escape", 27],
  esc: ["Escape", 27],
  tab: ["Tab", 9],
  backspace: ["Backspace", 8],
  delete: ["Delete", 46],
  space: [" ", 32],
  arrowup: ["ArrowUp", 38],
  arrowdown: ["ArrowDown", 40],
  arrowleft: ["ArrowLeft", 37],
  arrowright: ["ArrowRight", 39],
  home: ["Home", 36],
  end: ["End", 35],
  pageup: ["PageUp", 33],
  pagedown: ["PageDown", 34],
};

async function pressKey(tab: BrowserTab, combo: string) {
  const parts = combo.split("+").map((p) => p.trim()).filter(Boolean);
  const keyName = parts.pop() ?? "";
  const mods = parts.map((p) => p.toLowerCase());
  const modifiers =
    (mods.includes("alt") ? 1 : 0) |
    (mods.includes("ctrl") || mods.includes("control") ? 2 : 0) |
    (mods.includes("meta") || mods.includes("cmd") ? 4 : 0) |
    (mods.includes("shift") ? 8 : 0);
  const known = KEYS[keyName.toLowerCase()];
  const key = known ? known[0] : keyName;
  const code = known ? known[1] : keyName.toUpperCase().charCodeAt(0);
  const typed = known ? (key === "Enter" ? "\r" : key === " " ? " " : undefined) : modifiers & 6 ? undefined : keyName;
  await cdp(tab, "Input.dispatchKeyEvent", {
    type: typed ? "keyDown" : "rawKeyDown",
    key,
    windowsVirtualKeyCode: code,
    modifiers,
    ...(typed ? { text: typed, unmodifiedText: typed } : {}),
  });
  await cdp(tab, "Input.dispatchKeyEvent", { type: "keyUp", key, windowsVirtualKeyCode: code, modifiers });
}

async function clickAt(tab: BrowserTab, x: number, y: number, double: boolean) {
  await cdp(tab, "Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
  for (let count = 1; count <= (double ? 2 : 1); count++) {
    await cdp(tab, "Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", buttons: 1, clickCount: count });
    await cdp(tab, "Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", buttons: 0, clickCount: count });
  }
}

const settle = (ms = 400) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Show the Browser tool: the agent works on the page the user can watch.
 * When it was hidden, wait for the page to take its place and size (a page
 * laid out at another size puts elements somewhere else).
 */
async function showBrowser() {
  const ui = useUiStore.getState();
  if (ui.rightPanelOpen && ui.activePanel === "browser") return;
  ui.openPanel("browser");
  await settle(350);
}

/** A short line on what the tab shows. */
async function pageSummary(tab: BrowserTab) {
  const info = await pageInfo(tab);
  if (info?.error) return `failed to load: ${info.error} — ${await nativeUrl(tab)}`;
  const url = info?.href ?? (await nativeUrl(tab));
  const title = info ? info.title : (agentTab(tab.id) ?? tab).title;
  const notes = [info?.status && info.status >= 400 ? `HTTP ${info.status}` : "", info && info.ready !== "complete" ? "still loading" : ""].filter(Boolean);
  return `${title || "(untitled page)"} — ${url}${notes.length ? ` (${notes.join(", ")})` : ""}`;
}

/** Wait for a navigation of `tab` to begin (its URL changes or a load starts), then to finish. */
async function waitForNavigation(tab: BrowserTab, before: string, timeoutMs = 3000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (agentTab(tab.id)?.loading) break;
    if ((await nativeUrl(tab, before)) !== before) break;
    await settle(100);
  }
  await useBrowserStore.getState().waitForLoad(tab.id);
  // Load events can trail the document: give it a moment to be complete.
  for (let i = 0; i < 20; i++) {
    const info = await pageInfo(tab);
    if (!info || info.ready === "complete" || info.error) break;
    await settle(150);
  }
}

/** back / forward / reload; a message when there is no page to go to. */
async function goHistory(tab: BrowserTab, action: "back" | "forward" | "reload"): Promise<string | null> {
  const before = await nativeUrl(tab);
  if (action !== "reload" && isWindows) {
    const history = await cdp(tab, "Page.getNavigationHistory").catch(() => null);
    const entries = (history?.entries ?? []) as Array<{ id: number; url: string }>;
    const index = Number(history?.currentIndex ?? -1);
    if (history && index >= 0) {
      const target = entries[index + (action === "back" ? -1 : 1)];
      if (!target) return `There is no ${action === "back" ? "earlier" : "later"} page in this tab's history.`;
      await cdp(tab, "Page.navigateToHistoryEntry", { entryId: target.id });
      await waitForNavigation(tab, before);
      return null;
    }
  }
  if (action === "reload") useBrowserStore.setState((s) => ({ tabs: s.tabs.map((t) => (t.id === tab.id ? { ...t, loading: true } : t)) }));
  useBrowserStore.getState().go(tab.id, action);
  await waitForNavigation(tab, before);
  return null;
}

/** Console messages logged since `after`, as lines. */
async function consoleSince(tab: BrowserTab, after: number) {
  const logs = (await evaluate(tab, `window.__evo?.console(50, false, ${after}) ?? []`).catch(() => [])) as Array<{ level: string; text: string }>;
  return Array.isArray(logs) ? logs.map((l) => `[${l.level}] ${l.text}`) : [];
}

const quote = (value: string) => JSON.stringify(value.length > 60 ? `${value.slice(0, 60)}…` : value);

async function browserTool(name: string, args: Record<string, any>): Promise<ToolResult> {
  const browser = useBrowserStore.getState();
  if (name === "browser_navigate") {
    const url = String(args.url ?? "").trim();
    if (!url) return text("browser_navigate needs a url.", true);
    await showBrowser();
    let tab = args.newTab ? undefined : agentTab(args.tabId);
    if (["back", "forward", "reload"].includes(url)) {
      if (!tab) return text("No browser tab is open to go back, forward or reload.", true);
      const problem = await goHistory(tab, url as "back" | "forward" | "reload");
      if (problem) return text(problem, true);
    } else if (tab) {
      await browser.navigate(tab.id, url);
      const error = useBrowserStore.getState().error;
      if (error) return text(error, true);
      await waitForNavigation(tab, "");
    } else {
      const id = await browser.newTab(url);
      if (!id) return text(useBrowserStore.getState().error ?? "Could not open a browser tab.", true);
      tab = agentTab(id);
      if (tab) await waitForNavigation(tab, "");
    }
    if (!tab || !agentTab(tab.id)) return text("The tab closed.", true);
    const info = await pageInfo(tab);
    if (info?.error) return text(`The page failed to load: ${info.error} (${url}, tab ${tab.id}).`, true);
    return text(`Loaded ${await pageSummary(tab)} (tab ${tab.id})`);
  }

  if (name === "browser_tabs") {
    const action = args.action ?? "list";
    if (action === "select" || action === "close") {
      const tab = agentTab(args.tabId);
      if (!tab || !args.tabId) return text(`No tab ${args.tabId ?? ""}.`, true);
      if (action === "select") browser.select(tab.id);
      else browser.closeTab(tab.id);
    }
    if (!useBrowserStore.getState().tabs.length) await adoptTabs();
    const { tabs, activeId } = useBrowserStore.getState();
    if (tabs.length === 0) return text("No browser tabs are open. Use browser_navigate to open one.");
    const lines = await Promise.all(
      tabs.map(async (t) => {
        // The live page, not what the last events said.
        const info = await pageInfo(t);
        const url = info?.error ? await nativeUrl(t) : (info?.href ?? t.url);
        const loading = info ? info.ready !== "complete" && !info.error : t.loading;
        if (info && !loading && t.loading) useBrowserStore.setState((s) => ({ tabs: s.tabs.map((x) => (x.id === t.id ? { ...x, loading: false } : x)) }));
        const title = info?.error ? `failed to load: ${info.error}` : (info?.title ?? t.title) || "(untitled page)";
        return `${t.id === activeId ? "* " : "  "}${t.id}: ${title} — ${url}${loading ? " (loading)" : ""}`;
      }),
    );
    return text(lines.join("\n"));
  }

  let tab = agentTab(args.tabId);
  if (!tab && !args.tabId && (await adoptTabs())) tab = agentTab();
  if (!tab) return text(args.tabId ? `No browser tab ${args.tabId}; see browser_tabs.` : "No browser tab is open. Use browser_navigate first.", true);

  switch (name) {
    case "browser_screenshot": {
      await showBrowser();
      if (!isWindows) return text("Screenshots are not available on this platform yet; use browser_read_page.", true);
      await settle(250);
      const shot = await cdp(tab, "Page.captureScreenshot", { format: "jpeg", quality: 80 });
      const data = String(shot.data ?? "");
      if (!data) return text("The browser returned no image.", true);
      return { content: [{ type: "image", data, mimeType: "image/jpeg" }, { type: "text", text: await pageSummary(tab) }] };
    }
    case "browser_read_page": {
      const filter = args.filter === "interactive" ? "interactive" : "all";
      const maxChars = typeof args.maxChars === "number" ? Math.min(Math.max(1000, args.maxChars), 200_000) : 30_000;
      return text(await helper<string>(tab, `readPage(${JSON.stringify({ filter, maxChars })})`));
    }
    case "browser_find":
      return text(await helper<string>(tab, `find(${JSON.stringify(String(args.query ?? ""))})`));
    case "browser_click":
      return await click(tab, args);
    case "browser_type":
      return await type(tab, args);
    case "browser_key": {
      if (!isWindows) return text("Key presses need the DevTools protocol (Windows).", true);
      await pressKey(tab, String(args.key ?? ""));
      await settle(200);
      const focused = await evaluate(tab, "(() => { const t = window.__evo?.typingTarget(); return t ? window.__evo.state(t.ref) : null; })()").catch(() => null);
      return text(`Pressed ${args.key}.${focused ? ` Focused: ${focused}.` : ""}`);
    }
    case "browser_form_input": {
      const state = await helper<string>(tab, `setValue(${JSON.stringify(args.ref)}, ${JSON.stringify(args.value)})`);
      return text(`Set ${args.ref}: ${state}.`);
    }
    case "browser_scroll": {
      let target = "";
      if (args.ref || args.text) {
        target = await helper<string>(tab, `scrollTo(${JSON.stringify({ ref: args.ref, query: args.text })})`);
      } else {
        const amount = typeof args.amount === "number" ? args.amount : 1;
        const script =
          args.direction === "top"
            ? "scrollTo(0, 0)"
            : args.direction === "bottom"
              ? "scrollTo(0, document.documentElement.scrollHeight)"
              : args.direction === "up" || args.direction === "down"
                ? `scrollBy(0, ${args.direction === "up" ? -1 : 1} * innerHeight * ${amount} * 0.9)`
                : "";
        if (!script) return text("browser_scroll needs a direction, a ref or text.", true);
        await evaluate(tab, `(${script}, 0)`);
      }
      const where = (await evaluate(tab, "[Math.round(scrollY), Math.max(0, document.documentElement.scrollHeight - innerHeight)]")) as [number, number];
      return text(`${target ? `Scrolled to ${target}` : `Scrolled ${args.direction}`}; now at ${where[0]} of ${where[1]}.`);
    }
    case "browser_eval": {
      const seq = Number(await evaluate(tab, "window.__evo?.logSeq() ?? 0").catch(() => 0)) || 0;
      let out: string;
      let failed = false;
      try {
        const value = await evaluate(tab, String(args.expression ?? "undefined"), true);
        const json = JSON.stringify(value, null, 2) ?? "undefined";
        out = json.length > 50_000 ? `${json.slice(0, 50_000)}\n… (truncated)` : json;
      } catch (error) {
        out = `Error: ${error instanceof Error ? error.message : String(error)}`;
        failed = true;
      }
      const logs = await consoleSince(tab, seq);
      return text(logs.length ? `${out}\n\nConsole:\n${logs.join("\n")}` : out, failed);
    }
    case "browser_console": {
      const limit = typeof args.limit === "number" ? args.limit : 100;
      const logs = await helper<Array<{ level: string; at: number; text: string }>>(tab, `console(${limit}, ${!!args.onlyErrors})`);
      if (!logs?.length) return text(args.onlyErrors ? "No errors since the page loaded." : "No console messages since the page loaded.");
      return text(logs.map((l) => `[${l.level}] ${l.text}`).join("\n"));
    }
    case "browser_network": {
      const limit = typeof args.limit === "number" ? args.limit : 100;
      const requests = await helper<Array<{ url: string; type: string; status?: number; ms: number; bytes?: number }>>(tab, `network(${limit})`);
      if (!requests?.length) return text("No requests recorded.");
      return text(requests.map((r) => `${r.status ?? "—"} ${r.type} ${r.url} ${r.ms}ms${r.bytes ? ` ${r.bytes}B` : ""}`).join("\n"));
    }
  }
  return text(`Unknown tool ${name}.`, true);
}

/**
 * Click by ref or point. A ref is clicked with real input at its centre when
 * nothing covers it; when the click does not take (a radio stays unchecked,
 * a field unfocused) the element is clicked or focused by script instead.
 */
async function click(tab: BrowserTab, args: Record<string, any>): Promise<ToolResult> {
  await showBrowser();
  const before = await nativeUrl(tab);
  const notes: string[] = [];
  const ref = args.ref ? String(args.ref) : "";
  let effect = "none";
  if (ref) {
    effect = await helper<string>(tab, `clickEffect(${JSON.stringify(ref)})`);
    if (!isWindows) {
      await helper(tab, `click(${JSON.stringify(ref)})`);
    } else {
      const point = await helper<{ x: number; y: number; hits: boolean; covered: string | null }>(tab, `point(${JSON.stringify(ref)})`);
      if (point.hits) {
        await settle(60);
        await clickAt(tab, point.x, point.y, !!args.doubleClick);
      } else {
        notes.push(point.covered ? `it was covered by ${point.covered}, so it was clicked by script` : "it was off screen, so it was clicked by script");
        await helper(tab, `click(${JSON.stringify(ref)})`);
      }
    }
  } else {
    const { x, y } = args;
    if (typeof x !== "number" || typeof y !== "number") return text("browser_click needs a ref or x and y.", true);
    if (!isWindows) return text("Clicking a point needs the DevTools protocol (Windows); click by ref instead.", true);
    await clickAt(tab, x, y, !!args.doubleClick);
  }
  await settle(250);
  if (ref && effect !== "none") {
    const took = await evaluate(tab, `window.__evo.took(${JSON.stringify(ref)}, ${JSON.stringify(effect)})`).catch(() => true);
    if (!took) {
      await helper(tab, effect === "check" ? `click(${JSON.stringify(ref)})` : `focus(${JSON.stringify(ref)})`);
      notes.push(`the click did not ${effect === "check" ? "select" : "focus"} it, so it was ${effect === "check" ? "clicked" : "focused"} by script`);
    }
  }
  // A click that navigates: wait for the new page.
  if (agentTab(tab.id)?.loading || (await nativeUrl(tab, before)) !== before) await waitForNavigation(tab, before);
  const state = ref ? await evaluate(tab, `window.__evo?.state(${JSON.stringify(ref)}) ?? null`).catch(() => null) : null;
  const focused = ref ? null : await evaluate(tab, "(() => { const t = window.__evo?.typingTarget(); return t ? window.__evo.state(t.ref) : null; })()").catch(() => null);
  const lines = [`Clicked ${ref || `(${Math.round(args.x)}, ${Math.round(args.y)})`}${notes.length ? ` (${notes.join("; ")})` : ""}.`];
  if (state) lines.push(`Now: ${state}`);
  else if (focused) lines.push(`Focused: ${focused}`);
  lines.push(`Page: ${await pageSummary(tab)}`);
  return text(lines.join("\n"));
}

/** Type into ref or the focused element, check the text arrived, and say where it went. */
async function type(tab: BrowserTab, args: Record<string, any>): Promise<ToolResult> {
  const value = String(args.text ?? "");
  const ref = args.ref ? String(args.ref) : "";
  if (ref) await helper(tab, `focus(${JSON.stringify(ref)})`);
  const target = await helper<{ ref: string; kind: string; value: string } | null>(tab, `typingTarget(${ref ? JSON.stringify(ref) : ""})`);
  const notes: string[] = [];
  if (target?.kind === "other") notes.push("it is not a text field; pass the ref of one");
  if (target?.kind === "set") {
    // Date, time, color, range, select: keys fill them part by part; set the value.
    await helper(tab, `setValue(${JSON.stringify(target.ref)}, ${JSON.stringify(value)})`);
  } else if (isWindows) {
    await cdp(tab, "Input.insertText", { text: value });
    await settle(60);
    if (target?.kind === "keys" && value) {
      const now = await helper<{ value: string } | null>(tab, `typingTarget(${JSON.stringify(target.ref)})`);
      const expected = ref ? target.value + value : null;
      if (now && now.value === target.value) {
        // Nothing arrived (the focus was not where it seemed): insert by script.
        await helper(tab, `insert(${JSON.stringify(target.ref)}, ${JSON.stringify(value)})`);
        notes.push("typed by script");
      } else if (now && expected && now.value !== expected && now.value.startsWith(target.value) && expected.endsWith(now.value.slice(target.value.length))) {
        // The first characters were dropped.
        await helper(tab, `setValue(${JSON.stringify(target.ref)}, ${JSON.stringify(expected)})`);
        notes.push("completed by script");
      }
    }
  } else {
    if (target?.kind !== "keys") return text("Typing needs a ref of a text field on this platform.", true);
    await helper(tab, `insert(${JSON.stringify(target.ref)}, ${JSON.stringify(value)})`);
  }
  if (args.submit) {
    const before = await nativeUrl(tab);
    if (isWindows) await pressKey(tab, "Enter");
    else await evaluate(tab, "document.activeElement?.form?.requestSubmit()");
    await settle(300);
    if (agentTab(tab.id)?.loading || (await nativeUrl(tab, before)) !== before) await waitForNavigation(tab, before);
  } else await settle(100);
  const into = target ? await evaluate(tab, `window.__evo?.state(${JSON.stringify(target.ref)}) ?? null`).catch(() => null) : null;
  const where = into ? `into ${into}` : target ? `into ${target.ref}, which is no longer on the page` : "with no field focused (the keys went to the page)";
  return text(`Typed ${quote(value)} ${where}${notes.length ? ` (${notes.join("; ")})` : ""}${args.submit ? `, then pressed Enter. Page: ${await pageSummary(tab)}` : "."}`);
}

export async function runUiTool(name: string, args: Record<string, any>): Promise<ToolResult> {
  try {
    if (name === "show_file") {
      const path = String(args.path ?? "");
      if (!path) return text("show_file needs a path.", true);
      const root = useEngineStore.getState().cwd ?? "";
      const full = root ? resolvePath(root, path) : path;
      await openFile(full, typeof args.line === "number" ? args.line : undefined);
      return text(`Showing ${full}${args.line ? ` at line ${args.line}` : ""} in the Files panel.`);
    }
    if (name === "terminal_run" || name === "terminal_read") return await terminalTool(name, args);
    return await browserTool(name, args);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    // The native page went away under the store: forget it.
    const closed = /browser tab (\S+) is closed/.exec(message);
    if (closed) {
      useBrowserStore.getState().closeTab(closed[1]);
      return text(`Browser tab ${closed[1]} is gone. Use browser_tabs or browser_navigate.`, true);
    }
    return text(message, true);
  }
}

/** The last `count` lines of a terminal tab's buffer, trailing blank lines dropped. */
function screenLines(key: string, count: number): string {
  const term = terminalInstance(key)?.term;
  if (!term) return "";
  const buffer = term.buffer.active;
  const lines: string[] = [];
  for (let i = 0; i < buffer.length; i++) {
    const line = buffer.getLine(i);
    const value = line?.translateToString(true) ?? "";
    // A line the terminal wrapped continues the one before it.
    if (line?.isWrapped && lines.length) lines[lines.length - 1] += value;
    else lines.push(value);
  }
  while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
  return lines.slice(-count).join("\n");
}

async function terminalTool(name: string, args: Record<string, any>): Promise<ToolResult> {
  const terminals = useTerminalStore.getState();
  if (name === "terminal_run") {
    const command = String(args.command ?? "").replace(/[\r\n]+$/, "");
    if (!command.trim()) return text("terminal_run needs a command.", true);
    if (/[\r\n]/.test(command)) return text("terminal_run takes one line.", true);
    useUiStore.getState().openPanel("terminal");
    await terminals.restore();
    const cwd = args.cwd ? String(args.cwd) : (useEngineStore.getState().cwd ?? undefined);
    const key = await terminals.create({ cwd });
    const tab = useTerminalStore.getState().tabs.find((t) => t.key === key);
    if (!key || !tab || tab.status !== "running") return text(useTerminalStore.getState().error ?? "Could not start a terminal.", true);
    // Let the shell print its prompt before typing.
    await settle(800);
    terminalInstance(key)?.send(`${command}\r`);
    await settle(1500);
    return text(`Started in terminal tab ${key} (${tab.shell}, ${tab.cwd}):\n${screenLines(key, 30)}`);
  }
  const tabs = useTerminalStore.getState().tabs;
  if (!args.tabId) {
    if (tabs.length === 0) return text("No terminal tabs are open.");
    return text(tabs.map((t) => `${t.key}: ${terminalLabel(t)} — ${t.cwd} (${t.status})`).join("\n"));
  }
  const tab = tabs.find((t) => t.key === args.tabId);
  if (!tab) return text(`No terminal tab ${args.tabId}.`, true);
  const wait = Math.min(Math.max(0, Number(args.waitMs) || 0), 30_000);
  if (wait) await settle(wait);
  const lines = Math.min(Math.max(1, Number(args.lines) || 80), 1000);
  const status = tab.status === "exited" ? ` (exited${tab.exitCode != null ? ` with code ${tab.exitCode}` : ""})` : "";
  return text(`${terminalLabel(tab)} — ${tab.cwd}${status}\n${screenLines(tab.key, lines)}`);
}
