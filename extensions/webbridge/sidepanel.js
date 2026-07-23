/* EvoFlux WebBridge P2 Side Panel.
 *
 * The panel is an extension page, so it may safely read the pairing credential
 * from extension storage. It only sends that credential in Authorization
 * headers to the relay it was paired with; never in URLs or page contexts.
 */

const DEFAULT_RELAY_BASE = "ws://127.0.0.1:8000";
const SESSIONS_PATH = "/api/team/webbridge/sessions";
const BINDINGS_PATH = "/api/team/webbridge/bindings";
const MODELS_PATH = "/api/team/webbridge/models";
const THEME_STORAGE_KEY = "webbridgeSideChatTheme";

const sessionTitle = document.getElementById("sessionTitle");
const pageTitle = document.getElementById("pageTitle");
const statusDot = document.getElementById("statusDot");
const stopBtn = document.getElementById("stopBtn");
const settingsBtn = document.getElementById("settingsBtn");
const settingsBackdrop = document.getElementById("settingsBackdrop");
const settingsDrawer = document.getElementById("settingsDrawer");
const closeSettingsBtn = document.getElementById("closeSettingsBtn");
const refreshBtn = document.getElementById("refreshBtn");
const newGroupedTabBtn = document.getElementById("newGroupedTabBtn");
const pickElementBtn = document.getElementById("pickElementBtn");
const takeControlBtn = document.getElementById("takeControlBtn");
const resumeAgentBtn = document.getElementById("resumeAgentBtn");
const bindingStatus = document.getElementById("bindingStatus");
const contextDetail = document.getElementById("contextDetail");
const pickedElementCard = document.getElementById("pickedElementCard");
const pickedElementLabel = document.getElementById("pickedElementLabel");
const clearElementBtn = document.getElementById("clearElementBtn");
const notice = document.getElementById("notice");
const transcript = document.getElementById("transcript");
const questionsRoot = document.getElementById("questions");
const composer = document.getElementById("composer");
const sendBtn = document.getElementById("sendBtn");
const composerStatus = document.getElementById("composerStatus");
const modelTrigger = document.getElementById("modelTrigger");
const modelLabel = document.getElementById("modelLabel");
const modelPopover = document.getElementById("modelPopover");
const modelSearch = document.getElementById("modelSearch");
const modelList = document.getElementById("modelList");
const activity = document.getElementById("activity");
const activityLabel = document.getElementById("activityLabel");
const activityDetail = document.getElementById("activityDetail");
const relayBaseInput = document.getElementById("relayBaseInput");
const saveConnectionBtn = document.getElementById("saveConnectionBtn");
const toggleConnectionBtn = document.getElementById("toggleConnectionBtn");
const settingsStatusDot = document.getElementById("settingsStatusDot");
const settingsStatusText = document.getElementById("settingsStatusText");
const settingsStatusDetail = document.getElementById("settingsStatusDetail");
const pairingSettings = document.getElementById("pairingSettings");
const pairLocalBtn = document.getElementById("pairLocalBtn");
const pairingCodeInput = document.getElementById("pairingCodeInput");
const pairCodeBtn = document.getElementById("pairCodeBtn");
const pairingSettingsDetail = document.getElementById("pairingSettingsDetail");
const themeControl = document.getElementById("themeControl");
const watchNeedleInput = document.getElementById("watchNeedleInput");
const watchTtlSelect = document.getElementById("watchTtlSelect");
const watchActionBtn = document.getElementById("watchActionBtn");
const watchSettingsDetail = document.getElementById("watchSettingsDetail");
const teachActionBtn = document.getElementById("teachActionBtn");
const discardTeachBtn = document.getElementById("discardTeachBtn");
const teachSettingsDetail = document.getElementById("teachSettingsDetail");
const retryContextBtn = document.getElementById("retryContextBtn");
const releaseControlBtn = document.getElementById("releaseControlBtn");
const newConversationBtn = document.getElementById("newConversationBtn");

let relayBase = DEFAULT_RELAY_BASE;
let pairingCredential = "";
let pairingRelayBase = "";
let activeTab = null;
let sessions = [];
let bindings = [];
let selectedSessionId = "";
let primaryBinding = null;
let activeTabIsGroupedChild = false;
let streamController = null;
let streamGeneration = 0;
let refreshGeneration = 0;
let liveMessage = null;
let pendingQuestions = new Map();
let humanControlLease = null;
let pendingComposerRequest = null;
let pickedElement = null;
let composerSending = false;
let activeTextWatch = null;
let activeTeachRecording = null;
let browserModels = [];
let currentSessionModel = null;
let modelCatalogLoaded = false;
let modelCatalogLoading = false;
let elementPickerActive = false;
let nextAutoBindActionId = "";
let markdownRenderTimer = null;
let transcriptPinned = true;
const agentStates = new Map();
const toolActivities = new Map();
const PANEL_REQUEST_STORAGE_KEY = "webbridgePanelPendingRequest";
let themePreference = "system";

const LOADING_VERBS = [
  "Brewing", "Cogitating", "Ideating", "Musing", "Percolating", "Pondering", "Tinkering", "Weaving",
];
let loadingVerbIndex = Math.floor(Math.random() * LOADING_VERBS.length);

function applyTheme(theme) {
  themePreference = ["light", "dark"].includes(theme) ? theme : "system";
  if (themePreference === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = themePreference;
  for (const button of themeControl.querySelectorAll("button")) {
    button.classList.toggle("active", button.dataset.themeValue === themePreference);
  }
}

async function initializeTheme() {
  const stored = await chrome.storage.local.get([THEME_STORAGE_KEY]);
  themePreference = ["system", "light", "dark"].includes(stored[THEME_STORAGE_KEY])
    ? stored[THEME_STORAGE_KEY]
    : "system";
  applyTheme(themePreference);
}

async function setTheme(theme) {
  applyTheme(theme);
  await chrome.storage.local.set({ [THEME_STORAGE_KEY]: themePreference });
}

function canonicalRelayBase() {
  return (relayBase || DEFAULT_RELAY_BASE)
    .trim()
    .replace(/\/+$/, "")
    .replace(/^http/i, "ws");
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

function hasPageTools(tab = activeTab) {
  return Boolean(browserOrigin(tab?.url || tab?.pendingUrl || ""));
}

function panelHttpBase() {
  const base = (relayBase || DEFAULT_RELAY_BASE)
    .trim()
    .replace(/\/+$/, "")
    .replace(/^ws:/i, "http:")
    .replace(/^wss:/i, "https:");
  let parsed;
  try {
    parsed = new URL(base);
  } catch {
    throw new Error("Relay URL is invalid");
  }
  const loopback = ["localhost", "127.0.0.1", "::1"].includes(parsed.hostname.toLowerCase());
  if (parsed.protocol !== "https:" && !loopback) {
    throw new Error("Remote Side Panel relays require HTTPS/WSS");
  }
  return base;
}

function panelSessionStorage() {
  return chrome.storage.session || chrome.storage.local;
}

async function sha256(value) {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function loadConfig() {
  const cfg = await chrome.storage.local.get([
    "relayBase",
    "pairingCredential",
    "pairingRelayBase",
  ]);
  relayBase = (cfg.relayBase || DEFAULT_RELAY_BASE).trim().replace(/\/+$/, "");
  pairingCredential = (cfg.pairingCredential || "").trim();
  pairingRelayBase = (cfg.pairingRelayBase || "").trim().replace(/\/+$/, "");
  if (!pairingCredential || pairingRelayBase !== canonicalRelayBase()) {
    throw new Error("Pair WebBridge with this relay before opening the Side Panel.");
  }
  let parsed;
  try {
    parsed = new URL(canonicalRelayBase());
  } catch {
    throw new Error("Relay URL is invalid");
  }
  if (!["ws:", "wss:"].includes(parsed.protocol)) {
    throw new Error("Relay URL must use ws, wss, http, or https");
  }
  const loopback = ["localhost", "127.0.0.1", "::1"].includes(parsed.hostname.toLowerCase());
  if (parsed.protocol === "ws:" && !loopback) {
    throw new Error("Remote Side Panel relays require HTTPS/WSS");
  }
}

async function panelFetch(path, options = {}) {
  await loadConfig();
  const response = await fetch(`${panelHttpBase()}${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${pairingCredential}`,
      ...(options.headers || {}),
    },
  });
  if (response.ok) return response;
  let message = `WebBridge request failed: ${response.status}`;
  try {
    const body = await response.json();
    const detail = body?.detail;
    message = detail?.message || (typeof detail === "string" ? detail : message);
  } catch {
    // Keep the status fallback for non-JSON response bodies.
  }
  throw new Error(message);
}

async function currentTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || tab.id == null) throw new Error("No active browser tab");
  return tab;
}

function selectedBinding() {
  return primaryBinding || bindings.find((binding) => binding.tab_id === activeTab?.id) || null;
}

function isBoundToSelectedSession() {
  const binding = selectedBinding();
  return Boolean(
    binding &&
    binding.session_id === selectedSessionId &&
    (activeTabIsGroupedChild || binding.origin === browserTabScope(activeTab))
  );
}

function setNotice(message, tone = "info") {
  notice.textContent = message;
  notice.className = `notice visible ${tone}`;
}

function clearNotice() {
  notice.textContent = "";
  notice.className = "notice";
}

function setComposerStatus(message = "", tone = "") {
  composerStatus.textContent = message;
  composerStatus.className = `composer-status ${tone}`.trim();
}

function setControlsDisabled(disabled) {
  refreshBtn.disabled = disabled;
  newGroupedTabBtn.disabled = disabled;
  pickElementBtn.disabled = disabled;
  takeControlBtn.disabled = disabled;
  resumeAgentBtn.disabled = disabled;
  composer.disabled = disabled;
  sendBtn.disabled = disabled;
  stopBtn.disabled = disabled;
  modelTrigger.disabled = disabled || !selectedSessionId;
}

function renderPickedElement() {
  const active = pickedElement?.tab_id === activeTab?.id;
  pickedElementCard.style.display = active ? "flex" : "none";
  pickedElementLabel.textContent = active
    ? `${pickedElement.name || pickedElement.text || pickedElement.selector}`
    : "";
  pickElementBtn.classList.toggle("active", active || elementPickerActive);
  pickElementBtn.title = active ? "Pick another element" : elementPickerActive ? "Element picker active" : "Pick an element from this page";
  pickElementBtn.setAttribute("aria-label", pickElementBtn.title);
}

function browserPanelElement(element, tabId) {
  if (!element || element.tab_id !== tabId) return null;
  return {
    page_url: element.page_url || "",
    selector: element.selector || "",
    tag: element.tag || "",
    role: element.role || "",
    name: element.name || "",
    text: element.text || "",
  };
}

function shortModelName(modelId) {
  const value = String(modelId || "");
  const separator = value.indexOf(":");
  return separator >= 0 ? value.slice(separator + 1) : value;
}

function renderModelTrigger(session = null) {
  if (session) currentSessionModel = session.model || null;
  const label = currentSessionModel ? shortModelName(currentSessionModel) : "Model";
  modelLabel.textContent = label;
  modelTrigger.title = currentSessionModel || "Use the lead agent's default model";
  modelTrigger.disabled = !selectedSessionId;
}

function closeModelPicker() {
  modelPopover.classList.remove("visible");
  modelTrigger.setAttribute("aria-expanded", "false");
}

function renderModelOptions(query = "") {
  const normalized = query.trim().toLowerCase();
  const visible = browserModels.filter((entry) => (
    !normalized || entry.id.toLowerCase().includes(normalized)
  )).slice(0, 60);
  modelList.replaceChildren();

  const appendOption = (model, label, detail) => {
    const option = document.createElement("button");
    option.type = "button";
    option.className = "model-option";
    option.dataset.modelId = model || "";
    option.setAttribute("role", "option");
    option.setAttribute("aria-selected", String((model || null) === currentSessionModel));
    const copy = document.createElement("span");
    copy.className = "model-option-copy";
    const name = document.createElement("strong");
    name.textContent = label;
    const meta = document.createElement("span");
    meta.textContent = detail;
    copy.append(name, meta);
    option.append(copy);
    modelList.append(option);
  };

  if (!normalized || "default lead model".includes(normalized)) {
    appendOption(null, "Default", "Use the lead agent model");
  }
  for (const entry of visible) {
    appendOption(entry.id, entry.model || shortModelName(entry.id), entry.provider || "Configured model");
  }
  if (!modelList.childElementCount) {
    const empty = document.createElement("div");
    empty.className = "model-empty";
    empty.textContent = modelCatalogLoading ? "Loading models…" : "No models found";
    modelList.append(empty);
  }
}

async function loadBrowserModels() {
  if (modelCatalogLoaded || modelCatalogLoading) return;
  modelCatalogLoading = true;
  renderModelOptions(modelSearch.value);
  try {
    const response = await panelFetch(MODELS_PATH);
    browserModels = await response.json();
    modelCatalogLoaded = true;
  } catch (error) {
    setComposerStatus(error.message || String(error), "error");
  } finally {
    modelCatalogLoading = false;
    renderModelOptions(modelSearch.value);
  }
}

async function openModelPicker() {
  if (!selectedSessionId) return;
  const open = !modelPopover.classList.contains("visible");
  if (!open) {
    closeModelPicker();
    return;
  }
  modelPopover.classList.add("visible");
  modelTrigger.setAttribute("aria-expanded", "true");
  renderModelOptions(modelSearch.value);
  await loadBrowserModels();
  modelSearch.focus();
}

async function selectSessionModel(model) {
  if (!selectedSessionId) return;
  modelTrigger.disabled = true;
  try {
    const response = await panelFetch(
      `${SESSIONS_PATH}/${encodeURIComponent(selectedSessionId)}/model`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: model || null }),
      }
    );
    const session = await response.json();
    currentSessionModel = session.model || null;
    const existing = sessions.find((item) => item.id === selectedSessionId);
    if (existing) existing.model = currentSessionModel;
    renderModelTrigger(session);
    setComposerStatus(currentSessionModel ? `Using ${shortModelName(currentSessionModel)}.` : "Using the lead agent's default model.");
    closeModelPicker();
  } catch (error) {
    setComposerStatus(error.message || String(error), "error");
  } finally {
    modelTrigger.disabled = false;
  }
}

async function refreshPickedElement() {
  const response = await chrome.runtime.sendMessage({ type: "get_picked_element" });
  if (!response?.ok) throw new Error(response?.error || "Could not read picked element");
  pickedElement = response.element || null;
  renderPickedElement();
}

function renderHumanControl() {
  const active = humanControlLease?.tab_id === selectedBinding()?.tab_id;
  takeControlBtn.style.display = active ? "none" : "inline-flex";
  resumeAgentBtn.style.display = active ? "inline-flex" : "none";
  if (active) contextDetail.textContent = "Agent paused — you control this tab";
  else if (activeTab) {
    contextDetail.textContent = browserOrigin(activeTab.url || activeTab.pendingUrl || "")
      || "Browser tools activate on HTTP(S) pages";
  }
}

async function refreshHumanControl() {
  const response = await chrome.runtime.sendMessage({
    type: "get_human_control",
    tab_id: selectedBinding()?.tab_id,
  });
  if (!response?.ok) throw new Error(response?.error || "Could not read human control state");
  humanControlLease = response.lease || null;
  renderHumanControl();
}

function renderBindingStatus() {
  const bound = isBoundToSelectedSession();
  const pageTools = hasPageTools();
  newGroupedTabBtn.disabled = !bound;
  composer.disabled = !bound;
  sendBtn.disabled = !bound || composerSending;
  pickElementBtn.disabled = !bound || !pageTools;
  takeControlBtn.disabled = !bound || !pageTools;
  if (bound) {
    bindingStatus.textContent = activeTabIsGroupedChild
      ? "Session group tab"
      : pageTools
        ? "Connected to this tab"
        : "Chat connected to this tab";
    contextDetail.textContent = activeTabIsGroupedChild
      ? "Agent defaults to the primary tab"
      : browserOrigin(activeTab?.url || activeTab?.pendingUrl || "")
        || "Browser tools activate on HTTP(S) pages";
    return;
  }
  bindingStatus.textContent = "Preparing browser session";
  contextDetail.textContent = "This happens automatically";
}

function clearTranscript() {
  transcript.replaceChildren();
  liveMessage = null;
}

function scrollTranscriptToEnd() {
  if (!transcriptPinned) return;
  requestAnimationFrame(() => { transcript.scrollTop = transcript.scrollHeight; });
}

function appendMessage(message, { live = false } = {}) {
  const empty = transcript.querySelector(".empty");
  if (empty) empty.remove();
  const item = document.createElement("article");
  item.className = `message ${message.role === "user" ? "user" : "assistant"}${live ? " live" : ""}`;
  const meta = document.createElement("span");
  meta.className = "message-meta";
  meta.textContent = message.role === "user" ? "You" : (message.agent || "EvoFlux");
  const content = document.createElement("div");
  content.className = "message-body";
  const rawContent = message.content || "";
  if (message.role === "assistant" && globalThis.WebBridgeMarkdown) {
    globalThis.WebBridgeMarkdown.render(content, rawContent);
  } else {
    content.textContent = rawContent;
  }
  item.append(meta, content);
  transcript.append(item);
  scrollTranscriptToEnd();
  return { item, content, rawContent };
}

function showEmptyTranscript(text) {
  clearTranscript();
  const empty = document.createElement("div");
  empty.className = "empty";
  empty.textContent = text;
  transcript.append(empty);
}

async function loadHistory() {
  if (!selectedSessionId) {
    showEmptyTranscript("EvoFlux will create a conversation for this tab.");
    return;
  }
  const response = await panelFetch(
    `${SESSIONS_PATH}/${encodeURIComponent(selectedSessionId)}/history?limit=100`
  );
  const body = await response.json();
  clearTranscript();
  if (!body.messages?.length) {
    showEmptyTranscript("No messages yet. Send a question from the Side Panel.");
    return;
  }
  for (const message of body.messages) appendMessage(message);
}

function renderQuestions() {
  questionsRoot.replaceChildren();
  const questions = [...pendingQuestions.values()];
  questionsRoot.classList.toggle("visible", questions.length > 0);
  for (const request of questions) {
    const card = document.createElement("article");
    card.className = "question-card";
    const inputs = [];
    request.questions.forEach((question, index) => {
      const prompt = document.createElement("p");
      prompt.textContent = question.question || `Question ${index + 1}`;
      card.append(prompt);
      const input = document.createElement("textarea");
      input.className = "answer";
      input.placeholder = "Your answer";
      input.setAttribute("aria-label", `Answer ${index + 1}`);
      card.append(input);
      inputs.push(input);
      if (Array.isArray(question.options) && question.options.length) {
        const options = document.createElement("div");
        options.className = "options";
        for (const optionText of question.options) {
          const option = document.createElement("button");
          option.type = "button";
          option.className = "option";
          option.textContent = optionText;
          option.addEventListener("click", () => { input.value = optionText; input.focus(); });
          options.append(option);
        }
        card.append(options);
      }
    });
    const reply = document.createElement("button");
    reply.type = "button";
    reply.className = "btn primary";
    reply.textContent = "Reply";
    reply.addEventListener("click", () => void submitQuestion(request, inputs, reply));
    card.append(reply);
    questionsRoot.append(card);
  }
}

async function loadPendingQuestions() {
  pendingQuestions.clear();
  if (!selectedSessionId) {
    renderQuestions();
    return;
  }
  const response = await panelFetch(
    `${SESSIONS_PATH}/${encodeURIComponent(selectedSessionId)}/questions/pending`
  );
  const body = await response.json();
  for (const request of body.questions || []) pendingQuestions.set(request.request_id, request);
  renderQuestions();
}

async function submitQuestion(request, inputs, button) {
  const answers = inputs.map((input) => input.value.trim());
  if (answers.some((answer) => !answer)) {
    setNotice("Answer every question before replying.", "error");
    return;
  }
  button.disabled = true;
  try {
    await panelFetch(
      `${SESSIONS_PATH}/${encodeURIComponent(selectedSessionId)}/questions/${encodeURIComponent(request.request_id)}/reply`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_session_id: request.session_id, answers }),
      }
    );
    pendingQuestions.delete(request.request_id);
    renderQuestions();
    clearNotice();
  } catch (error) {
    setNotice(error.message || String(error), "error");
  } finally {
    button.disabled = false;
  }
}

async function ensureAutoSession(tab) {
  const stableActionId = `side-chat-${await sha256(String(tab.id))}`;
  const response = await chrome.runtime.sendMessage({
    type: "ensure_browser_session_for_tab",
    action_id: nextAutoBindActionId || stableActionId,
  });
  nextAutoBindActionId = "";
  if (!response?.ok) throw new Error(response?.error || "Could not prepare a browser session");
  if (response.tab?.id !== tab.id) throw new Error("The active browser tab changed while Side Chat was loading.");
  return response;
}

async function refreshPanel({ preserveTranscript = false } = {}) {
  const generation = ++refreshGeneration;
  setControlsDisabled(true);
  try {
    await loadConfig();
    const nextTab = await currentTab();
    if (activeTab && activeTab.id !== nextTab.id) stopStream();
    activeTab = nextTab;
    pageTitle.textContent = activeTab.title || safePageUrl(activeTab.url || activeTab.pendingUrl || "") || "Side Chat";
    const ensured = await ensureAutoSession(activeTab);
    if (generation !== refreshGeneration) return;
    selectedSessionId = ensured.session_id;
    activeTabIsGroupedChild = Boolean(ensured.grouped);
    const [sessionResponse, bindingResponse] = await Promise.all([
      panelFetch(SESSIONS_PATH),
      panelFetch(BINDINGS_PATH),
    ]);
    if (generation !== refreshGeneration) return;
    sessions = await sessionResponse.json();
    bindings = await bindingResponse.json();
    primaryBinding = bindings.find((binding) => (
      binding.tab_id === ensured.binding_tab_id && binding.session_id === selectedSessionId
    )) || null;
    const session = sessions.find((item) => item.id === selectedSessionId) || ensured.session;
    sessionTitle.textContent = session?.title || "Browser conversation";
    renderModelTrigger(session);
    renderBindingStatus();
    await refreshHumanControl();
    await refreshPickedElement();
    if (generation !== refreshGeneration) return;
    statusDot.className = "status-dot live";
    clearNotice();
    if (!preserveTranscript) await loadHistory();
    await loadPendingQuestions();
    if (sessions.find((session) => session.id === selectedSessionId)?.running) {
      startStream();
    }
  } catch (error) {
    if (generation !== refreshGeneration) return;
    statusDot.className = "status-dot error";
    setNotice(error.message || String(error), "error");
    showEmptyTranscript("Side Chat could not prepare this browser tab. Open Settings to check the WebBridge connection.");
  } finally {
    if (generation !== refreshGeneration) return;
    setControlsDisabled(false);
    renderBindingStatus();
  }
}

async function startFreshConversation() {
  if (!activeTab?.id) return;
  setControlsDisabled(true);
  try {
    await panelFetch(`${BINDINGS_PATH}/${encodeURIComponent(activeTab.id)}`, { method: "DELETE" });
    stopStream();
    selectedSessionId = "";
    primaryBinding = null;
    activeTabIsGroupedChild = false;
    currentSessionModel = null;
    renderModelTrigger();
    nextAutoBindActionId = `side-chat-fresh-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    closeSettings();
    await refreshPanel();
  } catch (error) {
    setNotice(error.message || String(error), "error");
  } finally {
    setControlsDisabled(false);
  }
}

async function takeHumanControl() {
  if (!hasPageTools()) {
    setComposerStatus("Browser control is available after this tab opens an HTTP(S) page.");
    return;
  }
  setControlsDisabled(true);
  try {
    const response = await chrome.runtime.sendMessage({
      type: "take_human_control",
      tab_id: selectedBinding()?.tab_id,
    });
    if (!response?.ok) throw new Error(response?.error || "Could not take control of this tab");
    humanControlLease = response.lease || null;
    renderHumanControl();
    clearNotice();
  } catch (error) {
    setNotice(error.message || String(error), "error");
  } finally {
    setControlsDisabled(false);
  }
}

async function resumeAgent() {
  setControlsDisabled(true);
  try {
    const response = await chrome.runtime.sendMessage({
      type: "release_human_control",
      tab_id: selectedBinding()?.tab_id,
    });
    if (!response?.ok) throw new Error(response?.error || "Could not resume agent control");
    humanControlLease = null;
    renderHumanControl();
    clearNotice();
  } catch (error) {
    setNotice(error.message || String(error), "error");
  } finally {
    setControlsDisabled(false);
  }
}

async function startElementPicker() {
  if (!hasPageTools()) {
    setComposerStatus("Element picker is available after this tab opens an HTTP(S) page.");
    return;
  }
  pickElementBtn.disabled = true;
  try {
    const response = await chrome.runtime.sendMessage({ type: "start_element_picker" });
    if (!response?.ok) throw new Error(response?.error || "Could not start element picker");
    elementPickerActive = true;
    renderPickedElement();
    clearNotice();
    setComposerStatus("Picker active on the page · click an element or press Escape.");
  } catch (error) {
    elementPickerActive = false;
    renderPickedElement();
    setComposerStatus(error.message || String(error), "error");
  } finally {
    pickElementBtn.disabled = false;
  }
}

async function clearElement() {
  const response = await chrome.runtime.sendMessage({ type: "clear_picked_element" });
  if (!response?.ok) {
    setNotice(response?.error || "Could not clear picked element", "error");
    return;
  }
  pickedElement = null;
  renderPickedElement();
}

function stopStream() {
  streamGeneration += 1;
  streamController?.abort();
  streamController = null;
  clearTimeout(markdownRenderTimer);
  markdownRenderTimer = null;
  liveMessage = null;
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function readSse(response, onEvent) {
  if (!response.body) throw new Error("Side Panel stream has no body");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventType = "";
  let eventData = "";
  const dispatch = () => {
    if (!eventData) return;
    try { onEvent(eventType, JSON.parse(eventData)); } catch { /* Ignore malformed frame. */ }
    eventType = "";
    eventData = "";
  };
  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      if (buffer.trim()) {
        const line = buffer.trimEnd();
        if (line.startsWith("data:")) eventData = line.slice(5).trim();
      }
      dispatch();
      return;
    }
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const raw of lines) {
      const line = raw.trimEnd();
      if (!line) { dispatch(); continue; }
      if (line.startsWith("event:")) eventType = line.slice(6).trim();
      if (line.startsWith("data:")) eventData = eventData ? `${eventData}\n${line.slice(5).trim()}` : line.slice(5).trim();
    }
  }
}

function friendlyToolName(name) {
  return String(name || "tool")
    .replace(/^mcp__/, "")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function renderActivity() {
  const runningTool = [...toolActivities.values()].find((entry) => entry.state !== "done");
  const workingAgent = [...agentStates.entries()].find(([, state]) => state === "working");
  const working = Boolean(runningTool || workingAgent);
  activity.classList.toggle("visible", working);
  stopBtn.style.display = working ? "inline-flex" : "none";
  if (!working) return;
  if (runningTool) {
    activityLabel.textContent = friendlyToolName(runningTool.name);
    activityDetail.textContent = `${runningTool.agent || "EvoFlux"} is running a tool`;
    return;
  }
  activityLabel.textContent = LOADING_VERBS[loadingVerbIndex];
  activityDetail.textContent = `${workingAgent[0] || "EvoFlux"} is working`;
}

function scheduleLiveMarkdownRender() {
  if (!liveMessage || markdownRenderTimer) return;
  markdownRenderTimer = setTimeout(() => {
    markdownRenderTimer = null;
    if (!liveMessage) return;
    globalThis.WebBridgeMarkdown?.render(liveMessage.content, liveMessage.rawContent);
    scrollTranscriptToEnd();
  }, 80);
}

function flushLiveMarkdownRender() {
  clearTimeout(markdownRenderTimer);
  markdownRenderTimer = null;
  if (!liveMessage) return;
  globalThis.WebBridgeMarkdown?.render(liveMessage.content, liveMessage.rawContent);
  scrollTranscriptToEnd();
}

function handleStreamEvent(type, data) {
  if (type === "message") {
    const agent = data.agent || "EvoFlux";
    if (!liveMessage || liveMessage.agent !== agent) {
      flushLiveMarkdownRender();
      liveMessage = { agent, ...appendMessage({ role: "assistant", agent, content: "" }, { live: true }) };
    }
    liveMessage.rawContent += data.text || "";
    scheduleLiveMarkdownRender();
    return;
  }
  if (type === "agent_status") {
    agentStates.set(data.agent || "EvoFlux", data.status || "idle");
    if (data.status !== "working") {
      for (const [key, entry] of toolActivities) {
        if (!data.agent || entry.agent === data.agent) toolActivities.delete(key);
      }
    }
    renderActivity();
    return;
  }
  if (type === "activity") {
    const key = data.id || `${data.agent || "EvoFlux"}:${data.name || "tool"}`;
    if (data.state === "done") toolActivities.delete(key);
    else toolActivities.set(key, data);
    renderActivity();
    return;
  }
  if (type === "question_asked") {
    pendingQuestions.set(data.request_id, {
      request_id: data.request_id,
      session_id: data.session_id,
      questions: data.questions || [],
    });
    renderQuestions();
    return;
  }
  if (type === "error") {
    agentStates.clear();
    toolActivities.clear();
    renderActivity();
    setNotice(data.message || "EvoFlux stream failed.", "error");
    return;
  }
  if (type === "done") {
    flushLiveMarkdownRender();
    agentStates.clear();
    toolActivities.clear();
    renderActivity();
    return;
  }
  if (type === "title_update" && data.title) {
    pageTitle.textContent = data.title;
  }
}

async function runStream(sessionId, generation) {
  let attempts = 0;
  while (generation === streamGeneration && attempts < 30) {
    try {
      if (selectedSessionId !== sessionId) return;
      // The stream store replays the complete accumulated assistant text.
      // Rebuild from durable history before every attachment so reconnects
      // replace, rather than append to, the previous live replay. Refreshing
      // questions here also closes the disconnect gap while AskUser is waiting.
      liveMessage = null;
      await loadHistory();
      await loadPendingQuestions();
      if (generation !== streamGeneration || selectedSessionId !== sessionId) return;
      streamController = new AbortController();
      const response = await panelFetch(
        `${SESSIONS_PATH}/${encodeURIComponent(sessionId)}/stream`,
        { signal: streamController.signal }
      );
      let sawDone = false;
      let sawEvent = false;
      await readSse(response, (type, data) => {
        sawEvent = true;
        handleStreamEvent(type, data);
        if (type === "done") sawDone = true;
      });
      if (generation === streamGeneration) streamController = null;
      if (generation !== streamGeneration) return;
      if (sawDone || !sawEvent) {
        flushLiveMarkdownRender();
        liveMessage = null;
        await loadHistory();
        await loadPendingQuestions();
        return;
      }
    } catch (error) {
      if (generation === streamGeneration) streamController = null;
      if (error.name === "AbortError" || generation !== streamGeneration) return;
      if (attempts === 29) setNotice(error.message || String(error), "error");
    }
    attempts += 1;
    await delay(300);
  }
  if (generation === streamGeneration) {
    flushLiveMarkdownRender();
    liveMessage = null;
    await loadHistory();
    await loadPendingQuestions();
  }
}

function startStream() {
  if (!selectedSessionId || streamController) return;
  stopStream();
  const generation = streamGeneration;
  void runStream(selectedSessionId, generation);
}

async function sendMessage() {
  if (composerSending) return;
  const content = composer.value.trim();
  const sourceScope = browserTabScope(activeTab);
  if (!content || !selectedSessionId || !activeTab?.id) return;
  if (!isBoundToSelectedSession()) {
    setNotice("Bind this tab to the selected session before sending a message.", "error");
    return;
  }
  composerSending = true;
  sendBtn.disabled = true;
  setComposerStatus("Sending...");
  try {
    const element = browserPanelElement(pickedElement, activeTab.id);
    const elementKey = element
      ? `${element.page_url}:${element.selector}`
      : "";
    const requestShape = await sha256(
      `${selectedSessionId}:${activeTab.id}:${sourceScope}:${content}:${elementKey}`
    );
    if (!pendingComposerRequest) {
      const stored = await panelSessionStorage().get([PANEL_REQUEST_STORAGE_KEY]);
      pendingComposerRequest = stored[PANEL_REQUEST_STORAGE_KEY] || null;
    }
    if (!pendingComposerRequest || pendingComposerRequest.shape !== requestShape) {
      pendingComposerRequest = {
        shape: requestShape,
        id: globalThis.crypto?.randomUUID?.() || `panel-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      };
      await panelSessionStorage().set({ [PANEL_REQUEST_STORAGE_KEY]: pendingComposerRequest });
    }
    const response = await panelFetch(
      `${SESSIONS_PATH}/${encodeURIComponent(selectedSessionId)}/messages`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": pendingComposerRequest.id,
        },
        body: JSON.stringify({
          content,
          tab_id: activeTab.id,
          binding_tab_id: selectedBinding()?.tab_id || activeTab.id,
          origin: sourceScope,
          user_gesture: true,
          element,
        }),
      }
    );
    const result = await response.json();
    if (result.status !== "pending") {
      pendingComposerRequest = null;
      await panelSessionStorage().remove([PANEL_REQUEST_STORAGE_KEY]);
      composer.value = "";
      resizeComposer();
    }
    if (result.status === "pending") {
      setComposerStatus("Delivery is pending. Send again to retry safely.");
      return;
    }
    if (pickedElement?.tab_id === activeTab.id) {
      await clearElement();
    }
    appendMessage({ role: "user", content });
    setComposerStatus(result.status === "queued" ? "Queued behind the current turn." : "EvoFlux is responding.");
    agentStates.set("EvoFlux", "working");
    renderActivity();
    startStream();
  } catch (error) {
    stopStream();
    setComposerStatus(error.message || String(error), "error");
  } finally {
    composerSending = false;
    sendBtn.disabled = false;
  }
}

async function stopRun() {
  if (!selectedSessionId) {
    setNotice("No browser conversation is active on this tab.", "error");
    return;
  }
  stopBtn.disabled = true;
  try {
    await panelFetch(
      `${SESSIONS_PATH}/${encodeURIComponent(selectedSessionId)}/interrupt`,
      { method: "POST" }
    );
    stopStream();
    agentStates.clear();
    toolActivities.clear();
    renderActivity();
    setComposerStatus("Run stopped.");
    await loadHistory();
    await loadPendingQuestions();
  } catch (error) {
    setNotice(error.message || String(error), "error");
  } finally {
    stopBtn.disabled = false;
  }
}

function openSettings() {
  settingsBackdrop.classList.add("visible");
  settingsDrawer.classList.add("visible");
  settingsDrawer.removeAttribute("inert");
  settingsDrawer.setAttribute("aria-hidden", "false");
  void refreshSettings();
}

function closeSettings() {
  settingsBackdrop.classList.remove("visible");
  settingsDrawer.classList.remove("visible");
  settingsDrawer.setAttribute("inert", "");
  settingsDrawer.setAttribute("aria-hidden", "true");
}

async function refreshSettings() {
  try {
    const [config, response] = await Promise.all([
      chrome.storage.local.get(["relayBase"]),
      chrome.runtime.sendMessage({ type: "get_status" }),
    ]);
    if (document.activeElement !== relayBaseInput) relayBaseInput.value = config.relayBase || DEFAULT_RELAY_BASE;
    const connected = Boolean(response?.connected);
    settingsStatusDot.className = `status-dot ${connected ? "live" : "error"}`;
    settingsStatusText.textContent = connected ? "Connected" : "Disconnected";
    settingsStatusDetail.textContent = connected
      ? `Secure pairing ${response.pairing_id || "active"}`
      : response?.last_close_reason === "pairing"
        ? "Pairing was rejected or revoked."
        : "Reconnect or pair this extension to continue.";
    toggleConnectionBtn.textContent = connected ? "Disconnect" : "Reconnect";
    pairingSettings.style.display = response?.paired ? "none" : "block";
    activeTextWatch = (response?.text_watches || []).find((item) => item.tab_id === activeTab?.id) || null;
    if (activeTextWatch?.state === "matched") {
      watchActionBtn.textContent = "Send match";
      watchSettingsDetail.textContent = `Matched “${activeTextWatch.needle}”. Nothing is sent until you confirm.`;
    } else if (activeTextWatch) {
      watchActionBtn.textContent = "Cancel watch";
      watchSettingsDetail.textContent = `Watching for “${activeTextWatch.needle}”.`;
    } else {
      watchActionBtn.textContent = "Start watch";
      watchSettingsDetail.textContent = "A match stays private until you send it.";
    }
    const pageTools = hasPageTools();
    watchNeedleInput.disabled = Boolean(activeTextWatch) || !pageTools;
    watchTtlSelect.disabled = Boolean(activeTextWatch) || !pageTools;
    watchActionBtn.disabled = !selectedSessionId || !pageTools;
    if (!pageTools) {
      watchSettingsDetail.textContent = "Available after this tab opens an HTTP(S) page.";
    }
    activeTeachRecording = response?.teach_recording || null;
    const teachingThisTab = activeTeachRecording?.tab_id === activeTab?.id;
    teachActionBtn.textContent = teachingThisTab ? "Stop & save draft" : "Start recording";
    teachActionBtn.disabled = !selectedSessionId || !pageTools || Boolean(activeTeachRecording && !teachingThisTab);
    discardTeachBtn.style.display = teachingThisTab ? "inline-flex" : "none";
    teachSettingsDetail.textContent = !pageTools
      ? "Available after this tab opens an HTTP(S) page."
      : teachingThisTab
      ? `Recording ${activeTeachRecording.action_count || 0} semantic actions on this tab.`
      : activeTeachRecording
        ? "Teach Mode is recording in another tab."
        : response?.last_teach_draft
          ? "Draft saved. Review and approve it in EvoFlux before replay."
          : "Record semantic actions into a reviewable draft.";
    retryContextBtn.style.display = response?.pending_interaction ? "inline-flex" : "none";
    releaseControlBtn.disabled = !(response?.attached_tab_ids?.length);
    newConversationBtn.disabled = !selectedSessionId || activeTabIsGroupedChild;
    newConversationBtn.title = activeTabIsGroupedChild
      ? "Switch to the primary tab to start a fresh conversation"
      : "Create a new conversation for this primary tab";
  } catch (error) {
    settingsStatusDot.className = "status-dot error";
    settingsStatusText.textContent = "Extension unavailable";
    settingsStatusDetail.textContent = error.message || String(error);
  }
}

async function saveConnectionSettings() {
  saveConnectionBtn.disabled = true;
  try {
    await chrome.storage.local.set({
      relayBase: relayBaseInput.value.trim() || DEFAULT_RELAY_BASE,
    });
    await chrome.storage.local.remove(["accessToken"]);
    await chrome.runtime.sendMessage({ type: "config_updated" });
    settingsStatusDetail.textContent = "Saved. Reconnecting…";
    setTimeout(() => void refreshSettings(), 500);
  } finally {
    saveConnectionBtn.disabled = false;
  }
}

async function pairLocally() {
  pairLocalBtn.disabled = true;
  pairCodeBtn.disabled = true;
  pairingSettingsDetail.textContent = "Pairing with local EvoFlux…";
  try {
    await chrome.storage.local.set({ relayBase: relayBaseInput.value.trim() || DEFAULT_RELAY_BASE });
    const response = await chrome.runtime.sendMessage({ type: "pair_locally" });
    if (!response?.ok) throw new Error(response?.error || "Local pairing failed");
    pairingSettingsDetail.textContent = "Paired. Connecting…";
    setTimeout(() => { void refreshSettings(); void refreshPanel(); }, 500);
  } catch (error) {
    pairingSettingsDetail.textContent = error.message || String(error);
  } finally {
    pairLocalBtn.disabled = false;
    pairCodeBtn.disabled = false;
  }
}

async function pairWithCode() {
  const code = pairingCodeInput.value.trim().toUpperCase();
  if (!code) {
    pairingSettingsDetail.textContent = "Enter the one-time code shown in EvoFlux.";
    return;
  }
  pairLocalBtn.disabled = true;
  pairCodeBtn.disabled = true;
  pairingSettingsDetail.textContent = "Pairing…";
  try {
    await chrome.storage.local.set({ relayBase: relayBaseInput.value.trim() || DEFAULT_RELAY_BASE });
    const response = await chrome.runtime.sendMessage({ type: "pair_with_code", code });
    if (!response?.ok) throw new Error(response?.error || "Pairing failed");
    pairingCodeInput.value = "";
    pairingSettingsDetail.textContent = "Paired. Connecting…";
    setTimeout(() => { void refreshSettings(); void refreshPanel(); }, 500);
  } catch (error) {
    pairingSettingsDetail.textContent = error.message || String(error);
  } finally {
    pairLocalBtn.disabled = false;
    pairCodeBtn.disabled = false;
  }
}

async function toggleConnection() {
  await chrome.runtime.sendMessage({ type: "toggle_connection" });
  setTimeout(() => void refreshSettings(), 500);
}

async function runWatchAction() {
  watchActionBtn.disabled = true;
  try {
    let response;
    if (activeTextWatch?.state === "matched") {
      response = await chrome.runtime.sendMessage({ type: "send_matched_text_watch", watch_id: activeTextWatch.id });
    } else if (activeTextWatch) {
      response = await chrome.runtime.sendMessage({ type: "cancel_text_watch", watch_id: activeTextWatch.id });
    } else {
      if (!watchNeedleInput.value.trim()) throw new Error("Enter text to watch for.");
      response = await chrome.runtime.sendMessage({
        type: "arm_text_watch",
        session_id: selectedSessionId,
        needle: watchNeedleInput.value,
        ttl_minutes: watchTtlSelect.value,
      });
    }
    if (!response?.ok) throw new Error(response?.error || "Could not update the text watch");
    await refreshSettings();
  } catch (error) {
    watchSettingsDetail.textContent = error.message || String(error);
  } finally {
    watchActionBtn.disabled = !selectedSessionId || !hasPageTools();
  }
}

async function runTeachAction() {
  teachActionBtn.disabled = true;
  try {
    const response = activeTeachRecording?.tab_id === activeTab?.id
      ? await chrome.runtime.sendMessage({ type: "stop_teach_recording" })
      : await chrome.runtime.sendMessage({ type: "start_teach_recording", session_id: selectedSessionId });
    if (!response?.ok) throw new Error(response?.error || "Could not update Teach Mode");
    await refreshSettings();
  } catch (error) {
    teachSettingsDetail.textContent = error.message || String(error);
  } finally {
    teachActionBtn.disabled = !selectedSessionId || !hasPageTools() || Boolean(activeTeachRecording && activeTeachRecording.tab_id !== activeTab?.id);
  }
}

async function discardTeachRecording() {
  const response = await chrome.runtime.sendMessage({ type: "cancel_teach_recording" });
  if (!response?.ok) teachSettingsDetail.textContent = response?.error || "Could not discard recording";
  await refreshSettings();
}

async function retryBrowserContext() {
  retryContextBtn.disabled = true;
  try {
    const response = await chrome.runtime.sendMessage({ type: "retry_pending_interaction" });
    if (!response?.ok) throw new Error(response?.error || "Could not retry browser context");
    await refreshSettings();
  } catch (error) {
    settingsStatusDetail.textContent = error.message || String(error);
  } finally {
    retryContextBtn.disabled = false;
  }
}

async function releaseBrowserControl() {
  releaseControlBtn.disabled = true;
  await chrome.runtime.sendMessage({ type: "release_debuggers" });
  await refreshSettings();
}

async function openGroupedTab() {
  newGroupedTabBtn.disabled = true;
  try {
    const response = await chrome.runtime.sendMessage({
      type: "open_grouped_session_tab",
      session_id: selectedSessionId,
    });
    if (!response?.ok) throw new Error(response?.error || "Could not open a grouped tab");
    setComposerStatus("Opened a background tab in this session group.");
  } catch (error) {
    setNotice(error.message || String(error), "error");
  } finally {
    newGroupedTabBtn.disabled = false;
  }
}

function resizeComposer() {
  composer.style.height = "auto";
  composer.style.height = `${Math.min(composer.scrollHeight, 154)}px`;
}

settingsBtn.addEventListener("click", openSettings);
closeSettingsBtn.addEventListener("click", closeSettings);
settingsBackdrop.addEventListener("click", closeSettings);
saveConnectionBtn.addEventListener("click", () => void saveConnectionSettings());
toggleConnectionBtn.addEventListener("click", () => void toggleConnection());
pairLocalBtn.addEventListener("click", () => void pairLocally());
pairCodeBtn.addEventListener("click", () => void pairWithCode());
themeControl.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-theme-value]");
  if (button) void setTheme(button.dataset.themeValue);
});
watchActionBtn.addEventListener("click", () => void runWatchAction());
teachActionBtn.addEventListener("click", () => void runTeachAction());
discardTeachBtn.addEventListener("click", () => void discardTeachRecording());
retryContextBtn.addEventListener("click", () => void retryBrowserContext());
releaseControlBtn.addEventListener("click", () => void releaseBrowserControl());
newConversationBtn.addEventListener("click", () => void startFreshConversation());
newGroupedTabBtn.addEventListener("click", () => void openGroupedTab());
modelTrigger.addEventListener("click", () => void openModelPicker());
modelSearch.addEventListener("input", () => renderModelOptions(modelSearch.value));
modelList.addEventListener("click", (event) => {
  const option = event.target.closest("button[data-model-id]");
  if (option) void selectSessionModel(option.dataset.modelId || null);
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".model-picker")) closeModelPicker();
});
refreshBtn.addEventListener("click", () => void refreshPanel());
pickElementBtn.addEventListener("click", () => void startElementPicker());
clearElementBtn.addEventListener("click", () => void clearElement());
takeControlBtn.addEventListener("click", () => void takeHumanControl());
resumeAgentBtn.addEventListener("click", () => void resumeAgent());
sendBtn.addEventListener("click", () => void sendMessage());
stopBtn.addEventListener("click", () => void stopRun());
composer.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    void sendMessage();
  }
});
composer.addEventListener("input", resizeComposer);
transcript.addEventListener("scroll", () => {
  transcriptPinned = transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight <= 40;
}, { passive: true });
chrome.tabs.onActivated.addListener(() => void refreshPanel());
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (tabId === activeTab?.id && (changeInfo.url || changeInfo.status === "complete")) {
    void refreshPanel();
  }
});
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && (changes.relayBase || changes.pairingCredential || changes.pairingRelayBase)) {
    void refreshPanel();
  }
});
chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === "pairing_revoked") {
    stopStream();
    sessions = [];
    bindings = [];
    selectedSessionId = "";
    currentSessionModel = null;
    renderModelTrigger();
    pendingQuestions.clear();
    renderQuestions();
    showEmptyTranscript("WebBridge pairing was revoked. Pair the extension again to continue.");
    setNotice("WebBridge pairing was revoked.", "error");
    statusDot.className = "status-dot error";
    return;
  }
  if (message?.type === "element_picker_state") {
    if (message.tab_id !== activeTab?.id) return;
    elementPickerActive = Boolean(message.active);
    renderPickedElement();
    if (!elementPickerActive && !pickedElement) setComposerStatus("");
    return;
  }
  if (message?.type !== "element_picker_result") return;
  elementPickerActive = false;
  pickedElement = message.element || null;
  renderPickedElement();
  clearNotice();
  setComposerStatus("");
  composer.focus();
});
async function refreshRunningState() {
  if (!selectedSessionId || streamController) return;
  try {
    const response = await panelFetch(SESSIONS_PATH);
    sessions = await response.json();
    if (sessions.find((session) => session.id === selectedSessionId)?.running) {
      startStream();
      await loadPendingQuestions();
    }
  } catch {
    // The main refresh surface reports pairing/transport errors.
  }
}

void initializeTheme();
void refreshPanel();
setInterval(() => {
  loadingVerbIndex = (loadingVerbIndex + 1) % LOADING_VERBS.length;
  if (activity.classList.contains("visible") && toolActivities.size === 0) renderActivity();
}, 2800);
setInterval(() => void refreshRunningState(), 2000);