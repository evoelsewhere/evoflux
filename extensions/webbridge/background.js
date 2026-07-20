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
const RECONNECT_DELAY = 3000;
const HEARTBEAT_ALARM = "webbridge-heartbeat";
const HEARTBEAT_PERIOD_MIN = 0.5; // minimum period chrome.alarms allows

let ws = null;
let extensionId = generateId();
let connected = false;
let reconnectTimer = null;
let attachedTabs = new Map(); // tabId → true (CDP attached)
let manualDisconnect = false;
let lastCloseReason = null; // null | "auth" (4401) | "closed"
let relayBase = DEFAULT_RELAY_BASE;
let accessToken = "";

// ── Config (persisted in chrome.storage.local, edited via the popup) ─────────

async function loadConfig() {
  try {
    const cfg = await chrome.storage.local.get(["relayBase", "accessToken"]);
    relayBase = (cfg.relayBase || DEFAULT_RELAY_BASE).trim().replace(/\/+$/, "");
    accessToken = (cfg.accessToken || "").trim();
  } catch (e) {
    console.warn("[WebBridge] Failed to load config, using defaults:", e);
    relayBase = DEFAULT_RELAY_BASE;
    accessToken = "";
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

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(connect, RECONNECT_DELAY);
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
    extensionId = msg.extension_id;
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
        result = await cmdBack();
        break;
      case "forward":
        result = await cmdForward();
        break;
      case "reload":
        result = await cmdReload();
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

// Chrome detached the debugger outside our control (infobar Cancel,
// navigation to a restricted page, tab process gone) — forget the stale
// state so the next command re-attaches instead of failing.
chrome.debugger.onDetach.addListener((source) => {
  if (source.tabId && attachedTabs.delete(source.tabId)) {
    console.warn("[WebBridge] Debugger detached from tab", source.tabId);
    broadcastTabInfo();
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  attachedTabs.delete(tabId);
});

// ── Command implementations ──────────────────────────────────────────────────

async function cmdNavigate(params) {
  const tab = await getActiveTab();
  if (!tab) throw new Error("No active tab");

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
  const tab = await getActiveTab();
  if (!tab) throw new Error("No active tab");

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
  const tab = await getActiveTab();
  if (!tab) throw new Error("No active tab");

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
  const tab = await getActiveTab();
  if (!tab) throw new Error("No active tab");

  const { text } = params;

  // Input.insertText handles unicode/IME composition correctly and is a
  // single CDP call instead of two synthetic key events per character.
  await cdpSend(tab.id, "Input.insertText", { text });

  return { success: true, length: text.length };
}

async function cmdKey(params) {
  const tab = await getActiveTab();
  if (!tab) throw new Error("No active tab");

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
  const tab = await getActiveTab();
  if (!tab) throw new Error("No active tab");

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

async function cmdScreenshot(params) {
  const tab = await getActiveTab();
  if (!tab) throw new Error("No active tab");

  const { format = "png", quality = 80, fromSurface = true } = params || {};

  const result = await cdpSend(tab.id, "Page.captureScreenshot", {
    format: format === "jpeg" ? "jpeg" : "png",
    quality: format === "jpeg" ? quality : undefined,
    fromSurface,
  });

  // result.data is base64-encoded image
  return {
    success: true,
    data: result.data,
    format: format === "jpeg" ? "jpeg" : "png",
  };
}

async function cmdExtract() {
  const tab = await getActiveTab();
  if (!tab) throw new Error("No active tab");

  // Use Runtime.evaluate to extract page content
  const result = await cdpSend(tab.id, "Runtime.evaluate", {
    expression: `JSON.stringify({
      title: document.title,
      url: window.location.href,
      text: document.body?.innerText?.substring(0, 50000) || "",
      html: document.body?.innerHTML?.substring(0, 100000) || "",
      meta: {
        description: document.querySelector('meta[name="description"]')?.content || "",
        ogTitle: document.querySelector('meta[property="og:title"]')?.content || "",
        ogDescription: document.querySelector('meta[property="og:description"]')?.content || "",
      }
    })`,
    returnByValue: true,
  });

  const content = JSON.parse(result.result.value);
  return { success: true, ...content };
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

  if (id) {
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

async function cmdEvaluate(params) {
  const tab = await getActiveTab();
  if (!tab) throw new Error("No active tab");

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

async function cmdBack() {
  const tab = await getActiveTab();
  if (!tab) throw new Error("No active tab");

  await chrome.tabs.goBack(tab.id);
  return { success: true };
}

async function cmdForward() {
  const tab = await getActiveTab();
  if (!tab) throw new Error("No active tab");

  await chrome.tabs.goForward(tab.id);
  return { success: true };
}

async function cmdReload() {
  const tab = await getActiveTab();
  if (!tab) throw new Error("No active tab");

  await chrome.tabs.reload(tab.id);
  return { success: true };
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
