//! Window material: Mica on Windows 11, sidebar vibrancy on macOS.
//!
//! The window is created transparent; the UI paints every surface except the
//! sidebar, which shows the system material. When the platform cannot apply a
//! material (Windows 10, Linux) the UI falls back to an opaque sidebar, so the
//! result of [`apply`] is reported to it through [`window_material`].

use std::sync::Mutex;

use serde::Serialize;
use tauri::{State, Webview, Window};

#[derive(Clone, Copy, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
// Each platform constructs only its own variant.
#[allow(dead_code)]
pub enum Material {
    Mica,
    Vibrancy,
    None,
}

pub struct MaterialState(pub Mutex<Material>);

/// Apply the platform material to `window`. `dark` forces the Mica tint;
/// `None` follows the system theme.
#[allow(unused_variables)]
pub fn apply(window: &Window, dark: Option<bool>) -> Material {
    #[cfg(target_os = "windows")]
    {
        if window_vibrancy::apply_mica(window, dark).is_ok() {
            return Material::Mica;
        }
    }
    #[cfg(target_os = "macos")]
    {
        use window_vibrancy::{apply_vibrancy, NSVisualEffectMaterial, NSVisualEffectState};
        if apply_vibrancy(
            window,
            NSVisualEffectMaterial::Sidebar,
            Some(NSVisualEffectState::FollowsWindowActiveState),
            None,
        )
        .is_ok()
        {
            return Material::Vibrancy;
        }
    }
    Material::None
}

#[tauri::command]
pub fn window_material(state: State<'_, MaterialState>) -> Material {
    *state.0.lock().expect("material lock")
}

/// Re-tint the material when the app theme changes (Mica only; vibrancy
/// follows the system appearance on its own).
#[tauri::command]
// `Window`, not `WebviewWindow`: with browser tabs (child webviews) open the
// window holds several webviews and is no longer a `WebviewWindow`.
pub fn window_set_theme(window: Window, state: State<'_, MaterialState>, dark: bool) {
    let mut material = state.0.lock().expect("material lock");
    if *material == Material::Mica {
        *material = apply(&window, Some(dark));
    }
}

/// Open or close the web inspector (the app menu's Developer › Toggle
/// developer tools). `open` forces a state; without it the inspector toggles.
#[tauri::command]
pub fn window_devtools(webview: Webview, open: Option<bool>) {
    let show = open.unwrap_or(!webview.is_devtools_open());
    if show {
        webview.open_devtools();
    } else {
        webview.close_devtools();
    }
}

// ── Chat windows ────────────────────────────────────────────────────────────
//
// "Open in › New window" shows one chat in a window of its own. A chat lives
// in one window at a time: its window owns the chat's engine, the main window
// lets go of it and focuses that window instead of showing the chat itself.
// Closing the window stops the chat's engine (see `lib.rs`).

/// Window labels allow `a-zA-Z0-9-/:_`; chat ids are UUIDs or `chat-…`.
pub fn chat_window_label(chat: &str) -> String {
    let safe: String = chat
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() || c == '-' || c == '_' { c } else { '_' })
        .collect();
    format!("{CHAT_WINDOW_PREFIX}{safe}")
}

pub const CHAT_WINDOW_PREFIX: &str = "chat-";

/// Focus `chat`'s window when it has one; false otherwise.
#[tauri::command]
pub fn chat_window_focus(app: tauri::AppHandle, chat: String) -> bool {
    use tauri::Manager;
    match app.get_webview_window(&chat_window_label(&chat)) {
        Some(window) => {
            let _ = window.unminimize();
            let _ = window.set_focus();
            true
        }
        None => false,
    }
}

/// Show `chat` in a window of its own (or focus the one it has). Async: on
/// Windows a window built from a synchronous command deadlocks.
#[tauri::command]
pub async fn chat_window_open(app: tauri::AppHandle, chat: String, title: String) -> Result<(), String> {
    use tauri::{WebviewUrl, WebviewWindowBuilder};
    if chat_window_focus(app.clone(), chat.clone()) {
        return Ok(());
    }
    let id = serde_json::to_string(&chat).map_err(|e| e.to_string())?;
    let window = WebviewWindowBuilder::new(&app, chat_window_label(&chat), WebviewUrl::App("index.html".into()))
        .title(if title.trim().is_empty() { "Evo Harness".to_string() } else { format!("{title} — Evo Harness") })
        .inner_size(960.0, 780.0)
        .min_inner_size(520.0, 420.0)
        .decorations(false)
        .transparent(true)
        .shadow(true)
        // Tells the UI which chat this window shows (`src/lib/windows.ts`).
        .initialization_script(format!("window.__EVO_CHAT_WINDOW__ = {id};"))
        .build()
        .map_err(|e| format!("could not open a window: {e}"))?;
    // Same material as the main window; `window_material` reports it to both.
    use tauri::Manager;
    if let Some(window) = app.get_window(window.label()) {
        apply(&window, None);
    }
    Ok(())
}

/// Close `chat`'s window, if it has one (the chat was archived or deleted).
#[tauri::command]
pub fn chat_window_close(app: tauri::AppHandle, chat: String) {
    use tauri::Manager;
    if let Some(window) = app.get_webview_window(&chat_window_label(&chat)) {
        let _ = window.destroy();
    }
}
