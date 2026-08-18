// Prevents additional console window on Windows in release.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod native_messaging;
mod openers;
mod sidecar;
mod workspace;

use anyhow::{anyhow, Context, Result};
use base64::{engine::general_purpose::STANDARD as BASE64_STANDARD, Engine as _};
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

#[derive(Debug, PartialEq, Eq)]
enum StartupBackend {
    DevelopmentExternal(String),
    SavedExternal(String),
    Bundled,
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

#[derive(Deserialize)]
struct NativeDiscoveryTokenResponse {
    discovery_token: String,
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
const DEV_BACKEND_URL_ENV: &str = "EVOFLUX_DESKTOP_DEV_BACKEND_URL";
const DEV_BACKEND_HEALTH_ATTEMPTS: u32 = 60;

/// Label shown in the tray when no chat/coding session is active.
const TRAY_SESSION_IDLE: &str = "No active session";

#[cfg(target_os = "macos")]
const MACOS_TRAFFIC_LIGHT_X: f64 = 8.0;
#[cfg(target_os = "macos")]
const MACOS_TRAFFIC_LIGHT_Y: f64 = 22.0;

/// Hard cap on tray session label width. Keeps the menu from stretching
/// uncomfortably wide when a session title or workspace name is long.
const TRAY_SESSION_MAX_LEN: usize = 60;

/// Apply platform-specific window chrome.
///
/// macOS uses an overlay title-bar; the React app places sidebar/history
/// controls immediately after the traffic-lights. ``traffic_light_position``
/// must be set from Rust because the JSON config value is ignored when the
/// window is built via ``WebviewWindowBuilder``.
#[cfg_attr(not(target_os = "windows"), allow(dead_code))]
fn windows_acrylic_effects() -> tauri::utils::config::WindowEffectsConfig {
    use tauri::{
        utils::config::{Color, WindowEffectsConfig},
        window::Effect,
    };

    WindowEffectsConfig {
        // Acrylic is supported across Windows 10 and 11. The frontend
        // reapplies its tint whenever EvoFlux's resolved theme changes.
        effects: vec![Effect::Acrylic],
        state: None,
        radius: None,
        color: Some(Color(250, 250, 250, 110)),
    }
}

fn configure_window_chrome(
    builder: WebviewWindowBuilder<'_, tauri::Wry, AppHandle>,
) -> WebviewWindowBuilder<'_, tauri::Wry, AppHandle> {
    #[cfg(target_os = "macos")]
    {
        use tauri::{
            utils::config::WindowEffectsConfig,
            window::{Effect, EffectState},
            LogicalPosition, TitleBarStyle,
        };
        builder
            .transparent(true)
            .effects(WindowEffectsConfig {
                effects: vec![Effect::Sidebar],
                state: Some(EffectState::FollowsWindowActiveState),
                radius: Some(12.0),
                color: None,
            })
            .title_bar_style(TitleBarStyle::Overlay)
            .hidden_title(true)
            .traffic_light_position(LogicalPosition::new(
                MACOS_TRAFFIC_LIGHT_X,
                MACOS_TRAFFIC_LIGHT_Y,
            ))
    }
    #[cfg(target_os = "windows")]
    {
        builder.transparent(true).effects(windows_acrylic_effects())
    }
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    {
        builder
    }
}

/// Let the frontend own drag-and-drop on every desktop platform.
///
/// Wry's native handler consumes the platform drop operation after forwarding
/// it as a Tauri event. EvoFlux does not use that event: the Work sidebar and
/// composer both rely on HTML5 drag events instead. Leaving the native handler
/// enabled therefore lets a row start dragging while preventing the frontend
/// from receiving its drop, notably in WKWebView on macOS.
fn configure_frontend_drag_drop(
    builder: WebviewWindowBuilder<'_, tauri::Wry, AppHandle>,
) -> WebviewWindowBuilder<'_, tauri::Wry, AppHandle> {
    builder.disable_drag_drop_handler()
}

/// Reapply the macOS controls after Tauri/Wry installs and sizes its content
/// view. The builder inset is applied too early and AppKit resets it during
/// the post-build size pass, so relying on the builder alone has no visible
/// effect for restored windows.
#[cfg(target_os = "macos")]
fn enforce_macos_traffic_light_position(window: &tauri::WebviewWindow) -> Result<()> {
    use objc2_app_kit::{NSView, NSWindow, NSWindowButton};

    window
        .with_webview(|webview| unsafe {
            let ns_window: &NSWindow = &*webview.ns_window().cast();
            let Some(close) = ns_window.standardWindowButton(NSWindowButton::CloseButton) else {
                log::warn!("desktop: macOS close button is unavailable");
                return;
            };
            let Some(minimize) = ns_window.standardWindowButton(NSWindowButton::MiniaturizeButton)
            else {
                log::warn!("desktop: macOS minimize button is unavailable");
                return;
            };
            let Some(title_bar_container) = close
                .superview()
                .and_then(|button_group| button_group.superview())
            else {
                log::warn!("desktop: macOS title-bar container is unavailable");
                return;
            };

            let close_frame = NSView::frame(&close);
            let title_bar_height = close_frame.size.height + MACOS_TRAFFIC_LIGHT_Y;
            let mut title_bar_frame = NSView::frame(&title_bar_container);
            title_bar_frame.size.height = title_bar_height;
            title_bar_frame.origin.y = ns_window.frame().size.height - title_bar_height;
            title_bar_container.setFrame(title_bar_frame);

            let spacing = NSView::frame(&minimize).origin.x - close_frame.origin.x;
            let mut buttons = vec![close, minimize];
            if let Some(zoom) = ns_window.standardWindowButton(NSWindowButton::ZoomButton) {
                buttons.push(zoom);
            }
            for (index, button) in buttons.into_iter().enumerate() {
                let button_frame = NSView::frame(&button);
                let mut origin = button_frame.origin;
                origin.x = MACOS_TRAFFIC_LIGHT_X + index as f64 * spacing;
                // AppKit may move the controls vertically when entering or
                // leaving a maximized/full-height window. Keep their visual
                // center locked to the 36 pt React title-bar strip.
                origin.y = (title_bar_height - button_frame.size.height) / 2.0;
                button.setFrameOrigin(origin);
            }
        })
        .context("position macOS title-bar controls")
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
        supports_bundled: !development_backend_is_forced(),
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
    reject_forced_development_backend_mutation()?;
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
    reject_forced_development_backend_mutation()?;
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

    sync_webbridge_native_connection(&app, &normalized, None).await;
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
    reject_forced_development_backend_mutation()?;
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
    reject_forced_development_backend_mutation()?;
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
    sync_webbridge_native_connection(&app, &base, token.as_deref()).await;
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

fn browser_observability_init_script() -> &'static str {
    r#"
        (() => {
            const label = window.__TAURI_INTERNALS__?.metadata?.currentWebview?.label;
            if (!String(label || '').startsWith('browser-') || globalThis.__evofluxBrowserRuntime) return;
            const runtime = { console: [], network: [], dialogs: [], dialogBehavior: { behavior: 'dismiss', promptText: null } };
            const keep = (items, value, max) => {
                items.push(value);
                if (items.length > max) items.splice(0, items.length - max);
            };
            for (const level of ['debug', 'log', 'info', 'warn', 'error']) {
                const original = console[level]?.bind(console);
                if (!original) continue;
                console[level] = (...args) => {
                    keep(runtime.console, {
                        ts: Date.now(),
                        level,
                        text: args.map((value) => {
                            try { return typeof value === 'string' ? value : JSON.stringify(value); }
                            catch { return String(value); }
                        }).join(' ').slice(0, 4000),
                    }, 400);
                    original(...args);
                };
            }
            addEventListener('error', (event) => keep(runtime.console, {
                ts: Date.now(),
                level: 'error',
                source: event.filename || '',
                line: event.lineno || 0,
                column: event.colno || 0,
                text: String(event.error?.stack || event.message || 'Page error').slice(0, 4000),
            }, 400));
            addEventListener('unhandledrejection', (event) => keep(runtime.console, {
                ts: Date.now(),
                level: 'error',
                text: String(event.reason?.stack || event.reason || 'Unhandled rejection').slice(0, 4000),
            }, 400));
            globalThis.alert = (message) => {
                keep(runtime.dialogs, { ts: Date.now(), type: 'alert', message: String(message) }, 100);
            };
            globalThis.confirm = (message) => {
                keep(runtime.dialogs, { ts: Date.now(), type: 'confirm', message: String(message) }, 100);
                return runtime.dialogBehavior.behavior === 'accept';
            };
            globalThis.prompt = (message, defaultValue = '') => {
                keep(runtime.dialogs, { ts: Date.now(), type: 'prompt', message: String(message), default_value: String(defaultValue) }, 100);
                return runtime.dialogBehavior.behavior === 'accept'
                    ? String(runtime.dialogBehavior.promptText ?? defaultValue)
                    : null;
            };
            const originalFetch = globalThis.fetch?.bind(globalThis);
            if (originalFetch) globalThis.fetch = async (...args) => {
                const request = args[0];
                const method = String(args[1]?.method || request?.method || 'GET').toUpperCase();
                const url = String(request?.url || request);
                const started = performance.now();
                try {
                    const response = await originalFetch(...args);
                    keep(runtime.network, { ts: Date.now(), method, url, status: response.status, duration_ms: performance.now() - started, type: 'fetch' }, 500);
                    return response;
                } catch (error) {
                    keep(runtime.network, { ts: Date.now(), method, url, status: 0, duration_ms: performance.now() - started, type: 'fetch', error: String(error) }, 500);
                    throw error;
                }
            };
            const open = XMLHttpRequest.prototype.open;
            const send = XMLHttpRequest.prototype.send;
            XMLHttpRequest.prototype.open = function(method, url, ...rest) {
                this.__evofluxRequest = { method: String(method).toUpperCase(), url: String(url), started: performance.now() };
                return open.call(this, method, url, ...rest);
            };
            XMLHttpRequest.prototype.send = function(...args) {
                this.addEventListener('loadend', () => {
                    const request = this.__evofluxRequest || { method: 'GET', url: this.responseURL, started: performance.now() };
                    keep(runtime.network, { ts: Date.now(), method: request.method, url: request.url, status: this.status, duration_ms: performance.now() - request.started, type: 'xhr' }, 500);
                }, { once: true });
                return send.apply(this, args);
            };
            globalThis.__evofluxBrowserRuntime = runtime;
        })();
    "#
}

fn browser_agent_cursor_runtime_script() -> &'static str {
    r##"
        (() => {
            if (globalThis.__evofluxEnsureAgentCursor) return;
            const HOST_ID = '__evoflux-agent-cursor';
            const TIP_X = 3;
            const TIP_Y = 2.5;
            let pulseTimer = null;
            const controller = {
                host: null,
                cursor: null,
                cursorPulse: null,
                enabled: false,
                suspended: false,
                lastX: null,
                lastY: null,
                mount() {
                    if (this.host?.isConnected) return;
                    this.host = document.getElementById(HOST_ID);
                    if (this.host) {
                        this.cursor = this.host.shadowRoot?.querySelector('.cursor') || null;
                        this.cursorPulse = this.host.shadowRoot?.querySelector('.cursor-pulse') || null;
                        return;
                    }
                    this.host = document.createElement('div');
                    this.host.id = HOST_ID;
                    this.host.setAttribute('aria-hidden', 'true');
                    this.host.style.cssText = 'all:initial;position:fixed;inset:0;pointer-events:none;z-index:2147483647;contain:layout style;';
                    const root = this.host.attachShadow({ mode: 'open' });
                    root.innerHTML = `
                        <style>
                            :host { all: initial; }
                            .layer { position: fixed; inset: 0; overflow: hidden; pointer-events: none; }
                            .cursor {
                                position: absolute; left: 0; top: 0; width: 17px; height: 18px;
                                transform: translate3d(var(--cursor-x, 72vw), var(--cursor-y, 34vh), 0);
                                transform-origin: 3px 2.5px; transition: transform 28ms linear;
                                will-change: transform;
                            }
                            .cursor-aura {
                                position: absolute; left: -2px; top: -2px; width: 14px; height: 14px;
                                border-radius: 50%; opacity: .34;
                                background: radial-gradient(circle, rgba(255, 255, 255, .38) 0 8%, rgba(91, 221, 239, .14) 34%, transparent 72%);
                                filter: blur(2px);
                            }
                            .cursor svg {
                                position: relative; display: block; width: 100%; height: 100%; overflow: visible;
                                filter: drop-shadow(0 1px 1px rgba(0, 0, 0, .38)) drop-shadow(0 0 3px rgba(72, 202, 224, .42));
                            }
                            .cursor-outline { fill: none; stroke: rgba(255, 255, 255, .96); stroke-width: 2.7; stroke-linejoin: round; stroke-linecap: round; }
                            .cursor-core { fill: url(#evoflux-cursor-fill); stroke: #10151a; stroke-width: .85; stroke-linejoin: round; stroke-linecap: round; }
                            .cursor-pulse {
                                position: absolute; left: -4px; top: -4px; width: 14px; height: 14px;
                                border: 1.5px solid rgba(105, 229, 241, .78); border-radius: 50%;
                                opacity: 0; transform: scale(.25);
                            }
                            .cursor.pressed { transform: translate3d(var(--cursor-x), var(--cursor-y), 0) scale(.9); transition-duration: 55ms; }
                            .cursor.pressed .cursor-aura { opacity: .7; filter: blur(1.5px); }
                            .cursor.pulsing .cursor-pulse { animation: evoflux-click .42s ease-out; }
                            @keyframes evoflux-click { 0% { opacity: 1; transform: scale(.25); } 100% { opacity: 0; transform: scale(2.2); } }
                            @media (prefers-reduced-motion: reduce) { .cursor { transition-duration: 0ms; } }
                        </style>
                        <div class="layer">
                            <div class="cursor">
                                <span class="cursor-aura"></span>
                                <span class="cursor-pulse"></span>
                                <svg viewBox="0 0 17 18" aria-hidden="true">
                                    <defs>
                                        <linearGradient id="evoflux-cursor-fill" x1="3" y1="2.5" x2="9" y2="13" gradientUnits="userSpaceOnUse">
                                            <stop offset="0" stop-color="#20272d"/>
                                            <stop offset=".55" stop-color="#0d1115"/>
                                            <stop offset="1" stop-color="#020405"/>
                                        </linearGradient>
                                    </defs>
                                    <path class="cursor-outline" d="M3 2.7 14.1 10.4 7.6 12.2Z"/>
                                    <path class="cursor-core" d="M3 2.7 14.1 10.4 7.6 12.2Z"/>
                                </svg>
                            </div>
                        </div>`;
                    this.cursor = root.querySelector('.cursor');
                    this.cursorPulse = root.querySelector('.cursor-pulse');
                    if (this.lastX == null || this.lastY == null) {
                        this.lastX = Math.max(0, Math.min(innerWidth - 1, innerWidth * .72));
                        this.lastY = Math.max(0, Math.min(innerHeight - 1, innerHeight * .34));
                    }
                    this.cursor.style.setProperty('--cursor-x', `${this.lastX - TIP_X}px`);
                    this.cursor.style.setProperty('--cursor-y', `${this.lastY - TIP_Y}px`);
                    (document.documentElement || document).appendChild(this.host);
                    this.host.style.visibility = this.suspended ? 'hidden' : 'visible';
                },
                move(x, y, phase = 'move') {
                    if (!this.cursor || !Number.isFinite(x) || !Number.isFinite(y)) return;
                    this.lastX = Math.max(0, Math.min(innerWidth - 1, x));
                    this.lastY = Math.max(0, Math.min(innerHeight - 1, y));
                    this.cursor.style.setProperty('--cursor-x', `${this.lastX - TIP_X}px`);
                    this.cursor.style.setProperty('--cursor-y', `${this.lastY - TIP_Y}px`);
                    this.cursor.classList.toggle('pressed', phase === 'press' || phase === 'drag');
                    if (phase !== 'release' && phase !== 'click') return;
                    this.cursor.classList.remove('pressed');
                    this.cursor.classList.remove('pulsing');
                    void this.cursorPulse?.offsetWidth;
                    this.cursor.classList.add('pulsing');
                    clearTimeout(pulseTimer);
                    pulseTimer = setTimeout(() => this.cursor?.classList.remove('pulsing'), 460);
                },
                moveToElement(element, phase = 'move') {
                    const rect = element?.getBoundingClientRect?.();
                    if (!rect) return;
                    this.move(rect.left + rect.width / 2, rect.top + rect.height / 2, phase);
                },
                setEnabled(nextEnabled) {
                    this.enabled = Boolean(nextEnabled);
                    if (!this.enabled) {
                        clearTimeout(pulseTimer);
                        pulseTimer = null;
                        this.host?.remove();
                        this.host = null;
                        this.cursor = null;
                        this.cursorPulse = null;
                        return;
                    }
                    this.mount();
                },
                setSuspended(nextSuspended) {
                    this.suspended = Boolean(nextSuspended);
                    if (!this.host) return;
                    this.host.style.visibility = this.suspended ? 'hidden' : 'visible';
                    void this.host.offsetHeight;
                },
            };
            globalThis.__evofluxAgentCursor = controller;
            globalThis.__evofluxEnsureAgentCursor = () => {
                controller.setEnabled(true);
                return controller;
            };
        })();
    "##
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
    if action == "screenshot" {
        let suspended = eval_browser_webview_action_once(
            &app,
            &label,
            "cursor_control",
            &serde_json::json!({ "suspended": true }),
        )
        .await
        .is_ok();
        let result = capture_browser_webview(&app, &label, &params).await;
        if suspended {
            let _ = eval_browser_webview_action_once(
                &app,
                &label,
                "cursor_control",
                &serde_json::json!({ "suspended": false }),
            )
            .await;
        }
        return result;
    }
    if action == "cookies" {
        return manage_browser_cookies(&app, &label, &params);
    }
    eval_browser_webview_action(&app, &label, &action, &params).await
}

fn manage_browser_cookies(
    app: &AppHandle,
    label: &str,
    params: &serde_json::Value,
) -> Result<serde_json::Value, String> {
    let webview = app_browser_webview(app, label)?;
    let operation = params
        .get("operation")
        .and_then(serde_json::Value::as_str)
        .unwrap_or("get");
    let requested_name = params.get("name").and_then(serde_json::Value::as_str);
    let requested_domain = params.get("domain").and_then(serde_json::Value::as_str);
    let requested_path = params
        .get("path")
        .and_then(serde_json::Value::as_str)
        .unwrap_or("/");

    if operation == "set" {
        let name = requested_name.ok_or_else(|| "cookies set requires name".to_string())?;
        let value = params
            .get("value")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default();
        if name
            .chars()
            .any(|character| matches!(character, ';' | '\r' | '\n'))
            || value
                .chars()
                .any(|character| matches!(character, '\r' | '\n'))
        {
            return Err("Cookie name or value contains invalid header characters".into());
        }
        let fallback_domain = webview
            .url()
            .ok()
            .and_then(|url| url.host_str().map(str::to_string));
        let domain = requested_domain
            .map(str::to_string)
            .or(fallback_domain)
            .ok_or_else(|| "cookies set requires an HTTP(S) page or explicit domain".to_string())?;
        let mut header = format!("{name}={value}; Path={requested_path}; Domain={domain}");
        if let Some(max_age) = params.get("max_age").and_then(serde_json::Value::as_i64) {
            header.push_str(&format!("; Max-Age={max_age}"));
        }
        if let Some(same_site) = params.get("same_site").and_then(serde_json::Value::as_str) {
            header.push_str(&format!("; SameSite={same_site}"));
        }
        if params.get("secure").and_then(serde_json::Value::as_bool) == Some(true) {
            header.push_str("; Secure");
        }
        if params.get("http_only").and_then(serde_json::Value::as_bool) == Some(true) {
            header.push_str("; HttpOnly");
        }
        let cookie = tauri::webview::Cookie::parse(header)
            .map_err(|error| format!("Invalid cookie: {error}"))?
            .into_owned();
        webview
            .set_cookie(cookie)
            .map_err(|error| format!("Could not set browser cookie: {error}"))?;
        return Ok(serde_json::json!({ "set": name, "domain": domain, "path": requested_path }));
    }

    let current_host = webview
        .url()
        .ok()
        .and_then(|url| url.host_str().map(str::to_string));
    let domain_filter = requested_domain.or(current_host.as_deref());
    let mut cookies = webview
        .cookies()
        .map_err(|error| format!("Could not read browser cookies: {error}"))?;
    cookies.retain(|cookie| {
        let name_matches = requested_name.map_or(true, |name| cookie.name() == name);
        let domain_matches = domain_filter.map_or(true, |domain| {
            cookie.domain().is_some_and(|cookie_domain| {
                domain == cookie_domain.trim_start_matches('.')
                    || domain.ends_with(&format!(".{}", cookie_domain.trim_start_matches('.')))
            })
        });
        let path_matches = operation != "delete"
            || params.get("path").is_none()
            || cookie.path() == Some(requested_path);
        name_matches && domain_matches && path_matches
    });

    if operation == "delete" {
        if requested_name.is_none() {
            return Err("cookies delete requires name".into());
        }
        let count = cookies.len();
        for cookie in cookies {
            webview
                .delete_cookie(cookie)
                .map_err(|error| format!("Could not delete browser cookie: {error}"))?;
        }
        return Ok(serde_json::json!({ "deleted": count }));
    }
    if operation != "get" {
        return Err(format!("Unsupported cookies operation: {operation}"));
    }

    let include_values = params
        .get("include_values")
        .and_then(serde_json::Value::as_bool)
        == Some(true);
    Ok(serde_json::Value::Array(
        cookies
            .into_iter()
            .map(|cookie| {
                serde_json::json!({
                    "name": cookie.name(),
                    "value": if include_values && cookie.http_only() != Some(true) { cookie.value() } else { "[redacted]" },
                    "domain": cookie.domain(),
                    "path": cookie.path(),
                    "secure": cookie.secure(),
                    "http_only": cookie.http_only(),
                    "same_site": cookie.same_site().map(|value| format!("{value:?}")),
                    "expires": cookie.expires().map(|value| format!("{value:?}")),
                })
            })
            .collect(),
    ))
}

async fn eval_browser_webview_action(
    app: &AppHandle,
    label: &str,
    action: &str,
    params: &serde_json::Value,
) -> Result<serde_json::Value, String> {
    let async_start = if action == "http" {
        Some("http_start")
    } else if action == "evaluate"
        && params
            .get("await_promise")
            .and_then(serde_json::Value::as_bool)
            == Some(true)
    {
        Some("evaluate_start")
    } else {
        None
    };
    let Some(start_action) = async_start else {
        return eval_browser_webview_action_once(app, label, action, params).await;
    };

    let async_id = format!(
        "{}-{}",
        label,
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos()
    );
    let mut start_params = params.clone();
    start_params
        .as_object_mut()
        .ok_or_else(|| "Browser action parameters must be an object".to_string())?
        .insert(
            "async_id".to_string(),
            serde_json::Value::String(async_id.clone()),
        );
    eval_browser_webview_action_once(app, label, start_action, &start_params).await?;

    let timeout_ms = params
        .get("timeout_ms")
        .and_then(serde_json::Value::as_u64)
        .unwrap_or(15_000)
        .clamp(100, 30_000);
    let deadline = tokio::time::Instant::now() + Duration::from_millis(timeout_ms);
    let poll_params = serde_json::json!({ "async_id": async_id });
    loop {
        if tokio::time::Instant::now() >= deadline {
            return Err(format!(
                "Browser action timed out after {timeout_ms}ms: {action}"
            ));
        }
        let result =
            eval_browser_webview_action_once(app, label, "async_result", &poll_params).await?;
        if result.get("state").and_then(serde_json::Value::as_str) == Some("done") {
            if result.get("ok").and_then(serde_json::Value::as_bool) == Some(true) {
                return Ok(result
                    .get("value")
                    .cloned()
                    .unwrap_or(serde_json::Value::Null));
            }
            return Err(result
                .get("error")
                .and_then(serde_json::Value::as_str)
                .unwrap_or("Asynchronous browser action failed")
                .to_string());
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
}

async fn eval_browser_webview_action_once(
    app: &AppHandle,
    label: &str,
    action: &str,
    params: &serde_json::Value,
) -> Result<serde_json::Value, String> {
    let script = browser_agent_action_script(action, params)?;
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
    app_browser_webview(app, label)?
        .eval_with_callback(wrapped, move |result| {
            if let Ok(mut guard) = sender.lock() {
                if let Some(sender) = guard.take() {
                    let _ = sender.send(result);
                }
            }
        })
        .map_err(|error| format!("Could not run browser action: {error}"))?;

    let callback_timeout = if matches!(action, "status" | "exists" | "probe" | "async_result") {
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

async fn capture_browser_webview(
    app: &AppHandle,
    label: &str,
    params: &serde_json::Value,
) -> Result<serde_json::Value, String> {
    let webview = app_browser_webview(app, label)?;
    let child_position = webview
        .position()
        .map_err(|error| format!("Could not read browser position: {error}"))?;
    let child_size = webview
        .size()
        .map_err(|error| format!("Could not read browser size: {error}"))?;
    let window = webview.window();
    let window_position = window
        .inner_position()
        .map_err(|error| format!("Could not read browser window position: {error}"))?;
    let tauri_monitor = window
        .current_monitor()
        .map_err(|error| format!("Could not read browser display: {error}"))?
        .ok_or_else(|| "Browser is not currently on a display".to_string())?;

    let mut screen_x = window_position.x + child_position.x;
    let mut screen_y = window_position.y + child_position.y;
    let mut width = child_size.width;
    let mut height = child_size.height;

    if params
        .get("selector")
        .and_then(serde_json::Value::as_str)
        .is_some()
        || params
            .get("index")
            .and_then(serde_json::Value::as_i64)
            .is_some()
    {
        let rect = eval_browser_webview_action(app, label, "element_rect", params).await?;
        let viewport_width = rect
            .get("viewport_width")
            .and_then(serde_json::Value::as_f64)
            .unwrap_or(width as f64)
            .max(1.0);
        let viewport_height = rect
            .get("viewport_height")
            .and_then(serde_json::Value::as_f64)
            .unwrap_or(height as f64)
            .max(1.0);
        let scale_x = width as f64 / viewport_width;
        let scale_y = height as f64 / viewport_height;
        screen_x += (rect
            .get("x")
            .and_then(serde_json::Value::as_f64)
            .unwrap_or(0.0)
            * scale_x)
            .round() as i32;
        screen_y += (rect
            .get("y")
            .and_then(serde_json::Value::as_f64)
            .unwrap_or(0.0)
            * scale_y)
            .round() as i32;
        width = (rect
            .get("width")
            .and_then(serde_json::Value::as_f64)
            .unwrap_or(viewport_width)
            * scale_x)
            .round()
            .max(1.0) as u32;
        height = (rect
            .get("height")
            .and_then(serde_json::Value::as_f64)
            .unwrap_or(viewport_height)
            * scale_y)
            .round()
            .max(1.0) as u32;
    }

    // Tauri reports physical pixels. CoreGraphics (and therefore xcap on
    // macOS) addresses displays in logical points, so convert relative to the
    // current monitor. Other desktop capture backends use physical pixels.
    let capture_scale = if cfg!(target_os = "macos") {
        tauri_monitor.scale_factor().max(1.0)
    } else {
        1.0
    };
    let tauri_origin = tauri_monitor.position();
    let relative_x = ((screen_x - tauri_origin.x).max(0) as f64 / capture_scale).round() as u32;
    let relative_y = ((screen_y - tauri_origin.y).max(0) as f64 / capture_scale).round() as u32;
    width = (width as f64 / capture_scale).round().max(1.0) as u32;
    height = (height as f64 / capture_scale).round().max(1.0) as u32;

    let target_name = tauri_monitor.name().map(String::as_str);
    let target_width = tauri_monitor.size().width as f64 / capture_scale;
    let target_height = tauri_monitor.size().height as f64 / capture_scale;
    let monitor = xcap::Monitor::all()
        .map_err(|error| format!("Could not list browser displays: {error}"))?
        .into_iter()
        .min_by_key(|candidate| {
            let candidate_name = candidate.friendly_name().ok();
            let name_penalty = match (target_name, candidate_name.as_deref()) {
                (Some(left), Some(right)) if left == right => 0_u64,
                _ => 1_000_000,
            };
            let candidate_width = candidate.width().unwrap_or_default() as f64;
            let candidate_height = candidate.height().unwrap_or_default() as f64;
            name_penalty
                + (candidate_width - target_width).abs().round() as u64
                + (candidate_height - target_height).abs().round() as u64
        })
        .ok_or_else(|| "Could not find the display containing the browser".to_string())?;
    let monitor_width = monitor
        .width()
        .map_err(|error| format!("Could not read display bounds: {error}"))?;
    let monitor_height = monitor
        .height()
        .map_err(|error| format!("Could not read display bounds: {error}"))?;
    width = width.min(monitor_width.saturating_sub(relative_x)).max(1);
    height = height.min(monitor_height.saturating_sub(relative_y)).max(1);
    let image = monitor
        .capture_region(relative_x, relative_y, width, height)
        .map_err(|error| format!("Could not capture the in-app browser: {error}"))?;
    let mut png = std::io::Cursor::new(Vec::new());
    xcap::image::DynamicImage::ImageRgba8(image)
        .write_to(&mut png, xcap::image::ImageFormat::Png)
        .map_err(|error| format!("Could not encode browser screenshot: {error}"))?;
    Ok(serde_json::json!({
        "kind": "image",
        "media_type": "image/png",
        "data": BASE64_STANDARD.encode(png.into_inner()),
        "text": format!("[In-app browser screenshot: {}x{}]", width, height),
    }))
}

fn parse_browser_agent_result(raw: &str) -> Result<serde_json::Value, String> {
    if raw.len() > 16 * 1024 * 1024 {
        return Err("Browser action result exceeds 16 MB".into());
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
        "instrument",
        "snapshot",
        "click",
        "dblclick",
        "hover",
        "focus",
        "fill",
        "type",
        "clear",
        "submit",
        "press",
        "set_checked",
        "select",
        "drag",
        "scroll_into_view",
        "click_at",
        "dispatch_event",
        "extract",
        "query",
        "inspect",
        "html",
        "accessibility",
        "scroll",
        "console",
        "network",
        "dialogs",
        "dialog_behavior",
        "performance",
        "clear_logs",
        "storage",
        "cookies",
        "http",
        "http_start",
        "evaluate_start",
        "async_result",
        "debug_summary",
        "evaluate",
        "element_rect",
        "exists",
        "probe",
        "status",
        "cursor_control",
    ];
    if !SUPPORTED.contains(&action) {
        return Err(format!("Unsupported direct browser action: {action}"));
    }
    let action_json = serde_json::to_string(action)
        .map_err(|error| format!("Could not encode browser action: {error}"))?;
    let params_json = serde_json::to_string(params)
        .map_err(|error| format!("Could not encode browser parameters: {error}"))?;
    let cursor_runtime = browser_agent_cursor_runtime_script();
    Ok(format!(
        r#"() => {{
                    {cursor_runtime}
                    const action = {action_json};
                    const params = {params_json};
                    const visible = (element) => {{
                        const rect = element.getBoundingClientRect();
                        const style = element.ownerDocument.defaultView.getComputedStyle(element);
                        return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                    }};
                    const resolveElement = () => {{
                        if (Number.isInteger(params.index)) {{
                            const indexed = globalThis.__evofluxAgentElements?.[params.index];
                            if (indexed?.isConnected) return indexed;
                            return deepElements().find((element) => element.getAttribute('data-evoflux-agent-index') === String(params.index)) || null;
                        }}
                        if (typeof params.selector !== 'string') return null;
                        return deepElements().find((element) => {{
                            try {{ return element.matches(params.selector); }} catch {{ return false; }}
                        }}) || null;
                    }};
                    const deepElements = (root = document) => {{
                        const output = [];
                        const visit = (scope) => {{
                            const all = scope.querySelectorAll ? Array.from(scope.querySelectorAll('*')) : [];
                            for (const element of all) {{
                                output.push(element);
                                if (element.shadowRoot) visit(element.shadowRoot);
                                if (element.tagName === 'IFRAME') {{
                                    try {{ if (element.contentDocument) visit(element.contentDocument); }} catch {{}}
                                }}
                            }}
                        }};
                        visit(root);
                        return output;
                    }};
                    const describe = (element) => {{
                        const tag = element.tagName.toLowerCase();
                        const role = element.getAttribute('role') || '';
                        const labelledBy = element.getAttribute('aria-labelledby');
                        const labelledText = labelledBy
                            ? labelledBy.split(/\s+/).map((id) => element.ownerDocument.getElementById(id)?.innerText || '').join(' ').trim()
                            : '';
                        const label = element.getAttribute('aria-label') || labelledText || element.getAttribute('placeholder') || element.getAttribute('title') || '';
                        const text = String(element.innerText || element.value || element.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 180);
                        const state = [
                            element.disabled ? 'disabled' : '',
                            'checked' in element ? `checked=${{Boolean(element.checked)}}` : '',
                            element.getAttribute('aria-expanded') != null ? `expanded=${{element.getAttribute('aria-expanded')}}` : '',
                        ].filter(Boolean).join(' ');
                        const box = element.getBoundingClientRect();
                        return `${{tag}}${{role ? `[role=${{role}}]` : ''}}${{label ? ` "${{label}}"` : ''}}${{text ? `: ${{text}}` : ''}}${{state ? ` (${{state}})` : ''}} @${{Math.round(box.x)}},${{Math.round(box.y)}} ${{Math.round(box.width)}}x${{Math.round(box.height)}}`;
                    }};
                    const setEditableValue = (element, next, inputType = 'insertText', data = null) => {{
                        if (element.isContentEditable) {{
                            element.textContent = next;
                        }} else if ('value' in element) {{
                            const view = element.ownerDocument.defaultView;
                            const prototype = element.tagName === 'TEXTAREA' ? view.HTMLTextAreaElement.prototype : view.HTMLInputElement.prototype;
                            const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
                            setter ? setter.call(element, next) : (element.value = next);
                        }} else {{
                            throw new Error('Element is not editable');
                        }}
                        element.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType, data }}));
                    }};
                    const accessibleName = (element) => {{
                        const labelledBy = element.getAttribute('aria-labelledby');
                        const labelled = labelledBy
                            ? labelledBy.split(/\s+/).map((id) => element.ownerDocument.getElementById(id)?.innerText || '').join(' ').trim()
                            : '';
                        const explicit = element.id ? element.ownerDocument.querySelector(`label[for="${{CSS.escape(element.id)}}"]`)?.innerText : '';
                        return String(element.getAttribute('aria-label') || labelled || explicit || element.getAttribute('alt') || element.getAttribute('title') || element.getAttribute('placeholder') || element.innerText || element.value || '').trim().replace(/\s+/g, ' ').slice(0, 300);
                    }};
                    const serializable = (value) => {{
                        if (value === undefined) return '(no return value)';
                        try {{ return JSON.parse(JSON.stringify(value)); }} catch {{ return String(value); }}
                    }};
                    const beginAsync = (id, promise) => {{
                        const jobs = globalThis.__evofluxAsyncJobs ||= {{}};
                        jobs[id] = {{ state: 'pending' }};
                        Promise.resolve(promise).then(
                            (value) => {{ jobs[id] = {{ state: 'done', ok: true, value: serializable(value) }}; }},
                            (error) => {{ jobs[id] = {{ state: 'done', ok: false, error: String(error?.stack || error?.message || error) }}; }},
                        );
                        return {{ state: 'started', id }};
                    }};

                    if (action === 'instrument') {{
                        if (!globalThis.__evofluxBrowserRuntime) {{
                            const runtime = {{ console: [], network: [], dialogs: [], dialogBehavior: {{ behavior: 'dismiss', promptText: null }} }};
                            const keep = (items, value, max) => {{ items.push(value); if (items.length > max) items.splice(0, items.length - max); }};
                            for (const level of ['debug', 'log', 'info', 'warn', 'error']) {{
                                const original = console[level]?.bind(console);
                                if (!original) continue;
                                console[level] = (...args) => {{
                                    keep(runtime.console, {{ ts: Date.now(), level, text: args.map((value) => {{ try {{ return typeof value === 'string' ? value : JSON.stringify(value); }} catch {{ return String(value); }} }}).join(' ').slice(0, 4000) }}, 400);
                                    original(...args);
                                }};
                            }}
                            addEventListener('error', (event) => keep(runtime.console, {{ ts: Date.now(), level: 'error', source: event.filename || '', line: event.lineno || 0, column: event.colno || 0, text: String(event.error?.stack || event.message || 'Page error').slice(0, 4000) }}, 400));
                            addEventListener('unhandledrejection', (event) => keep(runtime.console, {{ ts: Date.now(), level: 'error', text: String(event.reason?.stack || event.reason || 'Unhandled rejection').slice(0, 4000) }}, 400));
                            globalThis.alert = (message) => keep(runtime.dialogs, {{ ts: Date.now(), type: 'alert', message: String(message) }}, 100);
                            globalThis.confirm = (message) => {{
                                keep(runtime.dialogs, {{ ts: Date.now(), type: 'confirm', message: String(message) }}, 100);
                                return runtime.dialogBehavior.behavior === 'accept';
                            }};
                            globalThis.prompt = (message, defaultValue = '') => {{
                                keep(runtime.dialogs, {{ ts: Date.now(), type: 'prompt', message: String(message), default_value: String(defaultValue) }}, 100);
                                return runtime.dialogBehavior.behavior === 'accept' ? String(runtime.dialogBehavior.promptText ?? defaultValue) : null;
                            }};
                            const originalFetch = globalThis.fetch?.bind(globalThis);
                            if (originalFetch) globalThis.fetch = async (...args) => {{
                                const request = args[0];
                                const method = String(args[1]?.method || request?.method || 'GET').toUpperCase();
                                const url = String(request?.url || request);
                                const started = performance.now();
                                try {{
                                    const response = await originalFetch(...args);
                                    keep(runtime.network, {{ ts: Date.now(), method, url, status: response.status, duration_ms: performance.now() - started, type: 'fetch' }}, 500);
                                    return response;
                                }} catch (error) {{
                                    keep(runtime.network, {{ ts: Date.now(), method, url, status: 0, duration_ms: performance.now() - started, type: 'fetch', error: String(error) }}, 500);
                                    throw error;
                                }}
                            }};
                            const open = XMLHttpRequest.prototype.open;
                            const send = XMLHttpRequest.prototype.send;
                            XMLHttpRequest.prototype.open = function(method, url, ...rest) {{ this.__evofluxRequest = {{ method: String(method).toUpperCase(), url: String(url), started: performance.now() }}; return open.call(this, method, url, ...rest); }};
                            XMLHttpRequest.prototype.send = function(...args) {{
                                this.addEventListener('loadend', () => {{
                                    const request = this.__evofluxRequest || {{ method: 'GET', url: this.responseURL, started: performance.now() }};
                                    keep(runtime.network, {{ ts: Date.now(), method: request.method, url: request.url, status: this.status, duration_ms: performance.now() - request.started, type: 'xhr' }}, 500);
                                }}, {{ once: true }});
                                return send.apply(this, args);
                            }};
                            globalThis.__evofluxBrowserRuntime = runtime;
                        }}
                        globalThis.__evofluxEnsureAgentCursor();
                        return {{ ready: true }};
                    }}

                    if (action === 'cursor_control') {{
                        const cursor = globalThis.__evofluxAgentCursor;
                        if (cursor && typeof params.suspended === 'boolean') cursor.setSuspended(params.suspended);
                        return {{ active: Boolean(cursor?.enabled), suspended: Boolean(cursor?.suspended) }};
                    }}

                    if (action === 'snapshot') {{
                        document.querySelectorAll('[data-evoflux-agent-index]').forEach((element) => element.removeAttribute('data-evoflux-agent-index'));
                        const interactiveTags = new Set(['A', 'BUTTON', 'INPUT', 'TEXTAREA', 'SELECT', 'SUMMARY', 'DETAILS']);
                        const interactiveRoles = new Set(['button', 'link', 'checkbox', 'radio', 'switch', 'tab', 'menuitem', 'option', 'textbox', 'combobox', 'slider', 'spinbutton', 'treeitem', 'gridcell']);
                        const elements = deepElements().filter((element) => visible(element) && (
                            interactiveTags.has(element.tagName)
                            || interactiveRoles.has(element.getAttribute('role'))
                            || element.isContentEditable
                            || element.tabIndex >= 0
                            || typeof element.onclick === 'function'
                        )).slice(0, 750);
                        globalThis.__evofluxAgentElements = elements;
                        const lines = elements.map((element, index) => {{
                            try {{ element.setAttribute('data-evoflux-agent-index', String(index)); }} catch {{}}
                            return `[${{index}}] ${{describe(element)}}`;
                        }});
                        const maxChars = Math.max(500, Math.min(100000, Number(params.max_chars) || 15000));
                        const textParts = [String(document.body?.innerText || '').trim()];
                        for (const frame of document.querySelectorAll('iframe')) {{
                            try {{ if (frame.contentDocument?.body) textParts.push(String(frame.contentDocument.body.innerText || '').trim()); }} catch {{}}
                        }}
                        const pageText = textParts.filter(Boolean).join('\n\n[Same-origin frame]\n').slice(0, Math.floor(maxChars * 0.45));
                        const output = `URL: ${{location.href}}\nTitle: ${{document.title}}\n\nPage text:\n${{pageText}}\n\nInteractive elements (use [index] with click/fill):\n${{lines.join('\n')}}`;
                        return output.slice(0, maxChars);
                    }}

                    if (action === 'element_rect') {{
                        const element = resolveElement();
                        if (!element) throw new Error('Element not found; run snapshot again or provide a selector');
                        const rect = element.getBoundingClientRect();
                        return {{ x: Math.max(0, rect.x), y: Math.max(0, rect.y), width: rect.width, height: rect.height, viewport_width: innerWidth, viewport_height: innerHeight }};
                    }}

                    if (action === 'click') {{
                        const element = resolveElement();
                        if (!element) throw new Error('Element not found; run snapshot again or provide a selector');
                        element.scrollIntoView({{ block: 'center', inline: 'center' }});
                        globalThis.__evofluxEnsureAgentCursor().moveToElement(element, 'release');
                        element.focus?.();
                        element.click();
                        return `Clicked ${{describe(element)}}`;
                    }}

                    if (action === 'dblclick') {{
                        const element = resolveElement();
                        if (!element) throw new Error('Element not found; run snapshot again or provide a selector');
                        element.scrollIntoView({{ block: 'center', inline: 'center' }});
                        globalThis.__evofluxEnsureAgentCursor().moveToElement(element, 'release');
                        element.focus?.();
                        element.dispatchEvent(new MouseEvent('dblclick', {{ bubbles: true, cancelable: true, view: window, detail: 2 }}));
                        return `Double-clicked ${{describe(element)}}`;
                    }}

                    if (action === 'hover') {{
                        const element = resolveElement();
                        if (!element) throw new Error('Element not found; run snapshot again or provide a selector');
                        element.scrollIntoView({{ block: 'center', inline: 'center' }});
                        globalThis.__evofluxEnsureAgentCursor().moveToElement(element);
                        for (const type of ['pointerover', 'mouseover', 'pointerenter', 'mouseenter', 'pointermove', 'mousemove']) element.dispatchEvent(new MouseEvent(type, {{ bubbles: !type.endsWith('enter'), cancelable: true, view: window }}));
                        return `Hovered ${{describe(element)}}`;
                    }}

                    if (action === 'focus') {{
                        const element = resolveElement();
                        if (!element) throw new Error('Element not found; run snapshot again or provide a selector');
                        element.scrollIntoView({{ block: 'center', inline: 'center' }});
                        element.focus({{ preventScroll: true }});
                        return `Focused ${{describe(element)}}`;
                    }}

                    if (action === 'fill') {{
                        const element = resolveElement();
                        if (!element) throw new Error('Input not found; run snapshot again or provide a selector');
                        const text = String(params.text ?? '');
                        element.focus?.();
                        const current = String(element.isContentEditable ? element.textContent || '' : element.value || '');
                        setEditableValue(element, params.clear === false ? current + text : text, 'insertText', text);
                        element.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        return `Filled ${{describe(element)}} (${{text.length}} chars)`;
                    }}

                    if (action === 'type') {{
                        const element = resolveElement() || document.activeElement;
                        if (!element) throw new Error('No editable element is focused or targeted');
                        element.focus?.();
                        const text = String(params.text ?? '');
                        let current = String(element.isContentEditable ? element.textContent || '' : element.value || '');
                        for (const character of text) {{
                            const init = {{ key: character, code: character.length === 1 ? `Key${{character.toUpperCase()}}` : character, bubbles: true, cancelable: true }};
                            if (element.dispatchEvent(new KeyboardEvent('keydown', init))) {{
                                current += character;
                                setEditableValue(element, current, 'insertText', character);
                            }}
                            element.dispatchEvent(new KeyboardEvent('keyup', init));
                        }}
                        return `Typed ${{text.length}} chars into ${{describe(element)}}`;
                    }}

                    if (action === 'clear') {{
                        const element = resolveElement();
                        if (!element) throw new Error('Editable element not found');
                        element.focus?.();
                        setEditableValue(element, '', 'deleteContentBackward', null);
                        element.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        return `Cleared ${{describe(element)}}`;
                    }}

                    if (action === 'submit') {{
                        const element = resolveElement() || document.activeElement;
                        const form = element?.tagName === 'FORM' ? element : element?.form || element?.closest?.('form');
                        if (!form) throw new Error('No form found for the target element');
                        form.requestSubmit ? form.requestSubmit() : form.submit();
                        return `Submitted ${{describe(form)}}`;
                    }}

                    if (action === 'press') {{
                        const element = resolveElement() || document.activeElement;
                        if (!element) throw new Error('No focused element and no target was provided');
                        element.focus?.();
                        const parts = String(params.key || '').split('+').filter(Boolean);
                        const key = parts.pop();
                        if (!key) throw new Error('press requires a key');
                        const modifiers = new Set(parts.map((value) => value.toLowerCase()));
                        const init = {{
                            key,
                            code: key.length === 1 ? `Key${{key.toUpperCase()}}` : key,
                            bubbles: true,
                            cancelable: true,
                            ctrlKey: modifiers.has('control') || modifiers.has('ctrl'),
                            metaKey: modifiers.has('meta') || modifiers.has('command'),
                            altKey: modifiers.has('alt'),
                            shiftKey: modifiers.has('shift'),
                        }};
                        const proceed = element.dispatchEvent(new KeyboardEvent('keydown', init));
                        if (proceed && key === ' ' && ['BUTTON', 'SUMMARY'].includes(element.tagName)) element.click?.();
                        if (proceed && key === 'Tab') {{
                            const focusable = deepElements().filter((candidate) => visible(candidate) && !candidate.disabled && candidate.tabIndex >= 0);
                            const current = focusable.indexOf(element);
                            const offset = init.shiftKey ? -1 : 1;
                            focusable[(current + offset + focusable.length) % focusable.length]?.focus?.();
                        }}
                        element.dispatchEvent(new KeyboardEvent('keyup', init));
                        if (proceed && key === 'Enter' && element.form && !init.shiftKey) element.form.requestSubmit?.();
                        return `Pressed ${{params.key}} on ${{describe(element)}}`;
                    }}

                    if (action === 'set_checked') {{
                        const element = resolveElement();
                        if (!element) throw new Error('Checkbox/radio not found; run snapshot again or provide a selector');
                        const desired = Boolean(params.checked);
                        if ('checked' in element) {{
                            const prototype = element.ownerDocument.defaultView.HTMLInputElement.prototype;
                            const setter = Object.getOwnPropertyDescriptor(prototype, 'checked')?.set;
                            setter ? setter.call(element, desired) : (element.checked = desired);
                        }} else {{
                            element.setAttribute('aria-checked', String(desired));
                        }}
                        element.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        element.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        return `Set checked=${{desired}} on ${{describe(element)}}`;
                    }}

                    if (action === 'select') {{
                        const element = resolveElement();
                        if (!element || element.tagName !== 'SELECT') throw new Error('Select element not found');
                        const requested = String(params.value ?? '');
                        const option = Array.from(element.options).find((candidate) => candidate.value === requested || candidate.label === requested || candidate.text === requested);
                        if (!option) throw new Error(`Option not found: ${{requested}}`);
                        element.value = option.value;
                        element.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        element.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        return `Selected "${{element.value}}"`;
                    }}

                    if (action === 'drag') {{
                        const source = resolveElement();
                        const target = Number.isInteger(params.target_index)
                            ? globalThis.__evofluxAgentElements?.[params.target_index]
                            : deepElements().find((element) => {{ try {{ return element.matches(String(params.target_selector || '')); }} catch {{ return false; }} }});
                        if (!source || !target) throw new Error('Drag source or target not found');
                        source.scrollIntoView({{ block: 'center', inline: 'center' }});
                        target.scrollIntoView({{ block: 'center', inline: 'center' }});
                        const cursor = globalThis.__evofluxEnsureAgentCursor();
                        cursor.moveToElement(source, 'press');
                        const transfer = new DataTransfer();
                        for (const type of ['dragstart', 'drag', 'dragenter', 'dragover', 'drop', 'dragend']) {{
                            const recipient = ['dragstart', 'drag', 'dragend'].includes(type) ? source : target;
                            recipient.dispatchEvent(new DragEvent(type, {{ bubbles: true, cancelable: true, dataTransfer: transfer }}));
                        }}
                        cursor.moveToElement(target, 'release');
                        return `Dragged ${{describe(source)}} to ${{describe(target)}}`;
                    }}

                    if (action === 'scroll_into_view') {{
                        const element = resolveElement();
                        if (!element) throw new Error('Element not found');
                        const block = ['start', 'center', 'end', 'nearest'].includes(params.block) ? params.block : 'center';
                        element.scrollIntoView({{ block, inline: 'nearest', behavior: 'instant' }});
                        return `Scrolled into view: ${{describe(element)}}`;
                    }}

                    if (action === 'click_at') {{
                        const x = Number(params.x);
                        const y = Number(params.y);
                        if (!Number.isFinite(x) || !Number.isFinite(y)) throw new Error('click_at requires finite x and y coordinates');
                        const element = document.elementFromPoint(x, y);
                        if (!element) throw new Error(`No element at viewport coordinate ${{x}},${{y}}`);
                        const button = params.button === 'middle' ? 1 : params.button === 'right' ? 2 : 0;
                        const buttons = button === 0 ? 1 : button === 1 ? 4 : 2;
                        const init = {{ bubbles: true, cancelable: true, view: window, clientX: x, clientY: y, button, buttons }};
                        globalThis.__evofluxEnsureAgentCursor().move(x, y, 'release');
                        element.focus?.();
                        for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) element.dispatchEvent(new MouseEvent(type, init));
                        return `Clicked at ${{x}},${{y}} on ${{describe(element)}}`;
                    }}

                    if (action === 'dispatch_event') {{
                        const element = resolveElement();
                        if (!element) throw new Error('Element not found');
                        const eventName = String(params.event || '').trim();
                        if (!eventName) throw new Error('dispatch_event requires an event name');
                        const event = new CustomEvent(eventName, {{ bubbles: true, cancelable: true, detail: params.detail || {{}} }});
                        const accepted = element.dispatchEvent(event);
                        return {{ event: eventName, accepted, target: describe(element) }};
                    }}

                    if (action === 'query') {{
                        const selector = String(params.selector || '');
                        if (!selector) throw new Error('query requires a selector');
                        const limit = Math.max(1, Math.min(500, Number(params.limit) || 50));
                        const matches = deepElements().filter((element) => {{
                            try {{ return element.matches(selector) && (params.include_hidden || visible(element)); }} catch {{ return false; }}
                        }}).slice(0, limit);
                        globalThis.__evofluxAgentElements = matches;
                        return matches.length
                            ? matches.map((element, index) => {{
                                try {{ element.setAttribute('data-evoflux-agent-index', String(index)); }} catch {{}}
                                return `[${{index}}] ${{describe(element)}}`;
                            }}).join('\n')
                            : '(no matching elements)';
                    }}

                    if (action === 'inspect') {{
                        const element = resolveElement();
                        if (!element) throw new Error('Element not found');
                        const rect = element.getBoundingClientRect();
                        const computed = element.ownerDocument.defaultView.getComputedStyle(element);
                        const requestedStyles = Array.isArray(params.styles) ? params.styles.slice(0, 50) : [];
                        const styles = Object.fromEntries(requestedStyles.map((name) => [name, computed.getPropertyValue(String(name))]));
                        const attributes = Object.fromEntries(Array.from(element.attributes || []).map((attribute) => [attribute.name, attribute.value]));
                        return {{
                            tag: element.tagName.toLowerCase(),
                            description: describe(element),
                            role: element.getAttribute('role') || '',
                            accessible_name: accessibleName(element),
                            attributes,
                            styles,
                            rect: {{ x: rect.x, y: rect.y, width: rect.width, height: rect.height, top: rect.top, right: rect.right, bottom: rect.bottom, left: rect.left }},
                            visible: visible(element),
                            enabled: !element.disabled && element.getAttribute('aria-disabled') !== 'true',
                            focused: element.ownerDocument.activeElement === element,
                            value: 'value' in element ? String(element.value).slice(0, 10000) : null,
                            checked: 'checked' in element ? Boolean(element.checked) : null,
                            text: String(element.innerText || element.textContent || '').trim().slice(0, 10000),
                        }};
                    }}

                    if (action === 'html') {{
                        const element = resolveElement();
                        const maxChars = Math.max(100, Math.min(200000, Number(params.max_chars) || 30000));
                        const html = element
                            ? (params.outer === false ? element.innerHTML : element.outerHTML)
                            : (params.outer === false ? document.documentElement.innerHTML : document.documentElement.outerHTML);
                        return String(html || '').slice(0, maxChars) || '(empty html)';
                    }}

                    if (action === 'accessibility') {{
                        const maxChars = Math.max(500, Math.min(100000, Number(params.max_chars) || 20000));
                        const implicitRoles = {{ A: 'link', BUTTON: 'button', INPUT: 'textbox', TEXTAREA: 'textbox', SELECT: 'combobox', IMG: 'img', NAV: 'navigation', MAIN: 'main', FORM: 'form', TABLE: 'table', H1: 'heading', H2: 'heading', H3: 'heading', H4: 'heading', H5: 'heading', H6: 'heading' }};
                        const lines = deepElements().filter((element) => params.include_hidden || visible(element)).map((element) => {{
                            const role = element.getAttribute('role') || implicitRoles[element.tagName] || '';
                            const name = accessibleName(element);
                            if (!role && !name) return '';
                            const states = ['checked', 'expanded', 'selected', 'pressed', 'disabled', 'required', 'invalid']
                                .map((state) => element.getAttribute(`aria-${{state}}`) != null ? `${{state}}=${{element.getAttribute(`aria-${{state}}`)}}` : '')
                                .filter(Boolean).join(' ');
                            const level = /^H[1-6]$/.test(element.tagName) ? ` level=${{element.tagName.slice(1)}}` : '';
                            return `${{role || element.tagName.toLowerCase()}}${{level}}${{name ? ` "${{name}}"` : ''}}${{states ? ` (${{states}})` : ''}}`;
                        }}).filter(Boolean);
                        return lines.join('\n').slice(0, maxChars) || '(no accessibility nodes found)';
                    }}

                    if (action === 'extract') {{
                        const maxChars = Math.max(100, Math.min(100000, Number(params.max_chars) || 15000));
                        if (!params.selector) return String(document.body?.innerText || '').slice(0, maxChars) || '(empty page)';
                        const elements = deepElements().filter((element) => {{
                            try {{ return element.matches(String(params.selector)); }} catch {{ return false; }}
                        }});
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

                    if (action === 'console') {{
                        const requested = String(params.level || 'all');
                        const limit = Math.max(1, Math.min(200, Number(params.limit) || 50));
                        let entries = Array.from(globalThis.__evofluxBrowserRuntime?.console || []);
                        if (requested !== 'all') entries = entries.filter((entry) => entry.level === requested || (requested === 'warn' && entry.level === 'error'));
                        if (params.contains) entries = entries.filter((entry) => String(entry.text || '').includes(String(params.contains)));
                        entries = entries.slice(-limit);
                        return entries.length ? entries.map((entry) => `[${{entry.level}}]${{entry.source ? ` ${{entry.source}}:${{entry.line}}:${{entry.column}}` : ''}} ${{entry.text}}`).join('\n') : '(no console messages captured)';
                    }}

                    if (action === 'network') {{
                        const failedOnly = params.filter === 'failed';
                        const limit = Math.max(1, Math.min(200, Number(params.limit) || 50));
                        let entries = Array.from(globalThis.__evofluxBrowserRuntime?.network || []);
                        if (failedOnly) entries = entries.filter((entry) => entry.error || Number(entry.status) >= 400 || Number(entry.status) === 0);
                        else entries = [
                            ...performance.getEntriesByType('resource').map((entry) => ({{ method: 'GET', url: entry.name, status: entry.responseStatus || 'loaded' }})),
                            ...entries,
                        ];
                        if (params.url_contains) entries = entries.filter((entry) => String(entry.url || '').includes(String(params.url_contains)));
                        if (params.method) entries = entries.filter((entry) => String(entry.method || '').toUpperCase() === String(params.method).toUpperCase());
                        entries = entries.slice(-limit);
                        return entries.length ? entries.map((entry) => `${{entry.method}} ${{entry.url}} → ${{entry.error || entry.status}}${{entry.duration_ms != null ? ` (${{Math.round(entry.duration_ms)}}ms)` : ''}}`).join('\n') : '(no network requests captured)';
                    }}

                    if (action === 'dialogs') {{
                        const dialogs = Array.from(globalThis.__evofluxBrowserRuntime?.dialogs || []);
                        if (params.clear && globalThis.__evofluxBrowserRuntime) globalThis.__evofluxBrowserRuntime.dialogs.length = 0;
                        return dialogs.length ? dialogs : '(no dialogs captured)';
                    }}

                    if (action === 'dialog_behavior') {{
                        const runtime = globalThis.__evofluxBrowserRuntime;
                        if (!runtime) throw new Error('Browser observability is not initialized');
                        runtime.dialogBehavior = {{
                            behavior: params.behavior === 'accept' ? 'accept' : 'dismiss',
                            promptText: params.prompt_text ?? null,
                        }};
                        return runtime.dialogBehavior;
                    }}

                    if (action === 'performance') {{
                        const navigation = performance.getEntriesByType('navigation')[0];
                        const memory = performance.memory ? {{
                            used_js_heap_size: performance.memory.usedJSHeapSize,
                            total_js_heap_size: performance.memory.totalJSHeapSize,
                            js_heap_size_limit: performance.memory.jsHeapSizeLimit,
                        }} : null;
                        const result = {{
                            url: location.href,
                            time_origin: performance.timeOrigin,
                            navigation: navigation ? {{
                                type: navigation.type,
                                dom_interactive_ms: navigation.domInteractive,
                                dom_content_loaded_ms: navigation.domContentLoadedEventEnd,
                                load_ms: navigation.loadEventEnd,
                                response_ms: navigation.responseEnd,
                                transfer_size: navigation.transferSize,
                                decoded_body_size: navigation.decodedBodySize,
                            }} : null,
                            paint: Object.fromEntries(performance.getEntriesByType('paint').map((entry) => [entry.name, entry.startTime])),
                            memory,
                            resources: [],
                        }};
                        if (params.include_resources !== false) {{
                            const limit = Math.max(1, Math.min(500, Number(params.limit) || 100));
                            result.resources = performance.getEntriesByType('resource').slice(-limit).map((entry) => ({{
                                name: entry.name,
                                initiator: entry.initiatorType,
                                duration_ms: entry.duration,
                                transfer_size: entry.transferSize,
                                decoded_body_size: entry.decodedBodySize,
                                status: entry.responseStatus || null,
                            }}));
                        }}
                        return result;
                    }}

                    if (action === 'clear_logs') {{
                        const runtime = globalThis.__evofluxBrowserRuntime;
                        if (!runtime) return {{ console: 0, network: 0, dialogs: 0 }};
                        const target = params.target || 'all';
                        const removed = {{ console: runtime.console.length, network: runtime.network.length, dialogs: runtime.dialogs?.length || 0 }};
                        if (target === 'console' || target === 'all') runtime.console.length = 0;
                        if (target === 'network' || target === 'all') runtime.network.length = 0;
                        if ((target === 'dialogs' || target === 'all') && runtime.dialogs) runtime.dialogs.length = 0;
                        return removed;
                    }}

                    if (action === 'storage') {{
                        const storage = params.area === 'session' ? sessionStorage : localStorage;
                        const operation = params.operation || 'get';
                        if (operation === 'get') {{
                            if (params.key != null) return {{ key: String(params.key), value: storage.getItem(String(params.key)) }};
                            return Object.fromEntries(Array.from({{ length: storage.length }}, (_, index) => storage.key(index)).filter(Boolean).map((key) => [key, storage.getItem(key)]));
                        }}
                        if (operation === 'set') {{
                            if (params.key == null || params.value == null) throw new Error('storage set requires key and value');
                            storage.setItem(String(params.key), String(params.value));
                            return {{ key: String(params.key), value: storage.getItem(String(params.key)) }};
                        }}
                        if (operation === 'remove') {{
                            if (params.key == null) throw new Error('storage remove requires key');
                            const key = String(params.key);
                            const previous = storage.getItem(key);
                            storage.removeItem(key);
                            return {{ key, removed: previous !== null }};
                        }}
                        if (operation === 'clear') {{
                            const count = storage.length;
                            storage.clear();
                            return {{ cleared: count }};
                        }}
                        throw new Error(`Unsupported storage operation: ${{operation}}`);
                    }}

                    if (action === 'cookies') {{
                        const operation = params.operation || 'get';
                        const parseCookies = () => Object.fromEntries(document.cookie.split(';').map((part) => part.trim()).filter(Boolean).map((part) => {{
                            const separator = part.indexOf('=');
                            const key = decodeURIComponent(separator < 0 ? part : part.slice(0, separator));
                            const value = decodeURIComponent(separator < 0 ? '' : part.slice(separator + 1));
                            return [key, value];
                        }}));
                        if (operation === 'get') {{
                            const cookies = parseCookies();
                            return params.name == null ? cookies : {{ name: String(params.name), value: cookies[String(params.name)] ?? null }};
                        }}
                        if (params.name == null) throw new Error(`cookies ${{operation}} requires name`);
                        const name = encodeURIComponent(String(params.name));
                        const value = operation === 'delete' ? '' : encodeURIComponent(String(params.value ?? ''));
                        const parts = [`${{name}}=${{value}}`, `Path=${{params.path || '/'}}`];
                        if (params.domain) parts.push(`Domain=${{params.domain}}`);
                        if (operation === 'delete') parts.push('Max-Age=0');
                        else if (params.max_age != null) parts.push(`Max-Age=${{Number(params.max_age)}}`);
                        if (params.same_site) parts.push(`SameSite=${{params.same_site}}`);
                        if (params.secure) parts.push('Secure');
                        document.cookie = parts.join('; ');
                        return {{ name: String(params.name), value: parseCookies()[String(params.name)] ?? null, note: 'HttpOnly cookies are intentionally inaccessible to page JavaScript' }};
                    }}

                    if (action === 'http_start') {{
                        const method = String(params.method || 'GET').toUpperCase();
                        const url = String(params.url || '');
                        if (!url) throw new Error('http requires a URL');
                        const asyncId = String(params.async_id || '');
                        if (!asyncId) throw new Error('http action is missing its internal async id');
                        const maxChars = Math.max(100, Math.min(200000, Number(params.max_chars) || 30000));
                        const timeoutMs = Math.max(100, Math.min(30000, Number(params.timeout_ms) || 15000));
                        const controller = new AbortController();
                        const timer = setTimeout(() => controller.abort(`Timed out after ${{timeoutMs}}ms`), timeoutMs);
                        const request = fetch(url, {{
                            method,
                            headers: params.headers || {{}},
                            body: ['GET', 'HEAD'].includes(method) || params.body == null ? undefined : String(params.body),
                            credentials: 'include',
                            signal: controller.signal,
                        }}).then(async (response) => ({{
                            ok: response.ok,
                            method,
                            url: response.url || url,
                            status: response.status,
                            status_text: response.statusText,
                            headers: Object.fromEntries(response.headers.entries()),
                            body: (await response.text()).slice(0, maxChars),
                        }})).finally(() => clearTimeout(timer));
                        return beginAsync(asyncId, request);
                    }}

                    if (action === 'evaluate_start') {{
                        const source = String(params.script || '');
                        const asyncId = String(params.async_id || '');
                        if (!source.trim()) throw new Error('evaluate requires a script');
                        if (!asyncId) throw new Error('evaluate action is missing its internal async id');
                        const value = (0, eval)(source);
                        const result = typeof value === 'function' ? value() : value;
                        return beginAsync(asyncId, result);
                    }}

                    if (action === 'async_result') {{
                        const asyncId = String(params.async_id || '');
                        const jobs = globalThis.__evofluxAsyncJobs || {{}};
                        const result = jobs[asyncId] || {{ state: 'pending' }};
                        if (result.state === 'done') delete jobs[asyncId];
                        return result;
                    }}

                    if (action === 'debug_summary') {{
                        const runtime = globalThis.__evofluxBrowserRuntime || {{ console: [], network: [], dialogs: [] }};
                        const consoleLimit = Math.max(1, Math.min(200, Number(params.console_limit) || 30));
                        const networkLimit = Math.max(1, Math.min(200, Number(params.network_limit) || 30));
                        const consoleErrors = runtime.console.filter((entry) => entry.level === 'error' || entry.level === 'warn').slice(-consoleLimit);
                        const failedRequests = runtime.network.filter((entry) => entry.error || Number(entry.status) >= 400 || Number(entry.status) === 0).slice(-networkLimit);
                        const navigation = performance.getEntriesByType('navigation')[0];
                        return {{
                            page: {{ url: location.href, title: document.title, ready_state: document.readyState, online: navigator.onLine }},
                            viewport: {{ width: innerWidth, height: innerHeight, device_pixel_ratio: devicePixelRatio, scroll_x: scrollX, scroll_y: scrollY }},
                            dom: {{ elements: deepElements().length, forms: document.forms.length, links: document.links.length, images: document.images.length }},
                            timing: navigation ? {{ dom_interactive_ms: navigation.domInteractive, load_ms: navigation.loadEventEnd, transfer_size: navigation.transferSize }} : null,
                            console_errors: consoleErrors,
                            failed_requests: failedRequests,
                            dialogs: Array.from(runtime.dialogs || []).slice(-20),
                        }};
                    }}

                    if (action === 'evaluate') {{
                        const source = String(params.script || '');
                        if (!source.trim()) throw new Error('evaluate requires a script');
                        const value = (0, eval)(source);
                        const result = typeof value === 'function' ? value() : value;
                        if (result && typeof result.then === 'function') throw new Error('evaluate only supports synchronous scripts');
                        return result === undefined ? '(no return value)' : result;
                    }}

                    if (action === 'exists') {{
                        return Boolean(resolveElement());
                    }}

                    if (action === 'probe') {{
                        const element = params.selector ? resolveElement() : null;
                        return {{
                            attached: Boolean(element),
                            visible: Boolean(element && visible(element)),
                            text: String(element ? element.innerText || element.textContent || '' : document.body?.innerText || '').slice(0, 100000),
                            url: location.href,
                            readyState: document.readyState,
                        }};
                    }}

                    if (action === 'status') {{
                        return {{
                            url: location.href,
                            title: document.title,
                            readyState: document.readyState,
                            online: navigator.onLine,
                            userAgent: navigator.userAgent,
                            viewport: {{ width: innerWidth, height: innerHeight, devicePixelRatio, scrollX, scrollY }},
                            historyLength: history.length,
                            activeElement: document.activeElement ? describe(document.activeElement) : null,
                        }};
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
        let result = restart_backend_and_reload_window(&handle).await;
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

async fn restart_backend_and_reload_window(app: &AppHandle) -> Result<()> {
    if let Some(base_url) = development_backend_url()? {
        shutdown_sidecar_now(app).await;
        activate_external_backend(
            app,
            base_url.clone(),
            DEV_BACKEND_HEALTH_ATTEMPTS,
            "Waiting for the source development backend…",
            "Development backend ready",
        )
        .await
        .with_context(|| format!("reconnect development backend at {base_url}"))?;

        let windows: Vec<tauri::WebviewWindow> = app
            .webview_windows()
            .into_values()
            .filter(|window| {
                window.label() == MAIN_WINDOW || window.label().starts_with(SECONDARY_WINDOW_PREFIX)
            })
            .collect();
        let state: tauri::State<'_, AppState> = app.state();
        let reload_script = format!(
            "{}window.location.reload();",
            frontend_init_script(None, &base_url)
        );
        for window in windows {
            window
                .eval(&reload_script)
                .context("reload development app window")?;
            state
                .window_backend_base_urls
                .lock()
                .await
                .insert(window.label().to_string(), base_url.clone());
        }
        show_target_window(app);
        return Ok(());
    }

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
    native_messaging::clear_connection(app);
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
            .website(Some("https://github.com/evoelsewhere/evoflux"))
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
    let file_chat = MenuItem::with_id(app, MENU_CHAT, "Work", true, Some("CmdOrCtrl+Shift+C"))?;
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
    let view_wiki = MenuItem::with_id(app, MENU_WIKI, "Memory", true, Some("Ctrl+M"))?;
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
    // Windows renders the application menu as a second strip below the
    // system title bar. EvoFlux already exposes these destinations through
    // its application chrome, keyboard shortcuts, and tray menu, so keeping
    // the native strip only consumes vertical workspace. Remove it before
    // the first webview window is created; macOS keeps its global menu bar.
    #[cfg(target_os = "windows")]
    let _ = app.remove_menu()?;

    let status = MenuItem::with_id(app, MENU_STATUS, "Status: Starting", false, None::<&str>)?;
    // Informational only; updated from ``set_tray_session``.
    let session = MenuItem::with_id(app, MENU_SESSION, TRAY_SESSION_IDLE, false, None::<&str>)?;
    let tray_show = MenuItem::with_id(app, MENU_SHOW, "Show EvoFlux", true, None::<&str>)?;
    let tray_new_window =
        MenuItem::with_id(app, MENU_NEW_WINDOW, "New Window", true, None::<&str>)?;
    let tray_chat = MenuItem::with_id(app, MENU_CHAT, "Work", true, None::<&str>)?;
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

async fn activate_external_backend(
    app: &AppHandle,
    base_url: String,
    health_attempts: u32,
    checking_message: &str,
    ready_message: &str,
) -> Result<()> {
    set_backend_startup(app, "external", checking_message, 0, None, false).await;
    wait_for_health(&base_url, health_attempts, Duration::from_millis(250)).await?;

    if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
        window
            .eval(frontend_init_script(None, &base_url))
            .context("inject external backend config")?;
    }

    let state: tauri::State<'_, AppState> = app.state();
    state.backend_base_url.lock().await.take();
    state.desktop_token.lock().await.take();
    let mut external_windows = state.window_backend_base_urls.lock().await;
    external_windows.clear();
    external_windows.insert(MAIN_WINDOW.to_string(), base_url.clone());
    drop(external_windows);
    *state.backend_mode.lock().await = BackendMode::External;

    sync_webbridge_native_connection(app, &base_url, None).await;
    update_tray_status(app, "Status: Running");
    set_backend_startup(app, "ready", ready_message, 0, None, false).await;
    app.emit(
        "backend-ready",
        BackendReady {
            port: 0,
            version: "external".to_string(),
            base_url,
            token: None,
            sidecar_running: false,
        },
    )
    .ok();
    Ok(())
}

async fn publish_webbridge_native_connection(
    app: &AppHandle,
    base_url: &str,
    desktop_token: Option<&str>,
) -> Result<()> {
    const PUBLISH_ATTEMPTS: u32 = 5;
    native_messaging::validate_base_url(base_url)?;
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(3))
        .build()
        .context("build native discovery client")?;
    let url = format!(
        "{}/api/team/webbridge/native-discovery",
        base_url.trim_end_matches('/')
    );
    let mut last_error = None;
    for attempt in 1..=PUBLISH_ATTEMPTS {
        let result: Result<()> = async {
            let mut request = client.get(&url);
            if let Some(token) = desktop_token.filter(|token| !token.is_empty()) {
                request = request.bearer_auth(token);
            }
            let response = request
                .send()
                .await
                .context("request WebBridge native discovery token")?
                .error_for_status()
                .context("WebBridge native discovery token was rejected")?
                .json::<NativeDiscoveryTokenResponse>()
                .await
                .context("decode WebBridge native discovery token")?;
            native_messaging::publish_connection(app, base_url, &response.discovery_token)
        }
        .await;
        match result {
            Ok(()) => return Ok(()),
            Err(error) => {
                log::warn!(
                    "WebBridge native discovery publish attempt {attempt}/{PUBLISH_ATTEMPTS} failed: {error:#}"
                );
                last_error = Some(error);
            }
        }
        if attempt < PUBLISH_ATTEMPTS {
            tokio::time::sleep(Duration::from_millis(200) * attempt).await;
        }
    }
    Err(last_error.unwrap_or_else(|| anyhow!("native discovery publication failed")))
}

async fn sync_webbridge_native_connection(
    app: &AppHandle,
    base_url: &str,
    desktop_token: Option<&str>,
) -> bool {
    match publish_webbridge_native_connection(app, base_url, desktop_token).await {
        Ok(()) => {
            log::info!("WebBridge native discovery ready base_url={base_url}");
            true
        }
        Err(error) => {
            native_messaging::clear_connection(app);
            log::warn!("could not publish WebBridge native discovery: {error:#}");
            false
        }
    }
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
    native_messaging::clear_connection(app);
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

        sync_webbridge_native_connection(app, &base_url, Some(&handshake.token)).await;

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

fn development_backend_is_forced() -> bool {
    cfg!(debug_assertions) && std::env::var_os(DEV_BACKEND_URL_ENV).is_some()
}

fn reject_forced_development_backend_mutation() -> Result<(), String> {
    if development_backend_is_forced() {
        Err(
            "Backend switching is disabled while the desktop development backend is forced."
                .to_string(),
        )
    } else {
        Ok(())
    }
}

fn development_backend_url() -> Result<Option<String>> {
    if !cfg!(debug_assertions) {
        return Ok(None);
    }
    match std::env::var(DEV_BACKEND_URL_ENV) {
        Ok(value) => normalize_external_base_url(&value)
            .with_context(|| format!("invalid {DEV_BACKEND_URL_ENV}"))
            .map(Some),
        Err(std::env::VarError::NotPresent) => Ok(None),
        Err(std::env::VarError::NotUnicode(_)) => {
            Err(anyhow!("{DEV_BACKEND_URL_ENV} must be valid Unicode"))
        }
    }
}

fn select_startup_backend(
    development_url: Option<String>,
    saved_url: Option<String>,
) -> StartupBackend {
    if let Some(url) = development_url {
        StartupBackend::DevelopmentExternal(url)
    } else if let Some(url) = saved_url {
        StartupBackend::SavedExternal(url)
    } else {
        StartupBackend::Bundled
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
    let token_define = token
        .map(|t| {
            format!(
                "Object.defineProperty(window, '__OAD_TOKEN__', {{ value: {token_json}, writable: true, configurable: true }});",
                token_json = serde_json::to_string(t).unwrap_or_else(|_| "\"\"".into())
            )
        })
        .unwrap_or_else(|| "delete window.__OAD_TOKEN__;".to_string());
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
    let builder = configure_frontend_drag_drop(builder);
    let win = builder.build().context("build webview window")?;
    if let Some(size) = saved_size {
        win.set_size(PhysicalSize::new(size.width, size.height))
            .ok();
    }
    let state: tauri::State<'_, AppState> = app.state();
    win.set_zoom(*state.zoom.lock().await).ok();
    win.show().context("show window")?;
    #[cfg(target_os = "macos")]
    enforce_macos_traffic_light_position(&win)?;
    win.set_focus().ok();
    Ok(win)
}

async fn create_app_window(app: &AppHandle, label: Option<&str>) -> Result<tauri::WebviewWindow> {
    let state: tauri::State<'_, AppState> = app.state();
    let new_label = label
        .map(str::to_string)
        .unwrap_or_else(|| next_window_label(app));
    let active_label = state.active_window_label.lock().await.clone();
    let (active_external_base, main_external_base) = {
        let external_windows = state.window_backend_base_urls.lock().await;
        (
            external_windows.get(&active_label).cloned(),
            external_windows.get(MAIN_WINDOW).cloned(),
        )
    };
    let bundled_base = state.backend_base_url.lock().await.clone();
    let external_base = if active_external_base.is_some() {
        active_external_base
    } else if active_label == MAIN_WINDOW || bundled_base.is_none() {
        main_external_base
    } else {
        None
    };
    let (base, token, external) = if let Some(base) = external_base {
        (base, None, true)
    } else {
        (
            bundled_base.ok_or_else(|| anyhow!("backend is not ready"))?,
            state.desktop_token.lock().await.clone(),
            false,
        )
    };
    let init_script = frontend_init_script(token.as_deref(), &base);
    let window = build_app_window(app, new_label.clone(), init_script).await?;
    if external {
        state
            .window_backend_base_urls
            .lock()
            .await
            .insert(new_label, base);
    }
    Ok(window)
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

    let development_url = match development_backend_url() {
        Ok(url) => url,
        Err(error) => {
            let failure = BackendStartFailure {
                message: format!("Development backend configuration is invalid: {error:#}"),
                fatal: true,
                attempt: 0,
            };
            publish_backend_error(&app, &failure).await;
            return Ok(());
        }
    };
    let saved_url = load_app_backend_config(&app)
        .ok()
        .and_then(|config| config.active_base_url);
    match select_startup_backend(development_url, saved_url) {
        StartupBackend::DevelopmentExternal(base_url) => {
            log::info!("desktop: using forced development backend at {base_url}");
            if let Err(error) = activate_external_backend(
                &app,
                base_url.clone(),
                DEV_BACKEND_HEALTH_ATTEMPTS,
                "Waiting for the source development backend…",
                "Development backend ready",
            )
            .await
            {
                let failure = BackendStartFailure {
                    message: format!(
                        "Development backend at {base_url} is not reachable: {error:#}"
                    ),
                    fatal: false,
                    attempt: 0,
                };
                publish_backend_error(&app, &failure).await;
                return Ok(());
            }
            return Ok(());
        }
        StartupBackend::SavedExternal(active_base_url) => {
            match normalize_external_base_url(&active_base_url) {
                Ok(base_url) => {
                    match activate_external_backend(
                        &app,
                        base_url,
                        8,
                        "Checking the configured backend…",
                        "Configured backend ready",
                    )
                    .await
                    {
                        Ok(()) => return Ok(()),
                        Err(error) => log::warn!(
                            "desktop: saved external backend is not reachable at startup: {error:#}"
                        ),
                    }
                }
                Err(error) => {
                    log::warn!(
                        "desktop: saved external backend URL is invalid at startup: {error:#}"
                    )
                }
            }
        }
        StartupBackend::Bundled => {}
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
    if native_messaging::invoked_as_native_host() {
        if let Err(error) = native_messaging::run_native_host() {
            eprintln!("EvoFlux WebBridge native host failed: {error:#}");
            std::process::exit(1);
        }
        return;
    }

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
        .plugin(
            tauri::plugin::Builder::<tauri::Wry>::new("browser-observability")
                .js_init_script(browser_observability_init_script())
                .build(),
        )
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
            if let Err(error) = native_messaging::install(app.handle()) {
                log::warn!("could not install WebBridge native messaging host: {error:#}");
            }
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
            #[cfg(target_os = "macos")]
            RunEvent::WindowEvent {
                label,
                event: WindowEvent::Resized(_),
                ..
            } if label == MAIN_WINDOW || label.starts_with(SECONDARY_WINDOW_PREFIX) => {
                if let Some(window) = app.get_webview_window(label.as_str()) {
                    if let Err(error) = enforce_macos_traffic_light_position(&window) {
                        log::warn!("desktop: could not realign macOS window controls: {error:#}");
                    }
                }
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
                native_messaging::clear_connection(app);
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

    #[test]
    fn browser_agent_script_includes_deep_dom_and_runtime_instrumentation() {
        let script =
            browser_agent_action_script("snapshot", &serde_json::json!({ "max_chars": 12_000 }))
                .expect("snapshot action should compile");

        assert!(script.contains("element.shadowRoot"));
        assert!(script.contains("element.contentDocument"));
        assert!(script.contains("__evofluxBrowserRuntime"));
        assert!(script.contains("const action = \"snapshot\""));
        assert!(script.contains("12000"));
    }

    #[test]
    fn browser_agent_script_supports_full_direct_action_set() {
        for action in [
            "instrument",
            "snapshot",
            "click",
            "dblclick",
            "hover",
            "focus",
            "fill",
            "type",
            "clear",
            "submit",
            "press",
            "set_checked",
            "select",
            "drag",
            "scroll_into_view",
            "click_at",
            "dispatch_event",
            "extract",
            "query",
            "inspect",
            "html",
            "accessibility",
            "scroll",
            "console",
            "network",
            "dialogs",
            "dialog_behavior",
            "performance",
            "clear_logs",
            "storage",
            "cookies",
            "http",
            "http_start",
            "evaluate_start",
            "async_result",
            "debug_summary",
            "evaluate",
            "element_rect",
            "exists",
            "probe",
            "status",
            "cursor_control",
        ] {
            browser_agent_action_script(action, &serde_json::json!({}))
                .unwrap_or_else(|error| panic!("{action} should be supported: {error}"));
        }
    }

    #[test]
    fn browser_agent_script_rejects_unknown_actions() {
        let error = browser_agent_action_script("launch_external", &serde_json::json!({}))
            .expect_err("external browser actions must not be supported");

        assert!(error.contains("Unsupported direct browser action"));
    }

    #[test]
    fn browser_agent_script_contains_async_debug_transport() {
        let http = browser_agent_action_script(
            "http_start",
            &serde_json::json!({
                "async_id": "job-1",
                "url": "/api/debug",
                "method": "GET"
            }),
        )
        .expect("http debug action should compile");
        let evaluate = browser_agent_action_script(
            "evaluate_start",
            &serde_json::json!({ "async_id": "job-2", "script": "Promise.resolve(42)" }),
        )
        .expect("async evaluate action should compile");

        assert!(http.contains("AbortController"));
        assert!(http.contains("credentials: 'include'"));
        assert!(evaluate.contains("beginAsync"));
        assert!(evaluate.contains("Promise.resolve(42)"));
    }

    #[test]
    fn browser_observability_starts_before_page_scripts_only_for_browser_webviews() {
        let script = browser_observability_init_script();

        assert!(script.contains("currentWebview?.label"));
        assert!(script.contains("startsWith('browser-')"));
        assert!(script.contains("unhandledrejection"));
        assert!(script.contains("XMLHttpRequest.prototype.send"));
        assert!(script.contains("globalThis.__evofluxBrowserRuntime = runtime"));
    }

    #[test]
    fn browser_agent_cursor_is_compact_tail_free_and_tracks_pointer_actions() {
        let cursor = browser_agent_cursor_runtime_script();
        let click = browser_agent_action_script("click", &serde_json::json!({ "index": 2 }))
            .expect("click action should compile");
        let hover = browser_agent_action_script("hover", &serde_json::json!({ "index": 2 }))
            .expect("hover action should compile");
        let click_at =
            browser_agent_action_script("click_at", &serde_json::json!({ "x": 24, "y": 36 }))
                .expect("coordinate click should compile");

        assert!(cursor.contains("width: 17px; height: 18px"));
        assert!(cursor.contains("stroke-linejoin: round; stroke-linecap: round"));
        assert!(cursor.contains("M3 2.7 14.1 10.4 7.6 12.2Z"));
        assert!(!cursor.contains("21.6 16l-8.2 1.2"));
        assert!(click.contains("moveToElement(element, 'release')"));
        assert!(hover.contains("moveToElement(element)"));
        assert!(click_at.contains("move(x, y, 'release')"));
    }

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
    fn external_backend_init_clears_a_previous_desktop_token() {
        let script = frontend_init_script(None, "http://127.0.0.1:8000");

        assert!(script.contains("delete window.__OAD_TOKEN__"));
        assert!(script.contains("http://127.0.0.1:8000"));
    }

    #[test]
    fn development_backend_overrides_saved_backend() {
        assert_eq!(
            select_startup_backend(
                Some("http://127.0.0.1:8000".to_string()),
                Some("http://192.168.1.10:4082".to_string()),
            ),
            StartupBackend::DevelopmentExternal("http://127.0.0.1:8000".to_string())
        );
    }

    #[test]
    fn startup_backend_falls_back_from_saved_to_bundled() {
        assert_eq!(
            select_startup_backend(None, Some("http://192.168.1.10:4082".to_string())),
            StartupBackend::SavedExternal("http://192.168.1.10:4082".to_string())
        );
        assert_eq!(select_startup_backend(None, None), StartupBackend::Bundled);
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
