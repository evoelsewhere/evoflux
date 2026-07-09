//! Native workspace file operations — fast filesystem access without
//! going through the Python HTTP sidecar.
//!
//! Provides Tauri commands for listing and reading workspace files
//! directly from Rust, eliminating the HTTP round-trip to the Python backend.

use base64::Engine;
use serde::Serialize;
use std::path::Path;
use walkdir::WalkDir;

/// Maximum number of files to return from a listing.
const MAX_FILES: usize = 2_000;

/// Directories to skip during workspace traversal (matches Python's `_SKIPPED_DIR_NAMES`).
const SKIPPED_DIRS: &[&str] = &[
    "node_modules",
    "dist",
    "build",
    ".venv",
    "venv",
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
    ".git",
];

/// A single file entry in the workspace listing.
#[derive(Serialize, Clone)]
pub struct WorkspaceFileEntry {
    /// POSIX-relative path (forward slashes).
    pub path: String,
    /// Just the filename.
    pub name: String,
    /// File size in bytes.
    pub size: u64,
    /// Last-modified timestamp (Unix seconds, fractional).
    pub mtime: f64,
    /// MIME type (best-effort guess from extension).
    pub mime: String,
}

/// Response payload for `list_workspace_files`.
#[derive(Serialize)]
pub struct WorkspaceFilesResult {
    pub session_id: String,
    pub files: Vec<WorkspaceFileEntry>,
    pub truncated: bool,
    pub workspace_root: String,
}

/// List every regular file under `root`, recursively.
///
/// - Skips `.git/` and common build/cache directories.
/// - Returns at most [`MAX_FILES`] entries.
/// - Paths are POSIX-relative (forward slashes).
#[tauri::command]
pub fn list_workspace_files(
    root: String,
    session_id: String,
) -> Result<WorkspaceFilesResult, String> {
    let root_path = Path::new(&root);
    if !root_path.is_dir() {
        return Ok(WorkspaceFilesResult {
            session_id,
            files: vec![],
            truncated: false,
            workspace_root: root,
        });
    }

    let root_resolved = root_path
        .canonicalize()
        .unwrap_or_else(|_| root_path.to_path_buf());

    let mut files: Vec<WorkspaceFileEntry> = Vec::with_capacity(256);
    let mut truncated = false;

    for entry in WalkDir::new(root_path)
        .follow_links(false)
        .into_iter()
        .filter_entry(|e| {
            if e.file_type().is_dir() {
                let name = e.file_name().to_string_lossy();
                return !SKIPPED_DIRS.contains(&name.as_ref());
            }
            true
        })
    {
        let entry = match entry {
            Ok(e) => e,
            Err(_) => continue,
        };

        if !entry.file_type().is_file() {
            continue;
        }

        let path = entry.path();

        // Containment check — skip symlinks that escaped the root.
        let resolved = match path.canonicalize() {
            Ok(r) => r,
            Err(_) => continue,
        };
        if !resolved.starts_with(&root_resolved) {
            continue;
        }

        let rel = path
            .strip_prefix(root_path)
            .unwrap_or(path)
            .to_string_lossy()
            .replace('\\', "/");

        let name = entry
            .file_name()
            .to_string_lossy()
            .into_owned();

        let meta = match entry.metadata() {
            Ok(m) => m,
            Err(_) => continue,
        };

        let size = meta.len();
        let mtime = meta
            .modified()
            .ok()
            .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0);

        let mime = mime_guess::from_path(path)
            .first_or_octet_stream()
            .to_string();

        files.push(WorkspaceFileEntry {
            path: rel,
            name,
            size,
            mtime,
            mime,
        });

        if files.len() >= MAX_FILES {
            truncated = true;
            break;
        }
    }

    // Sort by path for stable ordering (matching Python's sorted walk).
    files.sort_by(|a, b| a.path.cmp(&b.path));

    Ok(WorkspaceFilesResult {
        session_id,
        files,
        truncated,
        workspace_root: root,
    })
}

/// Read a single workspace file and return its content as a base64 string.
///
/// The caller should decode the base64 to get the raw bytes. This avoids
/// passing large binary payloads through the Tauri IPC boundary as raw bytes.
#[tauri::command]
pub fn read_workspace_file(root: String, path: String) -> Result<String, String> {
    let root_path = Path::new(&root);
    if !root_path.is_dir() {
        return Err("Workspace root does not exist".into());
    }

    let root_resolved = root_path
        .canonicalize()
        .unwrap_or_else(|_| root_path.to_path_buf());

    // Build the target path and reject traversal.
    let target = root_path.join(&path);
    let target_resolved = match target.canonicalize() {
        Ok(r) => r,
        Err(_) => return Err("File not found".into()),
    };
    if !target_resolved.starts_with(&root_resolved) {
        return Err("Path escapes workspace root".into());
    }
    if !target_resolved.is_file() {
        return Err("Not a file".into());
    }

    let bytes = std::fs::read(&target_resolved).map_err(|e| format!("Read failed: {e}"))?;
    Ok(base64::engine::general_purpose::STANDARD.encode(&bytes))
}
