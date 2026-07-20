/**
 * EvoFlux WebBridge — Chrome Extension Service Worker
 *
 * Connects to the EvoFlux backend relay via WebSocket and uses
 * chrome.debugger (CDP) to control the real browser.
 *
 * Architecture:
 *   Agent ←→ Backend Relay ←→ This Extension ←→ Real Browser (CDP)
 */

const DEFAULT_RELAY_BASE = "ws://127.0.0.1:8000";
const RELAY_PATH = "/api/team/webbridge/relay";
const RECONNECT_BASE_MS = 1000; // first retry delay
const RECONNECT_MAX_MS = 30000; // cap on the exponential backoff
const HEARTBEAT_ALARM = "webbridge-heartbeat";
const HEARTBEAT_PERIOD_MIN = 0.5; // minimum period chrome.alarms allows

let ws = null;
let extensionId = null; // loaded/persisted in chrome.storage.local (stable across SW restarts)
let connected = false;
let reconnectTimer = null;
let reconnectAttempts = 0;
let attachedTabs = new Map(); // tabId → true (CDP attached)
let manualDisconnect = false;
let lastCloseReason = null; // null | "auth" (4401) | "closed"
let relayBase = DEFAULT_RELAY_BASE;
let accessToken = "";

// ── Config (persisted in chrome.storage.local, edited via the popup) ─────────

async function loadConfig() {
  try {
    const cfg = await chrome.storage.local.get(["relayBase", "accessToken", "extensionId"]);
    relayBase = (cfg.relayBase || DEFAULT_RELAY_BASE).trim().replace(/\/+$/, "");
    accessToken = (cfg.accessToken || "").trim();
    // A stable id keeps the relay from accumulating a ghost registration on
    // every MV3 service-worker restart (which discards in-memory state).
    if (cfg.extensionId) {
      extensionId = cfg.extensionId;
    } else if (!extensionId) {
      extensionId = generateId();
      chrome.storage.local.set({ extensionId });
    }
  } catch (e) {
    console.warn("[WebBridge] Failed to load config, using defaults:", e);
    relayBase = DEFAULT_RELAY_BASE;
    accessToken = "";
    if (!extensionId) extensionId = generateId();
  }
}

function buildRelayUrl() {
  // Accept http(s):// bases too — normalize to ws(s)://.
  const base = (relayBase || DEFAULT_RELAY_BASE).replace(/^http/i, "ws");
  let url = base + RELAY_PATH;
  if (accessToken) url += "?_token=" + encodeURIComponent(accessToken);
  return url;
}

// ── Connection management ────────────────────────────────────────────────────

async function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;

  await loadConfig();
  manualDisconnect = false;

  let sock;
  try {
    sock = new WebSocket(buildRelayUrl());
  } catch (e) {
    console.error("[WebBridge] WebSocket creation failed:", e);
    scheduleReconnect();
    return;
  }
  ws = sock;

  sock.onopen = () => {
    if (ws !== sock) return; // superseded by a newer socket
    console.log("[WebBridge] Connected to relay");
    connected = true;
    lastCloseReason = null;
    reconnectAttempts = 0; // reset the backoff after a successful connect
    clearTimeout(reconnectTimer);

    // Register with the relay
    sock.send(JSON.stringify({
      type: "register",
      extension_id: extensionId,
      browser: detectBrowser(),
      version: chrome.runtime.getManifest().version,
    }));

    ensureHeartbeatAlarm();
    broadcastTabInfo();
  };

  sock.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleMessage(msg);
    } catch (e) {
      console.error("[WebBridge] Failed to parse message:", e);
    }
  };

  sock.onclose = (event) => {
    if (ws !== sock) return; // superseded socket — ignore its close event
    console.log("[WebBridge] Disconnected from relay (code", event.code + ")");
    connected = false;
    ws = null;
    // 4401 = relay rejected the access token — surface it in the popup.
    lastCloseReason = event.code === 4401 ? "auth" : "closed";
    if (!manualDisconnect) scheduleReconnect();
  };

  sock.onerror = (e) => {
    console.error("[WebBridge] WebSocket error:", e);
  };
}

function disconnect() {
  manualDisconnect = true;
  clearTimeout(reconnectTimer);
  if (ws) {
    try { ws.close(); } catch { /* already closed */ }
    ws = null;
  }
  connected = false;
}

// Exponential backoff with jitter, capped — avoids hammering the relay (and
// a thundering-herd of extensions all retrying in lock-step) while a backend
// is down, yet still recovers within seconds of it coming back.
function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  const backoff = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** reconnectAttempts);
  const delay = Math.round(backoff + Math.random() * 0.3 * backoff);
  reconnectAttempts++;
  reconnectTimer = setTimeout(connect, delay);
}

// MV3 service workers are killed regardless of setInterval — the heartbeat
// must run on chrome.alarms (0.5 min is the minimum period). The alarm both
// pings the relay and wakes the worker to re-establish a dropped connection.
function ensureHeartbeatAlarm() {
  chrome.alarms.create(HEARTBEAT_ALARM, { periodInMinutes: HEARTBEAT_PERIOD_MIN });
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== HEARTBEAT_ALARM) return;
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "ping" }));
  } else if (!manualDisconnect) {
    connect();
  }
});

function detectBrowser() {
  const ua = navigator.userAgent;
  if (ua.includes("Edg/")) return "edge";
  if (ua.includes("Chrome")) return "chrome";
  return "unknown";
}

function generateId() {
  return "ext-" + Math.random().toString(36).substring(2, 10);
}

// ── Message handling ─────────────────────────────────────────────────────────

async function handleMessage(msg) {
  if (msg.type === "registered") {
    console.log("[WebBridge] Registered with ID:", msg.extension_id);
    if (msg.extension_id && msg.extension_id !== extensionId) {
      extensionId = msg.extension_id;
      chrome.storage.local.set({ extensionId }); // keep the relay-confirmed id stable
    }
    return;
  }

  if (msg.type === "command") {
    await handleCommand(msg);
  }
}

async function handleCommand(msg) {
  const { request_id, action, params } = msg;

  try {
    let result;

    switch (action) {
      case "navigate":
        result = await cmdNavigate(params);
        break;
      case "click":
        result = await cmdClick(params);
        break;
      case "dblclick":
        result = await cmdDblClick(params);
        break;
      case "type":
        result = await cmdType(params);
        break;
      case "key":
        result = await cmdKey(params);
        break;
      case "scroll":
        result = await cmdScroll(params);
        break;
      case "screenshot":
        result = await cmdScreenshot(params);
        break;
      case "extract":
        result = await cmdExtract(params);
        break;
      case "get_tabs":
        result = await cmdGetTabs();
        break;
      case "switch_tab":
        result = await cmdSwitchTab(params);
        break;
      case "evaluate":
        result = await cmdEvaluate(params);
        break;
      case "back":
        result = await cmdBack(params);
        break;
      case "forward":
        result = await cmdForward(params);
        break;
      case "reload":
        result = await cmdReload(params);
        break;
      case "wait":
        result = await cmdWait(params);
        break;
      case "wait_for_selector":
        result = await cmdWaitForSelector(params);
        break;
      case "wait_for_load":
        result = await cmdWaitForLoad(params);
        break;
      case "wait_for_network_idle":
        result = await cmdWaitForNetworkIdle(params);
        break;
      case "click_selector":
        result = await cmdClickSelector(params);
        break;
      case "click_text":
        result = await cmdClickText(params);
        break;
      case "fill":
        result = await cmdFill(params);
        break;
      case "open_tab":
        result = await cmdOpenTab(params);
        break;
      case "close_tab":
        result = await cmdCloseTab(params);
        break;
      case "snapshot":
        result = await cmdSnapshot(params);
        break;
      case "extract_elements":
        result = await cmdExtractElements(params);
        break;
      case "scroll_to_bottom":
        result = await cmdScrollToBottom(params);
        break;
      case "status":
        result = await cmdStatus();
        break;
      default:
        sendResponse(request_id, false, null, `Unknown action: ${action}`);
        return;
    }

    sendResponse(request_id, true, result);
  } catch (e) {
    // Not a crash — the failure is reported back to the agent via
    // sendResponse(false). Keep it as a warning so chrome://extensions
    // "Errors" stays reserved for real extension faults.
    console.warn(`[WebBridge] Command failed (${action}):`, e.message);
    sendResponse(request_id, false, null, e.message);
  }
}

function sendResponse(request_id, success, data, error) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: "response",
      request_id,
      success,
      data,
      error: error || undefined,
    }));
  }
}

// ── CDP helper ───────────────────────────────────────────────────────────────

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

// Resolve the tab a command targets: an explicit params.tab_id (so a session
// can pin a tab and stay deterministic even if the user switches tabs), else
// the active tab.
async function resolveTab(params) {
  if (params && params.tab_id != null) {
    try {
      return await chrome.tabs.get(params.tab_id);
    } catch {
      throw new Error(`Tab ${params.tab_id} not found`);
    }
  }
  const tab = await getActiveTab();
  if (!tab) throw new Error("No active tab");
  return tab;
}

// Run an expression in the page and return its (JSON) value, raising on a
// thrown JS exception instead of silently returning undefined.
async function evalInPage(tabId, expression, awaitPromise = false) {
  const result = await cdpSend(tabId, "Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise,
  });
  if (result.exceptionDetails) {
    const ex = result.exceptionDetails;
    throw new Error(ex.exception?.description || ex.text || "Script error");
  }
  return result.result?.value;
}

// Dispatch a real press/release mouse click at viewport CSS coords (x,y),
// which triggers the full native event sequence element.click() skips.
async function clickAt(tabId, x, y) {
  await cdpSend(tabId, "Input.dispatchMouseEvent", {
    type: "mousePressed", x, y, button: "left", clickCount: 1,
  });
  await cdpSend(tabId, "Input.dispatchMouseEvent", {
    type: "mouseReleased", x, y, button: "left", clickCount: 1,
  });
}

async function ensureDebuggerAttached(tabId) {
  if (attachedTabs.has(tabId)) return;

  return new Promise((resolve, reject) => {
    chrome.debugger.attach({ tabId }, "1.3", () => {
      if (chrome.runtime.lastError) {
        reject(new Error(
          chrome.runtime.lastError.message +
          " (the tab may be a restricted page — chrome://, Web Store, or another extension's page — navigate to a normal page first)"
        ));
      } else {
        attachedTabs.set(tabId, true);
        resolve();
      }
    });
  });
}

async function detachDebugger(tabId) {
  if (!attachedTabs.has(tabId)) return;

  return new Promise((resolve) => {
    chrome.debugger.detach({ tabId }, () => {
      attachedTabs.delete(tabId);
      resolve();
    });
  });
}

function sendCommandOnce(tabId, method, params) {
  return new Promise((resolve, reject) => {
    chrome.debugger.sendCommand({ tabId }, method, params, (result) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else {
        resolve(result);
      }
    });
  });
}

async function cdpSend(tabId, method, params = {}) {
  await ensureDebuggerAttached(tabId);

  try {
    return await sendCommandOnce(tabId, method, params);
  } catch (e) {
    if (!/not attached/i.test(e.message)) throw e;
    // attachedTabs lied: Chrome auto-detaches on navigation to restricted
    // pages (chrome://, web store), the user can cancel the debugging
    // infobar, and an MV3 worker restart loses in-memory state. Drop the
    // stale entry, re-attach once, and retry the command.
    attachedTabs.delete(tabId);
    await ensureDebuggerAttached(tabId);
    return sendCommandOnce(tabId, method, params);
  }
}

// ── Network in-flight tracking (for wait_for_network_idle) ────────────────────
// tabId → Set of CDP requestIds currently in flight. Populated by the
// Network.* debugger events below; only meaningful once Network.enable has
// been sent for that tab (cmdWaitForNetworkIdle does that).
const networkInflight = new Map();
function netInc(tabId, id) {
  let s = networkInflight.get(tabId);
  if (!s) { s = new Set(); networkInflight.set(tabId, s); }
  s.add(id);
}
function netDec(tabId, id) {
  const s = networkInflight.get(tabId);
  if (s) s.delete(id);
}
function netCount(tabId) {
  const s = networkInflight.get(tabId);
  return s ? s.size : 0;
}

chrome.debugger.onEvent.addListener((source, method, params) => {
  const tabId = source.tabId;
  if (!tabId || !params) return;
  if (method === "Network.requestWillBeSent") netInc(tabId, params.requestId);
  else if (method === "Network.loadingFinished" || method === "Network.loadingFailed") netDec(tabId, params.requestId);
  else if (method === "Network.requestServedFromCache") netDec(tabId, params.requestId);
});

// Chrome detached the debugger outside our control (infobar Cancel,
// navigation to a restricted page, tab process gone) — forget the stale
// state so the next command re-attaches instead of failing.
chrome.debugger.onDetach.addListener((source) => {
  networkInflight.delete(source.tabId);
  if (source.tabId && attachedTabs.delete(source.tabId)) {
    console.warn("[WebBridge] Debugger detached from tab", source.tabId);
    broadcastTabInfo();
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  attachedTabs.delete(tabId);
  networkInflight.delete(tabId);
});

// ── Command implementations ──────────────────────────────────────────────────

async function cmdNavigate(params) {
  const tab = await resolveTab(params);

  await chrome.tabs.update(tab.id, { url: params.url });

  // Wait for navigation to complete
  return new Promise((resolve) => {
    const listener = (tabId, changeInfo) => {
      if (tabId === tab.id && changeInfo.status === "complete") {
        chrome.tabs.onUpdated.removeListener(listener);
        resolve({ success: true, url: params.url });
      }
    };
    chrome.tabs.onUpdated.addListener(listener);

    // Timeout after 30s
    setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      resolve({ success: true, url: params.url });
    }, 30000);
  });
}

async function cmdClick(params) {
  const tab = await resolveTab(params);

  const { x, y, button = "left" } = params;

  // Use CDP Input.dispatchMouseEvent
  await cdpSend(tab.id, "Input.dispatchMouseEvent", {
    type: "mousePressed",
    x,
    y,
    button: button === "right" ? "right" : "left",
    clickCount: 1,
  });
  await cdpSend(tab.id, "Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x,
    y,
    button: button === "right" ? "right" : "left",
    clickCount: 1,
  });

  return { success: true, x, y };
}

async function cmdDblClick(params) {
  const tab = await resolveTab(params);

  const { x, y } = params;

  for (let i = 0; i < 2; i++) {
    await cdpSend(tab.id, "Input.dispatchMouseEvent", {
      type: "mousePressed",
      x,
      y,
      button: "left",
      clickCount: i + 1,
    });
    await cdpSend(tab.id, "Input.dispatchMouseEvent", {
      type: "mouseReleased",
      x,
      y,
      button: "left",
      clickCount: i + 1,
    });
  }

  return { success: true, x, y };
}

async function cmdType(params) {
  const tab = await resolveTab(params);

  const { text } = params;

  // Input.insertText handles unicode/IME composition correctly and is a
  // single CDP call instead of two synthetic key events per character.
  await cdpSend(tab.id, "Input.insertText", { text });

  return { success: true, length: text.length };
}

async function cmdKey(params) {
  const tab = await resolveTab(params);

  const { key } = params;

  // Map common key names to CDP key values
  const keyMap = {
    "Enter": { key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 },
    "Tab": { key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 },
    "Escape": { key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 },
    "Backspace": { key: "Backspace", code: "Backspace", windowsVirtualKeyCode: 8 },
    "Delete": { key: "Delete", code: "Delete", windowsVirtualKeyCode: 46 },
    "ArrowUp": { key: "ArrowUp", code: "ArrowUp", windowsVirtualKeyCode: 38 },
    "ArrowDown": { key: "ArrowDown", code: "ArrowDown", windowsVirtualKeyCode: 40 },
    "ArrowLeft": { key: "ArrowLeft", code: "ArrowLeft", windowsVirtualKeyCode: 37 },
    "ArrowRight": { key: "ArrowRight", code: "ArrowRight", windowsVirtualKeyCode: 39 },
    "Home": { key: "Home", code: "Home", windowsVirtualKeyCode: 36 },
    "End": { key: "End", code: "End", windowsVirtualKeyCode: 35 },
    "PageUp": { key: "PageUp", code: "PageUp", windowsVirtualKeyCode: 33 },
    "PageDown": { key: "PageDown", code: "PageDown", windowsVirtualKeyCode: 34 },
  };

  const mapped = keyMap[key] || { key, code: key };

  await cdpSend(tab.id, "Input.dispatchKeyEvent", {
    type: "keyDown",
    ...mapped,
  });
  await cdpSend(tab.id, "Input.dispatchKeyEvent", {
    type: "keyUp",
    ...mapped,
  });

  return { success: true, key };
}

async function cmdScroll(params) {
  const tab = await resolveTab(params);

  const { dx = 0, dy = 0 } = params;

  // Use CDP Input.dispatchMouseEvent for scroll
  // Scroll events use mouseWheel with deltaX/deltaY
  await cdpSend(tab.id, "Input.dispatchMouseEvent", {
    type: "mouseWheel",
    x: 0,
    y: 0,
    deltaX: dx,
    deltaY: dy,
  });

  return { success: true, dx, dy };
}

async function getViewportMetrics(tabId) {
  return evalInPage(tabId, `(() => ({
    width: Math.round(window.innerWidth),
    height: Math.round(window.innerHeight),
    dpr: window.devicePixelRatio || 1,
    scrollX: Math.round(window.scrollX),
    scrollY: Math.round(window.scrollY),
    pageWidth: Math.round(Math.max(document.documentElement.scrollWidth, document.body ? document.body.scrollWidth : 0)),
    pageHeight: Math.round(Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0)),
  }))()`);
}

async function cmdScreenshot(params) {
  const tab = await resolveTab(params);
  const { format = "png", quality = 80, full_page = false } = params || {};
  const fmt = format === "jpeg" ? "jpeg" : "png";

  const vp = await getViewportMetrics(tab.id);

  // clip.scale = 1 makes 1 image pixel == 1 CSS pixel regardless of the
  // display's devicePixelRatio, so click coordinates the model reads off the
  // screenshot map 1:1 to Input.dispatchMouseEvent (which uses CSS pixels).
  // Without this a Retina (dpr=2) capture is 2x-sized and every click lands
  // at half the intended position.
  let clip;
  if (full_page) {
    // Cap height so an infinite-scroll page can't produce a huge capture.
    const MAX_FULL_PAGE_PX = 20000;
    clip = { x: 0, y: 0, width: vp.pageWidth, height: Math.min(vp.pageHeight, MAX_FULL_PAGE_PX), scale: 1 };
  } else {
    clip = { x: vp.scrollX, y: vp.scrollY, width: vp.width, height: vp.height, scale: 1 };
  }

  const result = await cdpSend(tab.id, "Page.captureScreenshot", {
    format: fmt,
    quality: fmt === "jpeg" ? quality : undefined,
    clip,
    captureBeyondViewport: true,
    fromSurface: true,
  });

  return {
    success: true,
    data: result.data,
    format: fmt,
    full_page,
    viewport: {
      width: clip.width,
      height: clip.height,
      dpr: vp.dpr,
      scrollX: vp.scrollX,
      scrollY: vp.scrollY,
    },
  };
}

async function cmdExtract(params) {
  const tab = await resolveTab(params);
  const { format = "text", selector = null, max_chars = 15000 } = params || {};
  const MODE = JSON.stringify(format === "markdown" || format === "html" ? format : "text");
  const SEL = selector ? JSON.stringify(selector) : "null";
  const MAX = Math.max(100, Math.min(200000, Number(max_chars) || 15000));

  const data = await evalInPage(
    tab.id,
    `(() => {
      const MODE = ${MODE}, SEL = ${SEL}, MAX = ${MAX};
      const root = SEL ? document.querySelector(SEL) : (document.body || document.documentElement);
      const base = {
        title: document.title,
        url: location.href,
        format: MODE,
        meta: {
          description: document.querySelector('meta[name="description"]')?.content || "",
          ogTitle: document.querySelector('meta[property="og:title"]')?.content || "",
        },
      };
      if (!root) return { ...base, content: "", missing: true };
      const inlineText = (n) => (n.textContent || "").replace(/\\s+/g, " ").trim();
      const walk = (node) => {
        let out = "";
        for (const c of node.childNodes) {
          if (c.nodeType === 3) { out += (c.textContent || "").replace(/\\s+/g, " "); continue; }
          if (c.nodeType !== 1) continue;
          const tag = c.tagName.toLowerCase();
          if (["script","style","noscript","template","svg","head","iframe"].includes(tag)) continue;
          const cs = getComputedStyle(c);
          if (cs && (cs.display === "none" || cs.visibility === "hidden")) continue;
          switch (tag) {
            case "h1": case "h2": case "h3": case "h4": case "h5": case "h6":
              out += "\\n\\n" + "#".repeat(+tag[1]) + " " + inlineText(c) + "\\n"; break;
            case "p": out += "\\n\\n" + walk(c).trim() + "\\n"; break;
            case "br": out += "  \\n"; break;
            case "hr": out += "\\n\\n---\\n"; break;
            case "strong": case "b": { const t = inlineText(c); out += t ? "**" + t + "**" : ""; break; }
            case "em": case "i": { const t = inlineText(c); out += t ? "*" + t + "*" : ""; break; }
            case "code": out += "\`" + (c.textContent || "") + "\`"; break;
            case "pre": out += "\\n\\n\`\`\`\\n" + (c.textContent || "") + "\\n\`\`\`\\n"; break;
            case "a": { const href = c.href || c.getAttribute("href") || ""; const t = inlineText(c); out += (href && t) ? "[" + t + "](" + href + ")" : t; break; }
            case "img": { const src = c.src || c.getAttribute("src") || ""; if (src) out += "![" + (c.getAttribute("alt") || "") + "](" + src + ")"; break; }
            case "ul": case "ol": {
              let i = 1;
              for (const li of c.children) {
                if (li.tagName.toLowerCase() !== "li") continue;
                out += "\\n" + (tag === "ol" ? (i++) + ". " : "- ") + walk(li).trim();
              }
              out += "\\n"; break;
            }
            case "blockquote": out += "\\n\\n" + walk(c).trim().split("\\n").map((l) => "> " + l).join("\\n") + "\\n"; break;
            case "table": {
              const rows = [...c.querySelectorAll("tr")];
              if (!rows.length) break;
              const cells = (tr) => [...tr.querySelectorAll("th,td")].map((td) => inlineText(td).replace(/\\|/g, "\\\\|"));
              const head = cells(rows[0]);
              out += "\\n\\n| " + head.join(" | ") + " |\\n| " + head.map(() => "---").join(" | ") + " |\\n";
              for (const tr of rows.slice(1)) out += "| " + cells(tr).join(" | ") + " |\\n";
              break;
            }
            default: out += walk(c);
          }
        }
        return out;
      };
      let content;
      if (MODE === "html") content = root.innerHTML || "";
      else if (MODE === "markdown") content = walk(root).replace(/[ \\t]+\\n/g, "\\n").replace(/\\n[ \\t]+\\n/g, "\\n\\n").replace(/\\n{3,}/g, "\\n\\n").trim();
      else content = root.innerText || "";
      return { ...base, content: content.slice(0, MAX) };
    })()`
  );
  // Keep legacy "text" key populated for older callers.
  return { success: true, ...data, text: data && data.format === "text" ? data.content : (data ? data.content : "") };
}

async function cmdExtractElements(params) {
  const tab = await resolveTab(params);
  const { selector, fields = null, limit = 100 } = params || {};
  if (!selector) throw new Error("extract_elements requires a selector");
  const SEL = JSON.stringify(selector);
  const FIELDS = JSON.stringify(fields || null);
  const LIMIT = Math.max(1, Math.min(1000, Number(limit) || 100));

  const records = await evalInPage(
    tab.id,
    `(() => {
      const els = [...document.querySelectorAll(${SEL})].slice(0, ${LIMIT});
      const fields = ${FIELDS};
      const txt = (el) => (el.innerText || el.textContent || "").replace(/\\s+/g, " ").trim();
      const pull = (rootEl, spec) => {
        let sel = spec, attr = null;
        const at = spec.lastIndexOf("@");
        if (at > 0) { sel = spec.slice(0, at); attr = spec.slice(at + 1); }
        const t = sel ? rootEl.querySelector(sel) : rootEl;
        if (!t) return null;
        if (attr) return ((attr === "href" || attr === "src") && t[attr]) ? t[attr] : t.getAttribute(attr);
        return txt(t);
      };
      return els.map((el) => {
        if (fields && typeof fields === "object") {
          const rec = {};
          for (const k in fields) rec[k] = pull(el, fields[k]);
          return rec;
        }
        const a = el.matches("a[href]") ? el : el.querySelector("a[href]");
        return { text: txt(el).slice(0, 300), href: a ? a.href : null };
      });
    })()`
  );
  return { success: true, records: records || [], count: (records || []).length };
}

async function cmdScrollToBottom(params) {
  const tab = await resolveTab(params);
  const max = Math.max(1, Math.min(100, Number(params?.max_scrolls) || 10));
  const delay = Math.max(50, Math.min(5000, Number(params?.delay_ms) || 600));
  const result = await evalInPage(
    tab.id,
    `(async () => {
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      const doc = document.documentElement;
      let scrolls = 0;
      for (let i = 0; i < ${max}; i++) {
        const h = doc.scrollHeight;
        window.scrollTo(0, h);
        scrolls++;
        await sleep(${delay});
        if (doc.scrollHeight <= h) break; // no new content loaded → at bottom
      }
      return {
        scrolls,
        final_height: doc.scrollHeight,
        at_bottom: window.innerHeight + window.scrollY >= doc.scrollHeight - 4,
      };
    })()`,
    true
  );
  return { success: true, ...(result || {}) };
}

async function cmdGetTabs() {
  const tabs = await chrome.tabs.query({});
  return {
    success: true,
    tabs: tabs.map((t, i) => ({
      index: i,
      id: t.id,
      url: t.url || "",
      title: t.title || "",
      active: t.active,
    })),
  };
}

async function cmdSwitchTab(params) {
  const { index, id } = params;

  // `id != null` (not `if (id)`) so a legitimate tab id of 0 isn't treated
  // as "no id given".
  if (id != null) {
    await chrome.tabs.update(id, { active: true });
    await chrome.windows.update((await chrome.tabs.get(id)).windowId, { focused: true });
    return { success: true, tab_id: id };
  }

  const tabs = await chrome.tabs.query({});
  if (index >= 0 && index < tabs.length) {
    await chrome.tabs.update(tabs[index].id, { active: true });
    await chrome.windows.update(tabs[index].windowId, { focused: true });
    return { success: true, tab_id: tabs[index].id };
  }

  throw new Error(`Tab index ${index} out of range`);
}

async function cmdOpenTab(params) {
  const { url, active = true } = params;
  if (!url) throw new Error("open_tab requires a url");
  const tab = await chrome.tabs.create({ url, active });
  return { success: true, tab_id: tab.id, url };
}

async function cmdCloseTab(params) {
  const { id, index } = params;
  let tabId = id;
  if (tabId == null) {
    if (index == null) throw new Error("close_tab requires an id or index");
    const tabs = await chrome.tabs.query({});
    if (index < 0 || index >= tabs.length) throw new Error(`Tab index ${index} out of range`);
    tabId = tabs[index].id;
  }
  await chrome.tabs.remove(tabId);
  return { success: true, tab_id: tabId };
}

async function cmdEvaluate(params) {
  const tab = await resolveTab(params);

  const { script } = params;

  const result = await cdpSend(tab.id, "Runtime.evaluate", {
    expression: script,
    returnByValue: true,
    awaitPromise: true,
  });

  return {
    success: true,
    value: result.result?.value,
    type: result.result?.type,
    description: result.result?.description,
  };
}

async function cmdBack(params) {
  const tab = await resolveTab(params);
  await chrome.tabs.goBack(tab.id);
  return { success: true };
}

async function cmdForward(params) {
  const tab = await resolveTab(params);
  await chrome.tabs.goForward(tab.id);
  return { success: true };
}

async function cmdReload(params) {
  const tab = await resolveTab(params);
  await chrome.tabs.reload(tab.id);
  return { success: true };
}

// ── Wait / element-based actions ─────────────────────────────────────────────

async function cmdWait(params) {
  const ms = Math.max(0, Math.min(60000, Number(params?.ms) || 0));
  await new Promise((r) => setTimeout(r, ms));
  return { success: true, ms };
}

async function cmdWaitForLoad(params) {
  const tab = await resolveTab(params);
  const { state = "load", timeout_ms = 30000 } = params || {};
  const target = state === "domcontentloaded" ? ["interactive", "complete"] : ["complete"];
  const deadline = Date.now() + timeout_ms;
  while (Date.now() < deadline) {
    const ready = await evalInPage(tab.id, "document.readyState");
    if (target.includes(ready)) return { success: true, state, readyState: ready };
    await new Promise((r) => setTimeout(r, 150));
  }
  throw new Error(`Timed out after ${timeout_ms}ms waiting for '${state}'`);
}

// Wait until the tab has had no in-flight network requests for `idle_ms`.
// Enables the CDP Network domain (idempotent) so the onEvent listener above
// can count requests; only traffic that starts after this call is counted, so
// call it right after the navigate/click that kicks off the XHR/fetch you
// care about. Ideal for SPAs that fetch their data after the initial load.
async function cmdWaitForNetworkIdle(params) {
  const tab = await resolveTab(params);
  const idleMs = Math.max(100, Math.min(10000, Number(params?.idle_ms) || 500));
  const timeoutMs = Math.max(500, Math.min(60000, Number(params?.timeout_ms) || 20000));
  await cdpSend(tab.id, "Network.enable", {});
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const deadline = Date.now() + timeoutMs;
  let quietStart = null;
  while (Date.now() < deadline) {
    if (netCount(tab.id) <= 0) {
      if (quietStart === null) quietStart = Date.now();
      else if (Date.now() - quietStart >= idleMs) return { success: true, idle: true, inflight: 0 };
    } else {
      quietStart = null;
    }
    await sleep(100);
  }
  return { success: true, idle: false, inflight: netCount(tab.id), timed_out: true };
}

async function cmdWaitForSelector(params) {
  const tab = await resolveTab(params);
  const { selector, state = "visible", timeout_ms = 10000 } = params || {};
  if (!selector) throw new Error("wait_for_selector requires a selector");
  const sel = JSON.stringify(selector);
  const wantVisible = state === "visible";
  const wantHidden = state === "hidden";
  const deadline = Date.now() + timeout_ms;
  while (Date.now() < deadline) {
    const status = await evalInPage(
      tab.id,
      `(() => {
        const el = document.querySelector(${sel});
        if (!el) return "absent";
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        const visible = r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none" && s.opacity !== "0";
        return visible ? "visible" : "present";
      })()`
    );
    if (wantHidden && (status === "absent" || status === "present")) return { success: true, state };
    if (!wantHidden && state === "attached" && status !== "absent") return { success: true, state };
    if (!wantHidden && wantVisible && status === "visible") return { success: true, state };
    await new Promise((r) => setTimeout(r, 150));
  }
  throw new Error(`Timed out after ${timeout_ms}ms waiting for ${selector} to be ${state}`);
}

// Scroll the matched element into view and return its viewport-relative CSS
// centre (matching the clip=scale-1 screenshot coordinate space).
async function elementCenter(tabId, expr) {
  const rect = await evalInPage(
    tabId,
    `(() => {
      const el = ${expr};
      if (!el) return null;
      el.scrollIntoView({ block: "center", inline: "center" });
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) return null;
      return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    })()`
  );
  return rect;
}

async function cmdClickSelector(params) {
  const tab = await resolveTab(params);
  const { selector, index = 0 } = params || {};
  if (!selector) throw new Error("click_selector requires a selector");
  const sel = JSON.stringify(selector);
  const center = await elementCenter(tab.id, `document.querySelectorAll(${sel})[${Number(index) || 0}]`);
  if (!center) throw new Error(`No visible element for selector ${selector} (index ${index})`);
  await clickAt(tab.id, center.x, center.y);
  return { success: true, selector, x: center.x, y: center.y };
}

async function cmdClickText(params) {
  const tab = await resolveTab(params);
  const { text, tag = null, exact = false } = params || {};
  if (!text) throw new Error("click_text requires text");
  const needle = JSON.stringify(text);
  const tagSel = tag ? JSON.stringify(tag) : "null";
  // Prefer the deepest (leaf-most) element whose own text matches, so we hit
  // the actual button/link rather than a wrapping container.
  const finder = `(() => {
    const needle = ${needle}, tagSel = ${tagSel}, exact = ${exact ? "true" : "false"};
    const root = tagSel ? document.querySelectorAll(tagSel) : document.querySelectorAll("a,button,[role=button],[role=link],input[type=submit],input[type=button],*");
    let best = null;
    for (const el of root) {
      const t = (el.innerText || el.value || "").trim();
      if (!t) continue;
      const hit = exact ? t === needle : t.includes(needle);
      if (!hit) continue;
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      if (!best || el.compareDocumentPosition(best) & Node.DOCUMENT_POSITION_CONTAINS || t.length < (best.innerText || "").trim().length) best = el;
    }
    return best;
  })()`;
  const center = await elementCenter(tab.id, finder);
  if (!center) throw new Error(`No visible element with text ${JSON.stringify(text)}`);
  await clickAt(tab.id, center.x, center.y);
  return { success: true, text, x: center.x, y: center.y };
}

async function cmdFill(params) {
  const tab = await resolveTab(params);
  const { selector, value = "", clear = true, submit = false } = params || {};
  if (!selector) throw new Error("fill requires a selector");
  const sel = JSON.stringify(selector);
  const val = JSON.stringify(value);
  // Use the native value setter + input/change events so frameworks (React,
  // Vue) that track their own state pick up the change.
  const ok = await evalInPage(
    tab.id,
    `(() => {
      const el = document.querySelector(${sel});
      if (!el) return false;
      el.focus();
      const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
      const next = ${clear ? "" : "(el.value || '') + "}${val};
      if (setter) setter.call(el, next); else el.value = next;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()`
  );
  if (!ok) throw new Error(`No element for selector ${selector}`);
  if (submit) {
    await cdpSend(tab.id, "Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
    await cdpSend(tab.id, "Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
  }
  return { success: true, selector, submitted: submit };
}

async function cmdSnapshot(params) {
  const tab = await resolveTab(params);
  const max = Math.max(1, Math.min(300, Number(params?.max_elements) || 80));
  const elements = await evalInPage(
    tab.id,
    `(() => {
      const MAX = ${max};
      const SEL = "a[href],button,input:not([type=hidden]),select,textarea,[role=button],[role=link],[role=tab],[role=menuitem],[role=checkbox],[role=radio],[contenteditable=true],[onclick]";
      function cssPath(el) {
        if (el.id) return "#" + CSS.escape(el.id);
        const parts = [];
        let node = el;
        for (let depth = 0; node && node.nodeType === 1 && depth < 4; depth++) {
          let sel = node.tagName.toLowerCase();
          if (node.id) { parts.unshift("#" + CSS.escape(node.id)); break; }
          const parent = node.parentElement;
          if (parent) {
            const sibs = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
            if (sibs.length > 1) sel += ":nth-of-type(" + (sibs.indexOf(node) + 1) + ")";
          }
          parts.unshift(sel);
          node = node.parentElement;
        }
        return parts.join(" > ");
      }
      const out = [];
      for (const el of document.querySelectorAll(SEL)) {
        if (out.length >= MAX) break;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        const s = getComputedStyle(el);
        if (s.visibility === "hidden" || s.display === "none") continue;
        const text = (el.innerText || el.value || el.getAttribute("aria-label") || el.getAttribute("placeholder") || "").trim().slice(0, 120);
        out.push({
          role: el.getAttribute("role") || el.tagName.toLowerCase(),
          text,
          name: el.getAttribute("name") || el.id || "",
          selector: cssPath(el),
          box: { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2), w: Math.round(r.width), h: Math.round(r.height) },
        });
      }
      return out;
    })()`
  );
  return { success: true, elements: elements || [] };
}

async function cmdStatus() {
  const tab = await getActiveTab();
  return {
    success: true,
    connected: true,
    active_tab: tab ? {
      id: tab.id,
      url: tab.url || "",
      title: tab.title || "",
    } : null,
  };
}

// ── Tab info broadcasting ────────────────────────────────────────────────────

function broadcastTabInfo() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;

  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const tab = tabs[0];
    if (!tab) return;

    ws.send(JSON.stringify({
      type: "event",
      event: "tab_updated",
      data: {
        url: tab.url || "",
        title: tab.title || "",
        tabs: [], // Will be filled by get_tabs command
      },
    }));
  });
}

// Listen for tab changes and broadcast
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (tab.active && changeInfo.status === "complete") {
    broadcastTabInfo();
  }
});

chrome.tabs.onActivated.addListener(() => {
  broadcastTabInfo();
});

// ── Message handlers (popup communication) ───────────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "get_status") {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      sendResponse({
        connected: connected,
        extension_id: extensionId,
        active_tab: tabs[0] ? { url: tabs[0].url, title: tabs[0].title } : null,
        last_close_reason: lastCloseReason,
        relay_base: relayBase,
      });
    });
    return true; // async sendResponse
  }

  if (msg.type === "toggle_connection") {
    if (connected || (ws && ws.readyState === WebSocket.CONNECTING)) {
      disconnect();
    } else {
      manualDisconnect = false;
      connect();
    }
    sendResponse({ ok: true });
    return true;
  }

  if (msg.type === "config_updated") {
    // Popup saved new relay URL / token — reload and reconnect.
    (async () => {
      disconnect();
      manualDisconnect = false;
      await loadConfig();
      connect();
    })();
    sendResponse({ ok: true });
    return true;
  }
});

// ── Initialize ───────────────────────────────────────────────────────────────

chrome.runtime.onStartup.addListener(() => {
  console.log("[WebBridge] Browser startup — reconnecting...");
  connect();
});

chrome.runtime.onInstalled.addListener(() => {
  console.log("[WebBridge] Extension installed/updated — connecting...");
  connect();
});

// Idempotent: guarantees the worker always has a wake-up scheduled, even
// after Chrome kills and revives the service worker.
ensureHeartbeatAlarm();

console.log("[WebBridge] Extension loaded, connecting...");
connect();
