//! Settings → Desktop: preferences the native shell owns rather than the
//! sidecar, because they change how the app process itself behaves.
//!
//! - Run on startup lives in the OS login entry (see `autostart`).
//! - The tray icon and Keep computer awake are saved in
//!   `desktop-settings.json` next to the other shell config files.

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::sync::atomic::Ordering;
use tauri::{AppHandle, Manager};

use crate::{app_config_file, autostart, keep_awake, AppState, MAIN_WINDOW, SECONDARY_WINDOW_PREFIX};

pub const TRAY_ID: &str = "main";

#[derive(Clone, Serialize, Deserialize)]
#[serde(default)]
struct SavedDesktopSettings {
    tray_icon: bool,
    keep_awake: bool,
}

impl Default for SavedDesktopSettings {
    fn default() -> Self {
        Self {
            tray_icon: true,
            keep_awake: false,
        }
    }
}

#[derive(Serialize)]
pub struct DesktopSettings {
    run_on_startup: bool,
    tray_icon: bool,
    keep_awake: bool,
}

#[derive(Deserialize)]
pub struct DesktopSettingsPatch {
    run_on_startup: Option<bool>,
    tray_icon: Option<bool>,
    keep_awake: Option<bool>,
}

fn settings_path(app: &AppHandle) -> Result<std::path::PathBuf> {
    app_config_file(app, "desktop-settings.json")
}

fn load(app: &AppHandle) -> SavedDesktopSettings {
    let read = || -> Result<SavedDesktopSettings> {
        let path = settings_path(app)?;
        if !path.exists() {
            return Ok(SavedDesktopSettings::default());
        }
        let bytes = std::fs::read(&path).with_context(|| format!("read {}", path.display()))?;
        serde_json::from_slice(&bytes).with_context(|| format!("parse {}", path.display()))
    };
    read().unwrap_or_else(|error| {
        log::warn!("desktop settings: using defaults: {error:#}");
        SavedDesktopSettings::default()
    })
}

fn save(app: &AppHandle, settings: &SavedDesktopSettings) -> Result<()> {
    let path = settings_path(app)?;
    let bytes = serde_json::to_vec_pretty(settings).context("serialize desktop settings")?;
    std::fs::write(&path, bytes).with_context(|| format!("write {}", path.display()))
}

fn current(app: &AppHandle, saved: &SavedDesktopSettings) -> DesktopSettings {
    DesktopSettings {
        run_on_startup: autostart::is_enabled(app).unwrap_or_else(|error| {
            log::warn!("autostart: could not read the login entry: {error:#}");
            false
        }),
        tray_icon: saved.tray_icon,
        keep_awake: saved.keep_awake,
    }
}

fn show_tray_icon(app: &AppHandle, visible: bool) {
    let state: tauri::State<'_, AppState> = app.state();
    state.tray_icon_enabled.store(visible, Ordering::SeqCst);
    if let Some(tray) = app.tray_by_id(TRAY_ID) {
        if let Err(error) = tray.set_visible(visible) {
            log::warn!("desktop settings: could not change tray visibility: {error}");
        }
    }
}

/// Whether the tray icon is on, read once when the main window opens.
pub fn tray_icon_enabled(app: &AppHandle) -> bool {
    let state: tauri::State<'_, AppState> = app.state();
    state.tray_icon_enabled.load(Ordering::SeqCst)
}

/// Apply the saved settings once the tray exists. The sleep assertion and
/// login-entry refresh touch processes and the filesystem, so they run off
/// the setup thread.
pub fn apply_at_startup(app: &AppHandle) {
    let saved = load(app);
    show_tray_icon(app, saved.tray_icon);
    let handle = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        if saved.keep_awake {
            if let Err(error) = keep_awake::set(true) {
                log::warn!("keep awake: could not stop the system sleeping: {error:#}");
            }
        }
        autostart::refresh(&handle);
    });
}

/// Should closing this window quit EvoFlux instead of hiding it?
///
/// With the tray icon off, a hidden window on Windows or Linux would leave
/// the app running with nothing on screen to bring it back, so closing the
/// last visible window quits. macOS keeps its Dock icon either way.
pub fn close_quits_app(app: &AppHandle, closing_label: &str) -> bool {
    if cfg!(target_os = "macos") || tray_icon_enabled(app) {
        return false;
    }
    !app.webview_windows().iter().any(|(label, window)| {
        label != closing_label
            && (label == MAIN_WINDOW || label.starts_with(SECONDARY_WINDOW_PREFIX))
            && window.is_visible().unwrap_or(false)
    })
}

#[tauri::command]
pub async fn app_desktop_settings(app: AppHandle) -> Result<DesktopSettings, String> {
    tauri::async_runtime::spawn_blocking(move || current(&app, &load(&app)))
        .await
        .map_err(|error| error.to_string())
}

#[tauri::command]
pub async fn app_update_desktop_settings(
    app: AppHandle,
    patch: DesktopSettingsPatch,
) -> Result<DesktopSettings, String> {
    tauri::async_runtime::spawn_blocking(move || -> Result<DesktopSettings> {
        let mut saved = load(&app);
        if let Some(enabled) = patch.run_on_startup {
            autostart::set_enabled(&app, enabled).context("update the login entry")?;
        }
        if let Some(enabled) = patch.keep_awake {
            keep_awake::set(enabled).context("update the sleep assertion")?;
            saved.keep_awake = enabled;
        }
        if let Some(visible) = patch.tray_icon {
            show_tray_icon(&app, visible);
            saved.tray_icon = visible;
        }
        save(&app, &saved)?;
        Ok(current(&app, &saved))
    })
    .await
    .map_err(|error| error.to_string())?
    .map_err(|error| format!("{error:#}"))
}
