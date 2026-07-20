/**
 * EvoFlux WebBridge — Popup script
 * Shows connection status and configures the relay URL / access token.
 */

const DEFAULT_RELAY_BASE = "ws://127.0.0.1:8000";

const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const statusDetail = document.getElementById("statusDetail");
const tabInfo = document.getElementById("tabInfo");
const tabUrl = document.getElementById("tabUrl");
const connectBtn = document.getElementById("connectBtn");
const relayBaseInput = document.getElementById("relayBase");
const accessTokenInput = document.getElementById("accessToken");

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
      statusDetail.textContent = `Extension ID: ${response.extension_id || "unknown"}`;

      if (response.active_tab) {
        tabInfo.style.display = "block";
        tabUrl.textContent = response.active_tab.url || "No URL";
      } else {
        tabInfo.style.display = "none";
      }

      connectBtn.textContent = "Disconnect";
      connectBtn.className = "btn btn-danger";
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
  } catch (e) {
    // Background script might not be ready
    statusDot.className = "status-dot connecting";
    statusText.textContent = "Starting...";
    statusDetail.className = "detail";
    statusDetail.textContent = "Extension service worker is initializing...";
    connectBtn.textContent = "Reconnect";
    connectBtn.className = "btn btn-primary";
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

// ── Wiring ───────────────────────────────────────────────────────────────────

connectBtn.addEventListener("click", toggleConnection);
relayBaseInput.addEventListener("input", onConfigInput);
accessTokenInput.addEventListener("input", onConfigInput);

// Initial load
loadConfig();
updateStatus();

// Poll every 2 seconds
setInterval(updateStatus, 2000);
