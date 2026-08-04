//! "Open with" support — detect which desktop apps can open the workspace
//! and launch them from the topbar menu.
//!
//! Detection is curated (a fixed catalog of well-known editors, file
//! managers, and terminals) rather than a full OS scan: it is fast,
//! deterministic, and never surfaces apps the user does not have.

use serde::Serialize;
use std::path::{Path, PathBuf};
use std::process::Command;

#[cfg(any(target_os = "macos", target_os = "windows"))]
use base64::Engine;

/// Kind of opener — used by the frontend for fallback presentation and ordering.
#[derive(Serialize, Clone, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum OpenerKind {
    Editor,
    FileManager,
    Terminal,
}

/// A desktop app that can open the workspace root.
#[derive(Serialize, Clone)]
pub struct WorkspaceOpener {
    /// Stable identifier passed back to `open_workspace_with`.
    pub id: String,
    /// Display name shown in the menu.
    pub name: String,
    /// Category for fallback presentation and ordering.
    pub kind: OpenerKind,
    /// PNG data URL extracted from the installed application by the OS.
    pub icon_data_url: Option<String>,
}

/// Catalog entry: how to detect and how to launch one app.
struct CatalogEntry {
    id: &'static str,
    name: &'static str,
    kind: OpenerKind,
    /// Absolute paths to probe (existence check).
    probe_paths: &'static [&'static str],
    /// Binaries to look up on PATH.
    probe_bins: &'static [&'static str],
}

#[cfg(target_os = "macos")]
const CATALOG: &[CatalogEntry] = &[
    CatalogEntry {
        id: "vscode",
        name: "VS Code",
        kind: OpenerKind::Editor,
        probe_paths: &[
            "/Applications/Visual Studio Code.app",
            "~/Applications/Visual Studio Code.app",
        ],
        probe_bins: &["code"],
    },
    CatalogEntry {
        id: "cursor",
        name: "Cursor",
        kind: OpenerKind::Editor,
        probe_paths: &["/Applications/Cursor.app", "~/Applications/Cursor.app"],
        probe_bins: &["cursor"],
    },
    CatalogEntry {
        id: "zed",
        name: "Zed",
        kind: OpenerKind::Editor,
        probe_paths: &["/Applications/Zed.app", "~/Applications/Zed.app"],
        probe_bins: &["zed"],
    },
    CatalogEntry {
        id: "sublime",
        name: "Sublime Text",
        kind: OpenerKind::Editor,
        probe_paths: &[
            "/Applications/Sublime Text.app",
            "~/Applications/Sublime Text.app",
        ],
        probe_bins: &["subl"],
    },
    CatalogEntry {
        id: "finder",
        name: "Finder",
        kind: OpenerKind::FileManager,
        // Finder always exists on macOS; no probes needed.
        probe_paths: &[],
        probe_bins: &[],
    },
    CatalogEntry {
        id: "terminal",
        name: "Terminal",
        kind: OpenerKind::Terminal,
        probe_paths: &["/System/Applications/Utilities/Terminal.app"],
        probe_bins: &[],
    },
    CatalogEntry {
        id: "iterm",
        name: "iTerm",
        kind: OpenerKind::Terminal,
        probe_paths: &["/Applications/iTerm.app", "~/Applications/iTerm.app"],
        probe_bins: &[],
    },
];

#[cfg(target_os = "windows")]
const CATALOG: &[CatalogEntry] = &[
    CatalogEntry {
        id: "vscode",
        name: "VS Code",
        kind: OpenerKind::Editor,
        probe_paths: &[
            r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
            r"%ProgramFiles%\Microsoft VS Code\Code.exe",
            r"%ProgramFiles(x86)%\Microsoft VS Code\Code.exe",
        ],
        probe_bins: &["code"],
    },
    CatalogEntry {
        id: "vscode-insiders",
        name: "VS Code Insiders",
        kind: OpenerKind::Editor,
        probe_paths: &[
            r"%LOCALAPPDATA%\Programs\Microsoft VS Code Insiders\Code - Insiders.exe",
            r"%ProgramFiles%\Microsoft VS Code Insiders\Code - Insiders.exe",
            r"%ProgramFiles(x86)%\Microsoft VS Code Insiders\Code - Insiders.exe",
        ],
        probe_bins: &["code-insiders"],
    },
    CatalogEntry {
        id: "cursor",
        name: "Cursor",
        kind: OpenerKind::Editor,
        probe_paths: &[
            r"%LOCALAPPDATA%\Programs\cursor\Cursor.exe",
            r"%LOCALAPPDATA%\Programs\Cursor\Cursor.exe",
            r"%ProgramFiles%\Cursor\Cursor.exe",
        ],
        probe_bins: &["cursor"],
    },
    CatalogEntry {
        id: "zed",
        name: "Zed",
        kind: OpenerKind::Editor,
        probe_paths: &[
            r"%LOCALAPPDATA%\Programs\Zed\Zed.exe",
            r"%ProgramFiles%\Zed\Zed.exe",
        ],
        probe_bins: &["zed"],
    },
    CatalogEntry {
        id: "sublime",
        name: "Sublime Text",
        kind: OpenerKind::Editor,
        probe_paths: &[
            r"%ProgramFiles%\Sublime Text\sublime_text.exe",
            r"%ProgramFiles(x86)%\Sublime Text\sublime_text.exe",
        ],
        probe_bins: &["subl"],
    },
    CatalogEntry {
        id: "explorer",
        name: "File Explorer",
        kind: OpenerKind::FileManager,
        // Always present on Windows.
        probe_paths: &[],
        probe_bins: &[],
    },
    CatalogEntry {
        id: "windows-terminal",
        name: "Windows Terminal",
        kind: OpenerKind::Terminal,
        probe_paths: &[r"%LOCALAPPDATA%\Microsoft\WindowsApps\wt.exe"],
        probe_bins: &["wt"],
    },
    CatalogEntry {
        id: "pwsh",
        name: "PowerShell 7",
        kind: OpenerKind::Terminal,
        probe_paths: &[
            r"%ProgramFiles%\PowerShell\7\pwsh.exe",
            r"%LOCALAPPDATA%\Microsoft\WindowsApps\pwsh.exe",
        ],
        probe_bins: &["pwsh"],
    },
    CatalogEntry {
        id: "powershell",
        name: "Windows PowerShell",
        kind: OpenerKind::Terminal,
        // Included with every supported Windows release.
        probe_paths: &[],
        probe_bins: &[],
    },
    CatalogEntry {
        id: "cmd",
        name: "Command Prompt",
        kind: OpenerKind::Terminal,
        // Always present on Windows.
        probe_paths: &[],
        probe_bins: &[],
    },
];

#[cfg(all(unix, not(target_os = "macos")))]
const CATALOG: &[CatalogEntry] = &[
    CatalogEntry {
        id: "vscode",
        name: "VS Code",
        kind: OpenerKind::Editor,
        probe_paths: &[],
        probe_bins: &["code"],
    },
    CatalogEntry {
        id: "vscodium",
        name: "VSCodium",
        kind: OpenerKind::Editor,
        probe_paths: &[],
        probe_bins: &["codium"],
    },
    CatalogEntry {
        id: "cursor",
        name: "Cursor",
        kind: OpenerKind::Editor,
        probe_paths: &[],
        probe_bins: &["cursor"],
    },
    CatalogEntry {
        id: "file-manager",
        name: "File Manager",
        kind: OpenerKind::FileManager,
        // xdg-open is effectively always available on desktop Linux.
        probe_paths: &[],
        probe_bins: &["xdg-open"],
    },
    CatalogEntry {
        id: "terminal",
        name: "Terminal",
        kind: OpenerKind::Terminal,
        probe_paths: &[],
        probe_bins: &["x-terminal-emulator", "gnome-terminal", "konsole"],
    },
];

/// Expand a leading `~/` or a Windows `%ENV_VAR%` prefix.
fn expand_probe_path(path: &str) -> PathBuf {
    #[cfg(target_os = "windows")]
    if let Some(rest) = path.strip_prefix('%') {
        if let Some(end) = rest.find('%') {
            let variable = &rest[..end];
            let suffix = rest[end + 1..].trim_start_matches(|c| c == '\\' || c == '/');
            if let Some(base) = std::env::var_os(variable) {
                return Path::new(&base).join(suffix);
            }
        }
    }

    if let Some(rest) = path.strip_prefix("~/") {
        if let Some(home) = std::env::var_os("HOME") {
            return Path::new(&home).join(rest);
        }
    }
    PathBuf::from(path)
}

/// Resolve a binary on PATH.
fn binary_on_path(bin: &str) -> Option<PathBuf> {
    let paths = std::env::var_os("PATH")?;
    #[cfg(target_os = "windows")]
    const EXTS: &[&str] = &[".exe", ".com", ".cmd", ".bat", ""];
    #[cfg(not(target_os = "windows"))]
    const EXTS: &[&str] = &[""];

    for dir in std::env::split_paths(&paths) {
        for ext in EXTS {
            let candidate = dir.join(format!("{bin}{ext}"));
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }
    None
}

/// Resolve the concrete executable for entries that launch a binary.
#[cfg(target_os = "windows")]
fn entry_executable(entry: &CatalogEntry) -> Option<PathBuf> {
    entry
        .probe_paths
        .iter()
        .map(|path| expand_probe_path(path))
        .find(|path| path.is_file())
        .or_else(|| entry.probe_bins.iter().find_map(|bin| binary_on_path(bin)))
}

/// Does this catalog entry exist on the current machine?
fn entry_available(entry: &CatalogEntry) -> bool {
    // Entries with no probes at all are platform built-ins — always available.
    if entry.probe_paths.is_empty() && entry.probe_bins.is_empty() {
        return true;
    }
    entry
        .probe_paths
        .iter()
        .any(|path| expand_probe_path(path).exists())
        || entry
            .probe_bins
            .iter()
            .any(|bin| binary_on_path(bin).is_some())
}

#[cfg(target_os = "macos")]
fn entry_icon_path(entry: &CatalogEntry) -> Option<PathBuf> {
    if entry.id == "finder" {
        return Some(PathBuf::from("/System/Library/CoreServices/Finder.app"));
    }

    entry
        .probe_paths
        .iter()
        .map(|path| expand_probe_path(path))
        .find(|path| path.exists())
        .or_else(|| entry.probe_bins.iter().find_map(|bin| binary_on_path(bin)))
}

#[cfg(target_os = "windows")]
fn entry_icon_path(entry: &CatalogEntry) -> Option<PathBuf> {
    let built_in = match entry.id {
        "explorer" => Some(r"%WINDIR%\explorer.exe"),
        "cmd" => Some(r"%WINDIR%\System32\cmd.exe"),
        "powershell" => Some(r"%WINDIR%\System32\WindowsPowerShell\v1.0\powershell.exe"),
        _ => None,
    }
    .map(expand_probe_path)
    .filter(|path| path.is_file());

    built_in.or_else(|| {
        entry
            .probe_paths
            .iter()
            .map(|path| expand_probe_path(path))
            .find(|path| path.is_file())
            .or_else(|| entry.probe_bins.iter().find_map(|bin| binary_on_path(bin)))
    })
}

#[cfg(any(target_os = "macos", target_os = "windows"))]
fn system_icon_data_url(entry: &CatalogEntry) -> Option<String> {
    let path = entry_icon_path(entry)?;
    // Icon providers are OS integrations and a malformed third-party icon
    // must not prevent the rest of the opener menu from loading.
    let icon = std::panic::catch_unwind(|| file_icon_provider::get_file_icon(path, 64))
        .ok()?
        .ok()?;
    let mut png_bytes = Vec::new();

    {
        let mut encoder = png::Encoder::new(&mut png_bytes, icon.width, icon.height);
        encoder.set_color(png::ColorType::Rgba);
        encoder.set_depth(png::BitDepth::Eight);
        let mut writer = encoder.write_header().ok()?;
        writer.write_image_data(&icon.pixels).ok()?;
    }

    Some(format!(
        "data:image/png;base64,{}",
        base64::engine::general_purpose::STANDARD.encode(png_bytes)
    ))
}

#[cfg(not(any(target_os = "macos", target_os = "windows")))]
fn system_icon_data_url(_entry: &CatalogEntry) -> Option<String> {
    None
}

/// List the desktop apps available to open the workspace root.
#[tauri::command]
pub async fn list_workspace_openers() -> Result<Vec<WorkspaceOpener>, String> {
    // Windows GUI processes can have long or network-backed PATH entries.
    // Keep filesystem probing off Tauri's IPC/UI thread so the menu can render
    // its loading state instead of freezing the entire WebView.
    tauri::async_runtime::spawn_blocking(|| {
        CATALOG
            .iter()
            .filter(|entry| entry_available(entry))
            .map(|entry| WorkspaceOpener {
                id: entry.id.to_string(),
                name: entry.name.to_string(),
                kind: entry.kind.clone(),
                icon_data_url: system_icon_data_url(entry),
            })
            .collect()
    })
    .await
    .map_err(|error| format!("Could not detect desktop applications: {error}"))
}

/// Launch an opener from the curated catalog with the workspace root.
///
/// `opener_id` must match a catalog entry — arbitrary binaries from the
/// frontend are rejected, and arguments are passed separately (no shell
/// string interpolation) to avoid injection via crafted paths.
#[tauri::command]
pub fn open_workspace_with(root: String, opener_id: String) -> Result<(), String> {
    let root_path = Path::new(&root);
    if !root_path.is_dir() {
        return Err("Workspace root does not exist".into());
    }
    let resolved = root_path
        .canonicalize()
        .unwrap_or_else(|_| root_path.to_path_buf());
    let root_str = resolved.to_string_lossy().into_owned();

    let entry = CATALOG
        .iter()
        .find(|e| e.id == opener_id)
        .ok_or_else(|| format!("Unknown opener: {opener_id}"))?;
    if !entry_available(entry) {
        return Err(format!("{} is not available on this machine", entry.name));
    }

    launch(entry, &resolved, &root_str).map_err(|e| format!("Failed to open {}: {e}", entry.name))
}

#[cfg(target_os = "macos")]
fn launch(entry: &CatalogEntry, _root: &Path, root_str: &str) -> std::io::Result<()> {
    // `open -a "App Name" <path>` handles both .app bundles and PATH bins
    // uniformly, and lets the OS bring the app to the foreground.
    Command::new("open")
        .arg("-a")
        .arg(entry.name)
        .arg(root_str)
        .spawn()?;
    Ok(())
}

#[cfg(target_os = "windows")]
fn launch(entry: &CatalogEntry, _root: &Path, root_str: &str) -> std::io::Result<()> {
    match entry.id {
        "explorer" => {
            Command::new("explorer.exe").arg(root_str).spawn()?;
        }
        "cmd" => {
            Command::new("cmd.exe")
                .arg("/K")
                .current_dir(root_str)
                .spawn()?;
        }
        "powershell" => {
            Command::new("powershell.exe")
                .args(["-NoExit", "-Command", "Set-Location", "-LiteralPath"])
                .arg(root_str)
                .spawn()?;
        }
        "windows-terminal" => {
            let executable = entry_executable(entry).ok_or_else(|| {
                std::io::Error::new(
                    std::io::ErrorKind::NotFound,
                    "Windows Terminal executable was not found",
                )
            })?;
            Command::new(executable).arg("-d").arg(root_str).spawn()?;
        }
        "pwsh" => {
            let executable = entry_executable(entry).ok_or_else(|| {
                std::io::Error::new(
                    std::io::ErrorKind::NotFound,
                    "PowerShell 7 executable was not found",
                )
            })?;
            Command::new(executable)
                .args(["-NoExit", "-Command", "Set-Location", "-LiteralPath"])
                .arg(root_str)
                .spawn()?;
        }
        _ => {
            let executable = entry_executable(entry).ok_or_else(|| {
                std::io::Error::new(
                    std::io::ErrorKind::NotFound,
                    format!("no launcher executable for {}", entry.name),
                )
            })?;
            Command::new(executable).arg(root_str).spawn()?;
        }
    }
    Ok(())
}

#[cfg(all(unix, not(target_os = "macos")))]
fn launch(entry: &CatalogEntry, root: &Path, root_str: &str) -> std::io::Result<()> {
    match entry.id {
        "file-manager" => {
            Command::new("xdg-open").arg(root_str).spawn()?;
        }
        "terminal" => {
            // Prefer the first available terminal emulator from the probes.
            let bin = entry
                .probe_bins
                .iter()
                .find_map(|bin| binary_on_path(bin))
                .ok_or_else(|| {
                    std::io::Error::new(std::io::ErrorKind::NotFound, "no terminal emulator found")
                })?;
            Command::new(bin).current_dir(root).spawn()?;
        }
        _ => {
            let bin = entry
                .probe_bins
                .iter()
                .find_map(|bin| binary_on_path(bin))
                .ok_or_else(|| {
                    std::io::Error::new(
                        std::io::ErrorKind::NotFound,
                        format!("no launcher binary for {}", entry.name),
                    )
                })?;
            Command::new(bin).arg(root_str).spawn()?;
        }
    }
    Ok(())
}

#[cfg(all(test, target_os = "macos"))]
mod tests {
    use super::*;

    #[test]
    fn extracts_icons_for_installed_openers() {
        let installed = CATALOG
            .iter()
            .filter(|entry| entry_available(entry))
            .collect::<Vec<_>>();

        assert!(!installed.is_empty());

        for entry in installed {
            let data_url =
                system_icon_data_url(entry).unwrap_or_else(|| panic!("{} system icon", entry.name));
            assert!(data_url.starts_with("data:image/png;base64,iVBOR"));
        }
    }
}
