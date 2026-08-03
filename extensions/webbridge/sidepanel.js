/* EvoFlux WebBridge P2 Side Panel. */

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
const openInEvoFluxBtn = document.getElementById("openInEvoFluxBtn");
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
const contextChips = document.getElementById("contextChips");
const attachPageBtn = document.getElementById("attachPageBtn");
const attachSelectionBtn = document.getElementById("attachSelectionBtn");
const captureRegionBtn = document.getElementById("captureRegionBtn");
const attachFileBtn = document.getElementById("attachFileBtn");
const fileInput = document.getElementById("fileInput");
const notice = document.getElementById("notice");
const transcript = document.getElementById("transcript");
const loadOlderBtn = document.getElementById("loadOlderBtn");
const questionsRoot = document.getElementById("questions");
const composer = document.getElementById("composer");
const sendBtn = document.getElementById("sendBtn");
const composerStatus = document.getElementById("composerStatus");
const modelTrigger = document.getElementById("modelTrigger");
const modelLabel = document.getElementById("modelLabel");
const modelThinkingLabel = document.getElementById("modelThinkingLabel");
const modelProviderBadge = document.getElementById("modelProviderBadge");
const modelPopover = document.getElementById("modelPopover");
const modelSearch = document.getElementById("modelSearch");
const modelList = document.getElementById("modelList");
const modelCurrentName = document.getElementById("modelCurrentName");
const modelCurrentId = document.getElementById("modelCurrentId");
const modelCurrentProviderBadge = document.getElementById("modelCurrentProviderBadge");
const thinkingOptions = document.getElementById("thinkingOptions");
const thinkingAvailability = document.getElementById("thinkingAvailability");
const speedControl = document.getElementById("speedControl");
const speedAvailability = document.getElementById("speedAvailability");
const activity = document.getElementById("activity");
const activityLabel = document.getElementById("activityLabel");
const activityDetail = document.getElementById("activityDetail");
const relayBaseInput = document.getElementById("relayBaseInput");
const toggleConnectionBtn = document.getElementById("toggleConnectionBtn");
const settingsStatusDot = document.getElementById("settingsStatusDot");
const settingsStatusText = document.getElementById("settingsStatusText");
const settingsStatusDetail = document.getElementById("settingsStatusDetail");
const themeControl = document.getElementById("themeControl");
const watchNeedleInput = document.getElementById("watchNeedleInput");
const watchTtlSelect = document.getElementById("watchTtlSelect");
const watchActionBtn = document.getElementById("watchActionBtn");
const watchSettingsDetail = document.getElementById("watchSettingsDetail");
const watchList = document.getElementById("watchList");
const stopAllWatchesBtn = document.getElementById("stopAllWatchesBtn");
const teachActionBtn = document.getElementById("teachActionBtn");
const discardTeachBtn = document.getElementById("discardTeachBtn");
const teachSettingsDetail = document.getElementById("teachSettingsDetail");
const issueCaptureBtn = document.getElementById("issueCaptureBtn");
const reportIssueBtn = document.getElementById("reportIssueBtn");
const issueSettingsDetail = document.getElementById("issueSettingsDetail");
const retryContextBtn = document.getElementById("retryContextBtn");
const releaseControlBtn = document.getElementById("releaseControlBtn");

const annotationOverlay = document.getElementById("annotationOverlay");
const annotationCanvasWrapper = document.getElementById("annotationCanvasWrapper");
const annotationToolbar = document.getElementById("annotationToolbar");
const annotationUndoBtn = document.getElementById("annotationUndoBtn");
const annotationRedoBtn = document.getElementById("annotationRedoBtn");
const annotationClearBtn = document.getElementById("annotationClearBtn");
const annotationCancelBtn = document.getElementById("annotationCancelBtn");
const annotationSkipBtn = document.getElementById("annotationSkipBtn");
const annotationConfirmBtn = document.getElementById("annotationConfirmBtn");
const previewOverlay = document.getElementById("previewOverlay");
const previewImage = document.getElementById("previewImage");
const previewMeta = document.getElementById("previewMeta");
const previewBackBtn = document.getElementById("previewBackBtn");
const previewEditBtn = document.getElementById("previewEditBtn");
const previewCancelBtn = document.getElementById("previewCancelBtn");
const previewSendBtn = document.getElementById("previewSendBtn");

let annotationEditor = null;
let annotatedDataBase64 = null;
let annotationActive = false;
let previewActive = false;

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
let streamingSessionId = null;
let streamTask = null;
let refreshGeneration = 0;
let historyLoadGeneration = 0;
let questionLoadGeneration = 0;
let liveMessage = null;
const liveThinkingChars = new Map();
let pendingQuestions = new Map();
const activeTakeoverRequests = new Set();
let humanControlLease = null;
let pendingComposerRequest = null;
let pickedElement = null;
let panelContexts = [];
let regionCapture = null;
let panelFiles = [];
let panelFileTabId = null;
let composerSending = false;
let activeTextWatch = null;
let textWatches = [];
let activeTeachRecording = null;
let activeIssueCapture = null;
let browserModels = [];
let currentSessionModel = null;
let currentSessionThinkingLevel = null;
let currentSessionFastMode = false;
let modelCatalogLoaded = false;
let modelCatalogLoading = false;
let elementPickerActive = false;
let markdownRenderTimer = null;
let transcriptPinned = true;
let historyCursor = null;
const mediaObjectUrls = new Map();
const agentStates = new Map();
const toolActivities = new Map();
const PANEL_REQUEST_STORAGE_KEY = "webbridgePanelPendingRequest";
const PANEL_CONTEXT_DRAFT_STORAGE_KEY = "webbridgePanelContextDraft";
const TAB_PAGE_INSTANCE_STORAGE_KEY = "webbridgeTabPageInstance";
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
  let cfg = await chrome.storage.local.get([
    "relayBase",
    "pairingCredential",
    "pairingRelayBase",
  ]);
  relayBase = (cfg.relayBase || DEFAULT_RELAY_BASE).trim().replace(/\/+$/, "");
  pairingCredential = (cfg.pairingCredential || "").trim();
  pairingRelayBase = (cfg.pairingRelayBase || "").trim().replace(/\/+$/, "");
  if (!pairingCredential || pairingRelayBase !== canonicalRelayBase()) {
    const response = await chrome.runtime.sendMessage({ type: "ensure_connection" });
    if (!response?.ok) throw new Error(response?.error || "Could not connect to EvoFlux.");
    cfg = await chrome.storage.local.get(["pairingCredential", "pairingRelayBase"]);
    pairingCredential = (cfg.pairingCredential || "").trim();
    pairingRelayBase = (cfg.pairingRelayBase || "").trim().replace(/\/+$/, "");
    if (!pairingCredential || pairingRelayBase !== canonicalRelayBase()) {
      throw new Error("The EvoFlux connection is still starting.");
    }
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
  throw new PanelHttpError(message, response.status);
}

class PanelHttpError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "PanelHttpError";
    this.status = status;
  }

  get retryable() {
    return this.status === 408 || this.status === 425 || this.status === 429 || this.status >= 500;
  }
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
  attachPageBtn.disabled = disabled;
  attachSelectionBtn.disabled = disabled;
  captureRegionBtn.disabled = disabled;
  attachFileBtn.disabled = disabled;
  openInEvoFluxBtn.disabled = disabled || !selectedSessionId;
  if (annotationActive || previewActive) {
    captureRegionBtn.disabled = true;
    attachPageBtn.disabled = true;
    attachSelectionBtn.disabled = true;
    attachFileBtn.disabled = true;
  }
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

function renderPanelContexts() {
  contextChips.replaceChildren();
  const currentContexts = panelContexts.filter((context) => context.tab_id === activeTab?.id);
  const items = [
    ...currentContexts.map((context) => ({
      key: context.type,
      label: context.type === "selection" ? "Selection" : "Page",
      detail: context.text,
    })),
    ...(regionCapture?.tab_id === activeTab?.id ? [{
      key: "screenshot",
      label: "Region",
      detail: `${Math.round(regionCapture.clip.width)}×${Math.round(regionCapture.clip.height)}`,
    }] : []),
    ...(panelFileTabId === activeTab?.id ? panelFiles : []).map((file, index) => ({
      key: `file:${index}`,
      label: file.name,
      detail: `${file.type || "file"} · ${file.size} bytes`,
    })),
  ];
  contextChips.classList.toggle("visible", items.length > 0);
  for (const item of items) {
    const chip = document.createElement("div");
    chip.className = "context-chip";
    chip.title = item.detail;
    const label = document.createElement("span");
    label.textContent = item.label;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove ${item.label}`);
    remove.textContent = "×";
    remove.addEventListener("click", () => void removePanelContext(item.key));
    chip.append(label, remove);
    contextChips.append(chip);
  }
  attachPageBtn.classList.toggle("active", currentContexts.some((context) => context.type === "readable_page"));
  attachSelectionBtn.classList.toggle("active", currentContexts.some((context) => context.type === "selection"));
  captureRegionBtn.classList.toggle("active", regionCapture?.tab_id === activeTab?.id);
  attachFileBtn.classList.toggle("active", panelFiles.length > 0);
}

async function removePanelContext(type) {
  if (type === "screenshot") {
    await chrome.runtime.sendMessage({ type: "clear_region_capture" });
    regionCapture = null;
  } else if (type.startsWith("file:")) {
    panelFiles.splice(Number(type.split(":")[1]), 1);
    if (!panelFiles.length) panelFileTabId = null;
  } else {
    panelContexts = panelContexts.filter((context) => !(context.tab_id === activeTab?.id && context.type === type));
  }
  renderPanelContexts();
}

async function captureTextContext(type) {
  if (!hasPageTools()) return;
  const response = await chrome.runtime.sendMessage({ type: "capture_panel_context", kind: type });
  if (!response?.ok) {
    setComposerStatus(response?.error || "Could not capture browser context", "error");
    return;
  }
  panelContexts = panelContexts.filter((context) => !(context.tab_id === activeTab.id && context.type === type));
  panelContexts.push({ ...response.context, tab_id: activeTab.id });
  renderPanelContexts();
  setComposerStatus(`${type === "selection" ? "Selection" : "Page"} attached.`);
}

async function startRegionCapture() {
  if (!hasPageTools()) return;
  if (panelFiles.length) {
    panelFiles = [];
    renderPanelContexts();
  }
  const response = await chrome.runtime.sendMessage({ type: "start_region_picker" });
  if (!response?.ok) {
    setComposerStatus(response?.error || "Could not start region capture", "error");
    return;
  }
  setComposerStatus("Drag a region on the page · Escape to cancel.");
}

function selectPanelFiles(files) {
  const selected = [...files].slice(0, 10);
  const totalBytes = selected.reduce((total, file) => total + file.size, 0);
  if (totalBytes > 5_000_000) {
    setComposerStatus("Selected files exceed the 5 MB browser artifact limit.", "error");
    fileInput.value = "";
    return;
  }
  panelFiles = selected;
  panelFileTabId = activeTab?.id ?? null;
  if (regionCapture?.tab_id === activeTab?.id) {
    void chrome.runtime.sendMessage({ type: "clear_region_capture" });
    regionCapture = null;
  }
  renderPanelContexts();
  setComposerStatus(`${panelFiles.length} file${panelFiles.length === 1 ? "" : "s"} attached.`);
  fileInput.value = "";
}

async function openInEvoFlux() {
  if (!selectedSessionId) return;
  await chrome.tabs.create({
    url: `${panelHttpBase()}/${encodeURIComponent(selectedSessionId)}`,
    active: true,
  });
}

function base64PngBlob(value) {
  const binary = atob(value || "");
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return new Blob([bytes], { type: "image/png" });
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

function providerOf(modelId) {
  const value = String(modelId || "");
  const separator = value.indexOf(":");
  return separator >= 0 ? value.slice(0, separator) : "";
}

const PROVIDER_COLORS = {
  anthropic: "#d99162",
  azure: "#4da3ff",
  codex: "#5ec79b",
  google: "#6da1ff",
  groq: "#f08b62",
  ollama: "#a8b0b8",
  openai: "#5ec79b",
  openrouter: "#aa8dff",
};

const THINKING_LABELS = {
  none: "None",
  minimal: "Minimal",
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "X-High",
  max: "Max",
  ultra: "Ultra",
};

function thinkingLabel(level) {
  return level ? THINKING_LABELS[level] || level : "Default";
}

function thinkingColor(level) {
  if (!level || level === "none") return "var(--thinking-neutral)";
  if (["minimal", "low"].includes(level)) return "var(--thinking-low)";
  if (level === "medium") return "var(--thinking-medium)";
  if (level === "high") return "var(--thinking-high)";
  return "var(--thinking-max)";
}

function setProviderBadge(element, modelId) {
  const provider = providerOf(modelId);
  element.textContent = provider ? provider.slice(0, 2) : "AI";
  element.title = provider || "Lead agent default";
  element.style.setProperty("--provider-color", PROVIDER_COLORS[provider] || "var(--accent)");
}

function selectedModelOption() {
  return browserModels.find((entry) => entry.id === currentSessionModel) || null;
}

function supportsFastMode(modelId) {
  return String(modelId || "").startsWith("codex:");
}

function reconcileThinkingLevel(level, model) {
  return level && model?.thinking_levels?.includes(level) ? level : null;
}

function renderThinkingOptions() {
  const model = selectedModelOption();
  const levels = model?.thinking_levels || [];
  const options = [null, ...levels];
  thinkingOptions.replaceChildren();
  thinkingAvailability.textContent = levels.length ? thinkingLabel(currentSessionThinkingLevel) : "Provider default";
  for (const level of options) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "thinking-option";
    button.dataset.thinkingLevel = level || "";
    button.setAttribute("role", "radio");
    button.setAttribute("aria-checked", String(level === currentSessionThinkingLevel));
    button.disabled = !currentSessionModel;
    const dot = document.createElement("span");
    dot.className = "thinking-option-dot";
    dot.style.setProperty("--thinking-color", thinkingColor(level));
    const label = document.createElement("span");
    label.textContent = thinkingLabel(level);
    button.append(dot, label);
    thinkingOptions.append(button);
  }
}

function renderSpeedControl() {
  const available = supportsFastMode(currentSessionModel);
  if (!available) currentSessionFastMode = false;
  speedAvailability.textContent = available ? "" : "Fast unavailable";
  for (const button of speedControl.querySelectorAll("button[data-speed]")) {
    const fast = button.dataset.speed === "fast";
    button.disabled = fast ? !available : false;
    button.setAttribute("aria-checked", String(fast === currentSessionFastMode));
  }
}

function renderModelTrigger(session = null) {
  if (session) {
    if (session.id && session.id !== modelTrigger.dataset.sessionId) {
      currentSessionFastMode = false;
      modelTrigger.dataset.sessionId = session.id;
    }
    currentSessionModel = session.model || null;
    currentSessionThinkingLevel = session.thinking_level || null;
  }
  const label = currentSessionModel ? shortModelName(currentSessionModel) : "Model";
  modelLabel.textContent = label;
  modelThinkingLabel.textContent = thinkingLabel(currentSessionThinkingLevel);
  modelThinkingLabel.style.setProperty("--thinking-color", thinkingColor(currentSessionThinkingLevel));
  setProviderBadge(modelProviderBadge, currentSessionModel);
  setProviderBadge(modelCurrentProviderBadge, currentSessionModel);
  modelCurrentName.textContent = currentSessionModel ? label : "Choose a model";
  modelCurrentId.textContent = currentSessionModel || "Lead agent default";
  modelTrigger.title = currentSessionModel
    ? `${currentSessionModel} · ${thinkingLabel(currentSessionThinkingLevel)} thinking`
    : "Use the lead agent's default model";
  modelTrigger.disabled = !selectedSessionId;
  renderThinkingOptions();
  renderSpeedControl();
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
    const badge = document.createElement("span");
    badge.className = "provider-badge compact";
    setProviderBadge(badge, model);
    const copy = document.createElement("span");
    copy.className = "model-option-copy";
    const name = document.createElement("strong");
    name.textContent = label;
    const meta = document.createElement("span");
    meta.textContent = detail;
    copy.append(name, meta);
    const provider = document.createElement("span");
    provider.className = "model-provider-label";
    provider.textContent = providerOf(model) || "default";
    const check = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    check.classList.add("model-check");
    check.setAttribute("viewBox", "0 0 24 24");
    const checkPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
    checkPath.setAttribute("d", "m5 12 4 4L19 6");
    check.append(checkPath);
    option.append(badge, copy, provider, check);
    modelList.append(option);
  };

  if (!normalized || "default lead model".includes(normalized)) {
    appendOption(null, "Lead default", "Use the EvoFlux agent model");
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
    currentSessionThinkingLevel = reconcileThinkingLevel(
      currentSessionThinkingLevel,
      selectedModelOption(),
    );
  } catch (error) {
    setComposerStatus(error.message || String(error), "error");
  } finally {
    modelCatalogLoading = false;
    renderModelOptions(modelSearch.value);
    renderModelTrigger();
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

function setModelSettingsBusy(busy) {
  modelPopover.toggleAttribute("data-saving", busy);
  modelSearch.disabled = busy;
  for (const button of modelPopover.querySelectorAll("button")) button.disabled = busy;
  if (!busy) {
    renderThinkingOptions();
    renderSpeedControl();
  }
}

async function persistSessionModelSettings(model, thinkingLevel) {
  if (!selectedSessionId) return;
  const sessionId = selectedSessionId;
  setModelSettingsBusy(true);
  try {
    const response = await panelFetch(
      `${SESSIONS_PATH}/${encodeURIComponent(sessionId)}/model`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: model || null, thinking_level: thinkingLevel || null }),
      }
    );
    const session = await response.json();
    if (selectedSessionId !== sessionId) return;
    currentSessionModel = session.model || null;
    currentSessionThinkingLevel = session.thinking_level || null;
    if (!supportsFastMode(currentSessionModel)) currentSessionFastMode = false;
    const existing = sessions.find((item) => item.id === sessionId);
    if (existing) {
      existing.model = currentSessionModel;
      existing.thinking_level = currentSessionThinkingLevel;
    }
    renderModelTrigger(session);
    renderModelOptions(modelSearch.value);
    setComposerStatus(
      currentSessionModel
        ? `Using ${shortModelName(currentSessionModel)} · ${thinkingLabel(currentSessionThinkingLevel)} thinking.`
        : "Using the lead agent's default model."
    );
  } catch (error) {
    setComposerStatus(error.message || String(error), "error");
  } finally {
    setModelSettingsBusy(false);
    modelTrigger.disabled = !selectedSessionId;
  }
}

async function selectSessionModel(modelId) {
  const model = browserModels.find((entry) => entry.id === modelId) || null;
  const nextThinking = modelId
    ? reconcileThinkingLevel(currentSessionThinkingLevel, model)
    : null;
  await persistSessionModelSettings(modelId, nextThinking);
}

async function selectThinkingLevel(level) {
  if (!currentSessionModel) return;
  await persistSessionModelSettings(currentSessionModel, level || null);
}

function selectResponseSpeed(fast) {
  currentSessionFastMode = Boolean(fast && supportsFastMode(currentSessionModel));
  renderSpeedControl();
  setComposerStatus(currentSessionFastMode ? "Fast responses enabled for the next turn." : "Standard response speed.");
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
  renderComposerSubmitControl();
  if (bound) {
    bindingStatus.textContent = activeTabIsGroupedChild
      ? "Group tab"
      : "Primary tab";
    contextDetail.textContent = activeTabIsGroupedChild
      ? "Agent defaults to the primary tab"
      : browserOrigin(activeTab?.url || activeTab?.pendingUrl || "")
        || "Browser tools activate on HTTP(S) pages";
    return;
  }
  bindingStatus.textContent = "Preparing tab session";
  contextDetail.textContent = "WebBridge creates it automatically";
}

function clearTranscript() {
  for (const objectUrl of mediaObjectUrls.values()) URL.revokeObjectURL(objectUrl);
  mediaObjectUrls.clear();
  transcript.replaceChildren();
  transcript.append(loadOlderBtn);
  loadOlderBtn.classList.remove("visible");
  historyCursor = null;
  liveMessage = null;
  liveThinkingChars.clear();
  toolActivities.clear();
}

function panelMediaPath(source) {
  if (!selectedSessionId || !source || /^(?:https?:)?\/\//i.test(source)) return "";
  const clean = source.replace(/^\.\//, "").replace(/^\/+/, "");
  if (!clean || clean.split("/").includes("..")) return "";
  return `${SESSIONS_PATH}/${encodeURIComponent(selectedSessionId)}/media/${clean.split("/").map(encodeURIComponent).join("/")}`;
}

async function authenticatedMediaUrl(path) {
  if (mediaObjectUrls.has(path)) return mediaObjectUrls.get(path);
  const response = await panelFetch(path);
  const objectUrl = URL.createObjectURL(await response.blob());
  mediaObjectUrls.set(path, objectUrl);
  return objectUrl;
}

async function hydrateMarkdownMedia(root) {
  for (const image of root.querySelectorAll("img[data-webbridge-media-src]")) {
    const source = image.dataset.webbridgeMediaSrc || "";
    try {
      const path = panelMediaPath(source);
      if (!path) throw new Error("Unsupported media path");
      image.src = await authenticatedMediaUrl(path);
      image.removeAttribute("data-webbridge-media-src");
    } catch {
      const fallback = document.createElement("span");
      fallback.className = "media-unavailable";
      fallback.textContent = image.alt || "Image unavailable";
      image.replaceWith(fallback);
    }
  }
  for (const button of root.querySelectorAll("button[data-webbridge-remote-media-src]")) {
    button.addEventListener("click", () => {
      const source = button.dataset.webbridgeRemoteMediaSrc || "";
      if (!/^https?:\/\//i.test(source)) return;
      const image = document.createElement("img");
      image.src = source;
      image.alt = button.dataset.webbridgeRemoteMediaAlt || "Remote image";
      image.loading = "lazy";
      image.referrerPolicy = "no-referrer";
      button.replaceWith(image);
    }, { once: true });
  }
}

async function renderAttachments(item, attachments = []) {
  if (!attachments.length) return;
  const root = document.createElement("div");
  root.className = "message-attachments";
  item.append(root);
  for (const attachment of attachments) {
    const entry = document.createElement(attachment.category === "image" ? "figure" : "div");
    entry.className = `message-attachment ${attachment.category === "image" ? "image" : "file"}`;
    if (attachment.category === "image") {
      const image = document.createElement("img");
      image.alt = attachment.name || "Image";
      image.loading = "lazy";
      const caption = document.createElement("figcaption");
      caption.textContent = attachment.name || "Image";
      entry.append(image, caption);
      root.append(entry);
      try { image.src = await authenticatedMediaUrl(attachment.url); }
      catch { entry.replaceWith(Object.assign(document.createElement("span"), { className: "media-unavailable", textContent: `${attachment.name || "Image"} unavailable` })); }
      if (attachment.deletable) addAttachmentDelete(entry, attachment);
      continue;
    }
    const download = document.createElement("button");
    download.type = "button";
    download.textContent = attachment.name || "Attachment";
    download.addEventListener("click", async () => {
      try {
        const url = await authenticatedMediaUrl(attachment.url);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = attachment.name || "attachment";
        anchor.click();
      } catch (error) {
        setNotice(error.message || String(error), "error");
      }
    });
    entry.append(download);
    if (attachment.deletable) addAttachmentDelete(entry, attachment);
    root.append(entry);
  }
}

function addAttachmentDelete(entry, attachment) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "attachment-delete";
  button.textContent = "×";
  button.title = `Delete ${attachment.name || "attachment"}`;
  button.setAttribute("aria-label", button.title);
  button.addEventListener("click", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    button.disabled = true;
    try {
      await panelFetch(attachment.url, { method: "DELETE" });
      const objectUrl = mediaObjectUrls.get(attachment.url);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      mediaObjectUrls.delete(attachment.url);
      entry.remove();
    } catch (error) {
      button.disabled = false;
      setNotice(error.message || String(error), "error");
    }
  });
  entry.append(button);
}

function scrollTranscriptToEnd() {
  if (!transcriptPinned) return;
  requestAnimationFrame(() => { transcript.scrollTop = transcript.scrollHeight; });
}

function shortDisplayModel(model) {
  return String(model || "").split(":").at(-1)?.split("/").at(-1) || "";
}

function messageMeta(message) {
  const parts = [message.role === "user" ? "You" : (message.agent || "EvoFlux")];
  if (message.model) parts.push(shortDisplayModel(message.model));
  if (message.created_at) {
    const createdAt = new Date(message.created_at);
    if (Number.isFinite(createdAt.getTime())) {
      parts.push(new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(createdAt));
    }
  }
  if (Number.isFinite(message.response_duration_ms)) {
    parts.push(`${Math.max(0, message.response_duration_ms / 1000).toFixed(1)}s`);
  }
  return parts.join(" · ");
}

function renderMessageActivities(item, activities) {
  if (!Array.isArray(activities) || !activities.length) return null;
  const root = document.createElement("div");
  root.className = "message-activities";
  for (const activityItem of activities) {
    const row = document.createElement("div");
    row.className = `message-activity ${activityItem.state === "done" ? "done" : "pending"}`;
    const state = document.createElement("span");
    state.className = "message-activity-state";
    state.textContent = activityItem.state === "done" ? "✓" : "…";
    const label = document.createElement("span");
    label.textContent = friendlyToolName(activityItem.name);
    row.append(state, label);
    if (Number.isFinite(activityItem.duration_ms)) {
      const duration = document.createElement("time");
      duration.textContent = `${Math.max(0, activityItem.duration_ms / 1000).toFixed(1)}s`;
      row.append(duration);
    }
    root.append(row);
  }
  item.append(root);
  return root;
}

function appendMessage(message, { live = false, prepend = false } = {}) {
  const empty = transcript.querySelector(".empty");
  if (empty) empty.remove();
  const item = document.createElement("article");
  item.className = `message ${message.is_summary ? "compaction" : message.role === "user" ? "user" : "assistant"}${live ? " live" : ""}`;
  const meta = document.createElement("span");
  meta.className = "message-meta";
  meta.textContent = messageMeta(message);
  const content = document.createElement("div");
  content.className = "message-body";
  const rawContent = message.content || "";
  if (message.is_summary) {
    content.textContent = "Session compacted";
  } else if (message.role === "assistant" && globalThis.WebBridgeMarkdown) {
    globalThis.WebBridgeMarkdown.render(content, rawContent);
    void hydrateMarkdownMedia(content);
  } else {
    content.textContent = rawContent;
  }
  item.append(meta, content);
  renderMessageActivities(item, message.activities);
  void renderAttachments(item, message.attachments || []);
  if (prepend) transcript.insertBefore(item, loadOlderBtn.nextSibling);
  else transcript.append(item);
  if (!prepend) scrollTranscriptToEnd();
  return { item, content, rawContent };
}

function ensureLiveMessage(agent = "EvoFlux") {
  if (liveMessage?.agent === agent) return liveMessage;
  flushLiveMarkdownRender();
  liveMessage = {
    agent,
    ...appendMessage({ role: "assistant", agent, content: "" }, { live: true }),
  };
  liveMessage.item.classList.add("live-turn");
  return liveMessage;
}

function renderLiveTurnDetails(agent = liveMessage?.agent || "EvoFlux") {
  const message = ensureLiveMessage(agent);
  for (const existing of message.item.querySelectorAll(".live-thinking-summary, .message-activities")) {
    existing.remove();
  }
  const thinkingChars = liveThinkingChars.get(agent) || 0;
  const activities = [...toolActivities.values()].filter((entry) => (
    !entry.agent || entry.agent === agent
  ));
  if (thinkingChars > 0 || (agentStates.get(agent) === "working" && !activities.length)) {
    const thinking = document.createElement("div");
    thinking.className = "live-thinking-summary";
    thinking.textContent = thinkingChars > 0
      ? `Thought · ${thinkingChars.toLocaleString()} chars`
      : "Thinking…";
    message.item.append(thinking);
  }
  renderMessageActivities(message.item, activities);
  scrollTranscriptToEnd();
}

function showEmptyTranscript(text) {
  clearTranscript();
  const empty = document.createElement("div");
  empty.className = "empty";
  empty.textContent = text;
  transcript.append(empty);
}

async function loadHistory({ before = null, prepend = false } = {}) {
  const sessionId = selectedSessionId;
  const loadGeneration = ++historyLoadGeneration;
  if (!sessionId) {
    showEmptyTranscript("EvoFlux is preparing this tab session.");
    return;
  }
  let cursor = before;
  let body = null;
  for (let page = 0; page < 20; page += 1) {
    const path = cursor
      ? `${SESSIONS_PATH}/${encodeURIComponent(sessionId)}/history?before=${encodeURIComponent(cursor)}`
      : `${SESSIONS_PATH}/${encodeURIComponent(sessionId)}/history`;
    const response = await panelFetch(path);
    body = await response.json();
    if (loadGeneration !== historyLoadGeneration || sessionId !== selectedSessionId) return false;
    if (body.messages?.length || !body.has_more || !body.next_cursor) break;
    cursor = body.next_cursor;
  }
  if (loadGeneration !== historyLoadGeneration || sessionId !== selectedSessionId) return false;
  const previousHeight = transcript.scrollHeight;
  if (!prepend) clearTranscript();
  if (!body?.messages?.length) {
    if (!prepend) showEmptyTranscript("No messages yet. Send a question from the Side Panel.");
    historyCursor = body?.next_cursor || null;
    loadOlderBtn.classList.toggle("visible", Boolean(body?.has_more && historyCursor));
    return true;
  }
  if (prepend) {
    for (const message of [...body.messages].reverse()) appendMessage(message, { prepend: true });
    requestAnimationFrame(() => {
      transcript.scrollTop += transcript.scrollHeight - previousHeight;
    });
  } else {
    for (const message of body.messages) appendMessage(message);
  }
  historyCursor = body.next_cursor || null;
  loadOlderBtn.classList.toggle("visible", Boolean(body.has_more && historyCursor));
  return true;
}

function renderQuestions() {
  questionsRoot.replaceChildren();
  const questions = [...pendingQuestions.values()];
  const liveRequestIds = new Set(questions.map((request) => request.request_id));
  for (const requestId of activeTakeoverRequests) {
    if (!liveRequestIds.has(requestId)) activeTakeoverRequests.delete(requestId);
  }
  questionsRoot.classList.toggle("visible", questions.length > 0);
  for (const request of questions) {
    const card = document.createElement("article");
    card.className = "question-card";
    const inputs = [];
    const handoffs = request.questions.map((question) => question.browser_handoff || null);
    const needsTakeover = handoffs.some((handoff) => handoff?.kind === "take_over");
    request.questions.forEach((question, index) => {
      const handoff = handoffs[index];
      if (handoff) {
        const meta = document.createElement("div");
        meta.className = "handoff-meta";
        const title = document.createElement("strong");
        title.textContent = handoff.title || {
          take_over: "Take over this tab",
          confirm_action: "Confirm browser action",
          provide_secret: "Complete secure input",
          choose_option: "Choose an option",
        }[handoff.kind] || "Browser handoff";
        meta.append(title);
        for (const detail of [handoff.action, handoff.target, handoff.consequence].filter(Boolean)) {
          const line = document.createElement("div");
          line.textContent = detail;
          meta.append(line);
        }
        card.append(meta);
      }
      const prompt = document.createElement("p");
      prompt.textContent = question.question || `Question ${index + 1}`;
      card.append(prompt);
      const input = document.createElement("textarea");
      input.className = "answer";
      input.placeholder = handoff?.kind === "provide_secret"
        ? "No secret is read · click Completed after entering it on the page"
        : "Your answer";
      input.setAttribute("aria-label", `Answer ${index + 1}`);
      if (handoff?.kind === "provide_secret" || handoff?.kind === "take_over") {
        input.hidden = true;
        input.value = "completed";
      }
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
    reply.textContent = handoffs.some((handoff) => handoff?.kind === "take_over")
      ? "Done · Resume agent"
      : handoffs.some((handoff) => handoff?.kind === "provide_secret")
        ? "Completed"
        : "Reply";
    reply.addEventListener("click", () => void submitQuestion(request, inputs, reply));
    if (needsTakeover && !activeTakeoverRequests.has(request.request_id)) {
      activeTakeoverRequests.add(request.request_id);
      void takeHumanControl();
    }
    card.append(reply);
    questionsRoot.append(card);
  }
}

async function loadPendingQuestions() {
  const sessionId = selectedSessionId;
  const loadGeneration = ++questionLoadGeneration;
  if (!sessionId) {
    pendingQuestions.clear();
    renderQuestions();
    return;
  }
  const response = await panelFetch(
    `${SESSIONS_PATH}/${encodeURIComponent(sessionId)}/questions/pending`
  );
  const body = await response.json();
  if (loadGeneration !== questionLoadGeneration || sessionId !== selectedSessionId) return;
  pendingQuestions.clear();
  for (const request of body.questions || []) pendingQuestions.set(request.request_id, request);
  renderQuestions();
}

async function consumeContextMenuDraft() {
  if (!activeTab?.id) return;
  const storage = panelSessionStorage();
  const draftKey = `${PANEL_CONTEXT_DRAFT_STORAGE_KEY}:${activeTab.id}`;
  const pageInstanceKey = `${TAB_PAGE_INSTANCE_STORAGE_KEY}:${activeTab.id}`;
  const stored = await storage.get([draftKey, pageInstanceKey]);
  const draft = stored[draftKey];
  const currentPageUrl = safePageUrl(activeTab.url || activeTab.pendingUrl || "");
  if (
    !draft ||
    !draft.created_at ||
    Date.now() - draft.created_at > 5 * 60 * 1000 ||
    draft.page_url !== currentPageUrl ||
    !draft.page_instance_id ||
    draft.page_instance_id !== stored[pageInstanceKey]
  ) {
    if (draft) await storage.remove([draftKey]);
    return;
  }
  const payload = draft.payload || {};
  const metadata = payload.metadata || {};
  composer.value = payload.prompt || composer.value;
  resizeComposer();
  if (payload.context_type === "selection" && metadata.selection_text) {
    panelContexts = panelContexts.filter((context) => !(context.tab_id === activeTab.id && context.type === "selection"));
    panelContexts.push({
      tab_id: activeTab.id,
      type: "selection",
      page_url: metadata.page_url,
      title: metadata.page_title || "",
      text: metadata.selection_text,
    });
  } else {
    const detail = payload.context_type === "link" ? metadata.link_url : metadata.page_url;
    if (detail) {
      composer.value = `${composer.value}\n\nSource: ${detail}`.trim();
      resizeComposer();
    }
  }
  await storage.remove([draftKey]);
  renderPanelContexts();
  setComposerStatus("Browser context ready · review and send.");
  composer.focus();
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
    activeTakeoverRequests.delete(request.request_id);
    if (request.questions.some((question) => question.browser_handoff?.kind === "take_over")) {
      await resumeAgent();
    }
    renderQuestions();
    clearNotice();
  } catch (error) {
    setNotice(error.message || String(error), "error");
  } finally {
    button.disabled = false;
  }
}

async function resolvePanelSession(tab) {
  const response = await chrome.runtime.sendMessage({
    type: "ensure_browser_session_for_tab",
  });
  if (!response?.ok) throw new Error(response?.error || "Could not prepare this tab session");
  if (response.tab?.id !== tab.id) throw new Error("The active browser tab changed while Side Chat was loading.");
  return response;
}

async function refreshPanel({ preserveTranscript = false } = {}) {
  const generation = ++refreshGeneration;
  setControlsDisabled(true);
  try {
    await loadConfig();
    const nextTab = await currentTab();
    if (activeTab && activeTab.id !== nextTab.id) {
      stopStream();
      panelFiles = [];
      panelFileTabId = null;
    }
    activeTab = nextTab;
    pageTitle.textContent = activeTab.title || safePageUrl(activeTab.url || activeTab.pendingUrl || "") || "Side Chat";
    const ensured = await resolvePanelSession(activeTab);
    if (generation !== refreshGeneration) return;
    selectedSessionId = ensured.session_id || "";
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
    sessionTitle.textContent = session?.title || "EvoFlux Side Chat";
    renderModelTrigger(session);
    renderBindingStatus();
    if (selectedSessionId) await refreshHumanControl();
    else humanControlLease = null;
    await refreshPickedElement();
    const captureResponse = await chrome.runtime.sendMessage({ type: "get_region_capture" });
    regionCapture = captureResponse?.ok ? captureResponse.capture : null;
    renderPanelContexts();
    await consumeContextMenuDraft();
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
  streamingSessionId = null;
  streamTask = null;
  historyLoadGeneration += 1;
  questionLoadGeneration += 1;
  clearTimeout(markdownRenderTimer);
  markdownRenderTimer = null;
  liveMessage = null;
  liveThinkingChars.clear();
  toolActivities.clear();
  agentStates.clear();
  renderActivity();
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
  const normalized = String(name || "tool");
  if (normalized === "webbridge") return "Browsed web";
  if (normalized === "skill") return "Skill";
  return normalized
    .replace(/^mcp__/, "")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function isAgentWorking() {
  return (
    [...toolActivities.values()].some((entry) => entry.state !== "done")
    || [...agentStates.values()].some((state) => state === "working")
  );
}

function renderComposerSubmitControl() {
  const working = isAgentWorking();
  const stopMode = working && !composer.value.trim() && !composerSending;
  sendBtn.classList.toggle("stop-mode", stopMode);
  sendBtn.setAttribute("aria-label", stopMode ? "Stop generation" : "Send message");
  sendBtn.title = stopMode
    ? "Stop generation"
    : "Send (Enter) · New line (Shift+Enter)";
  composer.placeholder = working
    ? "Queue a follow-up or stop the run…"
    : "Message EvoFlux…";
  stopBtn.style.display = "none";
}

function renderActivity() {
  const runningTool = [...toolActivities.values()].find((entry) => entry.state !== "done");
  const workingAgent = [...agentStates.entries()].find(([, state]) => state === "working");
  const working = Boolean(runningTool || workingAgent);
  activity.classList.toggle("visible", working && !liveMessage);
  renderComposerSubmitControl();
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
    void hydrateMarkdownMedia(liveMessage.content);
    scrollTranscriptToEnd();
  }, 80);
}

function flushLiveMarkdownRender() {
  clearTimeout(markdownRenderTimer);
  markdownRenderTimer = null;
  if (!liveMessage) return;
  globalThis.WebBridgeMarkdown?.render(liveMessage.content, liveMessage.rawContent);
  void hydrateMarkdownMedia(liveMessage.content);
  scrollTranscriptToEnd();
}

function handleStreamEvent(type, data) {
  if (type === "message") {
    const agent = data.agent || "EvoFlux";
    ensureLiveMessage(agent);
    liveMessage.rawContent += data.text || "";
    scheduleLiveMarkdownRender();
    return;
  }
  if (type === "thinking") {
    const agent = data.agent || "EvoFlux";
    const chars = Number.isFinite(data.chars) ? Math.max(0, data.chars) : 0;
    liveThinkingChars.set(agent, (liveThinkingChars.get(agent) || 0) + chars);
    renderLiveTurnDetails(agent);
    renderActivity();
    return;
  }
  if (type === "agent_status") {
    const agent = data.agent || "EvoFlux";
    agentStates.set(agent, data.status || "idle");
    if (data.status === "working") renderLiveTurnDetails(agent);
    if (data.status !== "working") {
      for (const [key, entry] of toolActivities) {
        if (!data.agent || entry.agent === data.agent) {
          toolActivities.set(key, { ...entry, state: "done" });
        }
      }
      if (liveMessage) renderLiveTurnDetails(liveMessage.agent);
    }
    renderActivity();
    return;
  }
  if (type === "activity") {
    const key = data.id || `${data.agent || "EvoFlux"}:${data.name || "tool"}`;
    toolActivities.set(key, data);
    renderLiveTurnDetails(data.agent || "EvoFlux");
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
    if (liveMessage) renderLiveTurnDetails(liveMessage.agent);
    renderActivity();
    setNotice(data.message || "EvoFlux stream failed.", "error");
    return;
  }
  if (type === "provider_status") {
    const providerStatus = data.status || "updated";
    if (providerStatus === "fallback") {
      setNotice(`Switching model to ${data.fallback || "a fallback provider"}.`, "info");
    } else if (providerStatus === "retrying") {
      setComposerStatus(`Provider retry ${data.attempt || ""}/${data.max_attempts || ""}`.replace(/\/$/, ""));
    } else if (providerStatus === "exhausted") {
      setNotice(`${data.model || "Provider"} exhausted retry attempts.`, "error");
    }
    return;
  }
  if (type === "done") {
    flushLiveMarkdownRender();
    if (liveMessage) renderLiveTurnDetails(liveMessage.agent);
    agentStates.clear();
    renderActivity();
    return;
  }
  if (type === "title_update" && data.title) {
    sessionTitle.textContent = data.title;
    const session = sessions.find((item) => item.id === selectedSessionId);
    if (session) session.title = data.title;
  }
}

async function isSessionStillRunning(sessionId) {
  const response = await panelFetch(SESSIONS_PATH);
  const nextSessions = await response.json();
  if (selectedSessionId !== sessionId) return false;
  sessions = nextSessions;
  return Boolean(sessions.find((session) => session.id === sessionId)?.running);
}

async function runStream(sessionId, generation) {
  let attempts = 0;
  while (generation === streamGeneration) {
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
      if (attempts > 0) setComposerStatus("Reconnected · EvoFlux is responding.");
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
        if (sawDone) return;
        if (!sawEvent && !(await isSessionStillRunning(sessionId))) {
          setComposerStatus("");
          return;
        }
      }
      if (sawEvent) attempts = 0;
    } catch (error) {
      if (generation === streamGeneration) streamController = null;
      if (error.name === "AbortError" || generation !== streamGeneration) return;
      if (error instanceof PanelHttpError && !error.retryable) {
        setNotice(error.message || String(error), "error");
        return;
      }
    }
    attempts += 1;
    const backoff = Math.min(5000, 250 * 2 ** Math.min(attempts - 1, 5));
    const retryDelay = Math.round(backoff * (0.85 + Math.random() * 0.3));
    setComposerStatus(`Connection interrupted · retrying in ${(retryDelay / 1000).toFixed(1)}s.`);
    await delay(retryDelay);
  }
}

function startStream() {
  if (!selectedSessionId) return;
  if (streamTask && streamingSessionId === selectedSessionId) return;
  stopStream();
  const generation = streamGeneration;
  const sessionId = selectedSessionId;
  streamingSessionId = sessionId;
  const task = runStream(sessionId, generation);
  streamTask = task;
  void task.then(
    () => finalizeStreamTask(task, generation),
    (error) => {
      finalizeStreamTask(task, generation);
      if (generation === streamGeneration) {
        setNotice(error?.message || String(error), "error");
      }
    },
  );
}

function finalizeStreamTask(task, generation) {
  if (streamTask !== task) return;
  streamTask = null;
  streamingSessionId = null;
  if (generation === streamGeneration) streamController = null;
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
    const contexts = panelContexts
      .filter((context) => context.tab_id === activeTab.id)
      .map(({ tab_id: _tabId, ...context }) => context);
    const screenshotKey = regionCapture?.tab_id === activeTab.id
      ? `${regionCapture.page_url}:${JSON.stringify(regionCapture.clip)}:${regionCapture.data_base64.length}`
      : "";
    const activeFiles = panelFileTabId === activeTab.id ? panelFiles : [];
    const filesKey = activeFiles
      .map((file) => `${file.name}:${file.size}:${file.lastModified}`)
      .join("|");
    const requestShape = await sha256(
      `${selectedSessionId}:${activeTab.id}:${sourceScope}:${content}:${elementKey}:${JSON.stringify(contexts)}:${screenshotKey}:${filesKey}:${currentSessionModel || "default"}:${currentSessionThinkingLevel || "default"}:${currentSessionFastMode}`
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
    const body = {
      content,
      tab_id: activeTab.id,
      binding_tab_id: selectedBinding()?.tab_id || activeTab.id,
      origin: sourceScope,
      user_gesture: true,
      fast_mode: currentSessionFastMode,
      element,
      contexts,
    };
    let response;
    if (activeFiles.length) {
      const form = new FormData();
      form.append("payload", JSON.stringify(body));
      for (const file of activeFiles) form.append("attachments", file, file.name);
      response = await panelFetch(
        `${SESSIONS_PATH}/${encodeURIComponent(selectedSessionId)}/messages/attachments`,
        {
          method: "POST",
          headers: { "Idempotency-Key": pendingComposerRequest.id },
          body: form,
        }
      );
    } else if (regionCapture?.tab_id === activeTab.id) {
      const form = new FormData();
      form.append("payload", JSON.stringify({
        ...body,
        screenshot: {
          page_url: regionCapture.page_url,
          captured_at: regionCapture.captured_at,
          clip: regionCapture.clip,
          viewport: regionCapture.viewport,
        },
      }));
      form.append("screenshot", base64PngBlob(regionCapture.data_base64), "browser-region.png");
      response = await panelFetch(
        `${SESSIONS_PATH}/${encodeURIComponent(selectedSessionId)}/messages/screenshot`,
        {
          method: "POST",
          headers: { "Idempotency-Key": pendingComposerRequest.id },
          body: form,
        }
      );
    } else {
      response = await panelFetch(
        `${SESSIONS_PATH}/${encodeURIComponent(selectedSessionId)}/messages`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": pendingComposerRequest.id,
          },
          body: JSON.stringify(body),
        }
      );
    }
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
    panelContexts = panelContexts.filter((context) => context.tab_id !== activeTab.id);
    panelFiles = [];
    panelFileTabId = null;
    if (regionCapture?.tab_id === activeTab.id) {
      await chrome.runtime.sendMessage({ type: "clear_region_capture" });
      regionCapture = null;
    }
    renderPanelContexts();
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
    renderComposerSubmitControl();
  }
}

async function submitIssueReport(report) {
  if (!selectedSessionId || !activeTab?.id || !isBoundToSelectedSession()) {
    throw new Error("This tab session is not ready for an issue report.");
  }
  const form = new FormData();
  form.append("payload", JSON.stringify({
    content: "Investigate the browser issue captured on this page. Use the attached screenshot and redacted diagnostics as evidence.",
    tab_id: activeTab.id,
    binding_tab_id: selectedBinding()?.tab_id || activeTab.id,
    origin: browserTabScope(activeTab),
    user_gesture: true,
    fast_mode: currentSessionFastMode,
    element: browserPanelElement(pickedElement, activeTab.id),
    contexts: [],
    diagnostics: report.diagnostics || [],
    screenshot: {
      page_url: report.capture.page_url,
      captured_at: report.capture.captured_at,
      clip: report.capture.clip,
      viewport: report.capture.viewport,
    },
  }));
  form.append("screenshot", base64PngBlob(report.capture.data_base64), "browser-issue.png");
  const response = await panelFetch(
    `${SESSIONS_PATH}/${encodeURIComponent(selectedSessionId)}/messages/screenshot`,
    {
      method: "POST",
      headers: { "Idempotency-Key": globalThis.crypto?.randomUUID?.() || `issue-${Date.now()}` },
      body: form,
    }
  );
  return response.json();
}

async function stopRun() {
  if (!selectedSessionId) {
    setNotice("This tab session is not ready yet.", "error");
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
    const connecting = Boolean(response?.connecting);
    const nativeConnection = response?.connection_mode === "native";
    const nativeError = response?.native_error || "";
    settingsStatusDot.className = `status-dot ${connected ? "live" : connecting ? "" : "error"}`.trim();
    settingsStatusText.textContent = connected ? "Connected" : connecting ? "Connecting…" : "Disconnected";
    settingsStatusDetail.textContent = connected
      ? nativeConnection
        ? `Connected automatically to EvoFlux Desktop (${response.relay_base || DEFAULT_RELAY_BASE})`
        : `Connected to ${response.relay_base || DEFAULT_RELAY_BASE}`
      : connecting
        ? nativeConnection
          ? "Discovering EvoFlux Desktop automatically…"
          : `Connecting to ${response.relay_base || DEFAULT_RELAY_BASE}`
        : nativeError
          ? `Native Messaging unavailable: ${nativeError}`
          : nativeConnection
          ? "Waiting for EvoFlux Desktop…"
          : "Start EvoFlux Desktop to connect WebBridge automatically.";
    toggleConnectionBtn.textContent = connected || connecting ? "Disconnect" : "Reconnect";
    textWatches = response?.text_watches || [];
    activeTextWatch = textWatches.find((item) => item.tab_id === activeTab?.id) || null;
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
    renderWatchList();
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
    const issueResponse = await chrome.runtime.sendMessage({ type: "get_issue_capture" });
    activeIssueCapture = issueResponse?.ok ? issueResponse.capture : null;
    issueCaptureBtn.textContent = activeIssueCapture ? "Stop capture" : "Start capture";
    reportIssueBtn.disabled = !activeIssueCapture || !selectedSessionId || !pageTools;
    issueCaptureBtn.disabled = !selectedSessionId || !pageTools;
    issueSettingsDetail.textContent = !pageTools
      ? "Available after this tab opens an HTTP(S) page."
      : activeIssueCapture
        ? `Collecting redacted errors on this page · ${activeIssueCapture.entry_count || 0} captured.`
        : "Opt in to collect a small redacted console/network error ring for this page.";
    retryContextBtn.style.display = response?.pending_interaction ? "inline-flex" : "none";
    releaseControlBtn.disabled = !(response?.attached_tab_ids?.length);
  } catch (error) {
    settingsStatusDot.className = "status-dot error";
    settingsStatusText.textContent = "Extension unavailable";
    settingsStatusDetail.textContent = error.message || String(error);
  }
}

function renderWatchList() {
  watchList.replaceChildren();
  stopAllWatchesBtn.style.display = textWatches.length ? "inline-flex" : "none";
  for (const watch of textWatches) {
    const item = document.createElement("div");
    item.className = "watch-item";
    const copy = document.createElement("div");
    copy.className = "watch-item-copy";
    const label = document.createElement("strong");
    label.textContent = `${watch.state === "matched" ? "Matched" : "Watching"}: ${watch.needle}`;
    const page = document.createElement("span");
    page.textContent = watch.page_url;
    copy.append(label, page);
    const action = document.createElement("button");
    action.type = "button";
    action.className = `btn${watch.state === "matched" ? " primary" : ""}`;
    action.textContent = watch.state === "matched" ? "Send" : "Cancel";
    action.addEventListener("click", async () => {
      action.disabled = true;
      const response = await chrome.runtime.sendMessage({
        type: watch.state === "matched" ? "send_matched_text_watch" : "cancel_text_watch",
        watch_id: watch.id,
      });
      if (!response?.ok) watchSettingsDetail.textContent = response?.error || "Could not update watch";
      await refreshSettings();
    });
    item.append(copy, action);
    watchList.append(item);
  }
}

async function stopAllWatches() {
  stopAllWatchesBtn.disabled = true;
  try {
    const response = await chrome.runtime.sendMessage({ type: "cancel_all_text_watches" });
    if (!response?.ok) throw new Error(response?.error || "Could not stop watches");
    await refreshSettings();
  } catch (error) {
    watchSettingsDetail.textContent = error.message || String(error);
  } finally {
    stopAllWatchesBtn.disabled = false;
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

async function toggleIssueCapture() {
  issueCaptureBtn.disabled = true;
  try {
    const response = await chrome.runtime.sendMessage({
      type: activeIssueCapture ? "stop_issue_capture" : "start_issue_capture",
    });
    if (!response?.ok) throw new Error(response?.error || "Could not update issue capture");
    await refreshSettings();
  } catch (error) {
    issueSettingsDetail.textContent = error.message || String(error);
  } finally {
    issueCaptureBtn.disabled = !selectedSessionId || !hasPageTools();
  }
}

async function reportIssue() {
  reportIssueBtn.disabled = true;
  issueSettingsDetail.textContent = "Capturing evidence…";
  try {
    const response = await chrome.runtime.sendMessage({ type: "collect_issue_report" });
    if (!response?.ok) throw new Error(response?.error || "Could not collect issue evidence");
    const result = await submitIssueReport(response.report);
    closeSettings();
    appendMessage({ role: "user", content: "Investigate the captured browser issue." });
    setComposerStatus(result.status === "queued" ? "Issue report queued." : "Issue report sent.");
    startStream();
  } catch (error) {
    issueSettingsDetail.textContent = error.message || String(error);
  } finally {
    await refreshSettings();
  }
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
openInEvoFluxBtn.addEventListener("click", () => void openInEvoFlux());
closeSettingsBtn.addEventListener("click", closeSettings);
settingsBackdrop.addEventListener("click", closeSettings);
toggleConnectionBtn.addEventListener("click", () => void toggleConnection());
themeControl.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-theme-value]");
  if (button) void setTheme(button.dataset.themeValue);
});
watchActionBtn.addEventListener("click", () => void runWatchAction());
stopAllWatchesBtn.addEventListener("click", () => void stopAllWatches());
teachActionBtn.addEventListener("click", () => void runTeachAction());
discardTeachBtn.addEventListener("click", () => void discardTeachRecording());
issueCaptureBtn.addEventListener("click", () => void toggleIssueCapture());
reportIssueBtn.addEventListener("click", () => void reportIssue());
retryContextBtn.addEventListener("click", () => void retryBrowserContext());
releaseControlBtn.addEventListener("click", () => void releaseBrowserControl());
newGroupedTabBtn.addEventListener("click", () => void openGroupedTab());
modelTrigger.addEventListener("click", () => void openModelPicker());
modelSearch.addEventListener("input", () => renderModelOptions(modelSearch.value));
modelList.addEventListener("click", (event) => {
  const option = event.target.closest("button[data-model-id]");
  if (option) void selectSessionModel(option.dataset.modelId || null);
});
thinkingOptions.addEventListener("click", (event) => {
  const option = event.target.closest("button[data-thinking-level]");
  if (option) void selectThinkingLevel(option.dataset.thinkingLevel || null);
});
speedControl.addEventListener("click", (event) => {
  const option = event.target.closest("button[data-speed]");
  if (option) selectResponseSpeed(option.dataset.speed === "fast");
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".model-picker")) closeModelPicker();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && modelPopover.classList.contains("visible")) {
    closeModelPicker();
    modelTrigger.focus();
  }
});
refreshBtn.addEventListener("click", () => void refreshPanel());
loadOlderBtn.addEventListener("click", () => {
  if (!historyCursor) return;
  loadOlderBtn.disabled = true;
  void loadHistory({ before: historyCursor, prepend: true }).finally(() => {
    loadOlderBtn.disabled = false;
  });
});
pickElementBtn.addEventListener("click", () => void startElementPicker());
attachPageBtn.addEventListener("click", () => void captureTextContext("readable_page"));
attachSelectionBtn.addEventListener("click", () => void captureTextContext("selection"));
captureRegionBtn.addEventListener("click", () => void startRegionCapture());
attachFileBtn.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => selectPanelFiles(fileInput.files || []));
clearElementBtn.addEventListener("click", () => void clearElement());
takeControlBtn.addEventListener("click", () => void takeHumanControl());
resumeAgentBtn.addEventListener("click", () => void resumeAgent());
sendBtn.addEventListener("click", () => {
  if (sendBtn.classList.contains("stop-mode")) void stopRun();
  else void sendMessage();
});
stopBtn.addEventListener("click", () => void stopRun());
composer.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    void sendMessage();
  }
});
composer.addEventListener("input", () => {
  resizeComposer();
  renderComposerSubmitControl();
});
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
  if (message?.type === "connection_state") {
    const isConnected = Boolean(message.connected);
    const isConnecting = Boolean(message.connecting);
    statusDot.className = `status-dot ${isConnected ? "live" : isConnecting ? "" : "error"}`.trim();
    if (settingsDrawer.classList.contains("visible")) void refreshSettings();
    return;
  }
  if (message?.type === "pairing_revoked") {
    stopStream();
    sessions = [];
    bindings = [];
    selectedSessionId = "";
    currentSessionModel = null;
    renderModelTrigger();
    pendingQuestions.clear();
    renderQuestions();
    showEmptyTranscript("The WebBridge connection was reset. Reconnect to continue.");
    setNotice("The WebBridge connection was reset.", "error");
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
  if (message?.type === "region_capture_ready") {
    if (message.capture?.tab_id !== activeTab?.id) return;
    regionCapture = message.capture;
    renderPanelContexts();
    if (annotationEditor) {
      openAnnotation(regionCapture.data_base64);
    } else {
      setComposerStatus("Screen region attached.");
    }
    return;
  }
  if (message?.type === "region_capture_error") {
    setComposerStatus(message.error || "Could not capture region", "error");
    return;
  }
  if (message?.type === "region_capture_cancelled") {
    setComposerStatus(message.reason === "too_small" ? "Select a larger region." : "Region capture cancelled.");
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
  if (!selectedSessionId || streamTask) return;
  const sessionId = selectedSessionId;
  try {
    const response = await panelFetch(SESSIONS_PATH);
    const nextSessions = await response.json();
    if (selectedSessionId !== sessionId) return;
    sessions = nextSessions;
    const session = sessions.find((item) => item.id === sessionId);
    if (session) {
      sessionTitle.textContent = session.title || "EvoFlux Side Chat";
      if (
        (session.model || null) !== currentSessionModel
        || (session.thinking_level || null) !== currentSessionThinkingLevel
      ) {
        renderModelTrigger(session);
        renderModelOptions(modelSearch.value);
        setComposerStatus("Model settings synced from EvoFlux.");
      }
    }
    if (session?.running) {
      startStream();
      await loadPendingQuestions();
    }
  } catch {
    // The main refresh surface reports connection errors.
  }
}

void initializeTheme();
void refreshPanel();
setInterval(() => {
  loadingVerbIndex = (loadingVerbIndex + 1) % LOADING_VERBS.length;
  if (activity.classList.contains("visible") && toolActivities.size === 0) renderActivity();
}, 2800);
setInterval(() => void refreshRunningState(), 2000);

function initAnnotationEditor() {
  if (!globalThis.WebBridgeAnnotation) return;
  annotationEditor = new globalThis.WebBridgeAnnotation.AnnotationEditor(annotationOverlay);

  annotationOverlay.addEventListener("annotation:toolchange", (e) => {
    for (const btn of annotationToolbar.querySelectorAll("[data-tool]")) {
      btn.classList.toggle("active", btn.dataset.tool === e.detail.tool);
    }
  });
  annotationOverlay.addEventListener("annotation:colorchange", (e) => {
    for (const btn of annotationToolbar.querySelectorAll("[data-color]")) {
      btn.classList.toggle("active", btn.dataset.color === e.detail.color);
    }
  });
  annotationOverlay.addEventListener("annotation:strokechange", (e) => {
    for (const btn of annotationToolbar.querySelectorAll("[data-stroke]")) {
      btn.classList.toggle("active", btn.dataset.stroke === e.detail.stroke);
    }
  });
  annotationOverlay.addEventListener("annotation:cancel", () => void closeAnnotation(true));

  annotationToolbar.addEventListener("click", (e) => {
    const toolBtn = e.target.closest("[data-tool]");
    if (toolBtn) { annotationEditor.setTool(toolBtn.dataset.tool); return; }
    const colorBtn = e.target.closest("[data-color]");
    if (colorBtn) { annotationEditor.setColor(colorBtn.dataset.color); return; }
    const strokeBtn = e.target.closest("[data-stroke]");
    if (strokeBtn) { annotationEditor.setStroke(strokeBtn.dataset.stroke); return; }
  });

  annotationUndoBtn.addEventListener("click", () => annotationEditor.undo());
  annotationRedoBtn.addEventListener("click", () => annotationEditor.redo());
  annotationClearBtn.addEventListener("click", () => annotationEditor.clearAll());
  annotationCancelBtn.addEventListener("click", () => void closeAnnotation(true));
  annotationSkipBtn.addEventListener("click", () => void skipAnnotation());
  annotationConfirmBtn.addEventListener("click", () => void confirmAnnotation());

  previewBackBtn.addEventListener("click", () => void backToAnnotation());
  previewEditBtn.addEventListener("click", () => void backToAnnotation());
  previewCancelBtn.addEventListener("click", () => void closePreview(true));
  previewSendBtn.addEventListener("click", () => void sendFromPreview());
}

function openAnnotation(base64Png) {
  if (!annotationEditor) return;
  annotationActive = true;
  annotatedDataBase64 = null;
  annotationEditor.open(base64Png);
  setComposerStatus("Annotate the screenshot or skip to send as-is.");
}

function closeAnnotation(clearCapture) {
  annotationActive = false;
  annotatedDataBase64 = null;
  if (annotationEditor) annotationEditor.close();
  if (clearCapture && regionCapture?.tab_id === activeTab?.id) {
    void chrome.runtime.sendMessage({ type: "clear_region_capture" });
    regionCapture = null;
    renderPanelContexts();
    setComposerStatus("Screenshot discarded.");
  }
}

function skipAnnotation() {
  if (!regionCapture) { closeAnnotation(false); return; }
  annotatedDataBase64 = null;
  annotationActive = false;
  if (annotationEditor) annotationEditor.close();
  openPreview(regionCapture.data_base64, false);
}

function confirmAnnotation() {
  if (!annotationEditor) return;
  const png = annotationEditor.exportPng();
  if (!png) { setComposerStatus("Could not export annotated image.", "error"); return; }
  annotatedDataBase64 = png;
  annotationActive = false;
  annotationEditor.close();
  openPreview(png, true);
}

function openPreview(base64Png, isAnnotated) {
  previewActive = true;
  previewImage.src = `data:image/png;base64,${base64Png}`;
  const bytes = Math.round((base64Png.length * 3) / 4);
  const sizeLabel = bytes > 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${bytes} B`;
  const dim = regionCapture?.clip
    ? `${Math.round(regionCapture.clip.width)}×${Math.round(regionCapture.clip.height)}`
    : "";
  previewMeta.textContent = [
    isAnnotated ? "Annotated" : "Original",
    dim ? `${dim}px` : "",
    sizeLabel,
  ].filter(Boolean).join(" · ");
  previewOverlay.classList.add("visible");
}

function closePreview(clearCapture) {
  previewActive = false;
  previewOverlay.classList.remove("visible");
  previewImage.src = "";
  if (clearCapture) {
    closeAnnotation(true);
  }
}

function backToAnnotation() {
  previewActive = false;
  previewOverlay.classList.remove("visible");
  previewImage.src = "";
  if (regionCapture?.data_base64) {
    openAnnotation(regionCapture.data_base64);
  }
}

async function sendFromPreview() {
  previewActive = false;
  previewOverlay.classList.remove("visible");
  previewImage.src = "";

  if (annotatedDataBase64 && regionCapture?.tab_id === activeTab?.id) {
    regionCapture.data_base64 = annotatedDataBase64;
  }
  setComposerStatus("Sending screenshot…");
  await sendMessage();
}

initAnnotationEditor();
