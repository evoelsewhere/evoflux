//! Startup and background (Settings → General).
//!
//! * Run on startup: the OS starts evo at sign-in with [`HIDDEN_ARG`]
//!   (tauri-plugin-autostart). With the tray icon on it then stays in the
//!   tray without opening a window.
//! * Show in system tray: an icon in the notification area / menu bar.
//!   Closing the main window then only hides it, so running chats and
//!   scheduled tasks carry on; without the icon, closing the last window
//!   quits evo.
//! * Keep computer awake: holds off system sleep (not the display) while evo
//!   runs.
//!
//! Tray and keep-awake are stored in the app settings (`system.tray`,
//! `system.keepAwake`); run-on-startup is the OS's own record.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

use evo_store::logs::NewLog;
use serde::Serialize;
use serde_json::Value;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, State};
use tauri_plugin_autostart::ManagerExt;

use crate::db::Db;

/// Passed by the OS at sign-in: start in the tray, no window.
pub const HIDDEN_ARG: &str = "--hidden";

const TRAY_KEY: &str = "system.tray";
const AWAKE_KEY: &str = "system.keepAwake";
const TRAY_ID: &str = "main";

#[derive(Default)]
pub struct SystemState {
    tray: AtomicBool,
    awake: Mutex<Option<awake::Hold>>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SystemSettings {
    run_on_startup: bool,
    tray: bool,
    keep_awake: bool,
}

fn saved_flag(db: &Db, key: &str, default: bool) -> bool {
    db.with(|conn| evo_store::settings::all(conn))
        .ok()
        .and_then(|settings| settings.get(key).and_then(Value::as_bool))
        .unwrap_or(default)
}

/// Bring the main window back (tray click, second launch, dock icon).
pub fn show_main(app: &AppHandle) {
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.show();
        let _ = main.unminimize();
        let _ = main.set_focus();
    }
}

/// Apply the saved settings at launch, then show the main window unless the
/// OS started evo at sign-in and the tray can hold it.
pub fn setup(app: &AppHandle) {
    let db = app.state::<Db>();
    let state = app.state::<SystemState>();
    let tray = saved_flag(&db, TRAY_KEY, true);
    if tray {
        match build_tray(app) {
            Ok(()) => state.tray.store(true, Ordering::Relaxed),
            Err(error) => db.log(NewLog::new("warn", "shell", format!("no tray icon: {error}"))),
        }
    }
    if saved_flag(&db, AWAKE_KEY, false) {
        match awake::Hold::start() {
            Ok(hold) => *state.awake.lock().expect("awake lock") = Some(hold),
            Err(error) => db.log(NewLog::new("warn", "shell", format!("could not keep the computer awake: {error}"))),
        }
    }
    let hidden = std::env::args().any(|arg| arg == HIDDEN_ARG);
    if !(hidden && state.tray.load(Ordering::Relaxed)) {
        show_main(app);
    }
}

/// The main window's close button hides it while the tray icon is there.
pub fn on_close_requested(window: &tauri::Window, api: &tauri::CloseRequestApi) {
    if window.label() == "main" && window.state::<SystemState>().tray.load(Ordering::Relaxed) {
        api.prevent_close();
        let _ = window.hide();
    }
}

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    if app.tray_by_id(TRAY_ID).is_some() {
        return Ok(());
    }
    let open = MenuItem::with_id(app, "tray-open", "Open Evo Harness", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "tray-quit", "Quit Evo Harness", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &PredefinedMenuItem::separator(app)?, &quit])?;
    let mut builder = TrayIconBuilder::with_id(TRAY_ID)
        .tooltip("Evo Harness")
        .menu(&menu)
        // Left click opens the window; the menu is on right click.
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "tray-open" => show_main(app),
            "tray-quit" => quit_app(app),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
                show_main(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    Ok(())
}

/// Quit for real: stop every chat's engine, then exit.
pub fn quit_app(app: &AppHandle) {
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let engines = app.state::<crate::engine::EngineState>();
        for chat in engines.running().await {
            engines.stop(&chat).await;
        }
        app.exit(0);
    });
}

fn current(app: &AppHandle, state: &SystemState) -> SystemSettings {
    SystemSettings {
        run_on_startup: app.autolaunch().is_enabled().unwrap_or(false),
        tray: state.tray.load(Ordering::Relaxed),
        keep_awake: state.awake.lock().expect("awake lock").is_some(),
    }
}

#[tauri::command]
pub fn system_settings(app: AppHandle, state: State<'_, SystemState>) -> SystemSettings {
    current(&app, &state)
}

/// Turn one setting on or off (`runOnStartup`, `tray`, `keepAwake`); returns
/// all three as they now are.
#[tauri::command]
pub fn system_set(
    app: AppHandle,
    state: State<'_, SystemState>,
    db: State<'_, Db>,
    key: String,
    enabled: bool,
) -> Result<SystemSettings, String> {
    match key.as_str() {
        "runOnStartup" => {
            let autolaunch = app.autolaunch();
            if enabled { autolaunch.enable() } else { autolaunch.disable() }.map_err(|e| e.to_string())?;
        }
        "tray" => {
            if enabled {
                build_tray(&app).map_err(|e| format!("could not add the tray icon: {e}"))?;
            } else {
                app.remove_tray_by_id(TRAY_ID);
                // Nothing could bring a hidden main window back now.
                show_main(&app);
            }
            state.tray.store(enabled, Ordering::Relaxed);
            db.with(|conn| evo_store::settings::set(conn, TRAY_KEY, &Value::Bool(enabled)))?;
        }
        "keepAwake" => {
            let mut hold = state.awake.lock().expect("awake lock");
            if enabled && hold.is_none() {
                *hold = Some(awake::Hold::start()?);
            } else if !enabled {
                // Dropping the hold lets the computer sleep again.
                hold.take();
            }
            drop(hold);
            db.with(|conn| evo_store::settings::set(conn, AWAKE_KEY, &Value::Bool(enabled)))?;
        }
        other => return Err(format!("unknown setting {other}")),
    }
    db.log(NewLog::new("info", "shell", format!("{key} turned {}", if enabled { "on" } else { "off" })));
    Ok(current(&app, &state))
}

/// Holding off system sleep. The display may still turn off.
mod awake {
    /// Sleep is held off until this is dropped.
    pub struct Hold {
        #[cfg(target_os = "windows")]
        release: Option<std::sync::mpsc::Sender<()>>,
        #[cfg(not(target_os = "windows"))]
        child: std::process::Child,
    }

    #[cfg(target_os = "windows")]
    impl Hold {
        /// The execution state belongs to a thread: one thread holds it
        /// until told to let go.
        pub fn start() -> Result<Self, String> {
            use windows::Win32::System::Power::{SetThreadExecutionState, ES_CONTINUOUS, ES_SYSTEM_REQUIRED};
            let (release, wait) = std::sync::mpsc::channel::<()>();
            let (started, ok) = std::sync::mpsc::channel::<bool>();
            std::thread::Builder::new()
                .name("keep-awake".into())
                .spawn(move || {
                    let held = unsafe { SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED) };
                    let _ = started.send(held.0 != 0);
                    let _ = wait.recv();
                    unsafe { SetThreadExecutionState(ES_CONTINUOUS) };
                })
                .map_err(|e| e.to_string())?;
            match ok.recv() {
                Ok(true) => Ok(Self { release: Some(release) }),
                _ => Err("Windows refused to keep the computer awake".into()),
            }
        }
    }

    #[cfg(target_os = "windows")]
    impl Drop for Hold {
        fn drop(&mut self) {
            if let Some(release) = self.release.take() {
                let _ = release.send(());
            }
        }
    }

    #[cfg(not(target_os = "windows"))]
    impl Hold {
        pub fn start() -> Result<Self, String> {
            #[cfg(target_os = "macos")]
            let mut command = {
                // -i: no idle sleep; -w: stop with this process.
                let mut command = std::process::Command::new("/usr/bin/caffeinate");
                command.args(["-i", "-w", &std::process::id().to_string()]);
                command
            };
            #[cfg(not(target_os = "macos"))]
            let mut command = {
                let mut command = std::process::Command::new("systemd-inhibit");
                // The inhibitor lasts while `tail` waits for this process, so a
                // crash does not leave the computer unable to sleep.
                command.args([
                    "--what=sleep",
                    "--who=evo",
                    "--why=Keep computer awake is on",
                    "--mode=block",
                    "tail",
                    &format!("--pid={}", std::process::id()),
                    "-f",
                    "/dev/null",
                ]);
                command
            };
            let child = command
                .stdin(std::process::Stdio::null())
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .spawn()
                .map_err(|e| format!("could not keep the computer awake: {e}"))?;
            Ok(Self { child })
        }
    }

    #[cfg(not(target_os = "windows"))]
    impl Drop for Hold {
        fn drop(&mut self) {
            let _ = self.child.kill();
            let _ = self.child.wait();
        }
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn keep_awake_holds_and_lets_go() {
        let hold = super::awake::Hold::start().expect("hold off sleep");
        drop(hold);
        // A second hold after the first let go works too.
        drop(super::awake::Hold::start().expect("hold again"));
    }
}
