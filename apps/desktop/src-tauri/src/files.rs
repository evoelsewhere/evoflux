//! Files tool: browse, search, read and save files in the chat's folder.
//!
//! Text comes back as UTF-8 (lossy for stray bytes) up to a size limit;
//! images come back as data URLs; anything else is reported as binary so the
//! UI can offer to open it elsewhere. Saves check the modification time the
//! UI loaded, so an edit never silently overwrites a change made meanwhile
//! (by the agent, another editor or git).

use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;

use base64::Engine as _;
use serde::Serialize;

/// Larger text files are not loaded into the viewer.
const MAX_TEXT: u64 = 5 * 1024 * 1024;
/// Larger images are not inlined.
const MAX_IMAGE: u64 = 20 * 1024 * 1024;
/// Search walks at most this many files.
const MAX_WALK: usize = 200_000;
/// Folders listed but dimmed: build output and dependencies.
const HEAVY_DIRS: &[&str] = &["node_modules", "target", "dist", "build", ".next", ".venv", "__pycache__", ".turbo", ".cache"];

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Entry {
    name: String,
    path: String,
    dir: bool,
    size: u64,
    /// Build output, dependencies, hidden files: listed, but dimmed.
    dimmed: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase", rename_all_fields = "camelCase", tag = "kind")]
pub enum FileContent {
    Text { text: String, size: u64, mtime: u64, lossy: bool },
    Image { data_url: String, size: u64, mtime: u64 },
    Binary { size: u64, mtime: u64 },
    TooLarge { size: u64, mtime: u64 },
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Stat {
    exists: bool,
    dir: bool,
    size: u64,
    mtime: u64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SearchHit {
    path: String,
    relative: String,
    score: i64,
}

fn mtime_ms(meta: &std::fs::Metadata) -> u64 {
    meta.modified()
        .ok()
        .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

fn image_mime(path: &Path) -> Option<&'static str> {
    let ext = path.extension()?.to_str()?.to_ascii_lowercase();
    Some(match ext.as_str() {
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "webp" => "image/webp",
        "bmp" => "image/bmp",
        "ico" => "image/x-icon",
        "avif" => "image/avif",
        "svg" => "image/svg+xml",
        _ => return None,
    })
}

/// Text unless it has NUL bytes in its first 8 KiB.
fn looks_binary(bytes: &[u8]) -> bool {
    bytes.iter().take(8192).any(|b| *b == 0)
}

#[tauri::command]
pub fn fs_list_dir(path: String) -> Result<Vec<Entry>, String> {
    let dir = PathBuf::from(&path);
    let read = std::fs::read_dir(&dir).map_err(|e| format!("could not list {path}: {e}"))?;
    let mut entries: Vec<Entry> = read
        .filter_map(Result::ok)
        .filter_map(|entry| {
            let name = entry.file_name().to_string_lossy().into_owned();
            if name == ".git" {
                return None;
            }
            // Follow symlinks for the kind; a broken link lists as a file.
            let meta = std::fs::metadata(entry.path()).or_else(|_| entry.metadata()).ok()?;
            let dir = meta.is_dir();
            let dimmed = name.starts_with('.') || (dir && HEAVY_DIRS.contains(&name.as_str()));
            Some(Entry {
                path: entry.path().to_string_lossy().into_owned(),
                size: if dir { 0 } else { meta.len() },
                name,
                dir,
                dimmed,
            })
        })
        .collect();
    entries.sort_by(|a, b| b.dir.cmp(&a.dir).then_with(|| a.name.to_lowercase().cmp(&b.name.to_lowercase())));
    Ok(entries)
}

#[tauri::command]
pub fn fs_stat(path: String) -> Stat {
    match std::fs::metadata(&path) {
        Ok(meta) => Stat { exists: true, dir: meta.is_dir(), size: meta.len(), mtime: mtime_ms(&meta) },
        Err(_) => Stat { exists: false, dir: false, size: 0, mtime: 0 },
    }
}

#[tauri::command]
pub fn fs_read_file(path: String) -> Result<FileContent, String> {
    let file = PathBuf::from(&path);
    let meta = std::fs::metadata(&file).map_err(|e| format!("could not open {path}: {e}"))?;
    if meta.is_dir() {
        return Err(format!("{path} is a folder"));
    }
    let (size, mtime) = (meta.len(), mtime_ms(&meta));
    if let Some(mime) = image_mime(&file) {
        if size > MAX_IMAGE {
            return Ok(FileContent::TooLarge { size, mtime });
        }
        let bytes = std::fs::read(&file).map_err(|e| e.to_string())?;
        let data = base64::engine::general_purpose::STANDARD.encode(bytes);
        return Ok(FileContent::Image { data_url: format!("data:{mime};base64,{data}"), size, mtime });
    }
    if size > MAX_TEXT {
        return Ok(FileContent::TooLarge { size, mtime });
    }
    let bytes = std::fs::read(&file).map_err(|e| e.to_string())?;
    if looks_binary(&bytes) {
        return Ok(FileContent::Binary { size, mtime });
    }
    let bytes = bytes.strip_prefix(b"\xEF\xBB\xBF").unwrap_or(&bytes);
    match String::from_utf8(bytes.to_vec()) {
        Ok(text) => Ok(FileContent::Text { text, size, mtime, lossy: false }),
        Err(error) => Ok(FileContent::Text {
            text: String::from_utf8_lossy(error.as_bytes()).into_owned(),
            size,
            mtime,
            lossy: true,
        }),
    }
}

/// Save `text` to `path`. With `expected_mtime`, refuse (error starting with
/// `conflict:`) when the file changed on disk since it was loaded.
#[tauri::command]
pub fn fs_write_file(path: String, text: String, expected_mtime: Option<u64>) -> Result<u64, String> {
    let file = PathBuf::from(&path);
    if let (Some(expected), Ok(meta)) = (expected_mtime, std::fs::metadata(&file)) {
        if mtime_ms(&meta) != expected {
            return Err(format!("conflict: {path} changed on disk"));
        }
    }
    // Keep the line endings the file had is the editor's job; write what it has.
    std::fs::write(&file, text.as_bytes()).map_err(|e| format!("could not save {path}: {e}"))?;
    let meta = std::fs::metadata(&file).map_err(|e| e.to_string())?;
    Ok(mtime_ms(&meta))
}

/// A file pasted or dropped into the composer that has no path of its own
/// (copied image data, a file from the clipboard): save it under the app's
/// cache folder (`pastes/`) so the message can point at it. Returns its path.
#[tauri::command]
pub fn fs_save_paste(app: tauri::AppHandle, name: String, data: String) -> Result<String, String> {
    use tauri::Manager;
    let dir = app
        .path()
        .app_cache_dir()
        .map_err(|e| e.to_string())?
        .join("pastes");
    save_paste(&dir, &name, &data).map(|path| path.to_string_lossy().into_owned())
}

fn save_paste(dir: &Path, name: &str, data: &str) -> Result<PathBuf, String> {
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(data)
        .map_err(|e| format!("bad file data: {e}"))?;
    // Keep the name readable but safe; a stamp keeps pastes apart.
    let clean: String = name
        .chars()
        .map(|c| {
            if c.is_alphanumeric() || matches!(c, '.' | '-' | '_' | ' ') {
                c
            } else {
                '_'
            }
        })
        .collect();
    let clean = clean.trim().trim_start_matches('.');
    let clean = if clean.is_empty() { "pasted" } else { clean };
    let stamp = std::time::SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or_default();
    let folder = dir.join(stamp.to_string());
    std::fs::create_dir_all(&folder).map_err(|e| format!("could not save the pasted file: {e}"))?;
    let path = folder.join(clean);
    std::fs::write(&path, bytes).map_err(|e| format!("could not save the pasted file: {e}"))?;
    Ok(path)
}

/// Subsequence match of `query` in `candidate` (both lowercase); higher is
/// better: consecutive runs, matches after separators and in the file name win.
fn fuzzy_score(query: &str, candidate: &str) -> Option<i64> {
    if query.is_empty() {
        return Some(0);
    }
    let name_start = candidate.rfind(['/', '\\']).map(|i| i + 1).unwrap_or(0);
    let chars: Vec<char> = candidate.chars().collect();
    let mut score = 0i64;
    let mut position = 0usize;
    let mut previous: Option<usize> = None;
    for q in query.chars() {
        if q == ' ' {
            continue;
        }
        let found = (position..chars.len()).find(|&i| chars[i] == q)?;
        score += 1;
        if previous.is_some_and(|p| p + 1 == found) {
            score += 5;
        }
        if found == 0 || matches!(chars[found - 1], '/' | '\\' | '_' | '-' | '.' | ' ') {
            score += 3;
        }
        // Byte offset of the char for the name check (paths are mostly ASCII).
        let byte = candidate.char_indices().nth(found).map(|(b, _)| b).unwrap_or(0);
        if byte >= name_start {
            score += 2;
        }
        previous = Some(found);
        position = found + 1;
    }
    // Shorter paths first among equals.
    Some(score * 100 - chars.len() as i64)
}

/// Files under `root` whose relative path fuzzily matches `query`, honouring
/// .gitignore; best first.
#[tauri::command]
pub async fn fs_search(root: String, query: String, limit: Option<usize>) -> Result<Vec<SearchHit>, String> {
    let limit = limit.unwrap_or(50).min(500);
    tauri::async_runtime::spawn_blocking(move || {
        let root_path = PathBuf::from(&root);
        if !root_path.is_dir() {
            return Err(format!("{root} is not a folder"));
        }
        let needle = query.trim().to_lowercase();
        let mut hits: Vec<SearchHit> = Vec::new();
        let walker = ignore::WalkBuilder::new(&root_path)
            .hidden(false)
            .git_ignore(true)
            .git_global(true)
            .git_exclude(true)
            .require_git(false)
            .filter_entry(|entry| entry.file_name() != ".git")
            .build();
        for (seen, entry) in walker.filter_map(Result::ok).enumerate() {
            if seen > MAX_WALK {
                break;
            }
            if !entry.file_type().is_some_and(|t| t.is_file()) {
                continue;
            }
            let relative = entry
                .path()
                .strip_prefix(&root_path)
                .unwrap_or(entry.path())
                .to_string_lossy()
                .replace('\\', "/");
            if let Some(score) = fuzzy_score(&needle, &relative.to_lowercase()) {
                hits.push(SearchHit { path: entry.path().to_string_lossy().into_owned(), relative, score });
            }
        }
        hits.sort_by(|a, b| b.score.cmp(&a.score).then_with(|| a.relative.cmp(&b.relative)));
        hits.truncate(limit);
        Ok(hits)
    })
    .await
    .map_err(|e| e.to_string())?
}


/// A line of a file under `root` that contains the query.
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct GrepHit {
    path: String,
    relative: String,
    /// 1-based.
    line: usize,
    /// 1-based, in characters.
    column: usize,
    /// The line, trimmed and cut to about 200 characters around the match.
    preview: String,
}

/// Larger files are skipped by the content search.
const MAX_GREP_FILE: u64 = 1024 * 1024;

/// Lines of text files under `root` containing `query` (case-insensitive),
/// honouring .gitignore; at most `limit` lines, files in walk order.
#[tauri::command]
pub async fn fs_grep(root: String, query: String, limit: Option<usize>) -> Result<Vec<GrepHit>, String> {
    let limit = limit.unwrap_or(300).min(2000);
    tauri::async_runtime::spawn_blocking(move || grep(&root, &query, limit))
        .await
        .map_err(|e| e.to_string())?
}

fn grep(root: &str, query: &str, limit: usize) -> Result<Vec<GrepHit>, String> {
    let root_path = PathBuf::from(root);
    if !root_path.is_dir() {
        return Err(format!("{root} is not a folder"));
    }
    let needle = query.to_lowercase();
    if needle.trim().is_empty() {
        return Ok(Vec::new());
    }
    let mut hits = Vec::new();
    let walker = ignore::WalkBuilder::new(&root_path)
        .hidden(false)
        .git_ignore(true)
        .git_global(true)
        .git_exclude(true)
        .require_git(false)
        .filter_entry(|entry| entry.file_name() != ".git")
        .build();
    for (seen, entry) in walker.filter_map(Result::ok).enumerate() {
        if seen > MAX_WALK || hits.len() >= limit {
            break;
        }
        if !entry.file_type().is_some_and(|t| t.is_file()) {
            continue;
        }
        if entry.metadata().map(|m| m.len() > MAX_GREP_FILE).unwrap_or(true) {
            continue;
        }
        let Ok(bytes) = std::fs::read(entry.path()) else { continue };
        if looks_binary(&bytes) {
            continue;
        }
        let text = String::from_utf8_lossy(&bytes);
        let relative = entry
            .path()
            .strip_prefix(&root_path)
            .unwrap_or(entry.path())
            .to_string_lossy()
            .replace('\\', "/");
        for (index, line) in text.lines().enumerate() {
            let lower = line.to_lowercase();
            let Some(byte) = lower.find(&needle) else { continue };
            // Lowercasing can change byte lengths; map back by characters.
            let column = lower[..byte].chars().count();
            hits.push(GrepHit {
                path: entry.path().to_string_lossy().into_owned(),
                relative: relative.clone(),
                line: index + 1,
                column: column + 1,
                preview: preview(line, column),
            });
            if hits.len() >= limit {
                break;
            }
        }
    }
    Ok(hits)
}

/// `line` trimmed, cut to ~200 characters keeping the match (at `column`) in view.
fn preview(line: &str, column: usize) -> String {
    let chars: Vec<char> = line.chars().collect();
    let lead = chars.iter().take_while(|c| c.is_whitespace()).count();
    let start = lead.max(column.saturating_sub(60));
    let end = (start + 200).min(chars.len());
    let mut out: String = chars[start.min(end)..end].iter().collect();
    if start > lead {
        out.insert(0, '…');
    }
    if end < chars.len() {
        out.push('…');
    }
    out.trim_end().to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pasted_files_get_a_safe_name_and_their_bytes() {
        let dir = std::env::temp_dir().join(format!("evo-paste-test-{}", std::process::id()));
        let data = base64::engine::general_purpose::STANDARD.encode(b"hello");
        let path = save_paste(&dir, "../re:port?.txt", &data).unwrap();
        assert!(path.starts_with(&dir));
        assert_eq!(path.file_name().unwrap(), "_re_port_.txt");
        assert_eq!(std::fs::read(&path).unwrap(), b"hello");
        assert!(save_paste(&dir, "x", "not base64!").is_err());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn content_serializes_with_camel_case_fields() {
        let image = serde_json::to_value(FileContent::Image { data_url: "data:".into(), size: 1, mtime: 2 }).unwrap();
        assert_eq!(image["kind"], "image");
        assert_eq!(image["dataUrl"], "data:");
        let large = serde_json::to_value(FileContent::TooLarge { size: 1, mtime: 2 }).unwrap();
        assert_eq!(large["kind"], "tooLarge");
    }

    #[test]
    fn fuzzy_prefers_file_names_and_runs() {
        let a = fuzzy_score("main", "src/main.rs").unwrap();
        let b = fuzzy_score("main", "src/m/a/i/n.rs").unwrap();
        assert!(a > b);
        assert!(fuzzy_score("xyz", "src/main.rs").is_none());
        assert!(fuzzy_score("srmr", "src/main.rs").is_some());
    }

    #[test]
    fn reads_text_images_and_binary_and_detects_conflicts() {
        let dir = std::env::temp_dir().join(format!("evo-files-test-{}", std::process::id()));
        std::fs::create_dir_all(dir.join("sub")).unwrap();
        let text = dir.join("a.txt");
        std::fs::write(&text, "\u{feff}héllo").unwrap();
        std::fs::write(dir.join("b.png"), [0x89, b'P', b'N', b'G']).unwrap();
        std::fs::write(dir.join("c.bin"), [1, 0, 2]).unwrap();

        let path = text.to_string_lossy().into_owned();
        let FileContent::Text { text: body, mtime, .. } = fs_read_file(path.clone()).unwrap() else { panic!("text") };
        assert_eq!(body, "héllo");
        assert!(matches!(fs_read_file(dir.join("b.png").to_string_lossy().into()).unwrap(), FileContent::Image { .. }));
        assert!(matches!(fs_read_file(dir.join("c.bin").to_string_lossy().into()).unwrap(), FileContent::Binary { .. }));

        let saved = fs_write_file(path.clone(), "one".into(), Some(mtime)).unwrap();
        assert!(fs_write_file(path.clone(), "two".into(), Some(saved.saturating_sub(5000))).unwrap_err().starts_with("conflict:"));
        assert_eq!(std::fs::read_to_string(&text).unwrap(), "one");

        let listed = fs_list_dir(dir.to_string_lossy().into()).unwrap();
        assert!(listed[0].dir && listed[0].name == "sub");
        assert_eq!(listed.len(), 4);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn grep_finds_lines_case_insensitively_and_skips_binary() {
        let dir = std::env::temp_dir().join(format!("evo-grep-test-{}", std::process::id()));
        std::fs::create_dir_all(dir.join("src")).unwrap();
        std::fs::write(dir.join("src/a.rs"), "fn main() {\n    let Needle = 1;\n}\n").unwrap();
        std::fs::write(dir.join("b.bin"), [b'n', b'e', b'e', b'd', b'l', b'e', 0]).unwrap();
        let hits = grep(&dir.to_string_lossy(), "needle", 10).unwrap();
        assert_eq!(hits.len(), 1);
        assert_eq!(hits[0].relative, "src/a.rs");
        assert_eq!((hits[0].line, hits[0].column), (2, 9));
        assert_eq!(hits[0].preview, "let Needle = 1;");
        assert!(grep(&dir.to_string_lossy(), "  ", 10).unwrap().is_empty());
        let _ = std::fs::remove_dir_all(&dir);
    }
}
