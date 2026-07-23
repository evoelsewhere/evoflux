/* EvoFlux WebBridge P2 Side Panel.
 *
 * The panel is an extension page, so it may safely read the pairing credential
 * from extension storage. It only sends that credential in Authorization
 * headers to the relay it was paired with; never in URLs or page contexts.
 */

const DEFAULT_RELAY_BASE = "ws://127.0.0.1:8000";
const SESSIONS_PATH = "/api/team/webbridge/sessions";
const BINDINGS_PATH = "/api/team/webbridge/bindings";

const pageTitle = document.getElementById("pageTitle");
const statusDot = document.getElementById("statusDot");
const stopBtn = document.getElementById("stopBtn");
const sessionSelect = document.getElementById("sessionSelect");
const refreshBtn = document.getElementById("refreshBtn");
const bindBtn = document.getElementById("bindBtn");
const unbindBtn = document.getElementById("unbindBtn");
const pickElementBtn = document.getElementById("pickElementBtn");
const takeControlBtn = document.getElementById("takeControlBtn");
const resumeAgentBtn = document.getElementById("resumeAgentBtn");
const bindingStatus = document.getElementById("bindingStatus");
const controlStatus = document.getElementById("controlStatus");
const pickedElementStatus = document.getElementById("pickedElementStatus");
const pickedElementCard = document.getElementById("pickedElementCard");
const pickedElementLabel = document.getElementById("pickedElementLabel");
const clearElementBtn = document.getElementById("clearElementBtn");
const notice = document.getElementById("notice");
const transcript = document.getElementById("transcript");
const questionsRoot = document.getElementById("questions");
const composer = document.getElementById("composer");
const sendBtn = document.getElementById("sendBtn");
const composerStatus = document.getElementById("composerStatus");

let relayBase = DEFAULT_RELAY_BASE;
let pairingCredential = "";
let pairingRelayBase = "";
let activeTab = null;
let sessions = [];
let bindings = [];
let selectedSessionId = "";
let streamController = null;
let streamGeneration = 0;
let liveMessage = null;
let pendingQuestions = new Map();
let humanControlLease = null;
let pendingComposerRequest = null;
let pickedElement = null;
let composerSending = false;
const PANEL_REQUEST_STORAGE_KEY = "webbridgePanelPendingRequest";

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
  return bindings.find((binding) => binding.tab_id === activeTab?.id) || null;
}

function isBoundToSelectedSession() {
  const binding = selectedBinding();
  return Boolean(
    binding &&
    binding.session_id === selectedSessionId &&
    binding.origin === browserOrigin(activeTab?.url || activeTab?.pendingUrl || "")
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
  sessionSelect.disabled = disabled;
  refreshBtn.disabled = disabled;
  bindBtn.disabled = disabled;
  unbindBtn.disabled = disabled;
  pickElementBtn.disabled = disabled;
  takeControlBtn.disabled = disabled;
  resumeAgentBtn.disabled = disabled;
  composer.disabled = disabled;
  sendBtn.disabled = disabled;
  stopBtn.disabled = disabled;
}

function renderPickedElement() {
  const active = pickedElement?.tab_id === activeTab?.id;
  pickedElementCard.style.display = active ? "flex" : "none";
  pickedElementStatus.textContent = active
    ? `Picked ${pickedElement.role || pickedElement.tag || "element"}: ${pickedElement.name || pickedElement.text || pickedElement.selector}`
    : "";
  pickedElementLabel.textContent = active
    ? `${pickedElement.name || pickedElement.text || pickedElement.selector}`
    : "";
  pickElementBtn.textContent = active ? "Pick another" : "Pick element";
}

async function refreshPickedElement() {
  const response = await chrome.runtime.sendMessage({ type: "get_picked_element" });
  if (!response?.ok) throw new Error(response?.error || "Could not read picked element");
  pickedElement = response.element || null;
  renderPickedElement();
}

function renderHumanControl() {
  const active = humanControlLease?.tab_id === activeTab?.id;
  takeControlBtn.style.display = active ? "none" : "inline-flex";
  resumeAgentBtn.style.display = active ? "inline-flex" : "none";
  controlStatus.textContent = active
    ? "You control this tab"
    : "";
  controlStatus.className = active ? "binding warn" : "binding";
}

async function refreshHumanControl() {
  const response = await chrome.runtime.sendMessage({ type: "get_human_control" });
  if (!response?.ok) throw new Error(response?.error || "Could not read human control state");
  humanControlLease = response.lease || null;
  renderHumanControl();
}

function renderSessionOptions() {
  const previouslySelected = selectedSessionId;
  sessionSelect.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Choose a browser session";
  sessionSelect.append(placeholder);
  for (const session of sessions) {
    const option = document.createElement("option");
    option.value = session.id;
    option.textContent = session.title || "Untitled session";
    sessionSelect.append(option);
  }
  const currentBinding = selectedBinding();
  const candidate = currentBinding?.session_id || previouslySelected;
  selectedSessionId = sessions.some((session) => session.id === candidate) ? candidate : "";
  sessionSelect.value = selectedSessionId;
}

function renderBindingStatus() {
  const pageUrl = safePageUrl(activeTab?.url || activeTab?.pendingUrl || "");
  const bound = isBoundToSelectedSession();
  bindBtn.disabled = !selectedSessionId || !pageUrl;
  unbindBtn.disabled = !selectedBinding();
  bindBtn.style.display = bound ? "none" : "inline-flex";
  unbindBtn.style.display = bound ? "inline-flex" : "none";
  if (!pageUrl) {
    bindingStatus.textContent = "Open an HTTP(S) page to use browser tools";
    bindingStatus.className = "binding warn";
    return;
  }
  if (bound) {
    bindingStatus.textContent = "Tab connected";
    bindingStatus.className = "binding ok";
    return;
  }
  bindingStatus.textContent = selectedSessionId
    ? "Connect this tab to send messages"
    : "Choose a session";
  bindingStatus.className = "binding";
}

function clearTranscript() {
  transcript.replaceChildren();
  liveMessage = null;
}

function scrollTranscriptToEnd() {
  transcript.scrollTop = transcript.scrollHeight;
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
    showEmptyTranscript("Bind this tab to a browser session to see its transcript.");
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

async function refreshPanel({ preserveTranscript = false } = {}) {
  setControlsDisabled(true);
  try {
    await loadConfig();
    const nextTab = await currentTab();
    if (activeTab && activeTab.id !== nextTab.id) stopStream();
    activeTab = nextTab;
    pageTitle.textContent = activeTab.title || safePageUrl(activeTab.url || activeTab.pendingUrl || "WebBridge Side Panel");
    const [sessionResponse, bindingResponse] = await Promise.all([
      panelFetch(SESSIONS_PATH),
      panelFetch(BINDINGS_PATH),
    ]);
    sessions = await sessionResponse.json();
    bindings = await bindingResponse.json();
    renderSessionOptions();
    renderBindingStatus();
    await refreshHumanControl();
    await refreshPickedElement();
    statusDot.className = "status-dot live";
    clearNotice();
    if (!preserveTranscript) await loadHistory();
    await loadPendingQuestions();
    if (sessions.find((session) => session.id === selectedSessionId)?.running) {
      startStream();
    }
  } catch (error) {
    statusDot.className = "status-dot error";
    setNotice(error.message || String(error), "error");
    showEmptyTranscript("Connect a securely paired WebBridge extension to use this panel.");
  } finally {
    setControlsDisabled(false);
    renderBindingStatus();
  }
}

async function bindCurrentTab() {
  if (!selectedSessionId || !activeTab?.id) return;
  const origin = browserOrigin(activeTab.url || activeTab.pendingUrl || "");
  if (!origin) {
    setNotice("Side Panel only works on HTTP(S) pages.", "error");
    return;
  }
  setControlsDisabled(true);
  try {
    await panelFetch(`${BINDINGS_PATH}/${encodeURIComponent(activeTab.id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: selectedSessionId,
        origin,
        page_instance_id: `${activeTab.id}:${safePageUrl(activeTab.url || activeTab.pendingUrl || "")}`.slice(0, 128),
      }),
    });
    await refreshPanel();
  } catch (error) {
    setNotice(error.message || String(error), "error");
  } finally {
    setControlsDisabled(false);
  }
}

async function unbindCurrentTab() {
  if (!activeTab?.id) return;
  setControlsDisabled(true);
  try {
    await panelFetch(`${BINDINGS_PATH}/${encodeURIComponent(activeTab.id)}`, { method: "DELETE" });
    stopStream();
    await refreshPanel();
  } catch (error) {
    setNotice(error.message || String(error), "error");
  } finally {
    setControlsDisabled(false);
  }
}

async function takeHumanControl() {
  setControlsDisabled(true);
  try {
    const response = await chrome.runtime.sendMessage({ type: "take_human_control" });
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
    const response = await chrome.runtime.sendMessage({ type: "release_human_control" });
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
  pickElementBtn.disabled = true;
  try {
    const response = await chrome.runtime.sendMessage({ type: "start_element_picker" });
    if (!response?.ok) throw new Error(response?.error || "Could not start element picker");
    setNotice("Move over the page and click an element. Press Escape to cancel.");
  } catch (error) {
    setNotice(error.message || String(error), "error");
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

function handleStreamEvent(type, data) {
  if (type === "message") {
    const agent = data.agent || "EvoFlux";
    if (!liveMessage || liveMessage.agent !== agent) {
      liveMessage = { agent, ...appendMessage({ role: "assistant", agent, content: "" }, { live: true }) };
    }
    liveMessage.rawContent += data.text || "";
    globalThis.WebBridgeMarkdown?.render(liveMessage.content, liveMessage.rawContent);
    scrollTranscriptToEnd();
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
    setNotice(data.message || "EvoFlux stream failed.", "error");
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
  const origin = browserOrigin(activeTab?.url || activeTab?.pendingUrl || "");
  if (!content || !selectedSessionId || !activeTab?.id || !origin) return;
  if (!isBoundToSelectedSession()) {
    setNotice("Bind this tab to the selected session before sending a message.", "error");
    return;
  }
  composerSending = true;
  sendBtn.disabled = true;
  setComposerStatus("Sending...");
  try {
    const elementKey = pickedElement?.tab_id === activeTab.id
      ? `${pickedElement.page_url}:${pickedElement.selector}`
      : "";
    const requestShape = await sha256(
      `${selectedSessionId}:${activeTab.id}:${origin}:${content}:${elementKey}`
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
          origin,
          user_gesture: true,
          element: pickedElement?.tab_id === activeTab.id ? pickedElement : null,
        }),
      }
    );
    const result = await response.json();
    if (result.status !== "pending") {
      pendingComposerRequest = null;
      await panelSessionStorage().remove([PANEL_REQUEST_STORAGE_KEY]);
      composer.value = "";
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
    setNotice("Choose a browser session before stopping a run.", "error");
    return;
  }
  stopBtn.disabled = true;
  try {
    await panelFetch(
      `${SESSIONS_PATH}/${encodeURIComponent(selectedSessionId)}/interrupt`,
      { method: "POST" }
    );
    stopStream();
    setComposerStatus("Run stopped.");
    await loadHistory();
    await loadPendingQuestions();
  } catch (error) {
    setNotice(error.message || String(error), "error");
  } finally {
    stopBtn.disabled = false;
  }
}

sessionSelect.addEventListener("change", async () => {
  selectedSessionId = sessionSelect.value;
  stopStream();
  renderBindingStatus();
  try {
    await loadHistory();
    await loadPendingQuestions();
    if (sessions.find((session) => session.id === selectedSessionId)?.running) {
      startStream();
    }
  } catch (error) {
    setNotice(error.message || String(error), "error");
  }
});
refreshBtn.addEventListener("click", () => void refreshPanel());
bindBtn.addEventListener("click", () => void bindCurrentTab());
unbindBtn.addEventListener("click", () => void unbindCurrentTab());
pickElementBtn.addEventListener("click", () => void startElementPicker());
clearElementBtn.addEventListener("click", () => void clearElement());
takeControlBtn.addEventListener("click", () => void takeHumanControl());
resumeAgentBtn.addEventListener("click", () => void resumeAgent());
sendBtn.addEventListener("click", () => void sendMessage());
stopBtn.addEventListener("click", () => void stopRun());
composer.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    event.preventDefault();
    void sendMessage();
  }
});
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
    pendingQuestions.clear();
    renderQuestions();
    showEmptyTranscript("WebBridge pairing was revoked. Pair the extension again to continue.");
    setNotice("WebBridge pairing was revoked.", "error");
    statusDot.className = "status-dot error";
    return;
  }
  if (message?.type !== "element_picker_result") return;
  pickedElement = message.element || null;
  renderPickedElement();
  clearNotice();
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

void refreshPanel();
setInterval(() => void refreshRunningState(), 2000);