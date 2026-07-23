/**
 * EvoFlux WebBridge — Popup script
 * Shows connection status and configures the relay URL.
 */

const DEFAULT_RELAY_BASE = "ws://127.0.0.1:8000";

const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const statusDetail = document.getElementById("statusDetail");
const tabInfo = document.getElementById("tabInfo");
const tabTitle = document.getElementById("tabTitle");
const tabUrl = document.getElementById("tabUrl");
const controlDetail = document.getElementById("controlDetail");
const connectBtn = document.getElementById("connectBtn");
const releaseBtn = document.getElementById("releaseBtn");
const relayBaseInput = document.getElementById("relayBase");
const pairingCard = document.getElementById("pairingCard");
const localPairBtn = document.getElementById("localPairBtn");
const pairingCodeInput = document.getElementById("pairingCode");
const pairBtn = document.getElementById("pairBtn");
const pairingDetail = document.getElementById("pairingDetail");
const browserContextCard = document.getElementById("browserContextCard");
const openSidePanelBtn = document.getElementById("openSidePanelBtn");
const sessionSelect = document.getElementById("sessionSelect");
const bindSessionBtn = document.getElementById("bindSessionBtn");
const newSessionBtn = document.getElementById("newSessionBtn");
const quickPrompt = document.getElementById("quickPrompt");
const sendPagePromptBtn = document.getElementById("sendPagePromptBtn");
const retryInteractionBtn = document.getElementById("retryInteractionBtn");
const browserContextDetail = document.getElementById("browserContextDetail");
const watchNeedle = document.getElementById("watchNeedle");
const watchTtl = document.getElementById("watchTtl");
const armWatchBtn = document.getElementById("armWatchBtn");
const sendWatchBtn = document.getElementById("sendWatchBtn");
const cancelWatchBtn = document.getElementById("cancelWatchBtn");
const watchDetail = document.getElementById("watchDetail");
const startTeachBtn = document.getElementById("startTeachBtn");
const stopTeachBtn = document.getElementById("stopTeachBtn");
const cancelTeachBtn = document.getElementById("cancelTeachBtn");
const teachDetail = document.getElementById("teachDetail");
const extensionVersion = document.getElementById("extensionVersion");
let activeTabId = null;
let activeTextWatch = null;
let activeTeachRecording = null;

// ── Config ───────────────────────────────────────────────────────────────────

async function loadConfig() {
  try {
    const cfg = await chrome.storage.local.get(["relayBase"]);
    relayBaseInput.value = cfg.relayBase || DEFAULT_RELAY_BASE;
    await chrome.storage.local.remove(["accessToken"]);
  } catch {
    relayBaseInput.value = DEFAULT_RELAY_BASE;
  }
}

let saveTimer = null;

// Debounced: save config and tell the service worker to reconnect.
function onConfigInput() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveConfig, 500);
}

async function saveConfig(notify = true) {
  clearTimeout(saveTimer);
  await chrome.storage.local.set({
    relayBase: relayBaseInput.value.trim() || DEFAULT_RELAY_BASE,
  });
  await chrome.storage.local.remove(["accessToken"]);
  if (!notify) return;
  try {
    await chrome.runtime.sendMessage({ type: "config_updated" });
  } catch {
    // Service worker not running yet — it reads storage on startup anyway.
  }
}

// ── Status ───────────────────────────────────────────────────────────────────

async function updateStatus() {
  try {
    const response = await chrome.runtime.sendMessage({ type: "get_status" });
    if (response?.active_tab) activeTabId = response.active_tab.id ?? null;

    if (response && response.connected) {
      statusDot.className = "status-dot connected";
      statusText.textContent = "Connected";
      statusDetail.className = "detail";
      statusDetail.textContent = `Securely paired: ${response.pairing_id || "connected"}`;

      if (response.active_tab) {
        tabInfo.style.display = "block";
        tabTitle.textContent = response.active_tab.title || "Untitled";
        tabUrl.textContent = response.active_tab.url || "No URL";
      } else {
        tabInfo.style.display = "none";
      }

      connectBtn.textContent = "Disconnect";
      connectBtn.className = "btn btn-danger";
    } else if (response && response.last_close_reason === "pairing") {
      statusDot.className = "status-dot disconnected";
      statusText.textContent = "Pairing required";
      statusDetail.className = "detail auth-error";
      statusDetail.textContent = "The pairing was rejected or revoked. Generate a new code in EvoFlux.";
      tabInfo.style.display = "none";
      connectBtn.textContent = "Reconnect";
      connectBtn.className = "btn btn-primary";
    } else if (response && response.last_close_reason === "security") {
      statusDot.className = "status-dot disconnected";
      statusText.textContent = "Insecure relay URL"
      statusDetail.className = "detail auth-error";
      statusDetail.textContent = "Remote relays must use HTTPS or WSS. Plaintext is only allowed on loopback.";
      tabInfo.style.display = "none";
      connectBtn.textContent = "Reconnect";
      connectBtn.className = "btn btn-primary";
    } else if (response && response.last_close_reason === "ticket") {
      statusDot.className = "status-dot disconnected";
      statusText.textContent = "Ticket rejected";
      statusDetail.className = "detail auth-error";
      statusDetail.textContent = "The single-use relay ticket was invalid or expired. Reconnect to mint a new ticket.";
      tabInfo.style.display = "none";
      connectBtn.textContent = "Reconnect";
      connectBtn.className = "btn btn-primary";
    } else {
      statusDot.className = "status-dot disconnected";
      statusText.textContent = "Disconnected";
      statusDetail.className = "detail";
      statusDetail.textContent = "Not connected to EvoFlux relay server.";
      tabInfo.style.display = "none";
      connectBtn.textContent = "Reconnect";
      connectBtn.className = "btn btn-primary";
    }

    const attachedCount = response?.attached_tab_ids?.length || 0;
    controlDetail.textContent = attachedCount
      ? `Browser control active on ${attachedCount} tab${attachedCount === 1 ? "" : "s"}.`
      : "No tabs currently controlled.";
    releaseBtn.style.display = attachedCount ? "block" : "none";
    pairingCard.style.display = response?.paired ? "none" : "block";
    browserContextCard.style.display = response?.paired ? "block" : "none";
    retryInteractionBtn.style.display = response?.pending_interaction ? "block" : "none";
    if (response?.pending_interaction) {
      browserContextDetail.textContent = "A browser context send is waiting to retry.";
    }
    if (response?.last_interaction) {
      const interaction = response.last_interaction;
      browserContextDetail.textContent = interaction.error
        ? `Last send failed: ${interaction.error}`
        : `Last browser context: ${interaction.status || "sent"}.`;
    }
    activeTextWatch = (response?.text_watches || []).find(
      (watch) => watch.tab_id === activeTabId,
    ) || null;
    const watchMatched = activeTextWatch?.state === "matched";
    armWatchBtn.style.display = activeTextWatch ? "none" : "block";
    cancelWatchBtn.style.display = activeTextWatch ? "block" : "none";
    sendWatchBtn.style.display = watchMatched ? "block" : "none";
    watchNeedle.disabled = Boolean(activeTextWatch);
    watchTtl.disabled = Boolean(activeTextWatch);
    if (activeTextWatch) {
      watchDetail.textContent = watchMatched
        ? `Matched "${activeTextWatch.needle}". Confirm before sending it to EvoFlux.`
        : `Watching for "${activeTextWatch.needle}" on this page.`;
    } else {
      watchDetail.textContent = "A match waits for your confirmation before EvoFlux receives it.";
    }
    activeTeachRecording = response?.teach_recording || null;
    const teachingThisTab = activeTeachRecording?.tab_id === activeTabId;
    const isRecording = teachingThisTab && activeTeachRecording.state === "recording";
    startTeachBtn.style.display = activeTeachRecording ? "none" : "block";
    stopTeachBtn.style.display = teachingThisTab ? "block" : "none";
    cancelTeachBtn.style.display = teachingThisTab ? "block" : "none";
    if (activeTeachRecording) {
      if (teachingThisTab) {
        teachDetail.textContent = isRecording
          ? activeTeachRecording.truncated
            ? "Recording reached the 50-action limit. Stop and review this draft."
            : `Recording ${activeTeachRecording.action_count} semantic action${activeTeachRecording.action_count === 1 ? "" : "s"}.`
          : activeTeachRecording.stop_reason || "Ready to save the recorded draft.";
      } else {
        teachDetail.textContent = "Teach Mode is active in another browser tab.";
      }
    } else if (response?.last_teach_draft) {
      teachDetail.textContent = "Draft saved. Review and approve it in EvoFlux before replay.";
    } else {
      teachDetail.textContent = "Recorded actions become an EvoFlux draft for review and supervised replay.";
    }
  } catch (e) {
    // Background script might not be ready
    statusDot.className = "status-dot connecting";
    statusText.textContent = "Starting...";
    statusDetail.className = "detail";
    statusDetail.textContent = "Extension service worker is initializing...";
    connectBtn.textContent = "Reconnect";
    connectBtn.className = "btn btn-primary";
    controlDetail.textContent = "Browser control state unavailable.";
    releaseBtn.style.display = "none";
  }
}

function setBrowserControlsDisabled(disabled) {
  openSidePanelBtn.disabled = disabled;
  bindSessionBtn.disabled = disabled;
  newSessionBtn.disabled = disabled;
  sendPagePromptBtn.disabled = disabled;
  retryInteractionBtn.disabled = disabled;
  armWatchBtn.disabled = disabled;
  sendWatchBtn.disabled = disabled;
  cancelWatchBtn.disabled = disabled;
  startTeachBtn.disabled = disabled;
  stopTeachBtn.disabled = disabled;
  cancelTeachBtn.disabled = disabled;
}

async function refreshBrowserSessions() {
  try {
    const response = await chrome.runtime.sendMessage({ type: "get_browser_sessions" });
    if (!response?.ok) throw new Error(response?.error || "Could not load sessions");
    const selected = response.bindings?.find((binding) => binding.tab_id === activeTabId)?.session_id || sessionSelect.value;
    sessionSelect.replaceChildren();
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = "No browser session selected";
    sessionSelect.append(empty);
    for (const session of response.sessions || []) {
      const option = document.createElement("option");
      option.value = session.id;
      option.textContent = session.title || "Untitled session";
      option.selected = option.value === selected;
      sessionSelect.append(option);
    }
    browserContextDetail.textContent = selected
      ? "This tab is bound to the selected EvoFlux session."
      : "Choose a recent session or create one for this tab.";
  } catch (e) {
    browserContextDetail.textContent = e.message || String(e);
  }
}

async function bindCurrentTab() {
  const sessionId = sessionSelect.value;
  if (!sessionId) {
    browserContextDetail.textContent = "Choose a session first.";
    return;
  }
  setBrowserControlsDisabled(true);
  try {
    const response = await chrome.runtime.sendMessage({ type: "bind_tab_session", session_id: sessionId });
    if (!response?.ok) throw new Error(response?.error || "Could not bind this tab");
    browserContextDetail.textContent = "Current tab bound to the selected session.";
  } catch (e) {
    browserContextDetail.textContent = e.message || String(e);
  } finally {
    setBrowserControlsDisabled(false);
  }
}

async function createBrowserSession() {
  setBrowserControlsDisabled(true);
  try {
    const response = await chrome.runtime.sendMessage({ type: "create_browser_session" });
    if (!response?.ok) throw new Error(response?.error || "Could not create browser session");
    await refreshBrowserSessions();
    sessionSelect.value = response.session.id;
    browserContextDetail.textContent = "Created and bound a browser session for this tab.";
  } catch (e) {
    browserContextDetail.textContent = e.message || String(e);
  } finally {
    setBrowserControlsDisabled(false);
  }
}

async function sendQuickPrompt() {
  setBrowserControlsDisabled(true);
  browserContextDetail.textContent = "Sending page context...";
  try {
    const response = await chrome.runtime.sendMessage({
      type: "send_page_prompt",
      prompt: quickPrompt.value,
      session_id: sessionSelect.value || null,
    });
    if (!response?.ok) throw new Error(response?.error || "Could not send browser context");
    quickPrompt.value = "";
    browserContextDetail.textContent = `Sent to EvoFlux (${response.result.status || "accepted"}).`;
    await refreshBrowserSessions();
  } catch (e) {
    browserContextDetail.textContent = e.message || String(e);
  } finally {
    setBrowserControlsDisabled(false);
  }
}

async function retryPendingInteraction() {
  setBrowserControlsDisabled(true);
  browserContextDetail.textContent = "Retrying browser context...";
  try {
    const response = await chrome.runtime.sendMessage({ type: "retry_pending_interaction" });
    if (!response?.ok) throw new Error(response?.error || "Could not retry browser context");
    browserContextDetail.textContent = `Sent to EvoFlux (${response.result.status || "accepted"}).`;
    await updateStatus();
  } catch (e) {
    browserContextDetail.textContent = e.message || String(e);
    await updateStatus();
  } finally {
    setBrowserControlsDisabled(false);
  }
}

async function armTextWatch() {
  const sessionId = sessionSelect.value;
  if (!sessionId) {
    watchDetail.textContent = "Choose a browser session first.";
    return;
  }
  if (!watchNeedle.value.trim()) {
    watchDetail.textContent = "Enter text to watch for.";
    return;
  }
  setBrowserControlsDisabled(true);
  watchDetail.textContent = "Arming text watch...";
  try {
    const response = await chrome.runtime.sendMessage({
      type: "arm_text_watch",
      session_id: sessionId,
      needle: watchNeedle.value,
      ttl_minutes: watchTtl.value,
    });
    if (!response?.ok) throw new Error(response?.error || "Could not arm text watch");
    activeTextWatch = response.watch;
    await updateStatus();
  } catch (e) {
    watchDetail.textContent = e.message || String(e);
  } finally {
    setBrowserControlsDisabled(false);
  }
}

async function cancelTextWatch() {
  if (!activeTextWatch) return;
  setBrowserControlsDisabled(true);
  try {
    const response = await chrome.runtime.sendMessage({
      type: "cancel_text_watch",
      watch_id: activeTextWatch.id,
    });
    if (!response?.ok) throw new Error(response?.error || "Could not cancel text watch");
    activeTextWatch = null;
    await updateStatus();
  } catch (e) {
    watchDetail.textContent = e.message || String(e);
  } finally {
    setBrowserControlsDisabled(false);
  }
}

async function sendMatchedTextWatch() {
  if (!activeTextWatch) return;
  setBrowserControlsDisabled(true);
  watchDetail.textContent = "Sending matched watch...";
  try {
    const response = await chrome.runtime.sendMessage({
      type: "send_matched_text_watch",
      watch_id: activeTextWatch.id,
    });
    if (!response?.ok) throw new Error(response?.error || "Could not send matched watch");
    activeTextWatch = null;
    watchDetail.textContent = `Sent to EvoFlux (${response.result.status || "accepted"}).`;
    await refreshBrowserSessions();
    await updateStatus();
  } catch (e) {
    watchDetail.textContent = e.message || String(e);
    await updateStatus();
  } finally {
    setBrowserControlsDisabled(false);
  }
}

async function startTeachRecording() {
  const sessionId = sessionSelect.value;
  if (!sessionId) {
    teachDetail.textContent = "Choose a browser session first.";
    return;
  }
  setBrowserControlsDisabled(true);
  teachDetail.textContent = "Starting Teach Mode...";
  try {
    const response = await chrome.runtime.sendMessage({
      type: "start_teach_recording",
      session_id: sessionId,
    });
    if (!response?.ok) throw new Error(response?.error || "Could not start Teach Mode");
    activeTeachRecording = response.recording;
    await updateStatus();
  } catch (e) {
    teachDetail.textContent = e.message || String(e);
  } finally {
    setBrowserControlsDisabled(false);
  }
}

async function stopTeachRecording() {
  setBrowserControlsDisabled(true);
  teachDetail.textContent = "Saving Teach draft...";
  try {
    const response = await chrome.runtime.sendMessage({ type: "stop_teach_recording" });
    if (!response?.ok) throw new Error(response?.error || "Could not save Teach draft");
    activeTeachRecording = null;
    teachDetail.textContent = "Draft saved. Review and approve it in EvoFlux before replay.";
    await updateStatus();
  } catch (e) {
    teachDetail.textContent = e.message || String(e);
  } finally {
    setBrowserControlsDisabled(false);
  }
}

async function cancelTeachRecording() {
  setBrowserControlsDisabled(true);
  try {
    const response = await chrome.runtime.sendMessage({ type: "cancel_teach_recording" });
    if (!response?.ok) throw new Error(response?.error || "Could not discard Teach recording");
    activeTeachRecording = null;
    await updateStatus();
  } catch (e) {
    teachDetail.textContent = e.message || String(e);
  } finally {
    setBrowserControlsDisabled(false);
  }
}

async function pairExtension() {
  const code = pairingCodeInput.value.trim().toUpperCase();
  if (!code) {
    pairingDetail.textContent = "Enter the one-time code shown in EvoFlux.";
    return;
  }
  pairBtn.disabled = true;
  pairingDetail.textContent = "Pairing...";
  await saveConfig(false);
  try {
    const result = await chrome.runtime.sendMessage({ type: "pair_with_code", code });
    if (!result?.ok) throw new Error(result?.error || "Pairing failed");
    pairingCodeInput.value = "";
    pairingDetail.textContent = "Paired. Connecting with a scoped credential...";
    setTimeout(updateStatus, 500);
  } catch (e) {
    pairingDetail.textContent = e.message || String(e);
  } finally {
    pairBtn.disabled = false;
  }
}

async function pairLocalExtension() {
  localPairBtn.disabled = true;
  pairBtn.disabled = true;
  pairingDetail.textContent = "Pairing with local EvoFlux...";
  await saveConfig(false);
  try {
    const result = await chrome.runtime.sendMessage({ type: "pair_locally" });
    if (!result?.ok) throw new Error(result?.error || "Local pairing failed");
    pairingDetail.textContent = "Paired locally. Connecting...";
    setTimeout(updateStatus, 500);
  } catch (e) {
    pairingDetail.textContent = e.message || String(e);
  } finally {
    localPairBtn.disabled = false;
    pairBtn.disabled = false;
  }
}

async function toggleConnection() {
  // Persist the latest field values without sending config_updated — the
  // toggle itself reconnects, and connect() re-reads storage. Sending both
  // could race (config_updated reconnect → toggle sees CONNECTING → closes).
  await saveConfig(false);
  try {
    await chrome.runtime.sendMessage({ type: "toggle_connection" });
  } catch {
    // ignore — status poll will reflect the outcome
  }
  setTimeout(updateStatus, 500);
}

async function releaseBrowserControl() {
  releaseBtn.disabled = true;
  try {
    await chrome.runtime.sendMessage({ type: "release_debuggers" });
  } catch {
    // Status refresh below surfaces whether any tabs remain attached.
  } finally {
    releaseBtn.disabled = false;
    updateStatus();
  }
}

function openSidePanel() {
  openSidePanelBtn.disabled = true;
  if (!chrome.sidePanel?.open) {
    browserContextDetail.textContent = "Chrome Side Panel is unavailable in this browser.";
    openSidePanelBtn.disabled = false;
    return;
  }
  // Chrome requires sidePanel.open() to run directly inside a user gesture.
  // Forwarding this click through runtime.sendMessage loses that activation.
  const options = activeTabId != null
    ? { tabId: activeTabId }
    : { windowId: chrome.windows.WINDOW_ID_CURRENT };
  chrome.sidePanel.open(options).catch((error) => {
    browserContextDetail.textContent = error.message || String(error);
  }).finally(() => {
    openSidePanelBtn.disabled = false;
  });
}

// ── Wiring ───────────────────────────────────────────────────────────────────

connectBtn.addEventListener("click", toggleConnection);
pairBtn.addEventListener("click", pairExtension);
localPairBtn.addEventListener("click", pairLocalExtension);
releaseBtn.addEventListener("click", releaseBrowserControl);
openSidePanelBtn.addEventListener("click", openSidePanel);
bindSessionBtn.addEventListener("click", bindCurrentTab);
newSessionBtn.addEventListener("click", createBrowserSession);
sendPagePromptBtn.addEventListener("click", sendQuickPrompt);
retryInteractionBtn.addEventListener("click", retryPendingInteraction);
armWatchBtn.addEventListener("click", armTextWatch);
cancelWatchBtn.addEventListener("click", cancelTextWatch);
sendWatchBtn.addEventListener("click", sendMatchedTextWatch);
startTeachBtn.addEventListener("click", startTeachRecording);
stopTeachBtn.addEventListener("click", stopTeachRecording);
cancelTeachBtn.addEventListener("click", cancelTeachRecording);
relayBaseInput.addEventListener("input", onConfigInput);

// Initial load
extensionVersion.textContent = chrome.runtime.getManifest().version;
(async () => {
  await loadConfig();
  await updateStatus();
  await refreshBrowserSessions();
})();

// Poll every 2 seconds
setInterval(updateStatus, 2000);
