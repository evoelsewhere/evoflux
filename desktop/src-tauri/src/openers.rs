//! "Open with" support — detect which desktop apps can open the workspace
//! and launch them from the topbar menu.
//!
//! Detection is curated (a fixed catalog of well-known editors, file
//! managers, and terminals) rather than a full OS scan: it is fast,
//! deterministic, and never surfaces apps the user does not have.

use serde::Serialize;
use std::path::{Path, PathBuf};
use std::process::Command;

/// Kind of opener — used by the frontend to pick an icon and ordering.
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
    /// Category for icon/ordering.
    pub kind: OpenerKind,
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
        probe_paths: &[],
        probe_bins: &["code"],
    },
    CatalogEntry {
        id: "cursor",
        name: "Cursor",
        kind: OpenerKind::Editor,
        probe_paths: &[],
        probe_bins: &["cursor"],
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
        id: "powershell",
        name: "PowerShell",
        kind: OpenerKind::Terminal,
        probe_paths: &[],
        probe_bins: &["powershell"],
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

/// Expand a leading `~/` to the user's home directory.
fn expand_home(path: &str) -> PathBuf {
    if let Some(rest) = path.strip_prefix("~/") {
        if let Some(home) = std::env::var_os("HOME") {
            return Path::new(&home).join(rest);
        }
    }
    PathBuf::from(path)
}

/// Check whether a binary is resolvable on PATH.
fn binary_on_path(bin: &str) -> bool {
    let Some(paths) = std::env::var_os("PATH") else {
        return false;
    };
    #[cfg(target_os = "windows")]
    const EXTS: &[&str] = &[".exe", ".cmd", ".bat", ""];
    #[cfg(not(target_os = "windows"))]
    const EXTS: &[&str] = &[""];

    for dir in std::env::split_paths(&paths) {
        for ext in EXTS {
            let candidate = dir.join(format!("{bin}{ext}"));
            if candidate.is_file() {
                return true;
            }
        }
    }
    false
}

/// Does this catalog entry exist on the current machine?
fn entry_available(entry: &CatalogEntry) -> bool {
    // Entries with no probes at all are platform built-ins — always available.
    if entry.probe_paths.is_empty() && entry.probe_bins.is_empty() {
        return true;
    }
    entry.probe_paths.iter().any(|p| expand_home(p).exists())
        || entry.probe_bins.iter().any(|b| binary_on_path(b))
}

/// List the desktop apps available to open the workspace root.
#[tauri::command]
pub fn list_workspace_openers() -> Vec<WorkspaceOpener> {
    CATALOG
        .iter()
        .filter(|e| entry_available(e))
        .map(|e| WorkspaceOpener {
            id: e.id.to_string(),
            name: e.name.to_string(),
            kind: e.kind.clone(),
        })
        .collect()
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

    launch(entry, &resolved, &root_str)
        .map_err(|e| format!("Failed to open {}: {e}", entry.name))
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
            Command::new("explorer").arg(root_str).spawn()?;
        }
        "cmd" => {
            Command::new("cmd")
                .args(["/c", "start", "cmd"])
                .current_dir(root_str)
                .spawn()?;
        }
        "powershell" => {
            Command::new("powershell")
                .args(["-NoExit", "-Command", "Set-Location", root_str])
                .spawn()?;
        }
        _ => {
            // Editors: resolve from PATH (`code`, `cursor`, ...).
            let bin = entry
                .probe_bins
                .iter()
                .find(|b| binary_on_path(b))
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
                .find(|b| binary_on_path(b))
                .ok_or_else(|| {
                    std::io::Error::new(
                        std::io::ErrorKind::NotFound,
                        "no terminal emulator found",
                    )
                })?;
            Command::new(bin).current_dir(root).spawn()?;
        }
        _ => {
            let bin = entry
                .probe_bins
                .iter()
                .find(|b| binary_on_path(b))
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
