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
const RELAY_TICKET_PATH = "/api/team/webbridge/relay-ticket";
const PAIRING_EXCHANGE_PATH = "/api/team/webbridge/pairing/exchange";
const LOCAL_PAIRING_PATH = "/api/team/webbridge/pairing/local";
const BROWSER_SESSIONS_PATH = "/api/team/webbridge/sessions";
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
let pairingCredential = "";
let pairingId = "";
let pairingRelayBase = "";
let connectInFlight = false;

const COMMAND_CAPABILITIES = [
  "navigate", "click", "dblclick", "type", "key", "scroll", "screenshot",
  "extract", "get_tabs", "switch_tab", "evaluate", "back", "forward",
  "reload", "wait", "wait_for_selector", "wait_for_text", "wait_for_load",
  "wait_for_network_idle", "click_selector", "click_text", "hover", "focus",
  "select_option", "set_checked", "drag", "fill", "open_tab", "close_tab",
  "snapshot", "extract_elements", "scroll_to_bottom", "status",
];

// ── Config (persisted in chrome.storage.local, edited via the popup) ─────────

async function loadConfig() {
  try {
    const cfg = await chrome.storage.local.get([
      "relayBase", "accessToken", "extensionId", "pairingCredential", "pairingId",
      "pairingRelayBase",
    ]);
    relayBase = (cfg.relayBase || DEFAULT_RELAY_BASE).trim().replace(/\/+$/, "");
    accessToken = (cfg.accessToken || "").trim();
    pairingCredential = (cfg.pairingCredential || "").trim();
    pairingId = (cfg.pairingId || "").trim();
    pairingRelayBase = (cfg.pairingRelayBase || "").trim().replace(/\/+$/, "");
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

function canonicalRelayBase() {
  return (relayBase || DEFAULT_RELAY_BASE)
    .trim()
    .replace(/\/+$/, "")
    .replace(/^http/i, "ws");
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

function buildHttpUrl(path) {
  const base = (relayBase || DEFAULT_RELAY_BASE)
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

async function readTextWatches() {
  const stored = await chrome.storage.local.get([TEXT_WATCH_STORAGE_KEY]);
  const watches = Array.isArray(stored[TEXT_WATCH_STORAGE_KEY])
    ? stored[TEXT_WATCH_STORAGE_KEY]
    : [];
  const live = watches.filter((watch) => isLiveTextWatch(watch));
  if (live.length !== watches.length) {
    for (const watch of watches) {
      if (!isLiveTextWatch(watch)) clearWatchMatch(watch.tab_id);
    }
    await chrome.storage.local.set({ [TEXT_WATCH_STORAGE_KEY]: live });
  }
  return live;
}

async function writeTextWatches(watches) {
  await chrome.storage.local.set({ [TEXT_WATCH_STORAGE_KEY]: watches });
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
  const watches = await readTextWatches();
  const currentPageUrl = currentUrl == null ? null : safePageUrl(currentUrl);
  const retained = watches.filter((watch) => {
    if (watch.tab_id !== tabId) return true;
    return currentPageUrl !== null && watch.page_url === currentPageUrl;
  });
  if (retained.length !== watches.length) {
    await writeTextWatches(retained);
    clearWatchMatch(tabId);
  }
}

async function watchTextPresent(tabId, needle) {
  const results = await chrome.scripting.executeScript({
    target: { tabId },
    args: [needle],
    func: (expected) => {
      const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
      const root = document.body || document.documentElement;
      return normalize(root?.innerText || root?.textContent || "").includes(normalize(expected));
    },
  });
  return results.some((result) => result?.result === true);
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
  const watches = await readTextWatches();
  const retained = watches.filter((watch) => watch.tab_id !== tab.id);
  if (retained.length >= MAX_TEXT_WATCHES) {
    throw new Error(`WebBridge can keep at most ${MAX_TEXT_WATCHES} active watches.`);
  }
  const watch = {
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
  await writeTextWatches([...retained, watch]);
  clearWatchMatch(tab.id);
  ensureTextWatchAlarm();
  return textWatchSummary(watch);
}

async function cancelTextWatch(watchId) {
  const watches = await readTextWatches();
  const watch = watches.find((entry) => entry.id === watchId);
  if (!watch) return false;
  await writeTextWatches(watches.filter((entry) => entry.id !== watchId));
  clearWatchMatch(watch.tab_id);
  return true;
}

async function pollTextWatches() {
  const watches = await readTextWatches();
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
}

async function sendMatchedTextWatch(watchId) {
  const watches = await readTextWatches();
  const watch = watches.find((entry) => entry.id === watchId);
  if (!watch || watch.state !== "matched") {
    throw new Error("This text watch is no longer ready to send.");
  }
  let tab;
  try {
    tab = await chrome.tabs.get(watch.tab_id);
  } catch {
    await cancelTextWatch(watch.id);
    throw new Error("The watched tab was closed.");
  }
  const pageUrl = requireBrowserPageUrl(tab.url || tab.pendingUrl || "");
  if (pageUrl !== watch.page_url) {
    await cancelTextWatch(watch.id);
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
  await cancelTextWatch(watch.id);
  return result;
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

async function listBrowserSessions() {
  const response = await pairingFetch(BROWSER_SESSIONS_PATH);
  return response.json();
}

async function createBrowserSession(title, actionId) {
  const response = await pairingFetch(BROWSER_SESSIONS_PATH, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": `${actionId}:session`,
    },
    body: JSON.stringify({ title }),
  });
  return response.json();
}

async function listTabBindings() {
  const response = await pairingFetch(BINDINGS_PATH);
  return response.json();
}

async function bindTabToSession(tab, sessionId, pageUrl) {
  const origin = browserOrigin(pageUrl);
  if (!origin) throw new Error("Browser context can only be sent from an HTTP(S) page.");
  const response = await pairingFetch(`${BINDINGS_PATH}/${encodeURIComponent(tab.id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      origin,
      page_instance_id: `${tab.id}:${pageUrl || ""}`.slice(0, 128),
    }),
  });
  return response.json();
}

async function ensureSessionForTab(tab, pageUrl, actionId) {
  const bindings = await listTabBindings();
  const binding = bindings.find((item) => item.tab_id === tab.id);
  if (binding && binding.origin === browserOrigin(pageUrl)) return binding.session_id;

  const label = boundedText(tab.title) || browserOrigin(pageUrl) || "Browser page";
  const session = await createBrowserSession(
    `Browser: ${label}`.slice(0, 255),
    actionId,
  );
  await bindTabToSession(tab, session.id, pageUrl);
  return session.id;
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
    : await ensureSessionForTab(tab, pageUrl, requestId);
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

async function sendContextMenuInteraction(info, tab) {
  if (!tab || tab.id == null) throw new Error("No browser tab available");
  return submitBrowserContext(tab, contextMenuPayload(info, tab));
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
  if (!pairingCredential) return buildRelayUrl();
  if (!pairingRelayBase || pairingRelayBase !== canonicalRelayBase()) {
    const error = new Error("The relay URL changed. Pair WebBridge with this relay again.");
    error.code = "pairing";
    throw error;
  }

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

async function pairWithCode(code) {
  await loadConfig();
  assertRelayTransportSecure();
  const response = await fetch(buildHttpUrl(PAIRING_EXCHANGE_PATH), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      code: String(code || "").trim(),
      browser: detectBrowser(),
      version: chrome.runtime.getManifest().version,
    }),
  });
  if (!response.ok) {
    throw new Error(await responseError(response, "Pairing code rejected"));
  }
  const body = await response.json();
  if (!body?.credential || !body?.pairing_id) {
    throw new Error("Pairing response was incomplete");
  }
  await persistPairing(body);
  return { pairing_id: pairingId, scopes: body.scopes || [] };
}

async function persistPairing(body) {
  if (!body?.credential || !body?.pairing_id) {
    throw new Error("Pairing response was incomplete");
  }
  pairingCredential = body.credential;
  pairingId = body.pairing_id;
  pairingRelayBase = canonicalRelayBase();
  accessToken = "";
  await chrome.storage.local.set({
    pairingCredential,
    pairingId,
    pairingRelayBase,
    accessToken: "",
  });
}

async function pairLocally() {
  await loadConfig();
  assertRelayTransportSecure();
  const parsed = new URL(canonicalRelayBase());
  if (!["localhost", "127.0.0.1", "::1"].includes(parsed.hostname.toLowerCase())) {
    throw new Error("Code-free pairing is only available for a loopback EvoFlux relay.");
  }
  const response = await fetch(buildHttpUrl(LOCAL_PAIRING_PATH), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      label: `${detectBrowser() === "edge" ? "Edge" : "Chrome"} on this device`,
      browser: detectBrowser(),
      version: chrome.runtime.getManifest().version,
    }),
  });
  if (!response.ok) {
    throw new Error(await responseError(response, "Local pairing was rejected"));
  }
  const body = await response.json();
  await persistPairing(body);
  return { pairing_id: pairingId, scopes: body.scopes || [] };
}

// ── Connection management ────────────────────────────────────────────────────

async function connect() {
  if (connectInFlight || (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING))) return;

  connectInFlight = true;
  await loadConfig();
  manualDisconnect = false;

  let sock;
  try {
    sock = new WebSocket(await buildAuthenticatedRelayUrl());
  } catch (e) {
    connectInFlight = false;
    if (e.code === "pairing") {
      await clearRevokedPairingState();
      manualDisconnect = true;
    }
    if (e.code === "relay_security") manualDisconnect = true;
    lastCloseReason = e.code === "pairing" ? "pairing" : e.code === "relay_security" ? "security" : "closed";
    console.error("[WebBridge] Connection setup failed:", e);
    if (!manualDisconnect) scheduleReconnect();
    return;
  }
  ws = sock;
  connectInFlight = false;

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
      protocol_version: 2,
      extension_id: extensionId,
      client_instance_id: extensionId,
      browser: detectBrowser(),
      version: chrome.runtime.getManifest().version,
      capabilities: {
        commands: COMMAND_CAPABILITIES,
        interactions: ["context.share", "prompt.submit"],
        captures: ["selection", "link", "page_metadata"],
        ui: ["popup", "side_panel"],
        handoff: ["ask_user_reply", "human_control_lease"],
        automation: ["teach_mode", "text_watch"],
      },
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
    if (event.code === 4403) {
      manualDisconnect = true;
      clearRevokedPairingState().catch((error) => {
        console.warn("[WebBridge] Pairing cleanup failed:", error.message);
      });
    }
    // 4401 = relay rejected the access token — surface it in the popup.
    lastCloseReason = event.code === 4403 ? "pairing" : event.code === 4401 ? "auth" : "closed";
    if (!manualDisconnect) scheduleReconnect();
  };

  sock.onerror = (e) => {
    console.error("[WebBridge] WebSocket error:", e);
  };
}

async function clearRevokedPairingState() {
  pairingCredential = "";
  pairingId = "";
  pairingRelayBase = "";
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
  clearTimeout(reconnectTimer);
  if (ws) {
    try { ws.close(); } catch { /* already closed */ }
    ws = null;
  }
  connected = false;
  detachAllDebuggers().catch((e) => {
    console.warn("[WebBridge] Failed to release browser control:", e.message);
  });
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
  return humanLeaseSummary(lease);
}

async function releaseHumanControlLease(tabId = null) {
  const leases = await readHumanControlLeases();
  if (tabId == null) {
    if (!Object.keys(leases).length) return false;
    await humanLeaseStorage().remove([HUMAN_LEASE_STORAGE_KEY]);
    return true;
  }
  if (!leases[tabId]) return false;
  delete leases[tabId];
  if (Object.keys(leases).length) {
    await humanLeaseStorage().set({ [HUMAN_LEASE_STORAGE_KEY]: leases });
  } else {
    await humanLeaseStorage().remove([HUMAN_LEASE_STORAGE_KEY]);
  }
  return true;
}

async function configureSidePanel() {
  if (!chrome.sidePanel?.setPanelBehavior) return;
  await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: false });
}

async function openSidePanelForActiveTab() {
  if (!chrome.sidePanel?.open) {
    throw new Error("Chrome Side Panel is unavailable in this browser.");
  }
  const tab = await getActiveTab();
  if (!tab || tab.id == null) throw new Error("No active tab");
  await chrome.sidePanel.open({ tabId: tab.id });
  return { tab_id: tab.id };
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
  await chrome.tabs.sendMessage(tab.id, { type: "webbridge_element_picker", enabled: true });
  return { tab_id: tab.id };
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

  // Use CDP Input.dispatchMouseEvent
  await cdpSend(tab.id, "Input.dispatchMouseEvent", {
    type: "mousePressed",
    x,
    y,
    button: resolvedButton,
    clickCount: 1,
  });
  await cdpSend(tab.id, "Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x,
    y,
    button: resolvedButton,
    clickCount: 1,
  });

  return { success: true, x, y, button: resolvedButton };
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
  await chrome.tabs.goBack(tab.id);
  await broadcastTabInfo();
  return { success: true };
}

async function cmdForward(params) {
  const tab = await resolveTab(params);
  await chrome.tabs.goForward(tab.id);
  await broadcastTabInfo();
  return { success: true };
}

async function cmdReload(params) {
  const tab = await resolveTab(params);
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
    for (let step = 1; step <= moveSteps; step++) {
      current = {
        x: points.from.x + (points.to.x - points.from.x) * step / moveSteps,
        y: points.from.y + (points.to.y - points.from.y) * step / moveSteps,
      };
      await cdpSend(tab.id, "Input.dispatchMouseEvent", {
        type: "mouseMoved", x: current.x, y: current.y, button: "left", buttons: 1,
      });
      await new Promise((resolve) => setTimeout(resolve, 16));
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
  if (changeInfo.url) {
    cancelTextWatchesForTab(tabId, changeInfo.url).catch((error) => {
      console.warn("[WebBridge] Failed to update text watch scope:", error.message);
    });
    clearPickedElement(tabId).catch((error) => {
      console.warn("[WebBridge] Failed to clear picked element after navigation:", error.message);
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
  }
});

chrome.tabs.onActivated.addListener(() => {
  broadcastTabInfo();
});

chrome.tabs.onCreated.addListener(() => {
  broadcastTabInfo();
});

chrome.tabs.onMoved.addListener(() => {
  broadcastTabInfo();
});

// ── Message handlers (popup communication) ───────────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "element_picked") {
    (async () => {
      try {
        if (!sender.tab || sender.tab.id == null) {
          throw new Error("Picked elements must come from a browser tab.");
        }
        const tab = await chrome.tabs.get(sender.tab.id);
        const element = await savePickedElement(tab, msg.element);
        sendResponse({ ok: true, element });
        chrome.runtime.sendMessage({ type: "element_picker_result", element }).catch(() => {});
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
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
        extension_id: extensionId,
        active_tab: activeTab ? { id: activeTab.id, url: activeTab.url, title: activeTab.title } : null,
        attached_tab_ids: [...attachedTabs.keys()],
        last_close_reason: lastCloseReason,
        relay_base: relayBase,
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

  if (msg.type === "pair_with_code") {
    (async () => {
      try {
        const result = await pairWithCode(msg.code);
        disconnect();
        manualDisconnect = false;
        connect();
        sendResponse({ ok: true, ...result });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "pair_locally") {
    (async () => {
      try {
        const result = await pairLocally();
        disconnect();
        manualDisconnect = false;
        connect();
        sendResponse({ ok: true, ...result });
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

  if (msg.type === "open_side_panel") {
    (async () => {
      try {
        sendResponse({ ok: true, ...(await openSidePanelForActiveTab()) });
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

  if (msg.type === "take_human_control") {
    (async () => {
      try {
        sendResponse({ ok: true, lease: await takeHumanControlLease(await getActiveTab()) });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "release_human_control") {
    (async () => {
      try {
        const tab = await getActiveTab();
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
        sendResponse({ ok: true, lease: humanLeaseSummary(await humanLeaseForTab(await getActiveTab())) });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "get_browser_sessions") {
    (async () => {
      try {
        const sessions = await listBrowserSessions();
        const bindings = await listTabBindings();
        sendResponse({
          ok: true,
          sessions: Array.isArray(sessions) ? sessions : (sessions.data || []),
          bindings,
        });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "bind_tab_session") {
    (async () => {
      try {
        const tab = await getActiveTab();
        if (!tab || tab.id == null) throw new Error("No active tab");
        const binding = await bindTabToSession(
          tab,
          msg.session_id,
          tab.url || tab.pendingUrl || ""
        );
        sendResponse({ ok: true, binding });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "send_page_prompt") {
    (async () => {
      try {
        const tab = await getActiveTab();
        if (!tab || tab.id == null) throw new Error("No active tab");
        const result = await submitBrowserContext(tab, {
          context_type: "page_metadata",
          prompt: boundedText(msg.prompt) || "Help me understand this browser page.",
          metadata: {
            page_url: safePageUrl(tab.url || tab.pendingUrl || ""),
            page_title: boundedText(tab.title),
          },
        }, msg.session_id || null);
        sendResponse({ ok: true, result });
      } catch (e) {
        sendResponse({ ok: false, error: e.message });
      }
    })();
    return true;
  }

  if (msg.type === "create_browser_session") {
    (async () => {
      try {
        const tab = await getActiveTab();
        if (!tab || tab.id == null) throw new Error("No active tab");
        const pageUrl = requireBrowserPageUrl(tab.url || tab.pendingUrl || "");
        const label = boundedText(tab.title) || browserOrigin(pageUrl) || "Browser page";
        const actionId = msg.action_id || interactionId();
        const session = await createBrowserSession(
          `Browser: ${label}`.slice(0, 255),
          actionId,
        );
        await bindTabToSession(tab, session.id, pageUrl);
        sendResponse({ ok: true, session });
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
configureSidePanel().catch((e) => {
  console.warn("[WebBridge] Side Panel setup failed:", e.message);
});

console.log("[WebBridge] Extension loaded, connecting...");
connect();
