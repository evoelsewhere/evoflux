// Prevents additional console window on Windows in release.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod openers;
mod sidecar;
mod workspace;

use anyhow::{anyhow, Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::time::{Duration, Instant};
use tauri::{
    menu::{AboutMetadataBuilder, Menu, MenuItem, PredefinedMenuItem, SubmenuBuilder},
    tray::TrayIconBuilder,
    AppHandle, Emitter, Manager, PhysicalSize, RunEvent, WebviewUrl, WebviewWindowBuilder,
    WindowEvent, Wry,
};
use tauri_plugin_dialog::DialogExt;

#[cfg(test)]
use tauri_plugin_dialog::MessageDialogResult;
use tauri_plugin_opener::OpenerExt;
use tokio::sync::{oneshot, Mutex};

use crate::sidecar::{Handshake, Sidecar};

/// Shared application state.
struct AppState {
    sidecar: Arc<Mutex<Option<Sidecar>>>,
    desktop_token: Arc<Mutex<Option<String>>>,
    backend_base_url: Arc<Mutex<Option<String>>>,
    backend_mode: Arc<Mutex<BackendMode>>,
    window_backend_base_urls: Arc<Mutex<HashMap<String, String>>>,
    backend_startup: Arc<Mutex<BackendStartupStatus>>,
    backend_start_lock: Arc<Mutex<()>>,
    startup_started: Instant,
    force_reloading: Arc<AtomicBool>,
    quitting: Arc<AtomicBool>,
    tray_status: Arc<Mutex<Option<MenuItem<Wry>>>>,
    tray_session: Arc<Mutex<Option<MenuItem<Wry>>>>,
    active_window_label: Arc<Mutex<String>>,
    /// Current webview zoom factor, mutated by the View > Zoom menu
    /// items. Session-only — not persisted across restarts.
    zoom: Arc<Mutex<f64>>,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum BackendMode {
    Bundled,
    External,
}

impl BackendMode {
    fn as_str(self) -> &'static str {
        match self {
            Self::Bundled => "bundled",
            Self::External => "external",
        }
    }
}

#[derive(Clone, Serialize, Deserialize)]
struct SavedAppServer {
    base_url: String,
    name: Option<String>,
}

#[derive(Clone, Serialize, Deserialize)]
struct AppBackendConfig {
    active_base_url: Option<String>,
    servers: Vec<SavedAppServer>,
}

#[derive(Clone, Copy, Serialize, Deserialize)]
struct SavedWindowState {
    width: u32,
    height: u32,
}

#[derive(Clone, Serialize)]
struct AppBackendStatus {
    base_url: String,
    token: Option<String>,
    mode: String,
    sidecar_running: bool,
    external: bool,
    supports_bundled: bool,
    servers: Vec<SavedAppServer>,
    startup: BackendStartupStatus,
}

#[derive(Clone, Serialize)]
struct BackendStartupStatus {
    phase: String,
    message: String,
    attempt: u32,
    max_attempts: u32,
    elapsed_ms: u64,
    error: Option<String>,
    fatal: bool,
}

impl Default for BackendStartupStatus {
    fn default() -> Self {
        Self {
            phase: "preparing".to_string(),
            message: "Preparing the local engine…".to_string(),
            attempt: 0,
            max_attempts: SIDECAR_START_ATTEMPTS,
            elapsed_ms: 0,
            error: None,
            fatal: false,
        }
    }
}

impl Default for AppBackendConfig {
    fn default() -> Self {
        Self {
            active_base_url: None,
            servers: vec![SavedAppServer {
                base_url: "http://127.0.0.1:4082".to_string(),
                name: Some("Local CLI server".to_string()),
            }],
        }
    }
}

const MAIN_WINDOW: &str = "main";
const SECONDARY_WINDOW_PREFIX: &str = "main-";
const MENU_SHOW: &str = "show";
const MENU_NEW_WINDOW: &str = "new_window";
const MENU_HOME: &str = "home";
const MENU_CHAT: &str = "chat";
const MENU_CODING: &str = "coding";
const MENU_COMMAND_PALETTE: &str = "command_palette";
const MENU_WIKI: &str = "wiki";
const MENU_SCHEDULER: &str = "scheduler";
const MENU_SETTINGS: &str = "settings";
const MENU_PROVIDERS: &str = "providers";
const MENU_NOTIFICATIONS: &str = "notifications";
const MENU_TELEMETRY: &str = "telemetry";
const MENU_STATUS: &str = "status";
const MENU_SESSION: &str = "session";
const MENU_RELOAD: &str = "reload";
const MENU_FORCE_RELOAD: &str = "force_reload";
const MENU_ZOOM_IN: &str = "zoom_in";
const MENU_ZOOM_OUT: &str = "zoom_out";
const MENU_ZOOM_RESET: &str = "zoom_reset";
const MENU_OPEN_CONFIG_DIR: &str = "open_config_dir";
const MENU_REVEAL_BACKEND_LOG: &str = "reveal_backend_log";
const MENU_QUIT: &str = "quit";
const MENU_EDIT_UNDO: &str = "edit_undo";
const MENU_EDIT_REDO: &str = "edit_redo";
const MENU_EDIT_CUT: &str = "edit_cut";
const MENU_EDIT_COPY: &str = "edit_copy";
const MENU_EDIT_PASTE: &str = "edit_paste";
const MENU_EDIT_SELECT_ALL: &str = "edit_select_all";

/// Zoom factor bounds and step. ``ZOOM_STEP`` is the multiplier per
/// ⌘+/⌘- press (≈20%, matching Chrome). Bounds keep the factor from
/// reaching values where the UI becomes unusable.
const ZOOM_MIN: f64 = 0.5;
const ZOOM_MAX: f64 = 3.0;
const ZOOM_STEP: f64 = 1.2;
const ZOOM_DEFAULT: f64 = 1.0;

/// The first attempt gets the largest cold-start budget. Retries benefit from
/// OS/Defender caches and use shorter budgets so startup cannot hang forever.
const SIDECAR_FIRST_HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(90);
const SIDECAR_RETRY_HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(45);
const SIDECAR_START_ATTEMPTS: u32 = 3;
const SIDECAR_RETRY_BASE_DELAY: Duration = Duration::from_millis(750);

/// Label shown in the tray when no chat/coding session is active.
const TRAY_SESSION_IDLE: &str = "No active session";

/// Hard cap on tray session label width. Keeps the menu from stretching
/// uncomfortably wide when a session title or workspace name is long.
const TRAY_SESSION_MAX_LEN: usize = 60;

/// Apply platform-specific window chrome.
///
/// macOS uses an overlay title-bar; the React app reserves a 70 pt left
/// inset for the traffic-lights. ``traffic_light_position`` must be set
/// from Rust because the JSON config value is ignored when the window is
/// built via ``WebviewWindowBuilder``. ``y`` is a *bottom* inset (tao
/// resizes the native title-bar to ``button_height + y`` — tao 0.35.x,
/// macos/view.rs:1152); 22 pt centres against our 40 pt header.
fn configure_window_chrome(
    builder: WebviewWindowBuilder<'_, tauri::Wry, AppHandle>,
) -> WebviewWindowBuilder<'_, tauri::Wry, AppHandle> {
    #[cfg(target_os = "macos")]
    {
        use tauri::{LogicalPosition, TitleBarStyle};
        builder
            .title_bar_style(TitleBarStyle::Overlay)
            .hidden_title(true)
            .traffic_light_position(LogicalPosition::new(12.0, 22.0))
    }
    #[cfg(target_os = "windows")]
    {
        builder
    }
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    {
        builder
    }
}

#[derive(Clone, Serialize)]
struct BackendReady {
    port: u16,
    version: String,
    base_url: String,
    token: Option<String>,
    sidecar_running: bool,
}

#[derive(Clone, Serialize)]
struct BackendError {
    message: String,
    fatal: bool,
    attempt: u32,
    max_attempts: u32,
}

#[cfg(any(target_os = "macos", target_os = "ios"))]
#[tauri::command]
fn request_voice_permissions() -> Result<bool, String> {
    use block2::RcBlock;
    use objc2::runtime::Bool;
    use objc2_av_foundation::{AVAuthorizationStatus, AVCaptureDevice, AVMediaTypeAudio};
    use objc2_speech::{SFSpeechRecognizer, SFSpeechRecognizerAuthorizationStatus};
    use std::sync::mpsc;

    let audio_type = unsafe { AVMediaTypeAudio.expect("AVMediaTypeAudio is available") };
    let microphone_status = unsafe { AVCaptureDevice::authorizationStatusForMediaType(audio_type) };
    let microphone_granted = if microphone_status == AVAuthorizationStatus::Authorized {
        true
    } else if microphone_status == AVAuthorizationStatus::Denied
        || microphone_status == AVAuthorizationStatus::Restricted
    {
        false
    } else {
        let (tx, rx) = mpsc::channel();
        let handler: RcBlock<dyn Fn(Bool)> = RcBlock::new(move |granted: Bool| {
            let _ = tx.send(granted.as_bool());
        });
        unsafe {
            AVCaptureDevice::requestAccessForMediaType_completionHandler(audio_type, &handler);
        }
        rx.recv()
            .map_err(|_| "microphone permission request was cancelled".to_string())?
    };

    let speech_status = unsafe { SFSpeechRecognizer::authorizationStatus() };
    let speech_granted = if speech_status == SFSpeechRecognizerAuthorizationStatus::Authorized {
        true
    } else if speech_status == SFSpeechRecognizerAuthorizationStatus::Denied
        || speech_status == SFSpeechRecognizerAuthorizationStatus::Restricted
    {
        false
    } else {
        let (tx, rx) = mpsc::channel();
        let handler: RcBlock<dyn Fn(SFSpeechRecognizerAuthorizationStatus)> =
            RcBlock::new(move |status: SFSpeechRecognizerAuthorizationStatus| {
                let _ = tx.send(status == SFSpeechRecognizerAuthorizationStatus::Authorized);
            });
        unsafe {
            SFSpeechRecognizer::requestAuthorization(&handler);
        }
        rx.recv()
            .map_err(|_| "speech recognition permission request was cancelled".to_string())?
    };

    Ok(microphone_granted && speech_granted)
}

#[cfg(not(any(target_os = "macos", target_os = "ios")))]
#[tauri::command]
fn request_voice_permissions() -> Result<bool, String> {
    Ok(true)
}

#[derive(Deserialize)]
struct SaveWorkspaceFileRequest {
    url: String,
    filename: String,
}

#[tauri::command]
async fn save_workspace_file(
    app: AppHandle,
    request: SaveWorkspaceFileRequest,
) -> Result<bool, String> {
    let filename = Path::new(&request.filename)
        .file_name()
        .and_then(|name| name.to_str())
        .filter(|name| !name.is_empty())
        .unwrap_or("download")
        .to_string();
    let target = app
        .dialog()
        .file()
        .set_title("Save file")
        .set_file_name(filename)
        .blocking_save_file();
    let Some(target) = target else {
        return Ok(false);
    };
    let path = target
        .into_path()
        .map_err(|_| "Selected destination is not a local file path".to_string())?;
    let bytes = reqwest::get(&request.url)
        .await
        .map_err(|e| format!("Download file: {e}"))?
        .error_for_status()
        .map_err(|e| format!("Download file: {e}"))?
        .bytes()
        .await
        .map_err(|e| format!("Read downloaded file: {e}"))?;
    tokio::fs::write(&path, bytes)
        .await
        .map_err(|e| format!("Write {}: {e}", path.display()))?;
    Ok(true)
}

#[tauri::command]
async fn backend_health(state: tauri::State<'_, AppState>) -> Result<bool, String> {
    let mut guard = state.sidecar.lock().await;
    match guard.as_mut() {
        Some(s) => Ok(s.is_alive()),
        None => Ok(false),
    }
}

#[tauri::command]
async fn backend_logs_path(
    app: AppHandle,
    state: tauri::State<'_, AppState>,
) -> Result<String, String> {
    let guard = state.sidecar.lock().await;
    match guard.as_ref() {
        Some(s) => Ok(s.log_path().to_string_lossy().into_owned()),
        None => Sidecar::log_path_for(&app)
            .map(|path| path.to_string_lossy().into_owned())
            .map_err(|error| format!("{error:#}")),
    }
}

#[tauri::command]
async fn app_backend_status(
    app: AppHandle,
    window: tauri::WebviewWindow,
    state: tauri::State<'_, AppState>,
) -> Result<AppBackendStatus, String> {
    app_backend_status_for_window(app, state, window.label()).await
}

async fn app_backend_status_for_window(
    app: AppHandle,
    state: tauri::State<'_, AppState>,
    window_label: &str,
) -> Result<AppBackendStatus, String> {
    let bundled_base_url = state.backend_base_url.lock().await.clone();
    let window_base_url = state
        .window_backend_base_urls
        .lock()
        .await
        .get(window_label)
        .cloned();
    let external = window_base_url.is_some();
    let base_url = window_base_url
        .or(bundled_base_url)
        .unwrap_or_else(|| "".to_string());
    let sidecar_running = state
        .sidecar
        .lock()
        .await
        .as_mut()
        .is_some_and(|s| s.is_alive());
    let mode = if external {
        BackendMode::External
    } else {
        BackendMode::Bundled
    };
    let servers = load_app_backend_config(&app)
        .unwrap_or_else(|_| AppBackendConfig::default())
        .servers;
    let token = if external {
        None
    } else {
        state.desktop_token.lock().await.clone()
    };
    let startup = state.backend_startup.lock().await.clone();
    Ok(AppBackendStatus {
        base_url,
        token,
        mode: mode.as_str().to_string(),
        sidecar_running,
        external: mode == BackendMode::External,
        supports_bundled: true,
        servers,
        startup,
    })
}

#[tauri::command]
async fn app_save_backend_server(
    app: AppHandle,
    window: tauri::WebviewWindow,
    base_url: String,
    name: Option<String>,
) -> Result<AppBackendStatus, String> {
    let normalized = normalize_external_base_url(&base_url).map_err(|e| format!("{e:#}"))?;
    save_app_backend_config(
        &app,
        Some(&normalized),
        normalize_server_name(name).as_deref(),
        false,
    )
    .map_err(|e| format!("{e:#}"))?;
    app_backend_status_for_window(app.clone(), app.state(), window.label())
        .await
        .map_err(|e| format!("{e:#}"))
}

#[tauri::command]
async fn app_use_external_backend(
    app: AppHandle,
    window: tauri::WebviewWindow,
    base_url: String,
    name: Option<String>,
    persist: Option<bool>,
) -> Result<AppBackendStatus, String> {
    let normalized = normalize_external_base_url(&base_url).map_err(|e| format!("{e:#}"))?;
    wait_for_health(&normalized, 8, Duration::from_millis(250))
        .await
        .map_err(|e| format!("External backend is not reachable: {e:#}"))?;

    let state: tauri::State<'_, AppState> = app.state();
    state
        .window_backend_base_urls
        .lock()
        .await
        .insert(window.label().to_string(), normalized.clone());

    if persist.unwrap_or(true) {
        save_app_backend_config(
            &app,
            Some(&normalized),
            normalize_server_name(name).as_deref(),
            true,
        )
        .map_err(|e| format!("{e:#}"))?;
    }

    let init_script = frontend_init_script(None, &normalized);
    window
        .eval(&init_script)
        .map_err(|e| format!("inject external backend config: {e:#}"))?;
    update_tray_status(&app, "Status: Running");
    window
        .emit(
            "backend-ready",
            BackendReady {
                port: 0,
                version: "external".to_string(),
                base_url: normalized,
                token: None,
                sidecar_running: false,
            },
        )
        .ok();

    app_backend_status_for_window(app.clone(), app.state(), window.label())
        .await
        .map_err(|e| format!("{e:#}"))
}

#[tauri::command]
async fn app_remove_backend_server(
    app: AppHandle,
    window: tauri::WebviewWindow,
    base_url: String,
) -> Result<AppBackendStatus, String> {
    let normalized = normalize_external_base_url(&base_url).map_err(|e| format!("{e:#}"))?;
    remove_app_backend_server(&app, &normalized).map_err(|e| format!("{e:#}"))?;
    let state: tauri::State<'_, AppState> = app.state();
    state
        .window_backend_base_urls
        .lock()
        .await
        .retain(|_, active| {
            normalize_external_base_url(active).map_or(true, |active| active != normalized)
        });
    app_backend_status_for_window(app.clone(), app.state(), window.label())
        .await
        .map_err(|e| format!("{e:#}"))
}

#[tauri::command]
async fn app_use_bundled_backend(
    app: AppHandle,
    window: tauri::WebviewWindow,
) -> Result<(), String> {
    let state: tauri::State<'_, AppState> = app.state();

    let base = state
        .backend_base_url
        .lock()
        .await
        .clone()
        .ok_or_else(|| "bundled backend is not ready".to_string())?;
    state
        .window_backend_base_urls
        .lock()
        .await
        .remove(window.label());
    save_app_backend_config(&app, None, None, true).map_err(|e| format!("{e:#}"))?;
    let token = state.desktop_token.lock().await.clone();
    let init_script = frontend_init_script(token.as_deref(), &base);
    window
        .eval(&init_script)
        .map_err(|e| format!("inject bundled backend config: {e:#}"))?;
    window
        .emit(
            "backend-ready",
            BackendReady {
                port: 0,
                version: "bundled".to_string(),
                base_url: base,
                token,
                sidecar_running: true,
            },
        )
        .ok();
    Ok(())
}

#[tauri::command]
async fn app_new_window(app: AppHandle) -> Result<(), String> {
    create_app_window(&app, None)
        .await
        .map(|_| ())
        .map_err(|e| format!("{e:#}"))
}

#[tauri::command]
async fn app_open_browser_devtools(app: AppHandle, cdp_url: String) -> Result<(), String> {
    use tauri::{WebviewUrl, WebviewWindowBuilder};

    // Derive the DevTools frontend URL from the CDP HTTP endpoint.
    // Chromium serves its built-in DevTools at /devtools/inspector.html
    // which connects back via WebSocket.
    let ws_url = cdp_url
        .trim_start_matches("http://")
        .trim_start_matches("https://");
    let devtools_url = format!(
        "{}/devtools/inspector.html?ws={}",
        cdp_url.trim_end_matches('/'),
        ws_url,
    );

    let label = next_window_label(&app);

    let parsed: url::Url = devtools_url
        .parse()
        .map_err(|e| format!("Invalid devtools URL: {e}"))?;

    let win = WebviewWindowBuilder::new(&app, label, WebviewUrl::External(parsed))
        .title("Browser DevTools")
        .inner_size(1280.0, 820.0)
        .min_inner_size(760.0, 560.0)
        .build()
        .map_err(|e| format!("Failed to open DevTools: {e}"))?;

    let _ = win.show();
    let _ = win.set_focus();
    Ok(())
}

fn app_browser_webview(app: &AppHandle, label: &str) -> Result<tauri::Webview, String> {
    app.get_webview(label)
        .ok_or_else(|| format!("Browser webview not found: {label}"))
}

#[tauri::command]
async fn app_browser_webview_navigate(
    app: AppHandle,
    label: String,
    url: String,
) -> Result<String, String> {
    let parsed = url::Url::parse(&url).map_err(|error| format!("Invalid browser URL: {error}"))?;
    let webview = app_browser_webview(&app, &label)?;
    webview
        .navigate(parsed)
        .map_err(|error| format!("Browser navigation failed: {error}"))?;
    Ok(url)
}

#[tauri::command]
async fn app_browser_webview_command(
    app: AppHandle,
    label: String,
    action: String,
    value: Option<String>,
    backwards: Option<bool>,
) -> Result<(), String> {
    let webview = app_browser_webview(&app, &label)?;
    match action.as_str() {
        "back" => webview.eval("history.back()"),
        "forward" => webview.eval("history.forward()"),
        "reload" => webview.reload(),
        "focus" => webview.set_focus(),
        "print" => webview.print(),
        "clear_data" => webview.clear_all_browsing_data(),
        "find" => {
            let query = serde_json::to_string(&value.unwrap_or_default())
                .map_err(|error| format!("Invalid find query: {error}"))?;
            webview.eval(format!(
                "window.find({query}, false, {}, true, false, false, false)",
                backwards.unwrap_or(false)
            ))
        }
        #[cfg(debug_assertions)]
        "devtools" => {
            webview.open_devtools();
            Ok(())
        }
        _ => return Err(format!("Unsupported browser command: {action}")),
    }
    .map_err(|error| format!("Browser command failed: {error}"))
}

#[tauri::command]
async fn app_browser_webview_url(app: AppHandle, label: String) -> Result<String, String> {
    app_browser_webview(&app, &label)?
        .url()
        .map(|url| url.to_string())
        .map_err(|error| format!("Could not read browser URL: {error}"))
}

#[tauri::command]
async fn app_browser_webview_agent_action(
    app: AppHandle,
    label: String,
    action: String,
    params: serde_json::Value,
) -> Result<serde_json::Value, String> {
    if !label.starts_with("browser-") {
        return Err("Agent browser actions require a browser WebView".into());
    }
    let script = browser_agent_action_script(&action, &params)?;
    let wrapped = format!(
        r#"(() => {{
                    try {{
                        return JSON.stringify({{ ok: true, value: ({script})() }});
                    }} catch (error) {{
                        return JSON.stringify({{ ok: false, error: String(error?.message ?? error) }});
                    }}
                }})()"#
    );

    let (sender, receiver) = oneshot::channel();
    let sender = Arc::new(std::sync::Mutex::new(Some(sender)));
    app_browser_webview(&app, &label)?
        .eval_with_callback(wrapped, move |result| {
            if let Ok(mut guard) = sender.lock() {
                if let Some(sender) = guard.take() {
                    let _ = sender.send(result);
                }
            }
        })
        .map_err(|error| format!("Could not run browser action: {error}"))?;

    let callback_timeout = if action == "status" || action == "exists" {
        Duration::from_millis(750)
    } else {
        Duration::from_secs(35)
    };
    match tokio::time::timeout(callback_timeout, receiver).await {
        Ok(Ok(raw)) => parse_browser_agent_result(&raw),
        Ok(Err(_)) => Err("Browser action response channel closed".into()),
        Err(_) => Err(format!("Browser action timed out: {action}")),
    }
}

fn parse_browser_agent_result(raw: &str) -> Result<serde_json::Value, String> {
    if raw.len() > 2 * 1024 * 1024 {
        return Err("Browser action result exceeds 2 MB".into());
    }
    let mut value: serde_json::Value = serde_json::from_str(raw)
        .map_err(|error| format!("Invalid browser action result: {error}"))?;
    if let Some(encoded) = value.as_str() {
        value = serde_json::from_str(encoded)
            .map_err(|error| format!("Invalid encoded browser action result: {error}"))?;
    }
    if value.get("ok").and_then(serde_json::Value::as_bool) == Some(true) {
        Ok(value
            .get("value")
            .cloned()
            .unwrap_or(serde_json::Value::Null))
    } else {
        Err(value
            .get("error")
            .and_then(serde_json::Value::as_str)
            .unwrap_or("Browser action failed")
            .to_string())
    }
}

fn browser_agent_action_script(action: &str, params: &serde_json::Value) -> Result<String, String> {
    const SUPPORTED: &[&str] = &[
        "snapshot", "click", "fill", "select", "extract", "scroll", "exists", "status",
    ];
    if !SUPPORTED.contains(&action) {
        return Err(format!("Unsupported direct browser action: {action}"));
    }
    let action_json = serde_json::to_string(action)
        .map_err(|error| format!("Could not encode browser action: {error}"))?;
    let params_json = serde_json::to_string(params)
        .map_err(|error| format!("Could not encode browser parameters: {error}"))?;
    Ok(format!(
        r#"() => {{
                    const action = {action_json};
                    const params = {params_json};
                    const visible = (element) => {{
                        const rect = element.getBoundingClientRect();
                        const style = getComputedStyle(element);
                        return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                    }};
                    const resolveElement = () => {{
                        if (Number.isInteger(params.index)) {{
                            return document.querySelector(`[data-evoflux-agent-index="${{params.index}}"]`);
                        }}
                        return typeof params.selector === 'string' ? document.querySelector(params.selector) : null;
                    }};
                    const describe = (element) => {{
                        const tag = element.tagName.toLowerCase();
                        const label = element.getAttribute('aria-label') || element.getAttribute('placeholder') || '';
                        const text = String(element.innerText || element.value || element.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 180);
                        return `${{tag}}${{label ? ` "${{label}}"` : ''}}${{text ? `: ${{text}}` : ''}}`;
                    }};

                    if (action === 'snapshot') {{
                        document.querySelectorAll('[data-evoflux-agent-index]').forEach((element) => element.removeAttribute('data-evoflux-agent-index'));
                        const selector = 'a,button,input,textarea,select,[role="button"],[role="link"],[contenteditable="true"],summary';
                        const elements = Array.from(document.querySelectorAll(selector)).filter(visible).slice(0, 500);
                        const lines = elements.map((element, index) => {{
                            element.setAttribute('data-evoflux-agent-index', String(index));
                            return `[${{index}}] ${{describe(element)}}`;
                        }});
                        const maxChars = Math.max(500, Math.min(100000, Number(params.max_chars) || 15000));
                        const pageText = String(document.body?.innerText || '').trim().slice(0, Math.floor(maxChars * 0.45));
                        const output = `URL: ${{location.href}}\nTitle: ${{document.title}}\n\nPage text:\n${{pageText}}\n\nInteractive elements (use [index] with click/fill):\n${{lines.join('\n')}}`;
                        return output.slice(0, maxChars);
                    }}

                    if (action === 'click') {{
                        const element = resolveElement();
                        if (!element) throw new Error('Element not found; run snapshot again or provide a selector');
                        element.scrollIntoView({{ block: 'center', inline: 'center' }});
                        element.focus?.();
                        element.click();
                        return `Clicked ${{describe(element)}}`;
                    }}

                    if (action === 'fill') {{
                        const element = resolveElement();
                        if (!element) throw new Error('Input not found; run snapshot again or provide a selector');
                        const text = String(params.text ?? '');
                        element.focus?.();
                        if (element.isContentEditable) {{
                            element.textContent = params.clear === false ? String(element.textContent || '') + text : text;
                        }} else if ('value' in element) {{
                            const next = params.clear === false ? String(element.value || '') + text : text;
                            const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                            const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
                            setter ? setter.call(element, next) : (element.value = next);
                        }} else {{
                            throw new Error('Element is not editable');
                        }}
                        element.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText', data: text }}));
                        element.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        return `Filled ${{describe(element)}} (${{text.length}} chars)`;
                    }}

                    if (action === 'select') {{
                        const element = document.querySelector(String(params.selector || ''));
                        if (!(element instanceof HTMLSelectElement)) throw new Error('Select element not found');
                        element.value = String(params.value ?? '');
                        element.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        element.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        return `Selected "${{element.value}}"`;
                    }}

                    if (action === 'extract') {{
                        const maxChars = Math.max(100, Math.min(100000, Number(params.max_chars) || 15000));
                        if (!params.selector) return String(document.body?.innerText || '').slice(0, maxChars) || '(empty page)';
                        const elements = Array.from(document.querySelectorAll(String(params.selector)));
                        if (!elements.length) throw new Error(`No element found for selector: ${{params.selector}}`);
                        const values = elements.map((element) => params.attribute ? element.getAttribute(String(params.attribute)) || '' : String(element.innerText || element.textContent || '').trim());
                        return values.join('\n').slice(0, maxChars) || '(empty)';
                    }}

                    if (action === 'scroll') {{
                        const pixels = Number(params.pixels) || 500;
                        const delta = params.direction === 'up' ? -pixels : pixels;
                        window.scrollBy({{ top: delta, behavior: 'instant' }});
                        return `Scrolled ${{params.direction || 'down'}} ${{Math.abs(pixels)}}px`;
                    }}

                    if (action === 'exists') {{
                        return Boolean(document.querySelector(String(params.selector || '')));
                    }}

                    if (action === 'status') {{
                        return {{ url: location.href, readyState: document.readyState }};
                    }}
                }}"#
    ))
}

fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn target_webview_window(app: &AppHandle) -> Option<tauri::WebviewWindow> {
    let state: tauri::State<'_, AppState> = app.state();
    let label =
        tauri::async_runtime::block_on(async { state.active_window_label.lock().await.clone() });
    app.get_webview_window(&label)
        .or_else(|| app.get_webview_window(MAIN_WINDOW))
}

fn show_target_window(app: &AppHandle) {
    if let Some(window) = target_webview_window(app) {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    } else {
        show_main_window(app);
    }
}

fn navigate_main_window(app: &AppHandle, path: &str) {
    show_target_window(app);
    if let Some(window) = target_webview_window(app) {
        let path_json = serde_json::to_string(path).unwrap_or_else(|_| "\"/\"".into());
        let _ = window.eval(format!("window.location.assign({path_json});"));
    }
}

fn emit_frontend_command(app: &AppHandle, command: &str) {
    show_target_window(app);
    let command = command.to_string();
    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        // If a tray command summons a just-created or still-loading webview,
        // give React a short window to mount its event listener.
        for _ in 0..5 {
            let _ = handle.emit("desktop-command", command.as_str());
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    });
}

fn open_config_dir(app: &AppHandle) {
    let config_dir = std::env::var("EVOFLUX_CONFIG_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| {
            app.path()
                .home_dir()
                .unwrap_or_else(|_| PathBuf::from("."))
                .join(".config")
                .join("evoflux")
        });
    if let Err(e) = std::fs::create_dir_all(&config_dir) {
        log::warn!("failed to create config dir {}: {e}", config_dir.display());
        return;
    }
    if let Err(e) = app
        .opener()
        .open_path(config_dir.to_string_lossy().into_owned(), None::<&str>)
    {
        log::warn!("failed to open config dir {}: {e}", config_dir.display());
    }
}

fn reveal_backend_log(app: &AppHandle) {
    let Ok(path) = Sidecar::log_path_for(app) else {
        log::warn!("backend log path unavailable");
        return;
    };
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    if !path.exists() {
        let _ = std::fs::write(&path, "EvoFlux backend has not written a log yet.\n");
    }
    if let Err(e) = app.opener().reveal_item_in_dir(&path) {
        log::warn!("failed to reveal backend log {}: {e}", path.display());
    }
}

#[tauri::command]
fn app_reveal_backend_log(app: AppHandle) -> Result<(), String> {
    reveal_backend_log(&app);
    Ok(())
}

fn persist_active_window_state(app: &AppHandle) {
    if let Some(window) = target_webview_window(app) {
        if let Err(e) = save_window_state(app, &window) {
            log::warn!("failed to save window state: {e:#}");
        }
    }
}

fn quit_app(app: &AppHandle) {
    persist_active_window_state(app);
    let state: tauri::State<'_, AppState> = app.state();
    state.quitting.store(true, Ordering::SeqCst);
    app.exit(0);
}

fn reload_main_window(app: &AppHandle) {
    show_target_window(app);
    if let Some(window) = target_webview_window(app) {
        let _ = window.eval("window.location.reload();");
    }
}

fn force_reload_app(app: &AppHandle) {
    let state: tauri::State<'_, AppState> = app.state();
    if state.force_reloading.swap(true, Ordering::SeqCst) {
        return;
    }

    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        update_tray_status(&handle, "Status: Reloading…");
        let result = restart_sidecar_and_reload_window(&handle).await;
        if let Err(e) = result {
            log::error!("failed to force reload backend: {e:#}");
            update_tray_status(&handle, "Status: Error");
            let already_published = handle
                .state::<AppState>()
                .backend_startup
                .lock()
                .await
                .phase
                == "error";
            if !already_published {
                publish_backend_error(
                    &handle,
                    &BackendStartFailure {
                        message: format!("{e:#}"),
                        fatal: false,
                        attempt: SIDECAR_START_ATTEMPTS,
                    },
                )
                .await;
            }
        }

        let state: tauri::State<'_, AppState> = handle.state();
        state.force_reloading.store(false, Ordering::SeqCst);
    });
}

#[tauri::command]
fn app_retry_backend(app: AppHandle) -> Result<(), String> {
    force_reload_app(&app);
    Ok(())
}

async fn restart_sidecar_and_reload_window(app: &AppHandle) -> Result<()> {
    let state: tauri::State<'_, AppState> = app.state();
    let existing_token = state.desktop_token.lock().await.clone();

    shutdown_sidecar_now(app).await;
    let ready = match start_bundled_backend_with_retry(app, existing_token.as_deref()).await {
        Ok(ready) => ready,
        Err(failure) => {
            publish_backend_error(app, &failure).await;
            return Err(anyhow!(failure.message));
        }
    };
    let token = ready.handshake.token.clone();

    log::info!(
        "sidecar handshake: port={} pid={} version={}",
        ready.handshake.port,
        ready.handshake.pid,
        ready.handshake.version
    );

    let init_script = frontend_init_script(Some(&token), &ready.base_url);
    let existing_windows: Vec<tauri::WebviewWindow> = app.webview_windows().into_values().collect();
    let external_windows = state.window_backend_base_urls.lock().await.clone();
    for window in existing_windows {
        if !external_windows.contains_key(window.label()) {
            window
                .eval(&init_script)
                .context("inject bundled backend config")?;
        }
        if cfg!(debug_assertions) {
            window
                .navigate(
                    "http://localhost:5173"
                        .parse()
                        .context("parse dev frontend url")?,
                )
                .context("navigate app window")?;
        }
    }
    show_target_window(app);

    let _ = state.desktop_token.lock().await.replace(token.clone());
    let _ = state
        .backend_base_url
        .lock()
        .await
        .replace(ready.base_url.clone());
    *state.backend_mode.lock().await = BackendMode::Bundled;
    let _ = state.sidecar.lock().await.replace(ready.sidecar);
    set_backend_startup(
        app,
        "ready",
        "Local engine ready",
        ready.attempt,
        None,
        false,
    )
    .await;
    app.emit(
        "backend-ready",
        BackendReady {
            port: ready.handshake.port,
            version: ready.handshake.version,
            base_url: ready.base_url,
            token: Some(token),
            sidecar_running: true,
        },
    )
    .ok();
    update_tray_status(app, "Status: Running");

    Ok(())
}

fn handle_desktop_menu(app: &AppHandle, id: &str) {
    match id {
        MENU_SHOW => show_main_window(app),
        MENU_NEW_WINDOW => {
            let handle = app.clone();
            tauri::async_runtime::spawn(async move {
                if let Err(e) = create_app_window(&handle, None).await {
                    log::error!("failed to create new window: {e:#}");
                }
            });
        }
        MENU_HOME => navigate_main_window(app, "/"),
        MENU_CHAT => navigate_main_window(app, "/"),
        MENU_CODING => navigate_main_window(app, "/coding"),
        MENU_COMMAND_PALETTE => emit_frontend_command(app, "command_palette"),
        MENU_WIKI => emit_frontend_command(app, "wiki"),
        MENU_SCHEDULER => emit_frontend_command(app, "scheduler"),
        MENU_EDIT_UNDO => emit_frontend_command(app, "edit_undo"),
        MENU_EDIT_REDO => emit_frontend_command(app, "edit_redo"),
        MENU_EDIT_CUT => emit_frontend_command(app, "edit_cut"),
        MENU_EDIT_COPY => emit_frontend_command(app, "edit_copy"),
        MENU_EDIT_PASTE => emit_frontend_command(app, "edit_paste"),
        MENU_EDIT_SELECT_ALL => emit_frontend_command(app, "edit_select_all"),
        MENU_SETTINGS => navigate_main_window(app, "/settings"),
        MENU_PROVIDERS => navigate_main_window(app, "/settings/providers"),
        MENU_NOTIFICATIONS => navigate_main_window(app, "/settings/notifications"),
        MENU_TELEMETRY => navigate_main_window(app, "/telemetry"),
        MENU_RELOAD => reload_main_window(app),
        MENU_FORCE_RELOAD => force_reload_app(app),
        MENU_ZOOM_IN => adjust_zoom(app, ZOOM_STEP),
        MENU_ZOOM_OUT => adjust_zoom(app, 1.0 / ZOOM_STEP),
        MENU_ZOOM_RESET => set_zoom(app, ZOOM_DEFAULT),
        MENU_OPEN_CONFIG_DIR => open_config_dir(app),
        MENU_REVEAL_BACKEND_LOG => reveal_backend_log(app),
        MENU_QUIT => quit_app(app),
        _ => {}
    }
}

/// Multiply the current zoom factor by ``factor`` and apply it, clamping
/// to ``[ZOOM_MIN, ZOOM_MAX]`` so the user can't shrink the UI to nothing
/// or blow it up past readable.
fn adjust_zoom(app: &AppHandle, factor: f64) {
    let state: tauri::State<'_, AppState> = app.state();
    let zoom = state.zoom.clone();
    let app_for_apply = app.clone();
    tauri::async_runtime::spawn(async move {
        let mut guard = zoom.lock().await;
        let next = (*guard * factor).clamp(ZOOM_MIN, ZOOM_MAX);
        *guard = next;
        apply_zoom_to_main(&app_for_apply, next);
    });
}

fn set_zoom(app: &AppHandle, value: f64) {
    let state: tauri::State<'_, AppState> = app.state();
    let zoom = state.zoom.clone();
    let app_for_apply = app.clone();
    let clamped = value.clamp(ZOOM_MIN, ZOOM_MAX);
    tauri::async_runtime::spawn(async move {
        *zoom.lock().await = clamped;
        apply_zoom_to_main(&app_for_apply, clamped);
    });
}

fn apply_zoom_to_main(app: &AppHandle, factor: f64) {
    for window in app.webview_windows().into_values() {
        if let Err(e) = window.set_zoom(factor) {
            log::warn!("set_zoom({factor}) failed for {}: {e}", window.label());
        }
    }
}

/// Cleanly stop the Python sidecar before a process re-exec.
///
/// Idempotent: ``.take()``s the sidecar out of shared state, so repeat
/// calls (or a race with ``ExitRequested``) are no-ops.
async fn shutdown_sidecar_now(app: &AppHandle) {
    let state: tauri::State<'_, AppState> = app.state();
    let sidecar = state.sidecar.clone();
    let mut guard = sidecar.lock().await;
    if let Some(mut s) = guard.take() {
        s.shutdown().await;
    }
}

/// Map a ``MessageDialogResult`` from an ``OkCancelCustom`` dialog to a
/// simple accept/cancel boolean.
///
/// ``OkCancelCustom`` yields ``Custom(label)`` matching the button text the
/// user pressed (rfd's behaviour, surfaced through tauri-plugin-dialog).
/// Some platforms still report a plain ``Ok``/``Cancel`` for the bundled
/// system dialog, so we accept either spelling of "yes".
#[cfg(test)]
fn dialog_result_is_accept(result: &MessageDialogResult, ok_label: &str) -> bool {
    match result {
        MessageDialogResult::Ok | MessageDialogResult::Yes => true,
        MessageDialogResult::Custom(s) => s == ok_label,
        MessageDialogResult::Cancel | MessageDialogResult::No => false,
    }
}

/// Build the "Update available" dialog body shown to the user.
///
/// Release notes are truncated to ~600 characters with an ellipsis so a
/// runaway changelog never produces a multi-screen modal. An empty/None
/// body collapses the notes paragraph entirely.
#[cfg(test)]
fn format_update_prompt(new_version: &str, current_version: &str, body: Option<&str>) -> String {
    const MAX_NOTES_CHARS: usize = 600;
    let notes = body.unwrap_or_default().trim();
    let trimmed = if notes.chars().count() > MAX_NOTES_CHARS {
        let mut s: String = notes.chars().take(MAX_NOTES_CHARS - 1).collect();
        s.push('…');
        s
    } else {
        notes.to_string()
    };
    if trimmed.is_empty() {
        format!("EvoFlux {new_version} is available (you have {current_version}).\n\nDownload now?")
    } else {
        format!(
            "EvoFlux {new_version} is available (you have {current_version}).\n\n{trimmed}\n\nDownload now?"
        )
    }
}

/// Format the tray status string shown during a bundle download.
///
/// ``total == Some(0)`` is treated the same as ``None`` — some HTTP
/// responses omit ``Content-Length`` and our caller passes whatever it
/// has — so we never produce a misleading ``"5/0 MB"`` label.
#[cfg(test)]
fn format_download_progress(downloaded_mb: usize, total_bytes: Option<u64>) -> String {
    match total_bytes {
        Some(total) if total > 0 => {
            let total_mb = total / (1024 * 1024);
            format!("Status: Downloading {downloaded_mb}/{total_mb} MB")
        }
        _ => format!("Status: Downloading {downloaded_mb} MB"),
    }
}

fn install_desktop_menus(app: &tauri::App) -> Result<()> {
    let about_metadata = {
        let mut builder = AboutMetadataBuilder::new()
            .name(Some("EvoFlux"))
            .version(Some(env!("CARGO_PKG_VERSION")))
            .copyright(Some("Copyright (c) 2026 EvoFlux contributors"))
            .website(Some("https://github.com/khuonghung/evoflux"))
            .website_label(Some("EvoFlux on GitHub"));
        if let Some(icon) = app.default_window_icon() {
            builder = builder.icon(Some(icon.clone()));
        }
        builder.build()
    };
    let app_about = PredefinedMenuItem::about(app, Some("About EvoFlux"), Some(about_metadata))?;

    let app_show = MenuItem::with_id(app, MENU_SHOW, "Show EvoFlux", true, None::<&str>)?;
    let app_new_window = MenuItem::with_id(
        app,
        MENU_NEW_WINDOW,
        "New Window",
        true,
        Some("CmdOrCtrl+N"),
    )?;
    let app_home = MenuItem::with_id(app, MENU_HOME, "Home", true, None::<&str>)?;
    let app_settings = MenuItem::with_id(app, MENU_SETTINGS, "Settings", true, None::<&str>)?;
    let app_providers = MenuItem::with_id(app, MENU_PROVIDERS, "Providers", true, None::<&str>)?;
    let app_notifications =
        MenuItem::with_id(app, MENU_NOTIFICATIONS, "Notifications", true, None::<&str>)?;
    let app_telemetry = MenuItem::with_id(app, MENU_TELEMETRY, "Telemetry", true, None::<&str>)?;
    let app_open_config_dir = MenuItem::with_id(
        app,
        MENU_OPEN_CONFIG_DIR,
        "View Config Folder",
        true,
        None::<&str>,
    )?;
    let app_reveal_backend_log = MenuItem::with_id(
        app,
        MENU_REVEAL_BACKEND_LOG,
        "View Backend Log",
        true,
        None::<&str>,
    )?;
    let app_quit = MenuItem::with_id(app, MENU_QUIT, "Quit EvoFlux", true, Some("CmdOrCtrl+Q"))?;
    let file_new_window = MenuItem::with_id(
        app,
        MENU_NEW_WINDOW,
        "New Window",
        true,
        Some("CmdOrCtrl+N"),
    )?;
    let file_home = MenuItem::with_id(app, MENU_HOME, "Home", true, Some("CmdOrCtrl+Shift+H"))?;
    let file_chat = MenuItem::with_id(app, MENU_CHAT, "Forge", true, Some("CmdOrCtrl+Shift+C"))?;
    let file_coding =
        MenuItem::with_id(app, MENU_CODING, "Coding", true, Some("CmdOrCtrl+Shift+K"))?;
    let file_quit = MenuItem::with_id(app, MENU_QUIT, "Quit EvoFlux", true, Some("CmdOrCtrl+Q"))?;
    let view_command_palette = MenuItem::with_id(
        app,
        MENU_COMMAND_PALETTE,
        "Command Palette…",
        true,
        Some("Ctrl+P"),
    )?;
    let view_wiki = MenuItem::with_id(app, MENU_WIKI, "Wiki", true, Some("Ctrl+M"))?;
    let view_scheduler =
        MenuItem::with_id(app, MENU_SCHEDULER, "Scheduled Tasks", true, Some("Ctrl+S"))?;
    let view_settings = MenuItem::with_id(app, MENU_SETTINGS, "Settings", true, None::<&str>)?;
    let view_telemetry = MenuItem::with_id(app, MENU_TELEMETRY, "Telemetry", true, None::<&str>)?;
    let view_reload = MenuItem::with_id(app, MENU_RELOAD, "Reload", true, Some("CmdOrCtrl+R"))?;
    let view_force_reload = MenuItem::with_id(
        app,
        MENU_FORCE_RELOAD,
        "Force Reload",
        true,
        Some("CmdOrCtrl+Shift+R"),
    )?;
    // ``CmdOrCtrl+=`` (not ``CmdOrCtrl++``) so the shortcut fires from the
    // bare ``=`` key — matches Chrome/Safari/VS Code and avoids requiring
    // Shift on US layouts.
    let view_zoom_in = MenuItem::with_id(app, MENU_ZOOM_IN, "Zoom In", true, Some("CmdOrCtrl+="))?;
    let view_zoom_out =
        MenuItem::with_id(app, MENU_ZOOM_OUT, "Zoom Out", true, Some("CmdOrCtrl+-"))?;
    let view_zoom_reset = MenuItem::with_id(
        app,
        MENU_ZOOM_RESET,
        "Actual Size",
        true,
        Some("CmdOrCtrl+0"),
    )?;

    // Edit submenu: PredefinedMenuItem gives native ⌘A/⌘C/⌘V/⌘X/⌘Z behavior on
    // macOS and adds visible menu entries on Windows/Linux, but on Windows the
    // predefined items may not bind Ctrl+A/C/V/X/Z accelerators automatically.
    // We therefore use explicit MenuItem entries with CmdOrCtrl accelerators
    // and route their events back to the webview via ``emit_frontend_command``,
    // which dispatches the corresponding document.execCommand.
    let edit_undo = MenuItem::with_id(app, MENU_EDIT_UNDO, "Undo", true, Some("CmdOrCtrl+Z"))?;
    let edit_redo = MenuItem::with_id(app, MENU_EDIT_REDO, "Redo", true, Some("CmdOrCtrl+Y"))?;
    let edit_cut = MenuItem::with_id(app, MENU_EDIT_CUT, "Cut", true, Some("CmdOrCtrl+X"))?;
    let edit_copy = MenuItem::with_id(app, MENU_EDIT_COPY, "Copy", true, Some("CmdOrCtrl+C"))?;
    let edit_paste = MenuItem::with_id(app, MENU_EDIT_PASTE, "Paste", true, Some("CmdOrCtrl+V"))?;
    let edit_select_all = MenuItem::with_id(
        app,
        MENU_EDIT_SELECT_ALL,
        "Select All",
        true,
        Some("CmdOrCtrl+A"),
    )?;

    let app_menu = SubmenuBuilder::new(app, "EvoFlux")
        .item(&app_about)
        .separator()
        .item(&app_show)
        .item(&app_new_window)
        .item(&app_home)
        .separator()
        .item(&app_settings)
        .item(&app_providers)
        .item(&app_notifications)
        .item(&app_telemetry)
        .separator()
        .item(&app_open_config_dir)
        .item(&app_reveal_backend_log)
        .separator()
        .item(&app_quit)
        .build()?;
    let file_menu = SubmenuBuilder::new(app, "File")
        .item(&file_new_window)
        .separator()
        .item(&file_home)
        .item(&file_chat)
        .item(&file_coding)
        .separator()
        .item(&file_quit)
        .build()?;
    let edit_menu = SubmenuBuilder::new(app, "Edit")
        .item(&edit_undo)
        .item(&edit_redo)
        .separator()
        .item(&edit_cut)
        .item(&edit_copy)
        .item(&edit_paste)
        .item(&edit_select_all)
        .build()?;
    let view_menu = SubmenuBuilder::new(app, "View")
        .item(&view_reload)
        .item(&view_force_reload)
        .separator()
        .item(&view_zoom_in)
        .item(&view_zoom_out)
        .item(&view_zoom_reset)
        .separator()
        .item(&view_command_palette)
        .item(&view_wiki)
        .item(&view_scheduler)
        .separator()
        .item(&view_settings)
        .item(&view_telemetry)
        .build()?;
    let window_menu = SubmenuBuilder::new(app, "Window")
        .minimize()
        .close_window_with_text("Hide to Tray")
        .build()?;
    let menu = Menu::with_items(
        app,
        &[&app_menu, &file_menu, &edit_menu, &view_menu, &window_menu],
    )?;
    app.set_menu(menu)?;

    let status = MenuItem::with_id(app, MENU_STATUS, "Status: Starting", false, None::<&str>)?;
    // Informational only; updated from ``set_tray_session``.
    let session = MenuItem::with_id(app, MENU_SESSION, TRAY_SESSION_IDLE, false, None::<&str>)?;
    let tray_show = MenuItem::with_id(app, MENU_SHOW, "Show EvoFlux", true, None::<&str>)?;
    let tray_new_window =
        MenuItem::with_id(app, MENU_NEW_WINDOW, "New Window", true, None::<&str>)?;
    let tray_chat = MenuItem::with_id(app, MENU_CHAT, "Forge", true, None::<&str>)?;
    let tray_coding = MenuItem::with_id(app, MENU_CODING, "Coding", true, None::<&str>)?;
    let tray_command_palette = MenuItem::with_id(
        app,
        MENU_COMMAND_PALETTE,
        "Command Palette…",
        true,
        None::<&str>,
    )?;
    let tray_settings = MenuItem::with_id(app, MENU_SETTINGS, "Settings", true, None::<&str>)?;
    let tray_open_config_dir = MenuItem::with_id(
        app,
        MENU_OPEN_CONFIG_DIR,
        "View Config Folder",
        true,
        None::<&str>,
    )?;
    let tray_reveal_backend_log = MenuItem::with_id(
        app,
        MENU_REVEAL_BACKEND_LOG,
        "View Backend Log",
        true,
        None::<&str>,
    )?;
    let tray_reload = MenuItem::with_id(app, MENU_RELOAD, "Reload Window", true, None::<&str>)?;
    let tray_quit = MenuItem::with_id(app, MENU_QUIT, "Quit EvoFlux", true, None::<&str>)?;
    let tray_menu = Menu::with_items(
        app,
        &[
            &status,
            &session,
            &PredefinedMenuItem::separator(app)?,
            &tray_show,
            &tray_new_window,
            &tray_chat,
            &tray_coding,
            &tray_command_palette,
            &PredefinedMenuItem::separator(app)?,
            &tray_settings,
            &tray_open_config_dir,
            &tray_reveal_backend_log,
            &tray_reload,
            &PredefinedMenuItem::separator(app)?,
            &tray_quit,
        ],
    )?;
    // Left-click opens the menu so the icon acts as a status surface, not
    // a launcher. We deliberately do not register ``on_menu_event`` here —
    // the app-level handler in ``main()`` already receives tray events,
    // so adding one would fire ``handle_desktop_menu`` twice.
    let mut tray = TrayIconBuilder::new()
        .menu(&tray_menu)
        .show_menu_on_left_click(true)
        .tooltip("EvoFlux");
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone()).icon_as_template(true);
    }
    tray.build(app)?;

    let state: tauri::State<'_, AppState> = app.state();
    tauri::async_runtime::block_on(async {
        state.tray_status.lock().await.replace(status);
        state.tray_session.lock().await.replace(session);
    });
    Ok(())
}

fn update_tray_status(app: &AppHandle, text: &str) {
    let state: tauri::State<'_, AppState> = app.state();
    let text = text.to_string();
    let status = state.tray_status.clone();
    tauri::async_runtime::spawn(async move {
        if let Some(item) = status.lock().await.as_ref() {
            let _ = item.set_text(text);
        }
    });
}

fn update_tray_session(app: &AppHandle, text: &str) {
    let state: tauri::State<'_, AppState> = app.state();
    let text = text.to_string();
    let session = state.tray_session.clone();
    tauri::async_runtime::spawn(async move {
        if let Some(item) = session.lock().await.as_ref() {
            let _ = item.set_text(text);
        }
    });
}

/// Frontend command: update the tray's session-label item.
///
/// Empty input falls back to the idle placeholder; long input is truncated
/// to ``TRAY_SESSION_MAX_LEN`` so the menu width stays sane.
#[tauri::command]
fn set_tray_session(app: AppHandle, text: String) -> Result<(), String> {
    let trimmed = text.trim();
    let label = if trimmed.is_empty() {
        TRAY_SESSION_IDLE.to_string()
    } else if trimmed.chars().count() > TRAY_SESSION_MAX_LEN {
        let mut s: String = trimmed.chars().take(TRAY_SESSION_MAX_LEN - 1).collect();
        s.push('…');
        s
    } else {
        trimmed.to_string()
    };
    update_tray_session(&app, &label);
    Ok(())
}

async fn wait_for_health(base: &str, attempts: u32, delay: Duration) -> Result<()> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .context("build reqwest client")?;
    let url = format!("{base}/api/health/live");
    for i in 0..attempts {
        match client.get(&url).send().await {
            Ok(r) if r.status().is_success() => return Ok(()),
            Ok(r) => log::debug!("health attempt {i} got status {}", r.status()),
            Err(e) => log::debug!("health attempt {i} failed: {e}"),
        }
        tokio::time::sleep(delay).await;
    }
    Err(anyhow!(
        "backend did not become healthy after {attempts} attempts"
    ))
}

struct ReadySidecar {
    sidecar: Sidecar,
    handshake: Handshake,
    base_url: String,
    attempt: u32,
}

struct BackendStartFailure {
    message: String,
    fatal: bool,
    attempt: u32,
}

async fn set_backend_startup(
    app: &AppHandle,
    phase: &str,
    message: impl Into<String>,
    attempt: u32,
    error: Option<String>,
    fatal: bool,
) {
    let state: tauri::State<'_, AppState> = app.state();
    let status = BackendStartupStatus {
        phase: phase.to_string(),
        message: message.into(),
        attempt,
        max_attempts: SIDECAR_START_ATTEMPTS,
        elapsed_ms: state.startup_started.elapsed().as_millis() as u64,
        error,
        fatal,
    };
    *state.backend_startup.lock().await = status.clone();
    app.emit("backend-progress", status).ok();
}

fn backend_error_is_fatal(message: &str) -> bool {
    let normalized = message.to_ascii_lowercase();
    [
        "can't locate revision",
        "cannot locate revision",
        "database schema revision",
        "alembic.ini not found",
        "sidecar bundle missing",
        "no python binary found",
        "locate python binary",
    ]
    .iter()
    .any(|needle| normalized.contains(needle))
}

async fn publish_backend_error(app: &AppHandle, failure: &BackendStartFailure) {
    set_backend_startup(
        app,
        "error",
        if failure.fatal {
            "The local engine needs attention."
        } else {
            "The local engine could not start."
        },
        failure.attempt,
        Some(failure.message.clone()),
        failure.fatal,
    )
    .await;
    update_tray_status(app, "Status: Error");
    app.emit(
        "backend-error",
        BackendError {
            message: failure.message.clone(),
            fatal: failure.fatal,
            attempt: failure.attempt,
            max_attempts: SIDECAR_START_ATTEMPTS,
        },
    )
    .ok();
}

async fn start_bundled_backend_with_retry(
    app: &AppHandle,
    desktop_token: Option<&str>,
) -> std::result::Result<ReadySidecar, BackendStartFailure> {
    let state: tauri::State<'_, AppState> = app.state();
    let _start_guard = state.backend_start_lock.lock().await;
    let operation_started = Instant::now();
    let mut last_failure = BackendStartFailure {
        message: "The local engine did not start.".to_string(),
        fatal: false,
        attempt: 0,
    };

    for attempt in 1..=SIDECAR_START_ATTEMPTS {
        set_backend_startup(
            app,
            "launching",
            format!("Launching the local engine… ({attempt}/{SIDECAR_START_ATTEMPTS})"),
            attempt,
            None,
            false,
        )
        .await;
        let attempt_started = Instant::now();
        let spawn_result = if let Some(token) = desktop_token {
            Sidecar::spawn_with_desktop_token(app, Some(token))
        } else {
            Sidecar::spawn(app)
        };
        let mut sidecar = match spawn_result {
            Ok(sidecar) => sidecar,
            Err(error) => {
                let message = format!("Sidecar unavailable: {error:#}");
                last_failure = BackendStartFailure {
                    fatal: backend_error_is_fatal(&message),
                    message,
                    attempt,
                };
                if last_failure.fatal {
                    break;
                }
                if attempt < SIDECAR_START_ATTEMPTS {
                    set_backend_startup(
                        app,
                        "retrying",
                        "Could not launch the engine. Retrying…",
                        attempt,
                        Some(last_failure.message.clone()),
                        false,
                    )
                    .await;
                    tokio::time::sleep(SIDECAR_RETRY_BASE_DELAY * attempt).await;
                }
                continue;
            }
        };

        set_backend_startup(
            app,
            "starting",
            "Loading Python and preparing the database…",
            attempt,
            None,
            false,
        )
        .await;
        let handshake_timeout = if attempt == 1 {
            SIDECAR_FIRST_HANDSHAKE_TIMEOUT
        } else {
            SIDECAR_RETRY_HANDSHAKE_TIMEOUT
        };
        let handshake = match sidecar.read_handshake(handshake_timeout).await {
            Ok(handshake) => handshake,
            Err(error) => {
                let tail = sidecar.log_tail(16 * 1024).await;
                let message = if tail.trim().is_empty() {
                    format!("Sidecar handshake failed: {error:#}")
                } else {
                    format!("Sidecar handshake failed: {error:#}\n\n{tail}")
                };
                last_failure = BackendStartFailure {
                    fatal: backend_error_is_fatal(&message),
                    message,
                    attempt,
                };
                sidecar.shutdown().await;
                log::warn!(
                    "desktop_startup_timing stage=handshake_failed attempt={} duration_ms={} fatal={}",
                    attempt,
                    attempt_started.elapsed().as_millis(),
                    last_failure.fatal
                );
                if last_failure.fatal {
                    break;
                }
                if attempt < SIDECAR_START_ATTEMPTS {
                    set_backend_startup(
                        app,
                        "retrying",
                        "The engine stopped during startup. Retrying…",
                        attempt,
                        Some(last_failure.message.clone()),
                        false,
                    )
                    .await;
                    tokio::time::sleep(SIDECAR_RETRY_BASE_DELAY * attempt).await;
                }
                continue;
            }
        };

        let base_url = format!("http://127.0.0.1:{}", handshake.port);
        set_backend_startup(
            app,
            "health",
            "Checking the local engine…",
            attempt,
            None,
            false,
        )
        .await;
        if let Err(error) = wait_for_health(&base_url, 60, Duration::from_millis(250)).await {
            let tail = sidecar.log_tail(16 * 1024).await;
            let message = format!("Sidecar health check failed: {error:#}\n\n{tail}");
            last_failure = BackendStartFailure {
                fatal: backend_error_is_fatal(&message),
                message,
                attempt,
            };
            sidecar.shutdown().await;
            if last_failure.fatal {
                break;
            }
            if attempt < SIDECAR_START_ATTEMPTS {
                set_backend_startup(
                    app,
                    "retrying",
                    "The engine did not answer. Retrying…",
                    attempt,
                    Some(last_failure.message.clone()),
                    false,
                )
                .await;
                tokio::time::sleep(SIDECAR_RETRY_BASE_DELAY * attempt).await;
            }
            continue;
        }

        log::info!(
            "desktop_startup_timing stage=sidecar_ready attempt={} attempt_ms={} total_ms={}",
            attempt,
            attempt_started.elapsed().as_millis(),
            operation_started.elapsed().as_millis()
        );
        return Ok(ReadySidecar {
            sidecar,
            handshake,
            base_url,
            attempt,
        });
    }

    Err(last_failure)
}

fn normalize_external_base_url(base_url: &str) -> Result<String> {
    let mut trimmed = base_url.trim().trim_end_matches('/');
    if let Some(stripped) = trimmed.strip_suffix("/api") {
        trimmed = stripped.trim_end_matches('/');
    }
    if trimmed.is_empty() {
        return Err(anyhow!("base URL is required"));
    }
    let parsed = reqwest::Url::parse(trimmed).context("parse base URL")?;
    match parsed.scheme() {
        "http" | "https" => Ok(trimmed.to_string()),
        scheme => Err(anyhow!("unsupported URL scheme: {scheme}")),
    }
}

fn normalize_server_name(name: Option<String>) -> Option<String> {
    name.map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn app_config_file(app: &AppHandle, name: &str) -> Result<PathBuf> {
    let dir = app
        .path()
        .app_config_dir()
        .context("resolve app config dir")?;
    std::fs::create_dir_all(&dir).context("create app config dir")?;
    Ok(dir.join(name))
}

fn app_backend_config_path(app: &AppHandle) -> Result<PathBuf> {
    app_config_file(app, "desktop-backend.json")
}

fn window_state_path(app: &AppHandle) -> Result<PathBuf> {
    app_config_file(app, "window-state.json")
}

fn load_window_state(app: &AppHandle) -> Result<Option<SavedWindowState>> {
    let path = window_state_path(app)?;
    if !path.exists() {
        return Ok(None);
    }
    let bytes = std::fs::read(&path).with_context(|| format!("read {}", path.display()))?;
    let state: SavedWindowState =
        serde_json::from_slice(&bytes).with_context(|| format!("parse {}", path.display()))?;
    if state.width < 760 || state.height < 560 {
        return Ok(None);
    }
    Ok(Some(state))
}

fn save_window_state(app: &AppHandle, window: &tauri::WebviewWindow) -> Result<()> {
    if window.is_minimized().unwrap_or(false) || window.is_maximized().unwrap_or(false) {
        return Ok(());
    }
    let size = window.inner_size().context("read window inner size")?;
    if size.width < 760 || size.height < 560 {
        return Ok(());
    }
    let path = window_state_path(app)?;
    let state = SavedWindowState {
        width: size.width,
        height: size.height,
    };
    let bytes = serde_json::to_vec_pretty(&state).context("serialize window state")?;
    std::fs::write(&path, bytes).with_context(|| format!("write {}", path.display()))
}

fn load_app_backend_config(app: &AppHandle) -> Result<AppBackendConfig> {
    let path = app_backend_config_path(app)?;
    if !path.exists() {
        return Ok(AppBackendConfig::default());
    }
    let bytes = std::fs::read(&path).with_context(|| format!("read {}", path.display()))?;
    let value: serde_json::Value =
        serde_json::from_slice(&bytes).with_context(|| format!("parse {}", path.display()))?;
    let config = if value
        .get("servers")
        .and_then(|servers| servers.as_array())
        .and_then(|servers| servers.first())
        .is_some_and(|server| server.is_string())
    {
        let active_base_url = value
            .get("active_base_url")
            .and_then(|url| url.as_str())
            .map(str::to_string);
        let servers = value
            .get("servers")
            .and_then(|servers| servers.as_array())
            .into_iter()
            .flatten()
            .filter_map(|server| server.as_str())
            .map(|base_url| SavedAppServer {
                base_url: base_url.to_string(),
                name: None,
            })
            .collect();
        AppBackendConfig {
            active_base_url,
            servers,
        }
    } else {
        serde_json::from_value(value).with_context(|| format!("parse {}", path.display()))?
    };
    Ok(config)
}

fn save_app_backend_config(
    app: &AppHandle,
    base_url: Option<&str>,
    name: Option<&str>,
    activate: bool,
) -> Result<()> {
    let path = app_backend_config_path(app)?;
    let mut config = load_app_backend_config(app).unwrap_or_default();
    if activate {
        config.active_base_url = base_url.map(str::to_string);
    }
    if let Some(url) = base_url {
        if let Some(saved) = config
            .servers
            .iter_mut()
            .find(|saved| saved.base_url == url)
        {
            if let Some(name) = name {
                saved.name = Some(name.to_string());
            }
        } else {
            config.servers.push(SavedAppServer {
                base_url: url.to_string(),
                name: name.map(str::to_string),
            });
        }
    }
    let bytes = serde_json::to_vec_pretty(&config).context("serialize desktop backend config")?;
    std::fs::write(&path, bytes).with_context(|| format!("write {}", path.display()))
}

fn remove_app_backend_server(app: &AppHandle, base_url: &str) -> Result<()> {
    let path = app_backend_config_path(app)?;
    let mut config = load_app_backend_config(app).unwrap_or_default();
    config.servers.retain(|server| {
        normalize_external_base_url(&server.base_url).map_or(true, |saved| saved != base_url)
    });
    if config
        .active_base_url
        .as_deref()
        .and_then(|active| normalize_external_base_url(active).ok())
        .as_deref()
        == Some(base_url)
    {
        config.active_base_url = None;
    }
    let bytes = serde_json::to_vec_pretty(&config).context("serialize desktop backend config")?;
    std::fs::write(&path, bytes).with_context(|| format!("write {}", path.display()))
}

fn frontend_webview_url() -> Result<WebviewUrl> {
    if cfg!(debug_assertions) {
        let dev_url = std::env::var("EVOFLUX_DESKTOP_DEV_URL")
            .unwrap_or_else(|_| "http://localhost:5173".to_string());
        Ok(WebviewUrl::External(
            dev_url.parse().context("parse dev frontend url")?,
        ))
    } else {
        Ok(WebviewUrl::App("index.html".into()))
    }
}

fn frontend_init_script(token: Option<&str>, base_url: &str) -> String {
    let token_define = token.map(|t| {
        format!(
            "Object.defineProperty(window, '__OAD_TOKEN__', {{ value: {token_json}, writable: true, configurable: true }});",
            token_json = serde_json::to_string(t).unwrap_or_else(|_| "\"\"".into())
        )
    }).unwrap_or_default();
    format!(
        "Object.defineProperty(window, '__OAD_API_BASE_URL__', {{ value: {base_json}, writable: true, configurable: true }});{token_define}",
        base_json = serde_json::to_string(base_url).unwrap_or_else(|_| "\"\"".into())
    )
}

fn backend_unavailable_init_script() -> String {
    "Object.defineProperty(window, '__OAD_BACKEND_UNAVAILABLE__', { value: true, writable: true, configurable: true });".to_string()
}

fn next_window_label(app: &AppHandle) -> String {
    for i in 2.. {
        let label = format!("{SECONDARY_WINDOW_PREFIX}{i}");
        if app.get_webview_window(&label).is_none() {
            return label;
        }
    }
    unreachable!("unbounded window-label iterator should always return")
}

async fn build_app_window(
    app: &AppHandle,
    label: String,
    init_script: String,
) -> Result<tauri::WebviewWindow> {
    let url = frontend_webview_url()?;
    let saved_size = load_window_state(app).ok().flatten();
    let initial_size = saved_size.unwrap_or(SavedWindowState {
        width: 1280,
        height: 820,
    });
    let builder = WebviewWindowBuilder::new(app, label, url)
        .title("EvoFlux")
        .inner_size(
            f64::from(initial_size.width),
            f64::from(initial_size.height),
        )
        .min_inner_size(760.0, 560.0)
        .initialization_script(&init_script)
        .visible(false);
    let builder = configure_window_chrome(builder);
    let win = builder.build().context("build webview window")?;
    if let Some(size) = saved_size {
        win.set_size(PhysicalSize::new(size.width, size.height))
            .ok();
    }
    let state: tauri::State<'_, AppState> = app.state();
    win.set_zoom(*state.zoom.lock().await).ok();
    win.show().context("show window")?;
    win.set_focus().ok();
    Ok(win)
}

async fn create_app_window(app: &AppHandle, label: Option<&str>) -> Result<tauri::WebviewWindow> {
    let state: tauri::State<'_, AppState> = app.state();
    let base = state
        .backend_base_url
        .lock()
        .await
        .clone()
        .ok_or_else(|| anyhow!("backend is not ready"))?;
    let token = state.desktop_token.lock().await.clone();
    let init_script = frontend_init_script(token.as_deref(), &base);
    build_app_window(
        app,
        label
            .map(str::to_string)
            .unwrap_or_else(|| next_window_label(app)),
        init_script,
    )
    .await
}

async fn start_backend_and_window(app: AppHandle) -> Result<()> {
    let state: tauri::State<'_, AppState> = app.state();
    if app.get_webview_window(MAIN_WINDOW).is_none() {
        build_app_window(
            &app,
            MAIN_WINDOW.to_string(),
            backend_unavailable_init_script(),
        )
        .await?;
    }

    if let Some(active_base_url) = load_app_backend_config(&app)
        .ok()
        .and_then(|config| config.active_base_url)
    {
        set_backend_startup(
            &app,
            "external",
            "Checking the configured backend…",
            0,
            None,
            false,
        )
        .await;
        match normalize_external_base_url(&active_base_url) {
            Ok(base) => match wait_for_health(&base, 8, Duration::from_millis(250)).await {
                Ok(()) => {
                    state
                        .window_backend_base_urls
                        .lock()
                        .await
                        .insert(MAIN_WINDOW.to_string(), base.clone());
                    if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
                        window
                            .eval(frontend_init_script(None, &base))
                            .context("inject external backend config")?;
                    }
                    update_tray_status(&app, "Status: Running");
                    set_backend_startup(&app, "ready", "Configured backend ready", 0, None, false)
                        .await;
                    app.emit(
                        "backend-ready",
                        BackendReady {
                            port: 0,
                            version: "external".to_string(),
                            base_url: base,
                            token: None,
                            sidecar_running: false,
                        },
                    )
                    .ok();
                    return Ok(());
                }
                Err(e) => {
                    log::warn!("desktop: saved external backend is not reachable at startup: {e:#}")
                }
            },
            Err(e) => {
                log::warn!("desktop: saved external backend URL is invalid at startup: {e:#}")
            }
        }
    }

    let ready = match start_bundled_backend_with_retry(&app, None).await {
        Ok(ready) => ready,
        Err(failure) => {
            log::warn!(
                "desktop: bundled backend failed at startup: {}",
                failure.message
            );
            publish_backend_error(&app, &failure).await;
            return Ok(());
        }
    };
    log::info!(
        "sidecar handshake: port={} pid={} version={}",
        ready.handshake.port,
        ready.handshake.pid,
        ready.handshake.version
    );
    let token = ready.handshake.token.clone();
    let init_script = frontend_init_script(Some(&token), &ready.base_url);

    let _ = state.sidecar.lock().await.replace(ready.sidecar);
    let _ = state
        .desktop_token
        .lock()
        .await
        .replace(ready.handshake.token);
    let _ = state
        .backend_base_url
        .lock()
        .await
        .replace(ready.base_url.clone());
    *state.backend_mode.lock().await = BackendMode::Bundled;

    if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
        window
            .eval(&init_script)
            .context("inject bundled backend config")?;
    }
    update_tray_status(&app, "Status: Running");
    set_backend_startup(
        &app,
        "ready",
        "Local engine ready",
        ready.attempt,
        None,
        false,
    )
    .await;

    app.emit(
        "backend-ready",
        BackendReady {
            port: ready.handshake.port,
            version: ready.handshake.version,
            base_url: ready.base_url,
            token: Some(token),
            sidecar_running: true,
        },
    )
    .ok();

    Ok(())
}

fn main() {
    let state = AppState {
        sidecar: Arc::new(Mutex::new(None)),
        desktop_token: Arc::new(Mutex::new(None)),
        backend_base_url: Arc::new(Mutex::new(None)),
        backend_mode: Arc::new(Mutex::new(BackendMode::Bundled)),
        window_backend_base_urls: Arc::new(Mutex::new(HashMap::new())),
        backend_startup: Arc::new(Mutex::new(BackendStartupStatus::default())),
        backend_start_lock: Arc::new(Mutex::new(())),
        startup_started: Instant::now(),
        force_reloading: Arc::new(AtomicBool::new(false)),
        quitting: Arc::new(AtomicBool::new(false)),
        tray_status: Arc::new(Mutex::new(None)),
        tray_session: Arc::new(Mutex::new(None)),
        active_window_label: Arc::new(Mutex::new(MAIN_WINDOW.to_string())),
        zoom: Arc::new(Mutex::new(ZOOM_DEFAULT)),
    };

    let log_plugin = tauri_plugin_log::Builder::new()
        .level(log::LevelFilter::Info)
        .build();

    tauri::Builder::default()
        .plugin(log_plugin)
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            show_main_window(app);
        }))
        .manage(state)
        .on_menu_event(|app, event| handle_desktop_menu(app, event.id().as_ref()))
        .invoke_handler(tauri::generate_handler![
            request_voice_permissions,
            save_workspace_file,
            backend_health,
            backend_logs_path,
            app_backend_status,
            app_retry_backend,
            app_reveal_backend_log,
            app_remove_backend_server,
            app_save_backend_server,
            app_use_external_backend,
            app_use_bundled_backend,
            app_new_window,
            app_open_browser_devtools,
            app_browser_webview_navigate,
            app_browser_webview_command,
            app_browser_webview_url,
            app_browser_webview_agent_action,
            set_tray_session,
            workspace::list_workspace_files,
            workspace::read_workspace_file,
            workspace::open_workspace_file_with_handle,
            workspace::open_workspace_root_with_handle,
            workspace::reveal_workspace_path_with_handle,
            workspace::list_directory,
            workspace::start_file_watcher,
            workspace::stop_file_watcher,
            openers::list_workspace_openers,
            openers::open_workspace_with,
        ])
        .setup(|app| {
            install_desktop_menus(app)?;
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                if let Err(e) = start_backend_and_window(handle.clone()).await {
                    log::error!("failed to start backend: {e:#}");
                    publish_backend_error(
                        &handle,
                        &BackendStartFailure {
                            message: format!("{e:#}"),
                            fatal: backend_error_is_fatal(&format!("{e:#}")),
                            attempt: 0,
                        },
                    )
                    .await;
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| match event {
            RunEvent::WindowEvent {
                label,
                event: WindowEvent::Focused(true),
                ..
            } if label == MAIN_WINDOW || label.starts_with(SECONDARY_WINDOW_PREFIX) => {
                let state: tauri::State<'_, AppState> = app.state();
                tauri::async_runtime::block_on(async {
                    *state.active_window_label.lock().await = label.to_string();
                });
            }
            RunEvent::WindowEvent {
                label,
                event: WindowEvent::CloseRequested { api, .. },
                ..
            } if label == MAIN_WINDOW || label.starts_with(SECONDARY_WINDOW_PREFIX) => {
                let state: tauri::State<'_, AppState> = app.state();
                if !state.quitting.load(Ordering::SeqCst) {
                    api.prevent_close();
                    if label == MAIN_WINDOW {
                        if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
                            let _ = window.hide();
                        }
                    } else if let Some(window) = app.get_webview_window(label.as_str()) {
                        let _ = window.destroy();
                        tauri::async_runtime::block_on(async {
                            state
                                .window_backend_base_urls
                                .lock()
                                .await
                                .remove(label.as_str());
                            *state.active_window_label.lock().await = MAIN_WINDOW.to_string();
                        });
                    }
                }
            }
            #[cfg(target_os = "macos")]
            RunEvent::Reopen {
                has_visible_windows: _,
                ..
            } => {
                show_main_window(app);
            }
            RunEvent::ExitRequested { .. } => {
                persist_active_window_state(app);
                let state: tauri::State<'_, AppState> = app.state();
                let sidecar = state.sidecar.clone();
                // Block so the child receives SIGTERM before the parent exits.
                tauri::async_runtime::block_on(async move {
                    if let Some(mut s) = sidecar.lock().await.take() {
                        s.shutdown().await;
                    }
                });
            }
            _ => {}
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── dialog_result_is_accept ──────────────────────────────────────────────
    //
    // Guards the OkCancelCustom mapping. rfd surfaces the user's choice as
    // ``Custom("Install")`` on macOS/Linux but the underlying system dialog
    // may report ``Ok``/``Yes`` instead — both must count as accept, and
    // every other variant (including a ``Custom`` with a different label)
    // must count as cancel.

    #[test]
    fn dialog_result_custom_with_matching_label_accepts() {
        assert!(dialog_result_is_accept(
            &MessageDialogResult::Custom("Install".into()),
            "Install"
        ));
    }

    #[test]
    fn dialog_result_custom_with_other_label_rejects() {
        assert!(!dialog_result_is_accept(
            &MessageDialogResult::Custom("Later".into()),
            "Install"
        ));
    }

    #[test]
    fn dialog_result_ok_and_yes_accept() {
        assert!(dialog_result_is_accept(&MessageDialogResult::Ok, "Install"));
        assert!(dialog_result_is_accept(
            &MessageDialogResult::Yes,
            "Install"
        ));
    }

    #[test]
    fn dialog_result_cancel_and_no_reject() {
        assert!(!dialog_result_is_accept(
            &MessageDialogResult::Cancel,
            "Install"
        ));
        assert!(!dialog_result_is_accept(
            &MessageDialogResult::No,
            "Install"
        ));
    }

    #[test]
    fn frontend_init_script_allows_runtime_backend_switches() {
        let script = frontend_init_script(Some("secret"), "http://127.0.0.1:4082");

        assert!(script.contains("__OAD_API_BASE_URL__"));
        assert!(script.contains("__OAD_TOKEN__"));
        assert_eq!(
            script.matches("writable: true, configurable: true").count(),
            2
        );
    }

    #[test]
    fn saved_backend_config_can_mark_external_backend_active() {
        let config = AppBackendConfig {
            active_base_url: Some("http://192.168.1.10:4082".to_string()),
            ..AppBackendConfig::default()
        };

        let serialized = serde_json::to_string(&config).expect("serialize config");
        let parsed: AppBackendConfig = serde_json::from_str(&serialized).expect("parse config");

        assert_eq!(
            parsed.active_base_url.as_deref(),
            Some("http://192.168.1.10:4082")
        );
    }

    // ── format_update_prompt ────────────────────────────────────────────────
    //
    // The prompt is the only thing the user reads before deciding to install,
    // so it must (a) always show both version numbers, (b) handle a missing
    // body without printing literal "None" or doubled blank lines, and
    // (c) bound the length so a runaway changelog doesn't blow out the modal.

    #[test]
    fn update_prompt_without_notes_omits_notes_paragraph() {
        let prompt = format_update_prompt("1.2.0", "1.1.0", None);
        assert!(prompt.contains("1.2.0"));
        assert!(prompt.contains("1.1.0"));
        assert!(prompt.contains("Download now?"));
        // Exactly one blank line between the version line and the call to
        // action — i.e. no orphan ``\n\n\n`` from an empty body.
        assert!(!prompt.contains("\n\n\n"));
    }

    #[test]
    fn update_prompt_with_empty_string_body_treated_as_no_notes() {
        let with_empty = format_update_prompt("1.2.0", "1.1.0", Some(""));
        let with_none = format_update_prompt("1.2.0", "1.1.0", None);
        assert_eq!(with_empty, with_none);
    }

    #[test]
    fn update_prompt_with_whitespace_only_body_treated_as_no_notes() {
        let prompt = format_update_prompt("1.2.0", "1.1.0", Some("   \n\t  "));
        let baseline = format_update_prompt("1.2.0", "1.1.0", None);
        assert_eq!(prompt, baseline);
    }

    #[test]
    fn update_prompt_includes_short_notes_verbatim() {
        let prompt = format_update_prompt("1.2.0", "1.1.0", Some("Fixed crash on launch"));
        assert!(prompt.contains("Fixed crash on launch"));
    }

    #[test]
    fn update_prompt_truncates_long_notes_with_ellipsis() {
        let long = "x".repeat(2000);
        let prompt = format_update_prompt("1.2.0", "1.1.0", Some(&long));
        // The xxxxx body itself must be capped well below the original
        // length and end with an ellipsis. Total prompt length is body +
        // surrounding template, so it stays under ~1000 chars.
        assert!(prompt.contains('…'));
        assert!(prompt.len() < 1000);
        assert!(prompt.contains("1.2.0"));
        assert!(prompt.contains("Download now?"));
    }

    #[test]
    fn update_prompt_truncation_respects_char_boundaries() {
        // A body of 700 multi-byte chars (3 bytes each in UTF-8) would
        // panic on a naive ``&body[..N]`` slice. ``chars().take`` keeps
        // us safe — assert we don't panic and produce a valid String.
        let multibyte_body: String = "✦".repeat(700);
        let prompt = format_update_prompt("1.2.0", "1.1.0", Some(&multibyte_body));
        assert!(prompt.contains('…'));
        assert!(prompt.is_char_boundary(prompt.len()));
    }

    // ── format_download_progress ────────────────────────────────────────────
    //
    // Closure-callable formatter for the tray status. Critical: never
    // produce "0/0 MB" or similar garbage when Content-Length is missing
    // or zero, and never divide by zero.

    #[test]
    fn download_progress_with_total_shows_fraction() {
        assert_eq!(
            format_download_progress(3, Some(50 * 1024 * 1024)),
            "Status: Downloading 3/50 MB"
        );
    }

    #[test]
    fn download_progress_without_total_omits_denominator() {
        assert_eq!(
            format_download_progress(7, None),
            "Status: Downloading 7 MB"
        );
    }

    #[test]
    fn download_progress_with_zero_total_falls_back_to_no_denominator() {
        // A misbehaving server that returns ``Content-Length: 0`` must not
        // produce ``"5/0 MB"`` — the fallback path drops the denominator.
        assert_eq!(
            format_download_progress(5, Some(0)),
            "Status: Downloading 5 MB"
        );
    }

    #[test]
    fn download_progress_handles_partial_megabyte_total() {
        // 500 KB total → integer-MB division yields 0, so we treat it
        // identically to "no total" rather than printing "0/0 MB".
        let small_total = 500 * 1024;
        let label = format_download_progress(0, Some(small_total));
        // Integer division gives ``0`` MB; not ideal but at least not
        // misleading — the formatter still prints a valid "downloading"
        // string and never panics.
        assert!(label.starts_with("Status: Downloading"));
    }

    #[test]
    fn migration_revision_errors_are_fatal() {
        assert!(backend_error_is_fatal(
            "Can't locate revision identified by '00000037'"
        ));
        assert!(backend_error_is_fatal(
            "Database schema revision '42' is newer than this build"
        ));
    }

    #[test]
    fn cold_start_timeout_is_retriable() {
        assert!(!backend_error_is_fatal(
            "timed out waiting for handshake while Defender scanned files"
        ));
    }
}
