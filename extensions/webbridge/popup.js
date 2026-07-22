/**
 * EvoFlux WebBridge — Popup script
 * Shows connection status and configures the relay URL / access token.
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
const accessTokenInput = document.getElementById("accessToken");
const pairingCard = document.getElementById("pairingCard");
const pairingCodeInput = document.getElementById("pairingCode");
const pairBtn = document.getElementById("pairBtn");
const pairingDetail = document.getElementById("pairingDetail");
const extensionVersion = document.getElementById("extensionVersion");

// ── Config ───────────────────────────────────────────────────────────────────

async function loadConfig() {
  try {
    const cfg = await chrome.storage.local.get(["relayBase", "accessToken"]);
    relayBaseInput.value = cfg.relayBase || DEFAULT_RELAY_BASE;
    accessTokenInput.value = cfg.accessToken || "";
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
    accessToken: accessTokenInput.value.trim(),
  });
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

    if (response && response.connected) {
      statusDot.className = "status-dot connected";
      statusText.textContent = "Connected";
      statusDetail.className = "detail";
      statusDetail.textContent = response.paired
        ? `Securely paired: ${response.pairing_id || "connected"}`
        : `Legacy connection: ${response.extension_id || "unknown"}`;

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
    } else if (response && response.last_close_reason === "auth") {
      statusDot.className = "status-dot disconnected";
      statusText.textContent = "Auth failed";
      statusDetail.className = "detail auth-error";
      statusDetail.textContent = "Relay rejected the connection (4401) — check the access token.";
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

// ── Wiring ───────────────────────────────────────────────────────────────────

connectBtn.addEventListener("click", toggleConnection);
pairBtn.addEventListener("click", pairExtension);
releaseBtn.addEventListener("click", releaseBrowserControl);
relayBaseInput.addEventListener("input", onConfigInput);
accessTokenInput.addEventListener("input", onConfigInput);

// Initial load
extensionVersion.textContent = chrome.runtime.getManifest().version;
loadConfig();
updateStatus();

// Poll every 2 seconds
setInterval(updateStatus, 2000);
