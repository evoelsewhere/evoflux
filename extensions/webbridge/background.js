/**
 * EvoFlux WebBridge — Chrome Extension Service Worker
 *
 * Connects to the EvoFlux backend relay via WebSocket and uses
 * chrome.debugger (CDP) to control the real browser.
 *
 * Architecture:
 *   Agent ←→ Backend Relay ←→ This Extension ←→ Real Browser (CDP)
 */

importScripts("semantic_runtime.js");

const DEFAULT_RELAY_BASE = "ws://127.0.0.1:4082";
const RELAY_PATH = "/api/team/webbridge/relay";
const RELAY_TICKET_PATH = "/api/team/webbridge/relay-ticket";
const NATIVE_PAIRING_PATH = "/api/team/webbridge/pairing/native";
const NATIVE_HOST_NAME = "com.evoflux.webbridge";
const BINDINGS_PATH = "/api/team/webbridge/bindings";
const INTERACTIONS_PATH = "/api/team/webbridge/interactions";
const TEACH_DRAFTS_PATH = "/api/team/webbridge/teach-drafts";
const MENU_SELECTION_ID = "webbridge-ask-selection";
const MENU_LINK_ID = "webbridge-ask-link";
const MENU_PAGE_ID = "webbridge-ask-page";
const MAX_CONTEXT_CHARS = 20000;
const PENDING_INTERACTION_TTL_MS = 5 * 60 * 1000;
const RECONNECT_BASE_MS = 1000; // first retry delay
const RECONNECT_MAX_MS = 30000; // cap on the exponential backoff
const CONNECT_TIMEOUT_MS = 15000;
const HEARTBEAT_ALARM = "webbridge-heartbeat";
const HEARTBEAT_PERIOD_MIN = 0.5; // minimum period chrome.alarms allows
const TEXT_WATCH_ALARM = "webbridge-text-watch";
const TEXT_WATCH_PERIOD_MIN = 0.5;
const TEXT_WATCH_STORAGE_KEY = "webbridgeTextWatches";
const MAX_TEXT_WATCHES = 10;
const MAX_TEXT_WATCH_NEEDLE_CHARS = 160;
const MAX_TEXT_WATCH_TTL_MINUTES = 24 * 60;
const TEACH_RECORDING_STORAGE_KEY = "webbridgeTeachRecording";
const MAX_TEACH_ACTIONS = 50;
const MAX_TEACH_SELECTOR_CHARS = 512;
const MAX_TEACH_VALUE_CHARS = 4_000;
const HUMAN_LEASE_STORAGE_KEY = "webbridgeHumanControlLease";
const HUMAN_LEASE_TTL_MS = 30 * 60 * 1000;
const PICKED_ELEMENT_STORAGE_KEY = "webbridgePickedElements";
const REGION_CAPTURE_STORAGE_KEY = "webbridgeRegionCaptures";
const PANEL_CONTEXT_DRAFT_STORAGE_KEY = "webbridgePanelContextDraft";
const TAB_PAGE_INSTANCE_STORAGE_KEY = "webbridgeTabPageInstance";
const TAB_SESSION_ACTION_STORAGE_KEY = "webbridgeTabSessionAction";
const DIAGNOSTIC_CAPTURE_TTL_MS = 15 * 60 * 1000;
const MAX_DIAGNOSTIC_ENTRIES = 30;

let ws = null;
let extensionId = null; // loaded/persisted in chrome.storage.local (stable across SW restarts)
const sessionGroupLocks = new Map();
let textWatchMutation = Promise.resolve();
let connected = false;
let reconnectTimer = null;
let reconnectAttempts = 0;
let attachedTabs = new Map(); // tabId → true (CDP attached)
let manualDisconnect = false;
let lastCloseReason = null; // null | "ticket" (4401) | "pairing" (4403) | "closed"
let relayBase = DEFAULT_RELAY_BASE;
let pairingCredential = "";
let pairingId = "";
let pairingRelayBase = "";
let pairingTransport = "";
let connectionMode = "native";
let nativeDiscoveryToken = "";
let nativeDiscoveryError = "";
let connectionCredentialInFlight = null;
let connectInFlight = false;
let connectionAttempt = 0;
let nativeRefreshInFlight = null;
let automationStateBroadcastTimer = null;
const agentControlOverlays = new Set();
const overlayCaptureSuspensions = new Map();
const agentPointerPositions = new Map();
const activePageDialogs = new Map();
const pageDialogHistory = new Map();

const COMMAND_CAPABILITIES = [
  "navigate", "click", "dblclick", "type", "key", "scroll", "screenshot",
  "extract", "get_tabs", "switch_tab", "evaluate", "back", "forward",
  "reload", "wait", "wait_for_selector", "wait_for_text", "wait_for_load",
  "wait_for_network_idle", "click_selector", "click_text", "hover", "focus",
  "select_option", "set_checked", "drag", "fill", "open_tab", "close_tab",
  "snapshot", "semantic_snapshot", "semantic_read", "semantic_select",
  "semantic_write", "extract_elements", "scroll_to_bottom", "resize",
  "reset_viewport", "dialogs", "handle_dialog", "status",
];

// ── Config (persisted in chrome.storage.local, edited in Side Chat settings) ─

async function loadConfig() {
  try {
    const cfg = await chrome.storage.local.get([
      "relayBase", "extensionId", "pairingCredential", "pairingId",
      "pairingRelayBase", "pairingTransport",
    ]);
    relayBase = (cfg.relayBase || DEFAULT_RELAY_BASE).trim().replace(/\/+$/, "");
    pairingCredential = (cfg.pairingCredential || "").trim();
    pairingId = (cfg.pairingId || "").trim();
    pairingRelayBase = (cfg.pairingRelayBase || "").trim().replace(/\/+$/, "");
    pairingTransport = (cfg.pairingTransport || "").trim();
    // A stable id keeps the relay from accumulating a ghost registration on
    // every MV3 service-worker restart (which discards in-memory state).
    if (cfg.extensionId) {
      extensionId = cfg.extensionId;
    } else if (!extensionId) {
      extensionId = generateId();
      chrome.storage.local.set({ extensionId });
    }
    await chrome.storage.local.remove(["accessToken"]);
  } catch (e) {
    console.warn("[WebBridge] Failed to load config, using defaults:", e);
    relayBase = DEFAULT_RELAY_BASE;
    if (!extensionId) extensionId = generateId();
  }
}

function requestNativeDiscovery() {
  return new Promise((resolve, reject) => {
    if (typeof chrome.runtime.sendNativeMessage !== "function") {
      reject(new Error("Native Messaging is unavailable"));
      return;
    }
    chrome.runtime.sendNativeMessage(NATIVE_HOST_NAME, { type: "discover" }, (response) => {
      const runtimeError = chrome.runtime.lastError;
      if (runtimeError) {
        reject(new Error(runtimeError.message || "Native Messaging failed"));
        return;
      }
      if (!response?.ok) {
        reject(new Error(response?.error || "EvoFlux Desktop is not running"));
        return;
      }
      resolve(response);
    });
  });
}

function failNativeDiscovery(message) {
  const error = new Error(message);
  error.code = "native_discovery";
  nativeDiscoveryError = message;
  throw error;
}

async function discoverNativeConnection() {
  let response;
  try {
    response = await requestNativeDiscovery();
  } catch (error) {
    nativeDiscoveryError = error?.message || String(error);
    error.code = "native_discovery";
    throw error;
  }
  if (response.protocol_version !== 1 || !Number.isInteger(response.app_pid) || response.app_pid <= 0) {
    failNativeDiscovery("EvoFlux Desktop returned an incompatible discovery response");
  }
  let parsed;
  try {
    parsed = new URL(response.base_url);
  } catch {
    failNativeDiscovery("EvoFlux Desktop returned an invalid connection address");
  }
  const loopback = ["localhost", "127.0.0.1", "::1"].includes(parsed.hostname.toLowerCase());
  if (parsed.protocol !== "http:" || !loopback || !parsed.port) {
    failNativeDiscovery("EvoFlux Desktop must expose an explicit loopback HTTP port");
  }
  const discoveryToken = String(response.discovery_token || "");
  if (discoveryToken.length < 32 || discoveryToken.length > 256) {
    failNativeDiscovery("EvoFlux Desktop returned an invalid discovery token");
  }

  relayBase = response.base_url.trim().replace(/\/+$/, "").replace(/^http:/i, "ws:");
  nativeDiscoveryToken = discoveryToken;
  connectionMode = "native";
  nativeDiscoveryError = "";
  const updates = { relayBase };
  // Native pairings are scoped to the desktop install, not its ephemeral
  // sidecar port. Carry a valid credential forward when the app restarts.
  if (pairingCredential && pairingTransport === "native") {
    pairingRelayBase = canonicalRelayBase();
    updates.pairingRelayBase = pairingRelayBase;
  }
  await chrome.storage.local.set(updates);
  return canonicalRelayBase();
}

function canonicalRelayBase(value = relayBase) {
  return (value || DEFAULT_RELAY_BASE)
    .trim()
    .replace(/\/+$/, "")
    .replace(/^http/i, "ws");
}

async function refreshNativeConnectionIfChanged() {
  if (manualDisconnect || connectionMode !== "native") return false;
  if (nativeRefreshInFlight) return nativeRefreshInFlight;

  const previousRelayBase = canonicalRelayBase();
  nativeRefreshInFlight = (async () => {
    try {
      const discoveredRelayBase = await discoverNativeConnection();
      if (discoveredRelayBase === previousRelayBase) return false;
      console.log(
        "[WebBridge] Desktop endpoint changed; reconnecting",
        previousRelayBase,
        "→",
        discoveredRelayBase,
      );
      if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
        lastCloseReason = "endpoint_changed";
        ws.close(1000, "Desktop endpoint changed");
      } else {
        clearTimeout(reconnectTimer);
        reconnectAttempts = 0;
        connect();
      }
      return true;
    } catch (error) {
      // A transient desktop restart must not tear down a relay that is still
      // alive. Surface the discovery error and retry on the next heartbeat.
      console.warn("[WebBridge] Native endpoint refresh failed:", error.message);
      broadcastConnectionState();
      return false;
    } finally {
      nativeRefreshInFlight = null;
    }
  })();
  return nativeRefreshInFlight;
}

function assertRelayTransportSecure() {
  let parsed;
  try {
    parsed = new URL(canonicalRelayBase());
  } catch {
    const error = new Error("Relay URL is invalid");
    error.code = "relay_security";
    throw error;
  }
  if (!['ws:', 'wss:'].includes(parsed.protocol)) {
    const error = new Error("Relay URL must use ws, wss, http, or https");
    error.code = "relay_security";
    throw error;
  }
  const host = parsed.hostname.toLowerCase();
  const loopback = host === "localhost" || host === "127.0.0.1" || host === "::1";
  if (parsed.protocol === "ws:" && !loopback) {
    const error = new Error("Remote WebBridge relays require HTTPS/WSS");
    error.code = "relay_security";
    throw error;
  }
}

function buildHttpUrl(path, value = relayBase) {
  const base = (value || DEFAULT_RELAY_BASE)
    .replace(/^ws:/i, "http:")
    .replace(/^wss:/i, "https:");
  return base + path;
}

function interactionId() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `interaction-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

function boundedText(value) {
  return String(value || "").replace(/\s+/g, " ").trim().slice(0, MAX_CONTEXT_CHARS);
}

function browserOrigin(url) {
  try {
    const parsed = new URL(url || "");
    return (parsed.protocol === "http:" || parsed.protocol === "https:") ? parsed.origin : "";
  } catch {
    return "";
  }
}

function browserTabScope(tab) {
  return browserOrigin(tab?.url || tab?.pendingUrl || "") || `tab:${tab?.id}`;
}

function requireBrowserPageUrl(url) {
  const safeUrl = safePageUrl(url);
  if (!safeUrl) {
    throw new Error("Browser context can only be sent from an HTTP(S) page.");
  }
  return safeUrl;
}

function safePageUrl(url) {
  try {
    const parsed = new URL(url || "");
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
    return `${parsed.origin}${parsed.pathname}`;
  } catch {
    return "";
  }
}

function normalizeWatchNeedle(value) {
  const needle = String(value || "").replace(/\s+/g, " ").trim();
  if (!needle) throw new Error("Enter text for WebBridge to watch.");
  if (needle.length > MAX_TEXT_WATCH_NEEDLE_CHARS) {
    throw new Error(`Watch text must be at most ${MAX_TEXT_WATCH_NEEDLE_CHARS} characters.`);
  }
  return needle;
}

function normalizeWatchTtlMinutes(value) {
  const minutes = Math.floor(Number(value));
  if (!Number.isFinite(minutes) || minutes < 1 || minutes > MAX_TEXT_WATCH_TTL_MINUTES) {
    throw new Error(`Watch duration must be between 1 and ${MAX_TEXT_WATCH_TTL_MINUTES} minutes.`);
  }
  return minutes;
}

function isLiveTextWatch(watch, now = Date.now()) {
  return Boolean(
    watch &&
    (watch.state === "armed" || watch.state === "matched") &&
    Number.isFinite(watch.expires_at) &&
    watch.expires_at > now
  );
}

async function readTextWatchesLocked() {
  const stored = await chrome.storage.local.get([TEXT_WATCH_STORAGE_KEY]);
  const watches = Array.isArray(stored[TEXT_WATCH_STORAGE_KEY])
    ? stored[TEXT_WATCH_STORAGE_KEY]
    : [];
  const live = watches.filter((watch) => isLiveTextWatch(watch));
  if (live.length !== watches.length) {
    for (const watch of watches) {
      if (!isLiveTextWatch(watch)) clearWatchMatch(watch.tab_id);
    }
    await writeTextWatches(live);
  }
  return live;
}

async function writeTextWatches(watches) {
  await chrome.storage.local.set({ [TEXT_WATCH_STORAGE_KEY]: watches });
  notifyAutomationState("text_watch");
}

async function withTextWatchMutation(operation) {
  const previous = textWatchMutation;
  let release;
  const current = new Promise((resolve) => { release = resolve; });
  textWatchMutation = current;
  await previous.catch(() => {});
  try {
    return await operation();
  } finally {
    release();
    if (textWatchMutation === current) textWatchMutation = Promise.resolve();
  }
}

async function readTextWatches() {
  return withTextWatchMutation(readTextWatchesLocked);
}

function showWatchMatch(tabId) {
  if (!chrome.action) return;
  chrome.action.setBadgeText({ tabId, text: "W" });
  chrome.action.setBadgeBackgroundColor({ tabId, color: "#ca8a04" });
  chrome.action.setTitle({
    tabId,
    title: "WebBridge watch matched. Open WebBridge to send it to EvoFlux.",
  });
}

function clearWatchMatch(tabId) {
  if (!chrome.action) return;
  chrome.action.setBadgeText({ tabId, text: "" });
}

function textWatchSummary(watch) {
  return {
    id: watch.id,
    tab_id: watch.tab_id,
    page_url: watch.page_url,
    session_id: watch.session_id,
    needle: watch.needle,
    state: watch.state,
    created_at: watch.created_at,
    expires_at: watch.expires_at,
    matched_at: watch.matched_at || null,
  };
}

function ensureTextWatchAlarm() {
  chrome.alarms.create(TEXT_WATCH_ALARM, { periodInMinutes: TEXT_WATCH_PERIOD_MIN });
}

async function cancelTextWatchesForTab(tabId, currentUrl = null) {
  const removed = await withTextWatchMutation(async () => {
    const watches = await readTextWatchesLocked();
    const currentPageUrl = currentUrl == null ? null : safePageUrl(currentUrl);
    const retained = watches.filter((watch) => {
      if (watch.tab_id !== tabId) return true;
      return currentPageUrl !== null && watch.page_url === currentPageUrl;
    });
    const removedWatches = watches.filter((watch) => !retained.includes(watch));
    if (retained.length !== watches.length) {
      await writeTextWatches(retained);
      clearWatchMatch(tabId);
    }
    return removedWatches;
  });
  if (removed.length) await setTextWatchObserver(tabId, null).catch(() => {});
  return Boolean(removed.length);
}

async function watchTextPresent(tabId, needle) {
  const results = await chrome.scripting.executeScript({
    target: { tabId },
    args: [needle],
    func: (expected) => {
      const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim().toLocaleLowerCase();
      const root = document.body || document.documentElement;
      return normalize(root?.innerText || root?.textContent || "").includes(normalize(expected));
    },
  });
  return results.some((result) => result?.result === true);
}

async function setTextWatchObserver(tabId, watch) {
  if (watch) {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ["text_watch.js"],
    });
  }
  return chrome.tabs.sendMessage(tabId, {
    type: "webbridge_text_watch",
    enabled: Boolean(watch),
    watch: watch ? { id: watch.id, needle: watch.needle } : null,
  });
}

async function markTextWatchMatched(watchId, tab, sourceUrl) {
  if (!tab || tab.id == null) throw new Error("Text watch match did not come from a tab.");
  return withTextWatchMutation(async () => {
    const watches = await readTextWatchesLocked();
    const index = watches.findIndex((watch) => watch.id === watchId);
    if (index < 0 || watches[index].state !== "armed") return null;
    const watch = watches[index];
    const currentPageUrl = safePageUrl(tab.url || tab.pendingUrl || "");
    if (
      watch.tab_id !== tab.id ||
      currentPageUrl !== watch.page_url ||
      safePageUrl(sourceUrl) !== watch.page_url
    ) {
      return null;
    }
    const updated = { ...watch, state: "matched", matched_at: Date.now() };
    watches[index] = updated;
    await writeTextWatches(watches);
    showWatchMatch(tab.id);
    return textWatchSummary(updated);
  });
}

async function restoreTextWatchObservers(tabId = null) {
  const watches = await readTextWatches();
  const armed = watches.filter((watch) => (
    watch.state === "armed" && (tabId == null || watch.tab_id === tabId)
  ));
  await Promise.allSettled(armed.map(async (watch) => {
    const tab = await chrome.tabs.get(watch.tab_id);
    if (safePageUrl(tab.url || tab.pendingUrl || "") !== watch.page_url) return;
    await setTextWatchObserver(watch.tab_id, watch);
  }));
}

async function armTextWatch(tab, sessionId, needleValue, ttlValue) {
  if (!tab || tab.id == null) throw new Error("No browser tab available");
  const pageUrl = requireBrowserPageUrl(tab.url || tab.pendingUrl || "");
  const normalizedSessionId = String(sessionId || "").trim();
  if (!normalizedSessionId) throw new Error("Choose a browser session before arming a watch.");
  const needle = normalizeWatchNeedle(needleValue);
  const ttlMinutes = normalizeWatchTtlMinutes(ttlValue);

  // Reuse the P1 binding endpoint so ownership and origin checks remain server-authoritative.
  await bindTabToSession(tab, normalizedSessionId, pageUrl);

  const now = Date.now();
  const watch = await withTextWatchMutation(async () => {
    const watches = await readTextWatchesLocked();
    const retained = watches.filter((entry) => entry.tab_id !== tab.id);
    if (retained.length >= MAX_TEXT_WATCHES) {
      throw new Error(`WebBridge can keep at most ${MAX_TEXT_WATCHES} active watches.`);
    }
    const next = {
      id: interactionId(),
      tab_id: tab.id,
      origin: browserOrigin(pageUrl),
      page_url: pageUrl,
      session_id: normalizedSessionId,
      needle,
      state: "armed",
      created_at: now,
      expires_at: now + ttlMinutes * 60 * 1000,
      matched_at: null,
    };
    await writeTextWatches([...retained, next]);
    return next;
  });
  clearWatchMatch(tab.id);
  ensureTextWatchAlarm();
  await setTextWatchObserver(tab.id, watch).catch((error) => {
    console.warn("[WebBridge] Real-time text watch unavailable; using polling:", error.message);
  });
  await pollTextWatches();
  const current = (await readTextWatches()).find((entry) => entry.id === watch.id) || watch;
  return textWatchSummary(current);
}

async function cancelTextWatch(watchId) {
  const watch = await withTextWatchMutation(async () => {
    const watches = await readTextWatchesLocked();
    const watch = watches.find((entry) => entry.id === watchId);
    if (!watch) return null;
    await writeTextWatches(watches.filter((entry) => entry.id !== watchId));
    clearWatchMatch(watch.tab_id);
    return watch;
  });
  if (watch) await setTextWatchObserver(watch.tab_id, null).catch(() => {});
  return Boolean(watch);
}

async function cancelAllTextWatches() {
  const watches = await withTextWatchMutation(async () => {
    const watches = await readTextWatchesLocked();
    await writeTextWatches([]);
    for (const watch of watches) clearWatchMatch(watch.tab_id);
    return watches;
  });
  await Promise.allSettled(watches.map((watch) => setTextWatchObserver(watch.tab_id, null)));
  return watches.length;
}

async function pollTextWatches() {
  return withTextWatchMutation(async () => {
    const watches = await readTextWatchesLocked();
    if (!watches.length) return [];

  let changed = false;
  const retained = [];
  const matched = [];
  for (const watch of watches) {
    if (watch.state !== "armed") {
      retained.push(watch);
      continue;
    }
    let tab;
    try {
      tab = await chrome.tabs.get(watch.tab_id);
    } catch {
      changed = true;
      continue;
    }
    if (safePageUrl(tab.url || tab.pendingUrl || "") !== watch.page_url) {
      clearWatchMatch(watch.tab_id);
      changed = true;
      continue;
    }
    try {
      if (await watchTextPresent(watch.tab_id, watch.needle)) {
        const updated = { ...watch, state: "matched", matched_at: Date.now() };
        retained.push(updated);
        matched.push(textWatchSummary(updated));
        showWatchMatch(watch.tab_id);
        changed = true;
      } else {
        retained.push(watch);
      }
    } catch (error) {
      // A transient navigation or restricted page must not leak page content or trigger a send.
      console.warn("[WebBridge] Text watch poll failed:", error.message);
      retained.push(watch);
    }
  }
    if (changed) await writeTextWatches(retained);
    return matched;
  });
}

async function sendMatchedTextWatch(watchId) {
  return withTextWatchMutation(async () => {
    const watches = await readTextWatchesLocked();
    const watch = watches.find((entry) => entry.id === watchId);
    if (!watch || watch.state !== "matched") {
      throw new Error("This text watch is no longer ready to send.");
    }
    let tab;
    try {
      tab = await chrome.tabs.get(watch.tab_id);
    } catch {
      await writeTextWatches(watches.filter((entry) => entry.id !== watch.id));
      clearWatchMatch(watch.tab_id);
      throw new Error("The watched tab was closed.");
    }
    const pageUrl = requireBrowserPageUrl(tab.url || tab.pendingUrl || "");
    if (pageUrl !== watch.page_url) {
      await writeTextWatches(watches.filter((entry) => entry.id !== watch.id));
      clearWatchMatch(watch.tab_id);
      throw new Error("The watched page changed. Arm a new text watch for this page.");
    }
    const result = await submitBrowserContext(
      tab,
      {
        context_type: "page_metadata",
        prompt: `The page watch for "${watch.needle}" matched. Help me assess this page.`,
        metadata: {
          page_url: pageUrl,
          page_title: boundedText(tab.title),
        },
      },
      watch.session_id,
      `${watch.id}:match`,
    );
    await writeTextWatches(watches.filter((entry) => entry.id !== watch.id));
    clearWatchMatch(watch.tab_id);
    return result;
  });
}

function teachRecordingSummary(recording) {
  if (!recording) return null;
  const actions = Array.isArray(recording.actions) ? recording.actions : [];
  return {
    id: recording.id,
    tab_id: recording.tab_id,
    session_id: recording.session_id,
    origin: recording.origin,
    start_url: recording.start_url,
    current_page_url: recording.current_page_url,
    title: recording.title,
    state: recording.state,
    action_count: actions.length,
    truncated: Boolean(recording.truncated),
    parameter_names: [...new Set(
      actions.filter((action) => action.secret && action.parameter).map((action) => action.parameter)
    )],
    stop_reason: recording.stop_reason || null,
  };
}

async function readTeachRecording() {
  const stored = await chrome.storage.local.get([TEACH_RECORDING_STORAGE_KEY]);
  const recording = stored[TEACH_RECORDING_STORAGE_KEY];
  return recording && typeof recording === "object" ? recording : null;
}

async function writeTeachRecording(recording) {
  await chrome.storage.local.set({ [TEACH_RECORDING_STORAGE_KEY]: recording });
  notifyAutomationState("teach_recording", recording?.tab_id ?? null);
}

function teachSelector(value) {
  const selector = String(value || "").trim();
  if (!selector || selector.length > MAX_TEACH_SELECTOR_CHARS) {
    throw new Error("Recorded selector is invalid.");
  }
  return selector;
}

function teachParameterName(value) {
  const parameter = String(value || "").trim();
  if (!/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(parameter)) {
    throw new Error("Recorded secret parameter name is invalid.");
  }
  return parameter;
}

function normalizeTeachAction(action) {
  const kind = String(action?.kind || "");
  if (kind === "click") {
    return { kind, selector: teachSelector(action.selector) };
  }
  if (kind === "fill") {
    const selector = teachSelector(action.selector);
    if (action.secret) {
      return {
        kind,
        selector,
        secret: true,
        parameter: teachParameterName(action.parameter),
      };
    }
    const value = String(action.value ?? "");
    if (value.length > MAX_TEACH_VALUE_CHARS) {
      throw new Error("Recorded field value is too long.");
    }
    return { kind, selector, value };
  }
  if (kind === "select") {
    const values = Array.isArray(action.values)
      ? action.values.map(String).filter(Boolean).slice(0, 20)
      : [];
    if (!values.length || values.some((value) => value.length > 512)) {
      throw new Error("Recorded select values are invalid.");
    }
    return { kind, selector: teachSelector(action.selector), values };
  }
  if (kind === "set_checked") {
    if (typeof action.checked !== "boolean") {
      throw new Error("Recorded checked state is invalid.");
    }
    return { kind, selector: teachSelector(action.selector), checked: action.checked };
  }
  throw new Error("Recorded action is not supported.");
}

async function setTeachRecorderEnabled(tabId, enabled) {
  if (enabled) {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ["teach_recorder.js"],
    });
  }
  await chrome.tabs.sendMessage(tabId, {
    type: "webbridge_teach_recording",
    enabled,
  });
}

async function appendTeachAction(recording, action) {
  const actions = Array.isArray(recording.actions) ? [...recording.actions] : [];
  const previous = actions.at(-1);
  const replacePrevious = previous &&
    previous.kind === action.kind &&
    previous.selector === action.selector &&
    ["fill", "select", "set_checked"].includes(action.kind);
  if (replacePrevious) {
    actions[actions.length - 1] = action;
  } else if (actions.length < MAX_TEACH_ACTIONS) {
    actions.push(action);
  } else {
    recording.truncated = true;
  }
  recording.actions = actions;
  recording.updated_at = Date.now();
  await writeTeachRecording(recording);
  return teachRecordingSummary(recording);
}

async function startTeachRecording(tab, sessionId) {
  if (!tab || tab.id == null) throw new Error("No browser tab available");
  const pageUrl = requireBrowserPageUrl(tab.url || tab.pendingUrl || "");
  const normalizedSessionId = String(sessionId || "").trim();
  if (!normalizedSessionId) throw new Error("Choose a browser session before starting Teach Mode.");
  await bindTabToSession(tab, normalizedSessionId, pageUrl);
  const recording = {
    id: interactionId(),
    tab_id: tab.id,
    session_id: normalizedSessionId,
    origin: browserOrigin(pageUrl),
    start_url: pageUrl,
    current_page_url: pageUrl,
    title: boundedText(tab.title) || "Recorded browser flow",
    state: "recording",
    actions: [],
    created_at: Date.now(),
    updated_at: Date.now(),
    truncated: false,
  };
  await writeTeachRecording(recording);
  try {
    await setTeachRecorderEnabled(tab.id, true);
  } catch (error) {
    await chrome.storage.local.remove([TEACH_RECORDING_STORAGE_KEY]);
    throw new Error(`Could not start Teach Mode: ${error.message}`);
  }
  return teachRecordingSummary(recording);
}

async function recordTeachAction(tab, action, sourceUrl = "") {
  const recording = await readTeachRecording();
  if (!recording || recording.state !== "recording" || recording.tab_id !== tab.id) {
    return null;
  }
  const pageUrl = safePageUrl(tab.url || tab.pendingUrl || "");
  const sourcePageUrl = sourceUrl ? safePageUrl(sourceUrl) : pageUrl;
  if (
    !pageUrl ||
    !sourcePageUrl ||
    sourcePageUrl !== pageUrl ||
    browserOrigin(pageUrl) !== recording.origin
  ) {
    return null;
  }
  recording.current_page_url = pageUrl;
  return appendTeachAction(recording, normalizeTeachAction(action));
}

async function handleTeachTabUpdate(tabId, changeInfo) {
  const recording = await readTeachRecording();
  if (!recording || recording.state !== "recording" || recording.tab_id !== tabId) return;
  if (changeInfo.url) {
    const nextPageUrl = safePageUrl(changeInfo.url);
    if (!nextPageUrl || browserOrigin(nextPageUrl) !== recording.origin) {
      recording.state = "ready";
      recording.stop_reason = "Recording stopped after cross-origin navigation.";
      await writeTeachRecording(recording);
      try {
        await setTeachRecorderEnabled(tabId, false);
      } catch {
        // The page may have been torn down while navigating.
      }
      return;
    }
    if (nextPageUrl !== recording.current_page_url) {
      recording.current_page_url = nextPageUrl;
      await appendTeachAction(recording, { kind: "navigate", url: nextPageUrl });
    }
  }
  if (changeInfo.status === "complete") {
    try {
      await setTeachRecorderEnabled(tabId, true);
    } catch (error) {
      console.warn("[WebBridge] Failed to resume Teach Mode after navigation:", error.message);
    }
  }
}

async function cancelTeachRecording(tabId = null) {
  const recording = await readTeachRecording();
  if (!recording || (tabId != null && recording.tab_id !== tabId)) return false;
  try {
    await setTeachRecorderEnabled(recording.tab_id, false);
  } catch {
    // The tab can close before the recorder is disabled.
  }
  await chrome.storage.local.remove([TEACH_RECORDING_STORAGE_KEY]);
  notifyAutomationState("teach_recording", recording.tab_id);
  return true;
}

async function createTeachDraft(recording) {
  const warnings = [];
  if (recording.truncated) {
    warnings.push("Recording reached the 50-action limit; later actions were not captured.");
  }
  if (recording.stop_reason) warnings.push(recording.stop_reason);
  const response = await pairingFetch(TEACH_DRAFTS_PATH, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: recording.session_id,
      tab_id: recording.tab_id,
      title: recording.title,
      origin: recording.origin,
      start_url: recording.start_url,
      actions: recording.actions,
      warnings,
      user_gesture: true,
    }),
  });
  return response.json();
}

async function finishTeachRecording() {
  const recording = await readTeachRecording();
  if (!recording) throw new Error("Teach Mode is not recording a browser flow.");
  if (recording.state === "recording") {
    try {
      await setTeachRecorderEnabled(recording.tab_id, false);
    } catch {
      // Preserve a valid local trace even if the page was closed.
    }
    recording.state = "ready";
    recording.updated_at = Date.now();
    await writeTeachRecording(recording);
  }
  if (!Array.isArray(recording.actions) || !recording.actions.length) {
    throw new Error("Teach Mode did not capture any supported browser actions.");
  }
  const draft = await createTeachDraft(recording);
  await chrome.storage.local.remove([TEACH_RECORDING_STORAGE_KEY]);
  await chrome.storage.local.set({ lastTeachDraft: draft });
  notifyAutomationState("teach_recording", recording.tab_id);
  return draft;
}

async function pairingFetch(path, options = {}) {
  await loadConfig();
  assertRelayTransportSecure();
  if (!pairingCredential || !pairingRelayBase || pairingRelayBase !== canonicalRelayBase()) {
    const error = new Error("Pair WebBridge with this relay before sending browser context.");
    error.code = "pairing";
    throw error;
  }
  const response = await fetch(buildHttpUrl(path), {
    ...options,
    headers: {
      Authorization: `Bearer ${pairingCredential}`,
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    const error = new Error(await responseError(response, "WebBridge request failed"));
    error.code = response.status === 401 ? "pairing" : "request";
    throw error;
  }
  return response;
}

async function createAndBindBrowserSession(tab, title, actionId) {
  const pageUrl = tab.url || tab.pendingUrl || "";
  const origin = browserTabScope(tab);
  const response = await pairingFetch(
    `${BINDINGS_PATH}/${encodeURIComponent(tab.id)}/sessions`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": `${actionId}:session`,
      },
      body: JSON.stringify({
        title,
        origin,
        page_instance_id: `${tab.id}:${origin}`.slice(0, 128),
      }),
    },
  );
  const result = await response.json();
  return {
    session_id: result.session.id,
    binding_tab_id: result.binding.tab_id,
    binding_origin: result.binding.origin,
    grouped: false,
    session: result.session,
    tab: {
      id: tab.id,
      title: tab.title || "",
      url: pageUrl,
      group_id: Number.isInteger(tab.groupId) ? tab.groupId : -1,
    },
  };
}

async function listTabBindings() {
  const response = await pairingFetch(BINDINGS_PATH);
  return response.json();
}

async function bindTabToSession(tab, sessionId, pageUrl) {
  const origin = browserOrigin(pageUrl) || `tab:${tab.id}`;
  const response = await pairingFetch(`${BINDINGS_PATH}/${encodeURIComponent(tab.id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      origin,
      page_instance_id: `${tab.id}:${origin}`.slice(0, 128),
    }),
  });
  return response.json();
}

async function ensureSessionForTab(tab, pageUrl) {
  return (await ensureSessionContextForTab(tab, pageUrl)).session_id;
}

async function resolveExistingSessionContextForTab(tab, pageUrl) {
  const bindings = await listTabBindings();
  const binding = bindings.find((item) => item.tab_id === tab.id);
  const scope = browserTabScope(tab);
  if (binding) {
    if (binding.origin !== scope) {
      await bindTabToSession(tab, binding.session_id, pageUrl);
    }
    return {
      session_id: binding.session_id,
      binding_tab_id: binding.tab_id,
      binding_origin: scope,
      grouped: false,
    };
  }

  if (Number.isInteger(tab.groupId) && tab.groupId >= 0) {
    const groupedTabs = await chrome.tabs.query({ groupId: tab.groupId });
    const groupedIds = new Set(groupedTabs.map((item) => item.id));
    const primaryBinding = bindings.find((item) => groupedIds.has(item.tab_id));
    const primaryTab = primaryBinding
      ? groupedTabs.find((item) => item.id === primaryBinding.tab_id)
      : null;
    if (primaryBinding && primaryTab) {
      const primaryScope = browserTabScope(primaryTab);
      if (primaryBinding.origin !== primaryScope) {
        await bindTabToSession(
          primaryTab,
          primaryBinding.session_id,
          primaryTab.url || primaryTab.pendingUrl || "",
        );
      }
      return {
        session_id: primaryBinding.session_id,
        binding_tab_id: primaryBinding.tab_id,
        binding_origin: primaryScope,
        grouped: true,
      };
    }
  }

  return null;
}

async function ensureSessionContextForTab(tab, pageUrl) {
  const existing = await resolveExistingSessionContextForTab(tab, pageUrl);
  if (existing) return existing;

  const label = boundedText(tab.title) || browserOrigin(pageUrl) || "Browser tab";
  return createAndBindBrowserSession(
    tab,
    `Browser: ${label}`.slice(0, 255),
    await tabSessionActionId(tab.id),
  );
}

function contextMenuPayload(info, tab) {
  const pageUrl = safePageUrl(info.pageUrl || tab.url || tab.pendingUrl || "");
  const common = {
    page_url: pageUrl,
    page_title: boundedText(tab.title),
  };
  if (info.menuItemId === MENU_SELECTION_ID) {
    return {
      context_type: "selection",
      prompt: "Help me understand the selected browser content.",
      metadata: { ...common, selection_text: boundedText(info.selectionText) },
    };
  }
  if (info.menuItemId === MENU_LINK_ID) {
    return {
      context_type: "link",
      prompt: "Help me understand this linked page and its relevance.",
      metadata: { ...common, link_url: safePageUrl(info.linkUrl || "") },
    };
  }
  return {
    context_type: "page_metadata",
    prompt: "Help me understand this browser page.",
    metadata: common,
  };
}

function showInteractionOutcome(tabId, result) {
  if (!chrome.action) return;
  const accepted = result && ["accepted", "queued"].includes(result.status);
  const text = accepted ? "OK" : "!";
  const color = accepted ? "#16a34a" : "#dc2626";
  chrome.action.setBadgeText({ tabId, text });
  chrome.action.setBadgeBackgroundColor({ tabId, color });
  chrome.action.setTitle({
    tabId,
    title: accepted ? "EvoFlux received browser context" : "EvoFlux could not receive browser context",
  });
}

async function submitBrowserContext(tab, payload, sessionIdOverride = null, actionId = null) {
  const pageUrl = requireBrowserPageUrl(
    payload.metadata.page_url || tab.url || tab.pendingUrl || ""
  );
  const requestId = actionId || interactionId();
  const pending = {
    action_id: requestId,
    tab_id: tab.id,
    page_url: pageUrl,
    payload,
    session_id: sessionIdOverride,
    created_at: Date.now(),
  };
  await chrome.storage.local.set({ pendingInteraction: pending });
  const sessionId = sessionIdOverride
    ? (await bindTabToSession(tab, sessionIdOverride, pageUrl), sessionIdOverride)
    : await ensureSessionForTab(tab, pageUrl);
  await chrome.storage.local.set({
    pendingInteraction: { ...pending, session_id: sessionId },
  });
  const response = await pairingFetch(INTERACTIONS_PATH, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": requestId,
    },
    body: JSON.stringify({
      kind: "context.share",
      delivery: "submit",
      source: {
        tab_id: tab.id,
        page_instance_id: `${tab.id}:${pageUrl}`.slice(0, 128),
        origin: browserOrigin(pageUrl),
        user_gesture: true,
      },
      target: { session_id: sessionId },
      payload: {
        prompt: payload.prompt,
        metadata: { context_type: payload.context_type, ...payload.metadata },
      },
    }),
  });
  const result = await response.json();
  await chrome.storage.local.set({
    lastInteraction: {
      ...result,
      context_type: payload.context_type,
      created_at: Date.now(),
    },
  });
  if (result.status !== "pending") {
    await chrome.storage.local.remove(["pendingInteraction"]);
  }
  showInteractionOutcome(tab.id, result);
  return result;
}

async function retryPendingInteraction() {
  const pending = await readPendingInteraction();
  if (!pending) throw new Error("No browser interaction is waiting to retry.");
  const tab = await chrome.tabs.get(pending.tab_id);
  const currentUrl = tab.url || tab.pendingUrl || "";
  if (browserOrigin(currentUrl) !== browserOrigin(pending.page_url)) {
    await chrome.storage.local.remove(["pendingInteraction"]);
    throw new Error("The browser tab changed origin. Send browser context again from the current page.");
  }
  return submitBrowserContext(
    tab,
    pending.payload,
    pending.session_id || null,
    pending.action_id,
  );
}

async function readPendingInteraction() {
  const stored = await chrome.storage.local.get(["pendingInteraction"]);
  const pending = stored.pendingInteraction;
  if (!pending) return null;
  if (!pending.created_at || Date.now() - pending.created_at > PENDING_INTERACTION_TTL_MS) {
    await chrome.storage.local.remove(["pendingInteraction"]);
    return null;
  }
  return pending;
}

function panelDraftKey(tabId) {
  return `${PANEL_CONTEXT_DRAFT_STORAGE_KEY}:${tabId}`;
}

function tabPageInstanceKey(tabId) {
  return `${TAB_PAGE_INSTANCE_STORAGE_KEY}:${tabId}`;
}

function tabSessionActionKey(tabId) {
  return `${TAB_SESSION_ACTION_STORAGE_KEY}:${tabId}`;
}

async function tabSessionActionId(tabId) {
  const storage = chrome.storage.session || chrome.storage.local;
  const key = tabSessionActionKey(tabId);
  const stored = await storage.get([key]);
  if (stored[key]) return stored[key];
  const actionId = interactionId();
  await storage.set({ [key]: actionId });
  return actionId;
}

async function tabPageInstanceId(tabId) {
  const storage = chrome.storage.session || chrome.storage.local;
  const key = tabPageInstanceKey(tabId);
  const stored = await storage.get([key]);
  if (stored[key]) return stored[key];
  const pageInstanceId = interactionId();
  await storage.set({ [key]: pageInstanceId });
  return pageInstanceId;
}

async function rotateTabPageInstance(tabId) {
  const storage = chrome.storage.session || chrome.storage.local;
  await storage.set({ [tabPageInstanceKey(tabId)]: interactionId() });
  await storage.remove([panelDraftKey(tabId)]);
}

async function clearPanelTabState(tabId) {
  const storage = chrome.storage.session || chrome.storage.local;
  await storage.remove([
    panelDraftKey(tabId),
    tabPageInstanceKey(tabId),
    tabSessionActionKey(tabId),
  ]);
}

async function sendContextMenuInteraction(info, tab) {
  if (!tab || tab.id == null) throw new Error("No browser tab available");
  const payload = contextMenuPayload(info, tab);
  const storage = chrome.storage.session || chrome.storage.local;
  const draftKey = panelDraftKey(tab.id);
  await storage.set({
    [draftKey]: {
      tab_id: tab.id,
      page_url: payload.metadata.page_url,
      page_instance_id: await tabPageInstanceId(tab.id),
      payload,
      created_at: Date.now(),
    },
  });
  if (chrome.sidePanel?.open) {
    await chrome.sidePanel.open({ tabId: tab.id });
  }
  return { status: "draft", context_type: payload.context_type };
}

function removeAllContextMenus() {
  return new Promise((resolve, reject) => {
    chrome.contextMenus.removeAll(() => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else {
        resolve();
      }
    });
  });
}

function createContextMenu(item) {
  return new Promise((resolve, reject) => {
    chrome.contextMenus.create(item, () => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else {
        resolve();
      }
    });
  });
}

async function setupContextMenus() {
  await removeAllContextMenus();
  await createContextMenu({
    id: MENU_SELECTION_ID,
    title: "Ask EvoFlux about selection",
    contexts: ["selection"],
    documentUrlPatterns: ["http://*/*", "https://*/*"],
  });
  await createContextMenu({
    id: MENU_LINK_ID,
    title: "Ask EvoFlux about link",
    contexts: ["link"],
    documentUrlPatterns: ["http://*/*", "https://*/*"],
  });
  await createContextMenu({
    id: MENU_PAGE_ID,
    title: "Ask EvoFlux about page",
    contexts: ["page"],
    documentUrlPatterns: ["http://*/*", "https://*/*"],
  });
}

async function responseError(response, fallback) {
  try {
    const body = await response.json();
    const detail = body?.detail;
    return detail?.message || (typeof detail === "string" ? detail : fallback);
  } catch {
    return fallback;
  }
}

async function buildAuthenticatedRelayUrl() {
  assertRelayTransportSecure();
  await ensureConnectionCredential();

  const response = await fetch(buildHttpUrl(RELAY_TICKET_PATH), {
    method: "POST",
    headers: { Authorization: `Bearer ${pairingCredential}` },
  });
  if (!response.ok) {
    const error = new Error(await responseError(response, "Pairing credential rejected"));
    error.code = response.status === 401 ? "pairing" : "ticket";
    throw error;
  }
  const body = await response.json();
  if (!body?.ticket) throw new Error("Relay ticket response was missing a ticket");

  const base = (relayBase || DEFAULT_RELAY_BASE).replace(/^http/i, "ws");
  return `${base}${RELAY_PATH}?_ticket=${encodeURIComponent(body.ticket)}`;
}

async function persistConnectionCredential(
  body,
  credentialRelayBase = canonicalRelayBase(),
  transport = connectionMode,
) {
  if (!body?.credential || !body?.pairing_id) {
    throw new Error("Connection response was incomplete");
  }
  pairingCredential = body.credential;
  pairingId = body.pairing_id;
  pairingRelayBase = credentialRelayBase;
  pairingTransport = transport;
  await chrome.storage.local.set({
    pairingCredential,
    pairingId,
    pairingRelayBase,
    pairingTransport,
  });
  await chrome.storage.local.remove(["accessToken"]);
}

async function bootstrapNativeConnection() {
  await loadConfig();
  assertRelayTransportSecure();
  if (connectionMode !== "native" || !nativeDiscoveryToken) {
    const error = new Error("EvoFlux Desktop Native Messaging is required");
    error.code = "native_discovery";
    throw error;
  }
  const bootstrapRelayBase = canonicalRelayBase();
  const parsed = new URL(bootstrapRelayBase);
  if (!["localhost", "127.0.0.1", "::1"].includes(parsed.hostname.toLowerCase())) {
    throw new Error("The connection address must point to EvoFlux on this device.");
  }
  const response = await fetch(buildHttpUrl(NATIVE_PAIRING_PATH, bootstrapRelayBase), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      label: `${detectBrowser() === "edge" ? "Edge" : "Chrome"} on this device`,
      browser: detectBrowser(),
      version: chrome.runtime.getManifest().version,
      discovery_token: nativeDiscoveryToken,
    }),
  });
  if (!response.ok) {
    throw new Error(await responseError(response, "Connection was rejected"));
  }
  const body = await response.json();
  await persistConnectionCredential(body, bootstrapRelayBase, "native");
  return { pairing_id: pairingId, scopes: body.scopes || [] };
}

async function ensureConnectionCredential() {
  if (pairingCredential && pairingRelayBase === canonicalRelayBase()) return;
  if (!connectionCredentialInFlight) {
    connectionCredentialInFlight = bootstrapNativeConnection().finally(() => {
      connectionCredentialInFlight = null;
    });
  }
  await connectionCredentialInFlight;
  // A settings change can race an in-flight bootstrap. Never mint a ticket
  // for the new relay with a credential scoped to the previous relay.
  if (!pairingCredential || pairingRelayBase !== canonicalRelayBase()) {
    return ensureConnectionCredential();
  }
}

// ── Connection management ────────────────────────────────────────────────────

async function connect() {
  if (
    manualDisconnect ||
    connectInFlight ||
    (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING))
  ) return;

  const attempt = ++connectionAttempt;
  connectInFlight = true;
  broadcastConnectionState();

  let sock;
  try {
    await loadConfig();
    await discoverNativeConnection();
    const relayUrl = await buildAuthenticatedRelayUrl();
    if (manualDisconnect || attempt !== connectionAttempt) return;
    sock = new WebSocket(relayUrl);
  } catch (e) {
    if (attempt !== connectionAttempt) return;
    if (e.code === "pairing") {
      await clearRevokedPairingState();
      manualDisconnect = connectionMode !== "native";
    }
    if (e.code === "relay_security") manualDisconnect = true;
    lastCloseReason = e.code === "pairing"
      ? "pairing"
      : e.code === "native_discovery"
        ? "native"
      : e.code === "relay_security"
        ? "security"
        : "closed";
    console.error("[WebBridge] Connection setup failed:", e);
    if (!manualDisconnect) scheduleReconnect();
    connectInFlight = false;
    broadcastConnectionState();
    return;
  } finally {
    if (attempt === connectionAttempt) connectInFlight = false;
  }
  if (manualDisconnect || attempt !== connectionAttempt) {
    try { sock.close(); } catch { /* superseded before handlers were installed */ }
    return;
  }
  ws = sock;
  broadcastConnectionState();
  const openTimeout = setTimeout(() => {
    if (ws === sock && sock.readyState === WebSocket.CONNECTING) {
      lastCloseReason = "timeout";
      console.warn("[WebBridge] Relay connection timed out; retrying.");
      try { sock.close(); } catch { /* close event will schedule reconnect */ }
    }
  }, CONNECT_TIMEOUT_MS);

  sock.onopen = () => {
    clearTimeout(openTimeout);
    if (ws !== sock || attempt !== connectionAttempt || manualDisconnect) {
      try { sock.close(); } catch { /* superseded socket */ }
      return;
    }
    console.log("[WebBridge] Connected to relay");
    connected = true;
    lastCloseReason = null;
    reconnectAttempts = 0; // reset the backoff after a successful connect
    clearTimeout(reconnectTimer);

    // Register with the relay
    sock.send(JSON.stringify({
      type: "register",
      protocol_version: 2,
      extension_id: extensionId,
      client_instance_id: extensionId,
      browser: detectBrowser(),
      version: chrome.runtime.getManifest().version,
      capabilities: {
        commands: COMMAND_CAPABILITIES,
        interactions: ["context.share", "prompt.submit"],
        captures: ["selection", "link", "page_metadata"],
        ui: ["side_panel"],
        handoff: ["ask_user_reply", "human_control_lease"],
        automation: ["teach_mode", "text_watch"],
      },
    }));

    ensureHeartbeatAlarm();
    broadcastTabInfo();
    broadcastAutomationState().catch((error) => {
      console.warn("[WebBridge] Failed to publish initial automation state:", error.message);
    });
    broadcastConnectionState();
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
    clearTimeout(openTimeout);
    if (ws !== sock) return; // superseded socket — ignore its close event
    console.log("[WebBridge] Disconnected from relay (code", event.code + ")");
    connected = false;
    ws = null;
    if (event.code === 4403) {
      manualDisconnect = connectionMode !== "native";
      clearRevokedPairingState().catch((error) => {
        console.warn("[WebBridge] Pairing cleanup failed:", error.message);
      });
    }
    // 4401 = the single-use relay ticket was invalid or expired.
    if (lastCloseReason !== "timeout" && lastCloseReason !== "endpoint_changed") {
      lastCloseReason = event.code === 4403 ? "pairing" : event.code === 4401 ? "ticket" : "closed";
    }
    broadcastConnectionState();
    if (!manualDisconnect) scheduleReconnect();
  };

  sock.onerror = (e) => {
    console.error("[WebBridge] WebSocket error:", e);
  };
}

function broadcastConnectionState() {
  chrome.runtime.sendMessage({
    type: "connection_state",
    connected,
    connecting: connectInFlight || Boolean(ws && ws.readyState === WebSocket.CONNECTING),
    last_close_reason: lastCloseReason,
    relay_base: relayBase,
    connection_mode: connectionMode,
    native_error: nativeDiscoveryError || null,
  }).catch(() => {});
}

function notifyAutomationState(feature, tabId = null) {
  chrome.runtime.sendMessage({
    type: "automation_state_changed",
    feature,
    tab_id: tabId,
  }).catch(() => {});
  clearTimeout(automationStateBroadcastTimer);
  automationStateBroadcastTimer = setTimeout(() => {
    automationStateBroadcastTimer = null;
    broadcastAutomationState().catch((error) => {
      console.warn("[WebBridge] Failed to sync automation state:", error.message);
    });
  }, 120);
}

async function automationStateSnapshot() {
  const [activeTabs, watches, recording, leases] = await Promise.all([
    chrome.tabs.query({ active: true, currentWindow: true }),
    readTextWatches(),
    readTeachRecording(),
    readHumanControlLeases(),
  ]);
  const activeTab = activeTabs[0] || null;
  const capture = activeTab?.id == null ? null : activeDiagnosticCapture(activeTab.id);
  const lease = activeTab?.id == null ? null : leases[activeTab.id] || null;
  return {
    updated_at: Date.now(),
    active_tab_id: activeTab?.id ?? null,
    text_watches: watches.map(textWatchSummary),
    teach_recording: teachRecordingSummary(recording),
    issue_capture: diagnosticSummary(capture),
    human_control_lease: humanLeaseSummary(lease),
    agent_control_tab_ids: [...agentControlOverlays],
  };
}

async function broadcastAutomationState() {
  const sock = ws;
  if (!sock || sock.readyState !== WebSocket.OPEN) return;
  const data = await automationStateSnapshot();
  if (ws !== sock || sock.readyState !== WebSocket.OPEN) return;
  sock.send(JSON.stringify({
    type: "event",
    event: "automation_state",
    data,
  }));
}

async function clearRevokedPairingState() {
  pairingCredential = "";
  pairingId = "";
  pairingRelayBase = "";
  pairingTransport = "";
  const watches = await readTextWatches().catch(() => []);
  for (const watch of watches) clearWatchMatch(watch.tab_id);
  await Promise.allSettled([
    detachAllDebuggers(),
    cancelTeachRecording(),
  ]);
  await chrome.storage.local.set({
    pairingCredential: "",
    pairingId: "",
    pairingRelayBase: "",
    pairingTransport: "",
  });
  await chrome.storage.local.remove([
    TEXT_WATCH_STORAGE_KEY,
    TEACH_RECORDING_STORAGE_KEY,
    "pendingInteraction",
    "lastInteraction",
    "lastTeachDraft",
  ]);
  await humanLeaseStorage().remove([
    HUMAN_LEASE_STORAGE_KEY,
    PICKED_ELEMENT_STORAGE_KEY,
    "webbridgePanelPendingRequest",
  ]);
  chrome.runtime.sendMessage({ type: "pairing_revoked" }).catch(() => {});
}

function disconnect() {
  manualDisconnect = true;
  connectionAttempt++;
  connectInFlight = false;
  clearTimeout(reconnectTimer);
  if (ws) {
    try { ws.close(); } catch { /* already closed */ }
    ws = null;
  }
  connected = false;
  detachAllDebuggers().catch((e) => {
    console.warn("[WebBridge] Failed to release browser control:", e.message);
  });
  broadcastConnectionState();
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
  if (alarm.name === HEARTBEAT_ALARM) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "ping" }));
      broadcastAutomationState().catch((error) => {
        console.warn("[WebBridge] Automation heartbeat sync failed:", error.message);
      });
      refreshNativeConnectionIfChanged().catch((error) => {
        console.warn("[WebBridge] Native endpoint heartbeat failed:", error.message);
      });
    } else if (!manualDisconnect) {
      connect();
    }
    return;
  }
  if (alarm.name === TEXT_WATCH_ALARM) {
    pollTextWatches().catch((error) => {
      console.warn("[WebBridge] Text watch poll failed:", error.message);
    });
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
    if (msg.pairing_id) {
      pairingId = msg.pairing_id;
      chrome.storage.local.set({ pairingId });
    } else if (msg.extension_id && msg.extension_id !== extensionId) {
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
      case "resize":
        result = await cmdResize(params);
        break;
      case "reset_viewport":
        result = await cmdResetViewport(params);
        break;
      case "dialogs":
        result = await cmdDialogs(params);
        break;
      case "handle_dialog":
        result = await cmdHandleDialog(params);
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
      case "wait_for_text":
        result = await cmdWaitForText(params);
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
      case "hover":
        result = await cmdHover(params);
        break;
      case "focus":
        result = await cmdFocus(params);
        break;
      case "select_option":
        result = await cmdSelectOption(params);
        break;
      case "set_checked":
        result = await cmdSetChecked(params);
        break;
      case "drag":
        result = await cmdDrag(params);
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
      case "semantic_snapshot":
        result = await globalThis.WebBridgeSemantic.snapshot(params);
        break;
      case "semantic_read":
        result = await globalThis.WebBridgeSemantic.read(params);
        break;
      case "semantic_select":
        result = await globalThis.WebBridgeSemantic.select(params);
        break;
      case "semantic_write":
        result = await globalThis.WebBridgeSemantic.write(params);
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

function humanLeaseSummary(lease) {
  if (!lease) return null;
  return {
    tab_id: lease.tab_id,
    origin: lease.origin,
    acquired_at: lease.acquired_at,
    expires_at: lease.expires_at,
  };
}

function humanLeaseStorage() {
  // Live handoff/control state must survive MV3 worker suspension but not a
  // browser restart. Chrome 116 provides storage.session; local is a guarded
  // fallback for test harnesses and older Chromium implementations.
  return chrome.storage.session || chrome.storage.local;
}

async function readHumanControlLeases() {
  const storage = humanLeaseStorage();
  const stored = await storage.get([HUMAN_LEASE_STORAGE_KEY]);
  const raw = stored[HUMAN_LEASE_STORAGE_KEY];
  const leases = raw?.tab_id != null ? { [raw.tab_id]: raw } : (raw || {});
  let changed = raw?.tab_id != null;
  for (const [tabId, lease] of Object.entries(leases)) {
    if (!lease || !Number.isFinite(lease.expires_at) || lease.expires_at <= Date.now()) {
      delete leases[tabId];
      changed = true;
    }
  }
  if (changed) {
    if (Object.keys(leases).length) {
      await storage.set({ [HUMAN_LEASE_STORAGE_KEY]: leases });
    } else {
      await storage.remove([HUMAN_LEASE_STORAGE_KEY]);
    }
  }
  return leases;
}

async function humanLeaseForTab(tab) {
  if (!tab || tab.id == null) return null;
  const leases = await readHumanControlLeases();
  const lease = leases[tab.id];
  if (!lease) return null;
  const origin = browserOrigin(tab.url || tab.pendingUrl || "");
  if (!origin || origin !== lease.origin) {
    delete leases[tab.id];
    if (Object.keys(leases).length) {
      await humanLeaseStorage().set({ [HUMAN_LEASE_STORAGE_KEY]: leases });
    } else {
      await humanLeaseStorage().remove([HUMAN_LEASE_STORAGE_KEY]);
    }
    return null;
  }
  return lease;
}

async function humanLeaseForWindow(windowId) {
  if (windowId == null) return null;
  const leases = await readHumanControlLeases();
  return Object.values(leases).find((lease) => lease.window_id === windowId) || null;
}

async function takeHumanControlLease(tab) {
  if (!tab || tab.id == null) throw new Error("No active browser tab");
  const origin = browserOrigin(tab.url || tab.pendingUrl || "");
  if (!origin) throw new Error("Human control can only be taken on an HTTP(S) page.");
  const now = Date.now();
  const lease = {
    tab_id: tab.id,
    window_id: tab.windowId,
    origin,
    acquired_at: now,
    expires_at: now + HUMAN_LEASE_TTL_MS,
  };
  const leases = await readHumanControlLeases();
  leases[tab.id] = lease;
  await humanLeaseStorage().set({ [HUMAN_LEASE_STORAGE_KEY]: leases });
  await setAgentControlOverlay(tab.id, false);
  notifyAutomationState("browser_control", tab.id);
  return humanLeaseSummary(lease);
}

async function releaseHumanControlLease(tabId = null) {
  const leases = await readHumanControlLeases();
  if (tabId == null) {
    if (!Object.keys(leases).length) return false;
    await humanLeaseStorage().remove([HUMAN_LEASE_STORAGE_KEY]);
    notifyAutomationState("browser_control");
    return true;
  }
  if (!leases[tabId]) return false;
  delete leases[tabId];
  if (Object.keys(leases).length) {
    await humanLeaseStorage().set({ [HUMAN_LEASE_STORAGE_KEY]: leases });
  } else {
    await humanLeaseStorage().remove([HUMAN_LEASE_STORAGE_KEY]);
  }
  notifyAutomationState("browser_control", tabId);
  return true;
}

async function releaseBrowserControlToHuman(tabId = null) {
  const tab = tabId == null ? await getActiveTab() : await chrome.tabs.get(tabId);
  if (!tab || tab.id == null) throw new Error("No active browser tab");
  const lease = await takeHumanControlLease(tab);
  await detachDebugger(tab.id);
  return { released: true, lease };
}

async function configureSidePanel() {
  if (!chrome.sidePanel?.setPanelBehavior) return;
  await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
}

async function addTabToSessionGroup(parentTab, childTab, sessionId) {
  if (!chrome.tabs?.group) return null;
  const existingGroupId = Number.isInteger(parentTab.groupId) && parentTab.groupId >= 0
    ? parentTab.groupId
    : null;
  const groupId = existingGroupId == null
    ? await chrome.tabs.group({
      tabIds: [parentTab.id, childTab.id],
      createProperties: { windowId: parentTab.windowId },
    })
    : existingGroupId;
  if (existingGroupId != null) {
    await chrome.tabs.group({ tabIds: childTab.id, groupId });
  }
  if (chrome.tabGroups?.update) {
    const suffix = boundedText(parentTab.title).slice(0, 24);
    await chrome.tabGroups.update(groupId, {
      title: suffix ? `EvoFlux · ${suffix}` : "EvoFlux",
      color: "blue",
      collapsed: false,
    });
  }
  return groupId;
}

async function withSessionGroupLock(sessionId, operation) {
  const key = String(sessionId || "default");
  const previous = sessionGroupLocks.get(key) || Promise.resolve();
  let release;
  const current = new Promise((resolve) => { release = resolve; });
  sessionGroupLocks.set(key, current);
  await previous.catch(() => {});
  try {
    return await operation();
  } finally {
    release();
    if (sessionGroupLocks.get(key) === current) sessionGroupLocks.delete(key);
  }
}

async function createGroupedSessionTab(parentTab, sessionId, { url = "chrome://newtab/", active = false } = {}) {
  if (!parentTab || parentTab.id == null) throw new Error("The session has no primary browser tab.");
  const childTab = await chrome.tabs.create({
    url,
    active,
    windowId: parentTab.windowId,
    openerTabId: parentTab.id,
    ...(Number.isInteger(parentTab.index) ? { index: parentTab.index + 1 } : {}),
  });
  const groupId = await withSessionGroupLock(sessionId, async () => {
    const currentParent = await chrome.tabs.get(parentTab.id);
    return addTabToSessionGroup(currentParent, childTab, sessionId);
  });
  await broadcastTabInfo();
  return { success: true, tab_id: childTab.id, group_id: groupId, url };
}

async function pickedElementStorage() {
  return chrome.storage.session || chrome.storage.local;
}

async function readPickedElements() {
  const storage = await pickedElementStorage();
  const stored = await storage.get([PICKED_ELEMENT_STORAGE_KEY]);
  return stored[PICKED_ELEMENT_STORAGE_KEY] || {};
}

async function pickedElementForTab(tabId) {
  const elements = await readPickedElements();
  return elements[tabId] || null;
}

async function clearPickedElement(tabId) {
  const storage = await pickedElementStorage();
  const elements = await readPickedElements();
  if (!elements[tabId]) return false;
  delete elements[tabId];
  if (Object.keys(elements).length) {
    await storage.set({ [PICKED_ELEMENT_STORAGE_KEY]: elements });
  } else {
    await storage.remove([PICKED_ELEMENT_STORAGE_KEY]);
  }
  return true;
}

function sanitizePickedElement(tab, raw) {
  const pageUrl = safePageUrl(tab.url || tab.pendingUrl || "");
  const sourceUrl = safePageUrl(raw?.page_url || "");
  const selector = String(raw?.selector || "").trim().slice(0, 512);
  if (!pageUrl || sourceUrl !== pageUrl || !selector) {
    throw new Error("Picked element does not belong to the active page.");
  }
  return {
    tab_id: tab.id,
    page_url: pageUrl,
    selector,
    tag: boundedText(raw?.tag).slice(0, 40),
    role: boundedText(raw?.role).slice(0, 80),
    name: boundedText(raw?.name).slice(0, 200),
    text: boundedText(raw?.text).slice(0, 500),
  };
}

async function savePickedElement(tab, raw) {
  const picked = sanitizePickedElement(tab, raw);
  const storage = await pickedElementStorage();
  const elements = await readPickedElements();
  elements[tab.id] = picked;
  await storage.set({ [PICKED_ELEMENT_STORAGE_KEY]: elements });
  return picked;
}

async function startElementPicker(tab) {
  if (!tab || tab.id == null) throw new Error("No active browser tab");
  requireBrowserPageUrl(tab.url || tab.pendingUrl || "");
  await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    files: ["element_picker.js"],
  });
  let lastError = null;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const response = await chrome.tabs.sendMessage(tab.id, {
        type: "webbridge_element_picker",
        enabled: true,
      });
      if (response?.ok) {
        chrome.runtime.sendMessage({
          type: "element_picker_state",
          active: true,
          tab_id: tab.id,
        }).catch(() => {});
        return { tab_id: tab.id };
      }
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 40));
  }
  throw lastError || new Error("Element picker did not become ready on this page.");
}

async function cancelElementPicker(tab) {
  if (!tab || tab.id == null) return false;
  try {
    await chrome.tabs.sendMessage(tab.id, { type: "webbridge_element_picker", enabled: false });
  } catch {
    // Navigation can tear down the picker before cancellation arrives.
  }
  return true;
}

function regionCaptureStorage() {
  return chrome.storage.session || chrome.storage.local;
}

async function readRegionCaptures() {
  const stored = await regionCaptureStorage().get([REGION_CAPTURE_STORAGE_KEY]);
  return stored[REGION_CAPTURE_STORAGE_KEY] || {};
}

async function regionCaptureForTab(tabId) {
  const captures = await readRegionCaptures();
  return captures[tabId] || null;
}

async function clearRegionCapture(tabId) {
  const storage = regionCaptureStorage();
  const captures = await readRegionCaptures();
  if (!captures[tabId]) return false;
  delete captures[tabId];
  if (Object.keys(captures).length) {
    await storage.set({ [REGION_CAPTURE_STORAGE_KEY]: captures });
  } else {
    await storage.remove([REGION_CAPTURE_STORAGE_KEY]);
  }
  return true;
}

function finiteRegionNumber(value, name) {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) throw new Error(`Invalid region ${name}.`);
  return number;
}

function sanitizeRegionSelection(tab, raw) {
  const pageUrl = safePageUrl(tab.url || tab.pendingUrl || "");
  if (!pageUrl || safePageUrl(raw?.page_url || "") !== pageUrl) {
    throw new Error("Selected region does not belong to the active page.");
  }
  const clip = {
    x: finiteRegionNumber(raw?.clip?.x, "x"),
    y: finiteRegionNumber(raw?.clip?.y, "y"),
    width: finiteRegionNumber(raw?.clip?.width, "width"),
    height: finiteRegionNumber(raw?.clip?.height, "height"),
  };
  const viewport = {
    width: finiteRegionNumber(raw?.viewport?.width, "viewport width"),
    height: finiteRegionNumber(raw?.viewport?.height, "viewport height"),
    page_x: finiteRegionNumber(raw?.viewport?.page_x, "page x"),
    page_y: finiteRegionNumber(raw?.viewport?.page_y, "page y"),
    scale: finiteRegionNumber(raw?.viewport?.scale, "scale"),
    dpr: finiteRegionNumber(raw?.viewport?.dpr, "device pixel ratio"),
  };
  if (
    clip.width < 8 || clip.height < 8 || viewport.width <= 0 || viewport.height <= 0 ||
    viewport.scale <= 0 || viewport.dpr <= 0 ||
    clip.x + clip.width > viewport.width + 1 || clip.y + clip.height > viewport.height + 1
  ) {
    throw new Error("Selected region is outside the current viewport.");
  }
  return { page_url: pageUrl, clip, viewport };
}

function closeRegionMetric(left, right, tolerance = 1) {
  return Math.abs(Number(left) - Number(right)) <= tolerance;
}

async function captureSelectedRegion(tab, raw, cdpOptions = {}) {
  if (!tab || tab.id == null) throw new Error("No active browser tab");
  const selected = sanitizeRegionSelection(tab, raw);
  const metrics = await cdpSend(tab.id, "Page.getLayoutMetrics", {}, cdpOptions);
  const visual = metrics.cssVisualViewport || metrics.visualViewport;
  if (!visual) throw new Error("Browser viewport metrics are unavailable.");
  const current = {
    width: Number(visual.clientWidth),
    height: Number(visual.clientHeight),
    page_x: Number(visual.pageX),
    page_y: Number(visual.pageY),
    scale: Number(visual.scale || 1),
  };
  const currentTab = await chrome.tabs.get(tab.id);
  if (
    safePageUrl(currentTab.url || currentTab.pendingUrl || "") !== selected.page_url ||
    !closeRegionMetric(current.width, selected.viewport.width) ||
    !closeRegionMetric(current.height, selected.viewport.height) ||
    !closeRegionMetric(current.page_x, selected.viewport.page_x) ||
    !closeRegionMetric(current.page_y, selected.viewport.page_y) ||
    !closeRegionMetric(current.scale, selected.viewport.scale, 0.01)
  ) {
    throw new Error("The page moved or resized. Select the region again.");
  }
  // cssVisualViewport and pointer coordinates are already CSS page pixels.
  // Applying visual scale or DPR again moves the clip off-surface at zoom.
  const result = await captureWithoutAgentControlOverlay(tab.id, () => (
    cdpSend(tab.id, "Page.captureScreenshot", {
      format: "png",
      clip: {
        x: current.page_x + selected.clip.x,
        y: current.page_y + selected.clip.y,
        width: selected.clip.width,
        height: selected.clip.height,
        scale: 1,
      },
      captureBeyondViewport: true,
      fromSurface: true,
    }, cdpOptions)
  ));
  if (!result?.data) throw new Error("Browser did not return a screenshot.");
  const capture = {
    tab_id: tab.id,
    page_url: selected.page_url,
    captured_at: new Date().toISOString(),
    clip: selected.clip,
    viewport: selected.viewport,
    data_base64: result.data,
  };
  const captures = await readRegionCaptures();
  captures[tab.id] = capture;
  await regionCaptureStorage().set({ [REGION_CAPTURE_STORAGE_KEY]: captures });
  return capture;
}

async function startRegionPicker(tab) {
  if (!tab || tab.id == null) throw new Error("No active browser tab");
  requireBrowserPageUrl(tab.url || tab.pendingUrl || "");
  await clearRegionCapture(tab.id);
  await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    files: ["region_picker.js"],
  });
  await chrome.tabs.sendMessage(tab.id, {
    type: "webbridge_region_picker",
    enabled: true,
  });
  return { tab_id: tab.id };
}

async function capturePanelContext(tab, kind) {
  if (!tab || tab.id == null) throw new Error("No active browser tab");
  const pageUrl = requireBrowserPageUrl(tab.url || tab.pendingUrl || "");
  if (!new Set(["selection", "readable_page"]).has(kind)) {
    throw new Error("Unsupported browser context type.");
  }
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId: tab.id, frameIds: [0] },
    func: (captureKind, maxChars) => {
      const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
      const safeUrl = `${location.origin}${location.pathname}`;
      if (captureKind === "selection") {
        return {
          type: captureKind,
          page_url: safeUrl,
          title: document.title || "",
          text: normalize(window.getSelection()?.toString()).slice(0, maxChars),
        };
      }
      const root = document.querySelector("main,article,[role=main]") || document.body || document.documentElement;
      const clone = root.cloneNode(true);
      for (const node of clone.querySelectorAll("script,style,noscript,input,textarea,select,option,[hidden],[aria-hidden=true]")) {
        node.remove();
      }
      return {
        type: captureKind,
        page_url: safeUrl,
        title: document.title || "",
        text: normalize(clone.innerText || clone.textContent).slice(0, maxChars),
      };
    },
    args: [kind, MAX_CONTEXT_CHARS],
  });
  const current = await chrome.tabs.get(tab.id);
  if (safePageUrl(current.url || current.pendingUrl || "") !== pageUrl) {
    throw new Error("The page changed while context was being captured.");
  }
  const text = boundedText(result?.text).slice(0, MAX_CONTEXT_CHARS);
  if (!text) {
    throw new Error(kind === "selection" ? "Select text on the page first." : "No readable page text was found.");
  }
  return {
    type: kind,
    page_url: pageUrl,
    title: boundedText(result?.title).slice(0, 500),
    text,
  };
}

// Resolve the tab a command targets: an explicit params.tab_id (so a session
// can pin a tab and stay deterministic even if the user switches tabs), else
// the active tab.
async function resolveTab(params) {
  let tab;
  if (params && params.tab_id != null) {
    try {
      tab = await chrome.tabs.get(params.tab_id);
    } catch {
      throw new Error(`Tab ${params.tab_id} not found`);
    }
  } else {
    tab = await getActiveTab();
    if (!tab) throw new Error("No active tab");
  }
  if (await humanLeaseForTab(tab)) {
    throw new Error("Human control is active for this tab. Wait for the user to resume the agent.");
  }
  if (
    params?._webbridge_expected_origin &&
    browserOrigin(tab.url || tab.pendingUrl || "") !== params._webbridge_expected_origin
  ) {
    throw new Error("Bound browser tab changed origin; bind this tab again before continuing.");
  }
  return tab;
}

// Run an expression in the page and return its (JSON) value, raising on a
// thrown JS exception instead of silently returning undefined.
async function evalInPage(tabId, expression, awaitPromise = false, cdpOptions = {}) {
  const result = await cdpSend(tabId, "Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise,
  }, cdpOptions);
  if (result.exceptionDetails) {
    const ex = result.exceptionDetails;
    throw new Error(ex.exception?.description || ex.text || "Script error");
  }
  return result.result?.value;
}

// Dispatch a real press/release mouse click at viewport CSS coords (x,y),
// which triggers the full native event sequence element.click() skips.
async function clickAt(tabId, x, y, button = "left", clickCount = 1) {
  await cdpSend(tabId, "Input.dispatchMouseEvent", {
    type: "mousePressed", x, y, button, clickCount,
  });
  await new Promise((resolve) => setTimeout(resolve, 48));
  await cdpSend(tabId, "Input.dispatchMouseEvent", {
    type: "mouseReleased", x, y, button, clickCount,
  });
}

function pointerPhase(params) {
  if (params.type === "mousePressed") return "press";
  if (params.type === "mouseReleased") return "release";
  if (params.buttons) return "drag";
  return "move";
}

function minimumJerk(progress) {
  const t = Math.max(0, Math.min(1, progress));
  return t * t * t * (10 + t * (-15 + 6 * t));
}

function humanPointerPath(from, to, preferredSteps = null) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const distance = Math.hypot(dx, dy);
  if (distance < 1) return [{ x: to.x, y: to.y }];

  const durationMs = Math.max(72, Math.min(360, 68 + distance * 0.34));
  const steps = Math.max(3, Math.min(24, preferredSteps || Math.round(durationMs / 16)));
  const perpendicularX = -dy / distance;
  const perpendicularY = dx / distance;
  const direction = Math.round(from.x + from.y + to.x + to.y) % 2 === 0 ? 1 : -1;
  const bend = Math.min(38, distance * 0.075) * direction;
  const control1 = {
    x: from.x + dx * 0.32 + perpendicularX * bend,
    y: from.y + dy * 0.32 + perpendicularY * bend,
  };
  const control2 = {
    x: from.x + dx * 0.72 + perpendicularX * bend * 0.38,
    y: from.y + dy * 0.72 + perpendicularY * bend * 0.38,
  };
  const points = [];
  for (let step = 1; step <= steps; step++) {
    const t = minimumJerk(step / steps);
    const inverse = 1 - t;
    points.push({
      x: inverse ** 3 * from.x + 3 * inverse ** 2 * t * control1.x + 3 * inverse * t ** 2 * control2.x + t ** 3 * to.x,
      y: inverse ** 3 * from.y + 3 * inverse ** 2 * t * control1.y + 3 * inverse * t ** 2 * control2.y + t ** 3 * to.y,
      delayMs: durationMs / steps,
    });
  }
  points[points.length - 1] = { x: to.x, y: to.y, delayMs: durationMs / steps };
  return points;
}

async function setAgentControlOverlay(tabId, enabled, pointer = null) {
  if (tabId == null) return false;
  if (!enabled) {
    agentControlOverlays.delete(tabId);
    overlayCaptureSuspensions.delete(tabId);
    agentPointerPositions.delete(tabId);
    try {
      await chrome.tabs.sendMessage(tabId, {
        type: "webbridge_agent_control",
        enabled: false,
      });
    } catch {
      // Restricted pages and navigations may remove the content script first.
    }
    return false;
  }

  try {
    if (agentControlOverlays.has(tabId) && !pointer) return true;
    if (!agentControlOverlays.has(tabId)) {
      await chrome.scripting.executeScript({
        target: { tabId, frameIds: [0] },
        files: ["agent_control_overlay.js"],
      });
    }
    const response = await chrome.tabs.sendMessage(tabId, {
      type: "webbridge_agent_control",
      enabled: true,
      pointer,
    });
    if (response?.ok === false) throw new Error("Control overlay rejected the update");
    if (
      !agentPointerPositions.has(tabId) &&
      Number.isFinite(response?.pointer?.x) &&
      Number.isFinite(response?.pointer?.y)
    ) {
      agentPointerPositions.set(tabId, {
        x: response.pointer.x,
        y: response.pointer.y,
      });
    }
    agentControlOverlays.add(tabId);
    return true;
  } catch (error) {
    agentControlOverlays.delete(tabId);
    agentPointerPositions.delete(tabId);
    console.warn("[WebBridge] Could not show the control overlay:", error.message);
    return false;
  }
}

async function setAgentControlOverlaySuspended(tabId, suspended) {
  if (tabId == null || !agentControlOverlays.has(tabId)) return false;
  const currentDepth = overlayCaptureSuspensions.get(tabId) || 0;
  const nextDepth = suspended ? currentDepth + 1 : Math.max(0, currentDepth - 1);
  if (nextDepth > 0) overlayCaptureSuspensions.set(tabId, nextDepth);
  else overlayCaptureSuspensions.delete(tabId);
  if ((suspended && currentDepth > 0) || (!suspended && nextDepth > 0)) return true;
  try {
    const response = await chrome.tabs.sendMessage(tabId, {
      type: "webbridge_agent_control",
      suspended: nextDepth > 0,
    });
    if (response?.ok === false) throw new Error("Control overlay rejected capture suspension");
    return true;
  } catch (error) {
    if (suspended) overlayCaptureSuspensions.delete(tabId);
    console.warn("[WebBridge] Could not suspend the control overlay for capture:", error.message);
    return false;
  }
}

async function captureWithoutAgentControlOverlay(tabId, capture) {
  const shouldSuspend = agentControlOverlays.has(tabId);
  if (!shouldSuspend) return capture();
  const suspended = await setAgentControlOverlaySuspended(tabId, true);
  try {
    return await capture();
  } finally {
    if (suspended && agentControlOverlays.has(tabId)) {
      await setAgentControlOverlaySuspended(tabId, false);
    }
  }
}

async function ensureDebuggerAttached(tabId, { showControl = true } = {}) {
  if (attachedTabs.has(tabId)) {
    if (showControl) await setAgentControlOverlay(tabId, true);
    return;
  }

  await new Promise((resolve, reject) => {
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
  // Page.enable is idempotent and makes JavaScript dialog events observable,
  // allowing the agent or Side Chat to handle native alert/confirm/prompt UI.
  await sendCommandOnce(tabId, "Page.enable", {}).catch((error) => {
    console.warn("[WebBridge] Page dialog events unavailable:", error.message);
  });
  if (showControl) {
    await setAgentControlOverlay(tabId, true);
    notifyAutomationState("browser_control", tabId);
  }
}

async function detachDebugger(tabId) {
  if (!attachedTabs.has(tabId)) {
    await setAgentControlOverlay(tabId, false);
    return;
  }

  await new Promise((resolve) => {
    chrome.debugger.detach({ tabId }, () => {
      attachedTabs.delete(tabId);
      resolve();
    });
  });
  await setAgentControlOverlay(tabId, false);
  notifyAutomationState("browser_control", tabId);
}

async function detachAllDebuggers() {
  const tabIds = [...attachedTabs.keys()];
  await Promise.all(tabIds.map((tabId) => detachDebugger(tabId)));
  return tabIds;
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

async function sendCommandResilient(tabId, method, params, attachOptions = {}) {
  try {
    return await sendCommandOnce(tabId, method, params);
  } catch (error) {
    if (!/not attached/i.test(error.message)) throw error;
    attachedTabs.delete(tabId);
    await ensureDebuggerAttached(tabId, attachOptions);
    return sendCommandOnce(tabId, method, params);
  }
}

async function dispatchHumanPointerMove(tabId, target, eventParams = {}) {
  const from = agentPointerPositions.get(tabId);
  const points = from
    ? humanPointerPath(from, target)
    : [{ x: target.x, y: target.y, delayMs: 0 }];
  let result;
  for (let index = 0; index < points.length; index++) {
    const point = points[index];
    await setAgentControlOverlay(tabId, true, {
      x: point.x,
      y: point.y,
      phase: eventParams.buttons ? "drag" : "move",
    });
    result = await sendCommandResilient(tabId, "Input.dispatchMouseEvent", {
      type: "mouseMoved",
      x: point.x,
      y: point.y,
      ...(eventParams.button ? { button: eventParams.button } : {}),
      ...(eventParams.buttons ? { buttons: eventParams.buttons } : {}),
      ...(eventParams.modifiers ? { modifiers: eventParams.modifiers } : {}),
    });
    agentPointerPositions.set(tabId, { x: point.x, y: point.y });
    if (index < points.length - 1 && point.delayMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, Math.max(8, point.delayMs)));
    }
  }
  if (points.length > 1) {
    // Let the overlay's short interpolation settle on the same coordinate
    // before a following press, matching the page's final mouseMoved event.
    await new Promise((resolve) => setTimeout(resolve, 28));
  }
  return result;
}

async function cdpSend(tabId, method, params = {}, attachOptions = {}) {
  await ensureDebuggerAttached(tabId, attachOptions);

  const pointerEvent =
    method === "Input.dispatchMouseEvent" &&
    Number.isFinite(params.x) &&
    Number.isFinite(params.y);
  if (pointerEvent && params.type === "mouseMoved" && !params.buttons) {
    return dispatchHumanPointerMove(tabId, { x: params.x, y: params.y }, params);
  }
  if (pointerEvent && params.type !== "mouseMoved" && params.type !== "mouseReleased") {
    const current = agentPointerPositions.get(tabId);
    if (!current || Math.hypot(params.x - current.x, params.y - current.y) >= 1) {
      await dispatchHumanPointerMove(tabId, { x: params.x, y: params.y });
    }
  }
  if (pointerEvent) {
    await setAgentControlOverlay(tabId, true, {
      x: params.x,
      y: params.y,
      phase: pointerPhase(params),
    });
  }

  const result = await sendCommandResilient(tabId, method, params, attachOptions);
  if (pointerEvent) agentPointerPositions.set(tabId, { x: params.x, y: params.y });
  return result;
}

// ── Network in-flight tracking (for wait_for_network_idle) ────────────────────
// tabId → Set of CDP requestIds currently in flight. Populated by the
// Network.* debugger events below; only meaningful once Network.enable has
// been sent for that tab (cmdWaitForNetworkIdle does that).
const networkInflight = new Map();
const diagnosticCaptures = new Map();
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

function redactDiagnosticText(value) {
  let text = String(value || "").slice(0, 4000);
  const secretKeys = "authorization|proxy-authorization|cookie|set-cookie|password|passwd|access_token|refresh_token|id_token|token|secret|api[-_]?key";
  text = text.replace(/https?:\/\/[^\s"'<>]+/gi, (url) => safePageUrl(url) || "[URL]");
  text = text.replace(
    new RegExp(`(["'])(${secretKeys})\\1\\s*:\\s*(["'])[^"'\\r\\n]*\\3`, "gi"),
    (_match, keyQuote, key, valueQuote) => `${keyQuote}${key}${keyQuote}:${valueQuote}[REDACTED]${valueQuote}`
  );
  text = text.replace(
    /\b(cookie|set-cookie)\b\s*["']?\s*[:=]\s*[^\r\n]*/gi,
    "$1=[REDACTED]"
  );
  text = text.replace(
    new RegExp(`\\b(${secretKeys})(?:%22|%27)?(?:%3a|%3d)(?:%22|%27)?(?:(?!%26)[^\\s&])+`, "gi"),
    "$1%3D[REDACTED]"
  );
  text = text.replace(
    new RegExp(`\\b(${secretKeys})\\b\\s*["']?\\s*[:=]\\s*["']?(?:Bearer\\s+)?[^"'\\s,;&}]+`, "gi"),
    "$1=[REDACTED]"
  );
  text = text.replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, "Bearer [REDACTED]");
  text = text.replace(/\beyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, "[REDACTED]");
  text = text.replace(/\b[A-Za-z0-9_-]{40,}\b/g, "[REDACTED]");
  return boundedText(text).slice(0, 1000);
}

function activeDiagnosticCapture(tabId) {
  const capture = diagnosticCaptures.get(tabId);
  if (!capture) return null;
  if (capture.expires_at <= Date.now()) {
    diagnosticCaptures.delete(tabId);
    if (capture.detach_on_stop && !agentControlOverlays.has(tabId)) {
      detachDebugger(tabId).catch(() => {});
    }
    return null;
  }
  return capture;
}

function diagnosticSummary(capture) {
  if (!capture) return null;
  return {
    tab_id: capture.tab_id,
    page_url: capture.page_url,
    expires_at: capture.expires_at,
    entry_count: capture.entries.length,
  };
}

function appendDiagnostic(tabId, entry) {
  const capture = activeDiagnosticCapture(tabId);
  if (!capture) return;
  capture.entries.push({
    ...entry,
    page_url: capture.page_url,
    captured_at: new Date().toISOString(),
  });
  if (capture.entries.length > MAX_DIAGNOSTIC_ENTRIES) {
    capture.entries.splice(0, capture.entries.length - MAX_DIAGNOSTIC_ENTRIES);
  }
  notifyAutomationState("issue_capture", tabId);
}

async function startDiagnosticCapture(tab) {
  if (!tab || tab.id == null) throw new Error("No active browser tab");
  const pageUrl = requireBrowserPageUrl(tab.url || tab.pendingUrl || "");
  const detachOnStop = !attachedTabs.has(tab.id);
  await ensureDebuggerAttached(tab.id, { showControl: false });
  await Promise.all([
    cdpSend(tab.id, "Runtime.enable", {}, { showControl: false }),
    cdpSend(tab.id, "Network.enable", {}, { showControl: false }),
    cdpSend(tab.id, "Log.enable", {}, { showControl: false }).catch(() => ({})),
  ]);
  const capture = {
    tab_id: tab.id,
    page_url: pageUrl,
    expires_at: Date.now() + DIAGNOSTIC_CAPTURE_TTL_MS,
    entries: [],
    requests: new Map(),
    detach_on_stop: detachOnStop,
  };
  diagnosticCaptures.set(tab.id, capture);
  notifyAutomationState("issue_capture", tab.id);
  return diagnosticSummary(capture);
}

async function stopDiagnosticCapture(tabId) {
  const capture = diagnosticCaptures.get(tabId);
  const stopped = diagnosticCaptures.delete(tabId);
  if (capture?.detach_on_stop && !agentControlOverlays.has(tabId)) {
    await detachDebugger(tabId);
  }
  notifyAutomationState("issue_capture", tabId);
  return stopped;
}

function consoleDiagnostic(params) {
  const level = String(params?.type || "").toLowerCase();
  if (!["warning", "error", "assert"].includes(level)) return null;
  const values = (params.args || []).map((arg) => arg.value ?? arg.description ?? "");
  return {
    kind: "console",
    level: level === "warning" ? "warning" : "error",
    message: redactDiagnosticText(values.join(" ")),
  };
}

async function captureIssueViewport(tab) {
  const metrics = await cdpSend(tab.id, "Page.getLayoutMetrics", {}, { showControl: false });
  const visual = metrics.cssVisualViewport || metrics.visualViewport;
  if (!visual) throw new Error("Browser viewport metrics are unavailable.");
  const dpr = await evalInPage(tab.id, "window.devicePixelRatio || 1", false, { showControl: false });
  return captureSelectedRegion(tab, {
    page_url: safePageUrl(tab.url || tab.pendingUrl || ""),
    clip: {
      x: 0,
      y: 0,
      width: Number(visual.clientWidth),
      height: Number(visual.clientHeight),
    },
    viewport: {
      width: Number(visual.clientWidth),
      height: Number(visual.clientHeight),
      page_x: Number(visual.pageX),
      page_y: Number(visual.pageY),
      scale: Number(visual.scale || 1),
      dpr: Number(dpr || 1),
    },
  }, { showControl: false });
}

async function collectIssueReport(tab) {
  const diagnostic = activeDiagnosticCapture(tab?.id);
  if (!diagnostic) throw new Error("Start issue capture before reporting an issue.");
  if (safePageUrl(tab.url || tab.pendingUrl || "") !== diagnostic.page_url) {
    await stopDiagnosticCapture(tab.id);
    throw new Error("The page changed. Start issue capture again.");
  }
  const existingRegion = await regionCaptureForTab(tab.id);
  const capture = existingRegion || await captureIssueViewport(tab);
  const entries = diagnostic.entries.map((entry) => ({ ...entry }));
  await stopDiagnosticCapture(tab.id);
  return { capture, diagnostics: entries };
}

chrome.debugger.onEvent.addListener((source, method, params) => {
  const tabId = source.tabId;
  if (!tabId || !params) return;
  const diagnostics = activeDiagnosticCapture(tabId);
  if (method === "Page.javascriptDialogOpening") {
    const history = pageDialogHistory.get(tabId) || [];
    const dialog = {
      id: `${tabId}:${Date.now()}:${history.length + 1}`,
      tab_id: tabId,
      type: String(params.type || "alert"),
      message: String(params.message || ""),
      default_prompt: String(params.defaultPrompt || ""),
      url: safePageUrl(params.url || ""),
      opened_at: new Date().toISOString(),
      active: true,
    };
    activePageDialogs.set(tabId, dialog);
    history.push(dialog);
    if (history.length > 100) history.splice(0, history.length - 100);
    pageDialogHistory.set(tabId, history);
    chrome.runtime.sendMessage({ type: "browser_dialog_opened", dialog }).catch(() => {});
  } else if (method === "Page.javascriptDialogClosed") {
    const dialog = activePageDialogs.get(tabId);
    if (dialog) {
      dialog.active = false;
      dialog.accepted = Boolean(params.result);
      dialog.user_input = params.userInput ? String(params.userInput) : "";
      dialog.closed_at = new Date().toISOString();
      activePageDialogs.delete(tabId);
      chrome.runtime.sendMessage({ type: "browser_dialog_closed", dialog }).catch(() => {});
    }
  } else if (method === "Network.requestWillBeSent") {
    netInc(tabId, params.requestId);
    if (diagnostics) {
      diagnostics.requests.set(params.requestId, {
        request_url: safePageUrl(params.request?.url || ""),
        method: boundedText(params.request?.method).slice(0, 16),
      });
    }
  } else if (method === "Network.responseReceived") {
    const status = Number(params.response?.status || 0);
    if (diagnostics && status >= 400) {
      const request = diagnostics.requests.get(params.requestId) || {};
      appendDiagnostic(tabId, {
        kind: "network",
        level: "error",
        message: `HTTP ${status}`,
        request_url: request.request_url || safePageUrl(params.response?.url || ""),
        method: request.method || "",
        status,
      });
    }
  } else if (method === "Network.loadingFinished" || method === "Network.loadingFailed") {
    netDec(tabId, params.requestId);
    if (method === "Network.loadingFailed" && diagnostics) {
      const request = diagnostics.requests.get(params.requestId) || {};
      appendDiagnostic(tabId, {
        kind: "network",
        level: "error",
        message: redactDiagnosticText(params.errorText || "Network request failed"),
        request_url: request.request_url || "",
        method: request.method || "",
      });
    }
    diagnostics?.requests.delete(params.requestId);
  }
  else if (method === "Network.requestServedFromCache") netDec(tabId, params.requestId);
  else if (method === "Runtime.consoleAPICalled") {
    const entry = consoleDiagnostic(params);
    if (entry) appendDiagnostic(tabId, entry);
  } else if (method === "Runtime.exceptionThrown") {
    appendDiagnostic(tabId, {
      kind: "console",
      level: "error",
      message: redactDiagnosticText(
        params.exceptionDetails?.exception?.description ||
        params.exceptionDetails?.text ||
        "Unhandled exception"
      ),
    });
  } else if (method === "Log.entryAdded") {
    const level = String(params.entry?.level || "").toLowerCase();
    if (["warning", "error"].includes(level)) {
      appendDiagnostic(tabId, {
        kind: "console",
        level,
        message: redactDiagnosticText(params.entry?.text || ""),
      });
    }
  }
});

// Chrome detached the debugger outside our control (infobar Cancel,
// navigation to a restricted page, tab process gone) — forget the stale
// state so the next command re-attaches instead of failing.
chrome.debugger.onDetach.addListener((source) => {
  networkInflight.delete(source.tabId);
  diagnosticCaptures.delete(source.tabId);
  activePageDialogs.delete(source.tabId);
  setAgentControlOverlay(source.tabId, false).catch(() => {});
  if (source.tabId && attachedTabs.delete(source.tabId)) {
    console.warn("[WebBridge] Debugger detached from tab", source.tabId);
    broadcastTabInfo();
    notifyAutomationState("browser_control", source.tabId);
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  attachedTabs.delete(tabId);
  agentControlOverlays.delete(tabId);
  overlayCaptureSuspensions.delete(tabId);
  agentPointerPositions.delete(tabId);
  networkInflight.delete(tabId);
  diagnosticCaptures.delete(tabId);
  activePageDialogs.delete(tabId);
  pageDialogHistory.delete(tabId);
  notifyAutomationState("tab_closed", tabId);
  cancelTextWatchesForTab(tabId).catch((error) => {
    console.warn("[WebBridge] Failed to cancel tab text watches:", error.message);
  });
  cancelTeachRecording(tabId).catch((error) => {
    console.warn("[WebBridge] Failed to cancel Teach Mode for a closed tab:", error.message);
  });
  releaseHumanControlLease(tabId).catch((error) => {
    console.warn("[WebBridge] Failed to release human control for a closed tab:", error.message);
  });
  clearPickedElement(tabId).catch((error) => {
    console.warn("[WebBridge] Failed to clear picked element for a closed tab:", error.message);
  });
  clearRegionCapture(tabId).catch((error) => {
    console.warn("[WebBridge] Failed to clear region capture for a closed tab:", error.message);
  });
  clearPanelTabState(tabId).catch((error) => {
    console.warn("[WebBridge] Failed to clear Side Chat draft for a closed tab:", error.message);
  });
  broadcastTabInfo();
});

// ── Command implementations ──────────────────────────────────────────────────

async function cmdNavigate(params) {
  const tab = await resolveTab(params);
  let timeoutId = null;
  let listener = null;
  const completed = new Promise((resolve) => {
    listener = (tabId, changeInfo) => {
      if (tabId === tab.id && changeInfo.status === "complete") {
        chrome.tabs.onUpdated.removeListener(listener);
        if (timeoutId) clearTimeout(timeoutId);
        resolve(true);
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
    timeoutId = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      resolve(false);
    }, 30000);
  });

  try {
    await chrome.tabs.update(tab.id, { url: params.url });
  } catch (e) {
    if (listener) chrome.tabs.onUpdated.removeListener(listener);
    if (timeoutId) clearTimeout(timeoutId);
    throw e;
  }
  const loaded = await completed;
  await broadcastTabInfo();
  const current = await chrome.tabs.get(tab.id);
  if (browserOrigin(current.url || current.pendingUrl || "")) {
    await ensureDebuggerAttached(current.id);
  }
  return {
    success: true,
    url: current.url || current.pendingUrl || params.url,
    timed_out: !loaded,
  };
}

async function cmdClick(params) {
  const tab = await resolveTab(params);

  const { x, y, button = "left" } = params;
  const resolvedButton = ["left", "middle", "right"].includes(button) ? button : "left";

  await clickAt(tab.id, x, y, resolvedButton);

  return { success: true, x, y, button: resolvedButton };
}

async function cmdDblClick(params) {
  const tab = await resolveTab(params);

  const { x, y } = params;

  for (let i = 0; i < 2; i++) {
    await clickAt(tab.id, x, y, "left", i + 1);
    if (i === 0) await new Promise((resolve) => setTimeout(resolve, 72));
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

  const { key, modifiers = [] } = params;

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
    "Space": { key: " ", code: "Space", windowsVirtualKeyCode: 32 },
  };

  let mapped = keyMap[key];
  if (!mapped && typeof key === "string" && key.length === 1) {
    const upper = key.toUpperCase();
    mapped = {
      key,
      code: /^[a-z]$/i.test(key) ? `Key${upper}` : key,
      windowsVirtualKeyCode: upper.charCodeAt(0),
    };
  }
  mapped ||= { key, code: key };

  const modifierBits = { Alt: 1, Control: 2, Meta: 4, Shift: 8 };
  const modifierMask = [...new Set(modifiers)]
    .reduce((mask, modifier) => mask | (modifierBits[modifier] || 0), 0);

  await cdpSend(tab.id, "Input.dispatchKeyEvent", {
    type: "keyDown",
    ...mapped,
    modifiers: modifierMask,
  });
  await cdpSend(tab.id, "Input.dispatchKeyEvent", {
    type: "keyUp",
    ...mapped,
    modifiers: modifierMask,
  });

  return { success: true, key, modifiers };
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

async function cmdResize(params) {
  const tab = await resolveTab(params);
  const presets = {
    mobile: { width: 375, height: 812, mobile: true, touch: true },
    tablet: { width: 768, height: 1024, mobile: true, touch: true },
    desktop: { width: 1280, height: 800, mobile: false, touch: false },
  };
  const preset = typeof params?.preset === "string" ? presets[params.preset] : null;
  const width = Math.round(Number(preset?.width ?? params?.width));
  const height = Math.round(Number(preset?.height ?? params?.height));
  if (!Number.isFinite(width) || !Number.isFinite(height) || width < 200 || height < 200) {
    throw new Error("resize requires a preset or width and height of at least 200px");
  }
  const dpr = Math.max(0.5, Math.min(4, Number(params?.device_scale_factor) || 1));
  const mobile = typeof params?.mobile === "boolean" ? params.mobile : Boolean(preset?.mobile);
  const touch = typeof params?.touch === "boolean" ? params.touch : Boolean(preset?.touch);
  await cdpSend(tab.id, "Emulation.setDeviceMetricsOverride", {
    width: Math.min(4000, width),
    height: Math.min(4000, height),
    deviceScaleFactor: dpr,
    mobile,
    screenWidth: Math.min(4000, width),
    screenHeight: Math.min(4000, height),
  });
  await cdpSend(tab.id, "Emulation.setTouchEmulationEnabled", {
    enabled: touch,
    maxTouchPoints: touch ? 5 : 1,
  });
  if (params?.color_scheme === "light" || params?.color_scheme === "dark") {
    await cdpSend(tab.id, "Emulation.setEmulatedMedia", {
      media: "",
      features: [{ name: "prefers-color-scheme", value: params.color_scheme }],
    });
  }
  return {
    success: true,
    viewport: await getViewportMetrics(tab.id),
    mobile,
    touch,
    color_scheme: params?.color_scheme || null,
  };
}

async function cmdResetViewport(params) {
  const tab = await resolveTab(params);
  await cdpSend(tab.id, "Emulation.clearDeviceMetricsOverride", {});
  await cdpSend(tab.id, "Emulation.setTouchEmulationEnabled", {
    enabled: false,
    maxTouchPoints: 1,
  });
  await cdpSend(tab.id, "Emulation.setEmulatedMedia", { media: "", features: [] });
  return { success: true, viewport: await getViewportMetrics(tab.id) };
}

async function cmdDialogs(params) {
  const tab = await resolveTab(params);
  const limit = Math.max(1, Math.min(100, Number(params?.limit) || 20));
  const history = (pageDialogHistory.get(tab.id) || []).slice(-limit);
  const active = activePageDialogs.get(tab.id) || null;
  if (params?.clear) pageDialogHistory.set(tab.id, active ? [active] : []);
  return { success: true, active, history };
}

async function cmdHandleDialog(params) {
  const tab = await resolveTab(params);
  return handlePageDialogForTab(tab.id, params);
}

async function handlePageDialogForTab(tabId, params) {
  const dialog = activePageDialogs.get(tabId);
  if (!dialog) throw new Error("No active JavaScript dialog in this tab");
  const accept = dialog.type === "alert" ? true : Boolean(params?.accept);
  const command = { accept };
  if (dialog.type === "prompt" && accept && params?.prompt_text != null) {
    command.promptText = String(params.prompt_text);
  }
  await sendCommandResilient(tabId, "Page.handleJavaScriptDialog", command, { showControl: false });
  return { success: true, type: dialog.type, accepted: accept, dialog_id: dialog.id };
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

  const result = await captureWithoutAgentControlOverlay(tab.id, () => (
    cdpSend(tab.id, "Page.captureScreenshot", {
      format: fmt,
      quality: fmt === "jpeg" ? quality : undefined,
      clip,
      captureBeyondViewport: true,
      fromSurface: true,
    })
  ));

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
    tabs: tabs.map(tabSummary),
  };
}

async function cmdSwitchTab(params) {
  const { index, id } = params;

  // `id != null` (not `if (id)`) so a legitimate tab id of 0 isn't treated
  // as "no id given".
  if (id != null) {
    const tab = await chrome.tabs.get(id);
    if (await humanLeaseForWindow(tab.windowId)) {
      throw new Error("Human control is active in this window. Wait for the user to resume the agent.");
    }
    await chrome.tabs.update(id, { active: true });
    await chrome.windows.update(tab.windowId, { focused: true });
    if (browserOrigin(tab.url || tab.pendingUrl || "")) await ensureDebuggerAttached(tab.id);
    await broadcastTabInfo();
    return { success: true, tab_id: id };
  }

  const tabs = await chrome.tabs.query({});
  if (index >= 0 && index < tabs.length) {
    const tab = tabs[index];
    if (await humanLeaseForWindow(tab.windowId)) {
      throw new Error("Human control is active in this window. Wait for the user to resume the agent.");
    }
    await chrome.tabs.update(tab.id, { active: true });
    await chrome.windows.update(tab.windowId, { focused: true });
    if (browserOrigin(tab.url || tab.pendingUrl || "")) await ensureDebuggerAttached(tab.id);
    await broadcastTabInfo();
    return { success: true, tab_id: tab.id };
  }

  throw new Error(`Tab index ${index} out of range`);
}

async function cmdOpenTab(params) {
  const { url, active = true } = params;
  if (!url) throw new Error("open_tab requires a url");
  if (active) {
    const current = await getActiveTab();
    if (current && await humanLeaseForWindow(current.windowId)) {
      throw new Error("Human control is active in this window. Open the tab in background or wait for the user to resume the agent.");
    }
  }
  const parentTabId = params._webbridge_parent_tab_id;
  if (parentTabId != null) {
    const parentTab = await chrome.tabs.get(parentTabId);
    return createGroupedSessionTab(parentTab, params._webbridge_session_id, { url, active });
  }
  const tab = await chrome.tabs.create({ url, active });
  await broadcastTabInfo();
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
  const tab = await chrome.tabs.get(tabId);
  if (await humanLeaseForTab(tab)) {
    throw new Error("Human control is active for this tab. Wait for the user to resume the agent.");
  }
  if (tab.active && await humanLeaseForWindow(tab.windowId)) {
    throw new Error("Human control is active in this window. Wait for the user to resume the agent.");
  }
  await chrome.tabs.remove(tabId);
  await broadcastTabInfo();
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

  if (result.exceptionDetails) {
    const ex = result.exceptionDetails;
    throw new Error(ex.exception?.description || ex.text || "Script error");
  }

  return {
    success: true,
    value: result.result?.value,
    type: result.result?.type,
    description: result.result?.description,
  };
}

async function cmdBack(params) {
  const tab = await resolveTab(params);
  await ensureDebuggerAttached(tab.id);
  await chrome.tabs.goBack(tab.id);
  await broadcastTabInfo();
  return { success: true };
}

async function cmdForward(params) {
  const tab = await resolveTab(params);
  await ensureDebuggerAttached(tab.id);
  await chrome.tabs.goForward(tab.id);
  await broadcastTabInfo();
  return { success: true };
}

async function cmdReload(params) {
  const tab = await resolveTab(params);
  await ensureDebuggerAttached(tab.id);
  await chrome.tabs.reload(tab.id);
  await broadcastTabInfo();
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

async function cmdWaitForText(params) {
  const tab = await resolveTab(params);
  const { text, selector = null, state = "visible", exact = false } = params || {};
  if (!text) throw new Error("wait_for_text requires text");
  const timeoutMs = Math.max(100, Math.min(60000, Number(params?.timeout_ms) || 10000));
  const needle = JSON.stringify(String(text).replace(/\s+/g, " ").trim());
  const sel = selector ? JSON.stringify(selector) : "null";
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const found = await evalInPage(
      tab.id,
      `(() => {
        const needle = ${needle}, selector = ${sel}, exact = ${exact ? "true" : "false"};
        const normalize = (value) => String(value || "").replace(/\\s+/g, " ").trim();
        const visible = (el) => {
          const rect = el.getBoundingClientRect();
          const style = getComputedStyle(el);
          return rect.width > 0 && rect.height > 0 && style.display !== "none" &&
            style.visibility !== "hidden" && style.opacity !== "0";
        };
        if (selector) {
          const root = document.querySelector(selector);
          if (!root || !visible(root)) return false;
          const value = normalize(root.innerText || root.textContent);
          return exact ? value === needle : value.includes(needle);
        }
        if (!exact) {
          const value = normalize((document.body || document.documentElement).innerText);
          return value.includes(needle);
        }
        for (const el of document.querySelectorAll("body *")) {
          if (visible(el) && normalize(el.innerText || el.textContent) === needle) return true;
        }
        return false;
      })()`
    );
    if ((state === "hidden" && !found) || (state !== "hidden" && found)) {
      return { success: true, text, state };
    }
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  throw new Error(`Timed out after ${timeoutMs}ms waiting for text ${JSON.stringify(text)} to be ${state}`);
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

async function cmdHover(params) {
  const tab = await resolveTab(params);
  const { selector, index = 0 } = params || {};
  if (!selector) throw new Error("hover requires a selector");
  const sel = JSON.stringify(selector);
  const itemIndex = Math.max(0, Number(index) || 0);
  const center = await elementCenter(tab.id, `document.querySelectorAll(${sel})[${itemIndex}]`);
  if (!center) throw new Error(`No visible element for selector ${selector} (index ${index})`);
  await cdpSend(tab.id, "Input.dispatchMouseEvent", {
    type: "mouseMoved",
    x: center.x,
    y: center.y,
  });
  return { success: true, selector, x: center.x, y: center.y };
}

async function cmdFocus(params) {
  const tab = await resolveTab(params);
  const { selector, index = 0 } = params || {};
  if (!selector) throw new Error("focus requires a selector");
  const sel = JSON.stringify(selector);
  const itemIndex = Math.max(0, Number(index) || 0);
  const focused = await evalInPage(
    tab.id,
    `(() => {
      const el = document.querySelectorAll(${sel})[${itemIndex}];
      if (!el || typeof el.focus !== "function") return false;
      el.scrollIntoView({ block: "center", inline: "center" });
      el.focus();
      return document.activeElement === el;
    })()`
  );
  if (!focused) throw new Error(`Element ${selector} (index ${index}) could not be focused`);
  return { success: true, selector, index: itemIndex };
}

async function cmdSelectOption(params) {
  const tab = await resolveTab(params);
  const { selector, values, match = "value" } = params || {};
  if (!selector) throw new Error("select_option requires a selector");
  if (!Array.isArray(values) || values.length === 0) {
    throw new Error("select_option requires at least one value");
  }
  const sel = JSON.stringify(selector);
  const requested = JSON.stringify(values.map(String));
  const matchBy = match === "label" ? "label" : "value";
  const result = await evalInPage(
    tab.id,
    `(() => {
      const el = document.querySelector(${sel});
      const requested = ${requested};
      const matchBy = ${JSON.stringify(matchBy)};
      if (!(el instanceof HTMLSelectElement)) return { error: "selector did not match a select element" };
      if (!el.multiple && requested.length > 1) return { error: "select is not multiple" };
      const normalize = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const wanted = new Set(requested.map((value) => matchBy === "label" ? normalize(value) : value));
      const matches = [...el.options].filter((option) => wanted.has(
        matchBy === "label" ? normalize(option.label || option.textContent) : option.value
      ));
      const found = new Set(matches.map((option) =>
        matchBy === "label" ? normalize(option.label || option.textContent) : option.value
      ));
      const missing = [...wanted].filter((value) => !found.has(value));
      if (missing.length) return { error: "option(s) not found: " + missing.join(", ") };
      const selectedSet = new Set(matches);
      for (const option of el.options) option.selected = selectedSet.has(option);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return {
        selected: [...el.selectedOptions].map((option) => ({
          value: option.value,
          label: normalize(option.label || option.textContent),
          index: option.index,
        })),
      };
    })()`
  );
  if (result?.error) throw new Error(result.error);
  return { success: true, selector, selected: result?.selected || [] };
}

async function checkedElementState(tabId, expression) {
  return evalInPage(
    tabId,
    `(() => {
      const el = ${expression};
      if (!el) return { exists: false };
      const role = el.getAttribute("role");
      const inputType = el instanceof HTMLInputElement ? el.type : "";
      const native = inputType === "checkbox" || inputType === "radio";
      const aria = ["checkbox", "radio", "switch", "menuitemcheckbox", "menuitemradio"].includes(role);
      if (!native && !aria) return { exists: true, supported: false };
      const checked = native ? el.checked : el.getAttribute("aria-checked") === "true";
      const disabled = Boolean(el.disabled) || el.getAttribute("aria-disabled") === "true";
      return { exists: true, supported: true, checked, disabled };
    })()`
  );
}

async function cmdSetChecked(params) {
  const tab = await resolveTab(params);
  const { selector, checked, index = 0 } = params || {};
  if (!selector) throw new Error("set_checked requires a selector");
  if (typeof checked !== "boolean") throw new Error("set_checked requires a boolean checked value");
  const sel = JSON.stringify(selector);
  const itemIndex = Math.max(0, Number(index) || 0);
  const expression = `document.querySelectorAll(${sel})[${itemIndex}]`;
  const before = await checkedElementState(tab.id, expression);
  if (!before?.exists) throw new Error(`No element for selector ${selector} (index ${index})`);
  if (!before.supported) throw new Error("Element is not a checkbox, radio, switch, or ARIA toggle");
  if (before.disabled) throw new Error("Element is disabled");
  if (before.checked === checked) {
    return { success: true, selector, checked, changed: false };
  }

  const center = await elementCenter(tab.id, expression);
  if (!center) throw new Error(`Element ${selector} is not visible`);
  await clickAt(tab.id, center.x, center.y);

  let after = null;
  for (let attempt = 0; attempt < 6; attempt++) {
    after = await checkedElementState(tab.id, expression);
    if (after?.checked === checked) break;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  if (after?.checked !== checked) {
    throw new Error(`Element remained checked=${after?.checked}; requested checked=${checked}`);
  }
  return { success: true, selector, checked, changed: true };
}

async function cmdDrag(params) {
  const tab = await resolveTab(params);
  const {
    source_selector,
    target_selector,
    source_index = 0,
    target_index = 0,
    steps = 10,
  } = params || {};
  if (!source_selector || !target_selector) {
    throw new Error("drag requires source_selector and target_selector");
  }
  const sourceSel = JSON.stringify(source_selector);
  const targetSel = JSON.stringify(target_selector);
  const sourceIndex = Math.max(0, Number(source_index) || 0);
  const targetIndex = Math.max(0, Number(target_index) || 0);
  const points = await evalInPage(
    tab.id,
    `(() => {
      const source = document.querySelectorAll(${sourceSel})[${sourceIndex}];
      const target = document.querySelectorAll(${targetSel})[${targetIndex}];
      if (!source || !target) return { error: "source or target element not found" };
      source.scrollIntoView({ block: "center", inline: "center" });
      const point = (el) => {
        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return null;
        const x = rect.left + rect.width / 2, y = rect.top + rect.height / 2;
        if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) return null;
        return { x, y };
      };
      const from = point(source), to = point(target);
      if (!from || !to) return { error: "source and target must both be visible in the viewport" };
      return { from, to };
    })()`
  );
  if (points?.error) throw new Error(points.error);

  const moveSteps = Math.max(2, Math.min(50, Number(steps) || 10));
  let current = points.from;
  await cdpSend(tab.id, "Input.dispatchMouseEvent", {
    type: "mouseMoved", x: current.x, y: current.y,
  });
  await cdpSend(tab.id, "Input.dispatchMouseEvent", {
    type: "mousePressed", x: current.x, y: current.y, button: "left", buttons: 1, clickCount: 1,
  });
  try {
    const dragPath = humanPointerPath(points.from, points.to, moveSteps);
    for (let step = 0; step < dragPath.length; step++) {
      current = dragPath[step];
      await cdpSend(tab.id, "Input.dispatchMouseEvent", {
        type: "mouseMoved", x: current.x, y: current.y, button: "left", buttons: 1,
      });
      if (step < dragPath.length - 1) {
        await new Promise((resolve) => setTimeout(resolve, Math.max(8, current.delayMs || 16)));
      }
    }
  } finally {
    await cdpSend(tab.id, "Input.dispatchMouseEvent", {
      type: "mouseReleased", x: current.x, y: current.y, button: "left", buttons: 0, clickCount: 1,
    });
  }
  return { success: true, source_selector, target_selector, from: points.from, to: points.to };
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
  const snapshot = await evalInPage(
    tab.id,
    `(() => {
      const MAX = ${max};
      const SEL = [
        "a[href]", "area[href]", "button", "input:not([type=hidden])", "select", "textarea", "summary",
        "[role=button]", "[role=link]", "[role=tab]", "[role=menuitem]", "[role=menuitemcheckbox]",
        "[role=menuitemradio]", "[role=checkbox]", "[role=radio]", "[role=switch]", "[role=combobox]",
        "[role=listbox]", "[role=option]", "[role=slider]", "[role=spinbutton]", "[role=textbox]",
        "[role=searchbox]", "[role=treeitem]", "[contenteditable=true]", "[tabindex]:not([tabindex='-1'])", "[onclick]",
      ].join(",");
      const normalize = (value) => String(value || "").replace(/\\s+/g, " ").trim();
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
      function inferredRole(el) {
        const explicit = el.getAttribute("role");
        if (explicit) return explicit;
        const tag = el.tagName.toLowerCase();
        if (tag === "a" || tag === "area") return "link";
        if (tag === "button" || tag === "summary") return "button";
        if (tag === "textarea" || el.isContentEditable) return "textbox";
        if (tag === "select") return el.multiple ? "listbox" : "combobox";
        if (tag !== "input") return tag;
        const inputRoles = {
          button: "button", submit: "button", reset: "button", image: "button",
          checkbox: "checkbox", radio: "radio", range: "slider", number: "spinbutton",
          search: "searchbox",
        };
        return inputRoles[el.type] || "textbox";
      }
      function accessibleName(el) {
        const aria = normalize(el.getAttribute("aria-label"));
        if (aria) return aria;
        const labelledBy = normalize(el.getAttribute("aria-labelledby"));
        if (labelledBy) {
          const value = normalize(labelledBy.split(/\\s+/).map((id) => document.getElementById(id)?.textContent).join(" "));
          if (value) return value;
        }
        const labels = el.labels ? normalize([...el.labels].map((label) => label.innerText || label.textContent).join(" ")) : "";
        if (labels) return labels;
        return normalize(
          el.getAttribute("alt") || el.getAttribute("title") || el.getAttribute("placeholder") ||
          el.innerText || ((el.type === "button" || el.type === "submit") ? el.value : "")
        );
      }
      function controlState(el) {
        const state = {};
        if ("disabled" in el || el.hasAttribute("aria-disabled")) {
          state.disabled = Boolean(el.disabled) || el.getAttribute("aria-disabled") === "true";
        }
        if ("checked" in el || el.hasAttribute("aria-checked")) {
          const aria = el.getAttribute("aria-checked");
          state.checked = aria === "mixed" ? "mixed" : (aria ? aria === "true" : Boolean(el.checked));
        }
        if ("selected" in el || el.hasAttribute("aria-selected")) {
          const aria = el.getAttribute("aria-selected");
          state.selected = aria ? aria === "true" : Boolean(el.selected);
        }
        for (const key of ["expanded", "pressed"]) {
          const value = el.getAttribute("aria-" + key);
          if (value != null) state[key] = value === "mixed" ? "mixed" : value === "true";
        }
        if ("required" in el || el.hasAttribute("aria-required")) {
          state.required = Boolean(el.required) || el.getAttribute("aria-required") === "true";
        }
        if ("readOnly" in el && el.readOnly) state.readonly = true;
        return state;
      }
      const out = [];
      for (const el of document.querySelectorAll(SEL)) {
        if (out.length >= MAX) break;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        const s = getComputedStyle(el);
        if (s.visibility === "hidden" || s.display === "none" || s.opacity === "0") continue;
        const isPassword = el instanceof HTMLInputElement && el.type === "password";
        const text = normalize(el.innerText || (isPassword ? "" : el.value)).slice(0, 120);
        const attributes = {};
        if (el.type) attributes.type = el.type;
        if (el.href) attributes.href = el.href;
        if (el.getAttribute("placeholder")) attributes.placeholder = el.getAttribute("placeholder");
        if (!isPassword && "value" in el && el.value) attributes.value = String(el.value).slice(0, 120);
        out.push({
          role: inferredRole(el),
          text,
          name: accessibleName(el).slice(0, 120),
          selector: cssPath(el),
          state: controlState(el),
          attributes,
          box: { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2), w: Math.round(r.width), h: Math.round(r.height) },
        });
      }
      return {
        url: location.href,
        title: document.title,
        viewport: {
          width: innerWidth,
          height: innerHeight,
          scrollX: Math.round(scrollX),
          scrollY: Math.round(scrollY),
        },
        elements: out,
      };
    })()`
  );
  return { success: true, ...(snapshot || {}), elements: snapshot?.elements || [] };
}

async function cmdStatus() {
  const tab = await getActiveTab();
  return {
    success: true,
    connected: true,
    agent_control_active: Boolean(tab?.id != null && agentControlOverlays.has(tab.id)),
    active_tab: tab ? {
      id: tab.id,
      url: tab.url || "",
      title: tab.title || "",
    } : null,
  };
}

// ── Tab info broadcasting ────────────────────────────────────────────────────

function tabSummary(tab, index) {
  return {
    index,
    id: tab.id,
    window_id: tab.windowId,
    url: tab.url || tab.pendingUrl || "",
    title: tab.title || "",
    active: tab.active,
    pinned: tab.pinned,
    group_id: Number.isInteger(tab.groupId) ? tab.groupId : -1,
  };
}

async function broadcastTabInfo() {
  const sock = ws;
  if (!sock || sock.readyState !== WebSocket.OPEN) return;

  try {
    const [activeTabs, tabs] = await Promise.all([
      chrome.tabs.query({ active: true, currentWindow: true }),
      chrome.tabs.query({}),
    ]);
    if (ws !== sock || sock.readyState !== WebSocket.OPEN) return;
    const activeTab = activeTabs[0] || null;
    sock.send(JSON.stringify({
      type: "event",
      event: "tab_updated",
      data: {
        url: activeTab?.url || activeTab?.pendingUrl || "",
        title: activeTab?.title || "",
        tabs: tabs.map(tabSummary),
      },
    }));
  } catch (e) {
    console.warn("[WebBridge] Failed to broadcast tab state:", e.message);
  }
}

// Keep backend policy/status accurate for both active and background tabs.
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading") {
    // The old document (and its injected overlay) is being replaced.
    agentControlOverlays.delete(tabId);
    overlayCaptureSuspensions.delete(tabId);
    agentPointerPositions.delete(tabId);
    activePageDialogs.delete(tabId);
  }
  if (changeInfo.url || changeInfo.status === "loading") {
    rotateTabPageInstance(tabId).catch((error) => {
      console.warn("[WebBridge] Failed to rotate Side Chat page identity:", error.message);
    });
  }
  if (changeInfo.url) {
    stopDiagnosticCapture(tabId).catch((error) => {
      console.warn("[WebBridge] Failed to stop issue collection after navigation:", error.message);
    });
    cancelTextWatchesForTab(tabId, changeInfo.url).catch((error) => {
      console.warn("[WebBridge] Failed to update text watch scope:", error.message);
    });
    clearPickedElement(tabId).catch((error) => {
      console.warn("[WebBridge] Failed to clear picked element after navigation:", error.message);
    });
    clearRegionCapture(tabId).catch((error) => {
      console.warn("[WebBridge] Failed to clear region capture after navigation:", error.message);
    });
  }
  handleTeachTabUpdate(tabId, changeInfo).catch((error) => {
    console.warn("[WebBridge] Failed to update Teach Mode scope:", error.message);
  });
  if (changeInfo.url) {
    humanLeaseForTab({ id: tabId, url: changeInfo.url }).catch((error) => {
      console.warn("[WebBridge] Failed to validate human control scope:", error.message);
    });
  }
  if (changeInfo.url || changeInfo.title || changeInfo.status === "complete") {
    broadcastTabInfo();
    notifyAutomationState("tab_updated", tabId);
  }
  if (changeInfo.status === "complete" && attachedTabs.has(tabId)) {
    chrome.tabs.get(tabId).then(async (tab) => {
      if (!await humanLeaseForTab(tab)) await setAgentControlOverlay(tabId, true);
    }).catch(() => {});
  }
  if (changeInfo.status === "complete") {
    restoreTextWatchObservers(tabId).catch((error) => {
      console.warn("[WebBridge] Failed to restore real-time text watch:", error.message);
    });
  }
});

chrome.tabs.onActivated.addListener(({ tabId }) => {
  broadcastTabInfo();
  notifyAutomationState("active_tab", tabId);
});

chrome.tabs.onCreated.addListener(() => {
  broadcastTabInfo();
});

chrome.tabs.onMoved.addListener(() => {
  broadcastTabInfo();
});

// ── Message handlers (Side Chat and content scripts) ─────────────────────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "get_browser_dialog") {
    (async () => {
      const tab = msg.tab_id != null ? await chrome.tabs.get(msg.tab_id) : await getActiveTab();
      sendResponse({
        ok: true,
        dialog: tab?.id == null ? null : activePageDialogs.get(tab.id) || null,
      });
    })().catch((e) => sendResponse({ ok: false, error: e.message }));
    return true;
  }

  if (msg.type === "handle_browser_dialog") {
    (async () => {
      const tab = msg.tab_id != null ? await chrome.tabs.get(msg.tab_id) : await getActiveTab();
      if (!tab?.id) throw new Error("No active browser tab");
      sendResponse({
        ok: true,
        ...(await handlePageDialogForTab(tab.id, {
          accept: Boolean(msg.accept),
          prompt_text: msg.prompt_text,
        })),
      });
    })().catch((e) => sendResponse({ ok: false, error: e.message }));
    return true;
  }

  if (msg.type === "region_selected") {
    (async () => {
      try {
        if (!sender.tab || sender.tab.id == null || (sender.frameId != null && sender.frameId !== 0)) {
          throw new Error("Screen regions must come from the top frame of a browser tab.");
        }
        const tab = await chrome.tabs.get(sender.tab.id);
        const capture = await captureSelectedRegion(tab, msg.selection);
        sendResponse({ ok: true, capture });
        chrome.runtime.sendMessage({ type: "region_capture_ready", capture }).catch(() => {});
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
        chrome.runtime.sendMessage({ type: "region_capture_error", error: e.message }).catch(() => {});
      }
    })();
    return true;
  }

  if (msg.type === "region_picker_cancelled") {
    chrome.runtime.sendMessage({ type: "region_capture_cancelled", reason: msg.reason || null }).catch(() => {});
    sendResponse({ ok: true });
    return true;
  }

  if (msg.type === "element_picked") {
    (async () => {
      try {
        if (!sender.tab || sender.tab.id == null) {
          throw new Error("Picked elements must come from a browser tab.");
        }
        const tab = await chrome.tabs.get(sender.tab.id);
        const element = await savePickedElement(tab, msg.element);
        sendResponse({ ok: true, element });
        chrome.runtime.sendMessage({
          type: "element_picker_state",
          active: false,
          tab_id: tab.id,
        }).catch(() => {});
        chrome.runtime.sendMessage({ type: "element_picker_result", element }).catch(() => {});
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "element_picker_cancelled") {
    chrome.runtime.sendMessage({
      type: "element_picker_state",
      active: false,
      tab_id: sender.tab?.id,
    }).catch(() => {});
    sendResponse({ ok: true });
    return true;
  }

  if (msg.type === "teach_action") {
    (async () => {
      try {
        if (!sender.tab || sender.tab.id == null) {
          throw new Error("Teach actions must come from the recorded browser tab.");
        }
        const tab = await chrome.tabs.get(sender.tab.id);
        const recording = await recordTeachAction(tab, msg.action, sender.url || "");
        sendResponse({ ok: true, recording });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "get_status") {
    (async () => {
      const [tabs, stored, watches, recording, pendingInteraction] = await Promise.all([
        chrome.tabs.query({ active: true, currentWindow: true }),
        chrome.storage.local.get(["lastInteraction", "lastTeachDraft"]),
        readTextWatches(),
        readTeachRecording(),
        readPendingInteraction(),
      ]);
      const activeTab = tabs[0] || null;
      const humanLease = await humanLeaseForTab(activeTab);
      sendResponse({
        connected: connected,
        connecting: connectInFlight || Boolean(ws && ws.readyState === WebSocket.CONNECTING),
        extension_id: extensionId,
        active_tab: activeTab ? { id: activeTab.id, url: activeTab.url, title: activeTab.title } : null,
        attached_tab_ids: [...attachedTabs.keys()],
        visual_control_tab_ids: [...agentControlOverlays],
        last_close_reason: lastCloseReason,
        relay_base: relayBase,
        connection_mode: connectionMode,
        native_error: nativeDiscoveryError || null,
        paired: Boolean(pairingCredential && pairingId),
        pairing_id: pairingId || null,
        last_interaction: stored.lastInteraction || null,
        pending_interaction: pendingInteraction,
        text_watches: watches.map(textWatchSummary),
        teach_recording: teachRecordingSummary(recording),
        last_teach_draft: stored.lastTeachDraft || null,
        human_control_lease: humanLeaseSummary(humanLease),
      });
    })().catch((e) => sendResponse({ ok: false, error: e.message }));
    return true; // async sendResponse
  }

  if (msg.type === "toggle_connection") {
    if (connected || connectInFlight || (ws && ws.readyState === WebSocket.CONNECTING)) {
      disconnect();
    } else {
      manualDisconnect = false;
      connect();
    }
    sendResponse({ ok: true });
    return true;
  }

  if (msg.type === "ensure_connection") {
    (async () => {
      try {
        await loadConfig();
        await discoverNativeConnection();
        await ensureConnectionCredential();
        sendResponse({ ok: true });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "webbridge_text_watch_matched") {
    (async () => {
      try {
        const matched = await markTextWatchMatched(msg.watch_id, sender.tab, msg.page_url);
        sendResponse({ ok: true, matched });
        if (matched) {
          notifyAutomationState("text_watch", matched.tab_id);
        }
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "release_debuggers") {
    (async () => {
      try {
        const released = await detachAllDebuggers();
        sendResponse({ ok: true, released });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "release_browser_control") {
    (async () => {
      try {
        sendResponse({ ok: true, ...(await releaseBrowserControlToHuman(msg.tab_id)) });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "start_element_picker") {
    (async () => {
      try {
        sendResponse({ ok: true, ...(await startElementPicker(await getActiveTab())) });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "cancel_element_picker") {
    (async () => {
      try {
        sendResponse({ ok: true, cancelled: await cancelElementPicker(await getActiveTab()) });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "get_picked_element") {
    (async () => {
      try {
        const tab = await getActiveTab();
        sendResponse({ ok: true, element: tab?.id == null ? null : await pickedElementForTab(tab.id) });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "clear_picked_element") {
    (async () => {
      try {
        const tab = await getActiveTab();
        sendResponse({ ok: true, cleared: tab?.id == null ? false : await clearPickedElement(tab.id) });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "start_region_picker") {
    (async () => {
      try {
        sendResponse({ ok: true, ...(await startRegionPicker(await getActiveTab())) });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "get_region_capture") {
    (async () => {
      try {
        const tab = await getActiveTab();
        sendResponse({ ok: true, capture: tab?.id == null ? null : await regionCaptureForTab(tab.id) });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "clear_region_capture") {
    (async () => {
      try {
        const tab = await getActiveTab();
        sendResponse({ ok: true, cleared: tab?.id == null ? false : await clearRegionCapture(tab.id) });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "capture_panel_context") {
    (async () => {
      try {
        const tab = await getActiveTab();
        sendResponse({ ok: true, context: await capturePanelContext(tab, msg.kind) });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "start_issue_capture") {
    (async () => {
      try {
        sendResponse({ ok: true, capture: await startDiagnosticCapture(await getActiveTab()) });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "stop_issue_capture") {
    (async () => {
      try {
        const tab = await getActiveTab();
        sendResponse({ ok: true, stopped: tab?.id == null ? false : await stopDiagnosticCapture(tab.id) });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "get_issue_capture") {
    (async () => {
      try {
        const tab = await getActiveTab();
        sendResponse({ ok: true, capture: tab?.id == null ? null : diagnosticSummary(activeDiagnosticCapture(tab.id)) });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "collect_issue_report") {
    (async () => {
      try {
        const tab = await getActiveTab();
        sendResponse({ ok: true, report: await collectIssueReport(tab) });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "take_human_control") {
    (async () => {
      try {
        const tab = msg.tab_id != null ? await chrome.tabs.get(msg.tab_id) : await getActiveTab();
        sendResponse({ ok: true, lease: await takeHumanControlLease(tab) });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "release_human_control") {
    (async () => {
      try {
        const tab = msg.tab_id != null ? await chrome.tabs.get(msg.tab_id) : await getActiveTab();
        sendResponse({ ok: true, released: await releaseHumanControlLease(tab?.id ?? null) });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "get_human_control") {
    (async () => {
      try {
        const tab = msg.tab_id != null ? await chrome.tabs.get(msg.tab_id) : await getActiveTab();
        sendResponse({ ok: true, lease: humanLeaseSummary(await humanLeaseForTab(tab)) });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "ensure_browser_session_for_tab") {
    (async () => {
      try {
        const tab = await getActiveTab();
        if (!tab || tab.id == null) throw new Error("No active tab");
        const pageUrl = tab.url || tab.pendingUrl || "";
        const context = await ensureSessionContextForTab(tab, pageUrl);
        sendResponse({
          ok: true,
          ...context,
          session: context.session || null,
          tab: {
            id: tab.id,
            title: tab.title || "",
            url: pageUrl,
            group_id: Number.isInteger(tab.groupId) ? tab.groupId : -1,
          },
        });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "open_grouped_session_tab") {
    (async () => {
      try {
        const tab = await getActiveTab();
        if (!tab || tab.id == null) throw new Error("No active tab");
        const pageUrl = tab.url || tab.pendingUrl || "";
        const context = await ensureSessionContextForTab(tab, pageUrl);
        if (context.session_id !== msg.session_id) {
          throw new Error("This tab is not part of that browser session.");
        }
        const primaryTab = await chrome.tabs.get(context.binding_tab_id);
        sendResponse({ ok: true, ...(await createGroupedSessionTab(primaryTab, msg.session_id)) });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "start_teach_recording") {
    (async () => {
      try {
        const tab = await getActiveTab();
        const recording = await startTeachRecording(tab, msg.session_id);
        sendResponse({ ok: true, recording });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "stop_teach_recording") {
    (async () => {
      try {
        sendResponse({ ok: true, draft: await finishTeachRecording() });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "cancel_teach_recording") {
    (async () => {
      try {
        sendResponse({ ok: true, cancelled: await cancelTeachRecording() });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "arm_text_watch") {
    (async () => {
      try {
        const tab = await getActiveTab();
        const watch = await armTextWatch(
          tab,
          msg.session_id,
          msg.needle,
          msg.ttl_minutes,
        );
        sendResponse({ ok: true, watch });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "cancel_text_watch") {
    (async () => {
      try {
        sendResponse({ ok: true, cancelled: await cancelTextWatch(msg.watch_id) });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "cancel_all_text_watches") {
    (async () => {
      try {
        sendResponse({ ok: true, cancelled: await cancelAllTextWatches() });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "send_matched_text_watch") {
    (async () => {
      try {
        const result = await sendMatchedTextWatch(msg.watch_id);
        sendResponse({ ok: true, result });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "retry_pending_interaction") {
    (async () => {
      try {
        const result = await retryPendingInteraction();
        sendResponse({ ok: true, result });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }
});

// ── Initialize ───────────────────────────────────────────────────────────────

chrome.runtime.onStartup.addListener(() => {
  console.log("[WebBridge] Browser startup — reconnecting...");
  configureSidePanel().catch((e) => {
    console.warn("[WebBridge] Side Panel setup failed:", e.message);
  });
  connect();
});

chrome.runtime.onInstalled.addListener(() => {
  setupContextMenus().catch((e) => console.warn("[WebBridge] Context menu setup failed:", e));
  configureSidePanel().catch((e) => {
    console.warn("[WebBridge] Side Panel setup failed:", e.message);
  });
  console.log("[WebBridge] Extension installed/updated — connecting...");
  connect();
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (![MENU_SELECTION_ID, MENU_LINK_ID, MENU_PAGE_ID].includes(info.menuItemId)) return;
  sendContextMenuInteraction(info, tab).catch((e) => {
    console.warn("[WebBridge] Context menu interaction failed:", e.message);
    chrome.storage.local.set({
      lastInteraction: { status: "rejected", error: e.message, created_at: Date.now() },
    });
  });
});

// Idempotent: guarantees the worker always has a wake-up scheduled, even
// after Chrome kills and revives the service worker.
ensureHeartbeatAlarm();
ensureTextWatchAlarm();
readPendingInteraction().catch((e) => {
  console.warn("[WebBridge] Failed to purge pending browser context:", e.message);
});
restoreTextWatchObservers().catch((e) => {
  console.warn("[WebBridge] Failed to restore real-time text watches:", e.message);
});
configureSidePanel().catch((e) => {
  console.warn("[WebBridge] Side Panel setup failed:", e.message);
});

console.log("[WebBridge] Extension loaded, connecting...");
connect();
