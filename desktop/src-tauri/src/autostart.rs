//! Run on startup: launch EvoFlux when the user signs in.
//!
//! The operating system's own login entry is the only record, so turning it
//! off in Task Manager or deleting the file shows up in Settings without a
//! second copy to fall out of step.
//!
//! - Windows: a value under `HKCU\...\CurrentVersion\Run`. Task Manager's
//!   Startup tab disables it through `StartupApproved\Run` rather than
//!   deleting it, so that flag is read too.
//! - macOS: a per-user LaunchAgent in `~/Library/LaunchAgents`.
//! - Linux: an XDG autostart entry in `$XDG_CONFIG_HOME/autostart`.

use anyhow::{Context, Result};
use std::path::PathBuf;
use tauri::AppHandle;

/// Passed by the login entry, so a launch at sign-in can start in the tray
/// instead of opening a window on the desktop.
pub const LAUNCH_ARG: &str = "--autostart";

pub fn launched_at_login() -> bool {
    std::env::args().skip(1).any(|arg| arg == LAUNCH_ARG)
}

pub fn is_enabled(app: &AppHandle) -> Result<bool> {
    platform::is_enabled(app)
}

pub fn set_enabled(app: &AppHandle, enabled: bool) -> Result<()> {
    if enabled {
        platform::enable(app, &launch_executable()?)
    } else {
        platform::disable(app)
    }
}

/// Point an existing login entry at this executable. A moved app bundle or
/// AppImage would otherwise leave the entry launching a path that is gone.
pub fn refresh(app: &AppHandle) {
    match is_enabled(app) {
        Ok(true) => {
            if let Err(error) = set_enabled(app, true) {
                log::warn!("autostart: could not refresh the login entry: {error:#}");
            }
        }
        Ok(false) => {}
        Err(error) => log::warn!("autostart: could not read the login entry: {error:#}"),
    }
}

fn launch_executable() -> Result<PathBuf> {
    // An AppImage runs from a temporary mount; the file the user keeps is
    // the one to launch.
    #[cfg(target_os = "linux")]
    if let Some(appimage) = std::env::var_os("APPIMAGE").filter(|path| !path.is_empty()) {
        return Ok(PathBuf::from(appimage));
    }
    std::env::current_exe().context("resolve the EvoFlux executable")
}

#[cfg(target_os = "windows")]
mod platform {
    use super::LAUNCH_ARG;
    use anyhow::{Context, Result};
    use std::path::Path;
    use tauri::AppHandle;
    use windows::core::HSTRING;
    use windows::Win32::Foundation::{ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND, WIN32_ERROR};
    use windows::Win32::System::Registry::{
        RegDeleteKeyValueW, RegGetValueW, RegSetKeyValueW, HKEY_CURRENT_USER, REG_ROUTINE_FLAGS,
        REG_SZ, RRF_RT_REG_BINARY, RRF_RT_REG_SZ,
    };

    const RUN_KEY: &str = r"Software\Microsoft\Windows\CurrentVersion\Run";
    const APPROVED_KEY: &str =
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run";

    /// The Run value is named after the product, so the dev build keeps an
    /// entry of its own.
    fn value_name(app: &AppHandle) -> String {
        app.package_info().name.clone()
    }

    fn missing(status: WIN32_ERROR) -> bool {
        status == ERROR_FILE_NOT_FOUND || status == ERROR_PATH_NOT_FOUND
    }

    fn read_value(key: &str, name: &str, flags: REG_ROUTINE_FLAGS) -> Result<Option<Vec<u8>>> {
        let key = HSTRING::from(key);
        let name = HSTRING::from(name);
        let mut size = 0u32;
        let status = unsafe {
            RegGetValueW(HKEY_CURRENT_USER, &key, &name, flags, None, None, Some(&mut size))
        };
        if missing(status) {
            return Ok(None);
        }
        status.ok().with_context(|| format!("read {key}\\{name}"))?;
        let mut data = vec![0u8; size as usize];
        let status = unsafe {
            RegGetValueW(
                HKEY_CURRENT_USER,
                &key,
                &name,
                flags,
                None,
                Some(data.as_mut_ptr().cast()),
                Some(&mut size),
            )
        };
        if missing(status) {
            return Ok(None);
        }
        status.ok().with_context(|| format!("read {key}\\{name}"))?;
        data.truncate(size as usize);
        Ok(Some(data))
    }

    fn delete_value(key: &str, name: &str) -> Result<()> {
        let key = HSTRING::from(key);
        let name = HSTRING::from(name);
        let status = unsafe { RegDeleteKeyValueW(HKEY_CURRENT_USER, &key, &name) };
        if missing(status) {
            return Ok(());
        }
        status.ok().with_context(|| format!("delete {key}\\{name}"))
    }

    pub fn is_enabled(app: &AppHandle) -> Result<bool> {
        let name = value_name(app);
        if read_value(RUN_KEY, &name, RRF_RT_REG_SZ)?.is_none() {
            return Ok(false);
        }
        // Task Manager marks a disabled entry with an odd first byte.
        let disabled = read_value(APPROVED_KEY, &name, RRF_RT_REG_BINARY)?
            .and_then(|flags| flags.first().copied())
            .is_some_and(|flag| flag & 1 == 1);
        Ok(!disabled)
    }

    pub fn enable(app: &AppHandle, exe: &Path) -> Result<()> {
        let name = value_name(app);
        let command = format!("\"{}\" {LAUNCH_ARG}", exe.display());
        let data: Vec<u16> = command.encode_utf16().chain(Some(0)).collect();
        let key = HSTRING::from(RUN_KEY);
        let value = HSTRING::from(name.as_str());
        unsafe {
            RegSetKeyValueW(
                HKEY_CURRENT_USER,
                &key,
                &value,
                REG_SZ.0,
                Some(data.as_ptr().cast()),
                (data.len() * std::mem::size_of::<u16>()) as u32,
            )
        }
        .ok()
        .with_context(|| format!("write {RUN_KEY}\\{name}"))?;
        // Turning it on here overrides an earlier "Disabled" in Task Manager.
        delete_value(APPROVED_KEY, &name)
    }

    pub fn disable(app: &AppHandle) -> Result<()> {
        let name = value_name(app);
        delete_value(RUN_KEY, &name)?;
        delete_value(APPROVED_KEY, &name)
    }
}

#[cfg(target_os = "macos")]
mod platform {
    use super::LAUNCH_ARG;
    use anyhow::{Context, Result};
    use std::path::{Path, PathBuf};
    use tauri::{AppHandle, Manager};

    fn label(app: &AppHandle) -> String {
        format!("{}.login", app.config().identifier)
    }

    fn plist_path(app: &AppHandle) -> Result<PathBuf> {
        Ok(app
            .path()
            .home_dir()
            .context("resolve the home directory")?
            .join("Library")
            .join("LaunchAgents")
            .join(format!("{}.plist", label(app))))
    }

    fn xml_escape(text: &str) -> String {
        text.replace('&', "&amp;")
            .replace('<', "&lt;")
            .replace('>', "&gt;")
            .replace('"', "&quot;")
    }

    pub fn is_enabled(app: &AppHandle) -> Result<bool> {
        Ok(plist_path(app)?.exists())
    }

    pub fn enable(app: &AppHandle, exe: &Path) -> Result<()> {
        let path = plist_path(app)?;
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .with_context(|| format!("create {}", parent.display()))?;
        }
        let plist = format!(
            r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exe}</string>
        <string>{LAUNCH_ARG}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>ProcessType</key>
    <string>Interactive</string>
</dict>
</plist>
"#,
            label = xml_escape(&label(app)),
            exe = xml_escape(&exe.to_string_lossy()),
        );
        std::fs::write(&path, plist).with_context(|| format!("write {}", path.display()))
    }

    pub fn disable(app: &AppHandle) -> Result<()> {
        let path = plist_path(app)?;
        match std::fs::remove_file(&path) {
            Err(error) if error.kind() != std::io::ErrorKind::NotFound => {
                Err(error).with_context(|| format!("remove {}", path.display()))
            }
            _ => Ok(()),
        }
    }
}

#[cfg(target_os = "linux")]
mod platform {
    use super::LAUNCH_ARG;
    use anyhow::{Context, Result};
    use std::path::{Path, PathBuf};
    use tauri::{AppHandle, Manager};

    fn entry_path(app: &AppHandle) -> Result<PathBuf> {
        let config_dir = match std::env::var_os("XDG_CONFIG_HOME").filter(|dir| !dir.is_empty()) {
            Some(dir) => PathBuf::from(dir),
            None => app
                .path()
                .home_dir()
                .context("resolve the home directory")?
                .join(".config"),
        };
        Ok(config_dir
            .join("autostart")
            .join(format!("{}.desktop", app.config().identifier)))
    }

    /// Quote one `Exec=` argument as the Desktop Entry spec requires.
    fn exec_quote(argument: &str) -> String {
        let mut quoted = String::with_capacity(argument.len() + 2);
        quoted.push('"');
        for ch in argument.chars() {
            match ch {
                '"' | '`' | '$' | '\\' => {
                    quoted.push('\\');
                    quoted.push(ch);
                }
                '%' => quoted.push_str("%%"),
                _ => quoted.push(ch),
            }
        }
        quoted.push('"');
        quoted
    }

    pub fn is_enabled(app: &AppHandle) -> Result<bool> {
        let path = entry_path(app)?;
        let Ok(entry) = std::fs::read_to_string(&path) else {
            return Ok(false);
        };
        // Desktop environments switch an entry off in place.
        let switched_off = entry.lines().map(str::trim).any(|line| {
            line.eq_ignore_ascii_case("Hidden=true")
                || line.eq_ignore_ascii_case("X-GNOME-Autostart-enabled=false")
        });
        Ok(!switched_off)
    }

    pub fn enable(app: &AppHandle, exe: &Path) -> Result<()> {
        let path = entry_path(app)?;
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .with_context(|| format!("create {}", parent.display()))?;
        }
        let entry = format!(
            "[Desktop Entry]\nType=Application\nName={name}\nExec={exec} {LAUNCH_ARG}\nTerminal=false\nX-GNOME-Autostart-enabled=true\n",
            name = app.package_info().name,
            exec = exec_quote(&exe.to_string_lossy()),
        );
        std::fs::write(&path, entry).with_context(|| format!("write {}", path.display()))
    }

    pub fn disable(app: &AppHandle) -> Result<()> {
        let path = entry_path(app)?;
        match std::fs::remove_file(&path) {
            Err(error) if error.kind() != std::io::ErrorKind::NotFound => {
                Err(error).with_context(|| format!("remove {}", path.display()))
            }
            _ => Ok(()),
        }
    }
}

#[cfg(not(any(target_os = "windows", target_os = "macos", target_os = "linux")))]
mod platform {
    use anyhow::{anyhow, Result};
    use std::path::Path;
    use tauri::AppHandle;

    pub fn is_enabled(_app: &AppHandle) -> Result<bool> {
        Ok(false)
    }

    pub fn enable(_app: &AppHandle, _exe: &Path) -> Result<()> {
        Err(anyhow!("Run on startup is not available on this platform"))
    }

    pub fn disable(_app: &AppHandle) -> Result<()> {
        Ok(())
    }
}
