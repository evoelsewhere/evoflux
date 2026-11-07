//! Custom instructions for Customize → Instructions: the standing text every
//! chat gets in its system prompt, in the files the context loader already
//! reads (`evo_harness::context_files`):
//!
//! * **Personal** — the instruction file in the agent dir
//!   (`~/.evo/agent/AGENTS.md`), for every chat;
//! * **Project** — the one in the chat's folder, for chats there (read only
//!   once the folder is trusted);
//! * **Parent folders** — files above the folder, also read; listed so the
//!   view shows everything in effect.
//!
//! In each folder the first of [`CONTEXT_FILE_CANDIDATES`] that exists is the
//! one read, so that is the one edited; a folder with none gets `AGENTS.md`.
//! Saving empty text removes the file. The caller reloads resources so idle
//! chats pick the change up.

use std::path::{Path, PathBuf};

use evo_harness::context_files::CONTEXT_FILE_CANDIDATES;
use serde_json::{json, Value};

/// Files larger than this are shown cut (and not editable here).
const MAX_CHARS: usize = 200_000;

fn first_in(dir: &Path) -> Option<PathBuf> {
    CONTEXT_FILE_CANDIDATES
        .iter()
        .map(|name| dir.join(name))
        .find(|path| path.is_file())
}

/// The file read in `dir`, or `AGENTS.md` when there is none yet.
pub fn target(dir: &Path) -> PathBuf {
    first_in(dir).unwrap_or_else(|| dir.join("AGENTS.md"))
}

fn agent_dir() -> Result<PathBuf, String> {
    crate::config::agent_dir().map_err(|e| e.to_string())
}

fn entry(path: &Path) -> Value {
    let content = std::fs::read_to_string(path).ok();
    let size = content.as_ref().map_or(0, |c| c.chars().count());
    json!({
        "path": path,
        "exists": content.is_some(),
        "content": content.map(|c| if size > MAX_CHARS { c.chars().take(MAX_CHARS).collect() } else { c }).unwrap_or_default(),
        "tooLarge": size > MAX_CHARS,
    })
}

/// Files in the folders above `cwd` (nearest last), not counting the agent dir.
fn parents(cwd: &Path, agent: &Path) -> Vec<PathBuf> {
    let mut found: Vec<PathBuf> = cwd
        .ancestors()
        .skip(1)
        .filter(|dir| *dir != agent)
        .filter_map(first_in)
        .collect();
    found.reverse();
    found
}

/// Personal, project and parent-folder instructions for a chat in `cwd`.
pub fn describe(cwd: &Path, trusted: bool) -> Result<Value, String> {
    let agent = agent_dir()?;
    let same = cwd == agent.as_path();
    let mut project = entry(&target(cwd));
    project["folder"] = json!(cwd);
    Ok(json!({
        "personal": entry(&target(&agent)),
        "project": if same { Value::Null } else { project },
        "parents": parents(cwd, &agent).iter().map(|p| entry(p)).collect::<Vec<_>>(),
        "trusted": trusted,
    }))
}

/// Save `scope` (`personal` or `project`); empty text removes the file.
pub fn save(cwd: &Path, scope: &str, content: &str) -> Result<(), String> {
    let path = match scope {
        "personal" => target(&agent_dir()?),
        "project" => target(cwd),
        other => return Err(format!("unknown scope `{other}`")),
    };
    if content.trim().is_empty() {
        return match std::fs::remove_file(&path) {
            Err(e) if e.kind() != std::io::ErrorKind::NotFound => Err(e.to_string()),
            _ => Ok(()),
        };
    }
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let mut text = content.replace("\r\n", "\n");
    if !text.ends_with('\n') {
        text.push('\n');
    }
    std::fs::write(&path, text).map_err(|e| format!("could not save {}: {e}", path.display()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_file_read_is_the_file_edited() {
        let dir = tempfile::tempdir().unwrap();
        assert_eq!(target(dir.path()), dir.path().join("AGENTS.md"));
        std::fs::write(dir.path().join("AGENTS.md"), "plain").unwrap();
        std::fs::write(dir.path().join("AGENTS.override.md"), "override").unwrap();
        assert_eq!(target(dir.path()), dir.path().join("AGENTS.override.md"));
    }

    #[test]
    fn saving_writes_and_empty_text_removes() {
        let dir = tempfile::tempdir().unwrap();
        save(dir.path(), "project", "Use tabs.\r\nBe brief.").unwrap();
        let path = dir.path().join("AGENTS.md");
        assert_eq!(
            std::fs::read_to_string(&path).unwrap(),
            "Use tabs.\nBe brief.\n"
        );
        save(dir.path(), "project", "  \n").unwrap();
        assert!(!path.exists());
        save(dir.path(), "project", "").unwrap();
        assert!(save(dir.path(), "team", "x").is_err());
    }

    #[test]
    fn parent_folders_are_listed_nearest_last() {
        let root = tempfile::tempdir().unwrap();
        let child = root.path().join("a").join("b");
        std::fs::create_dir_all(&child).unwrap();
        std::fs::write(root.path().join("AGENTS.md"), "root").unwrap();
        std::fs::write(root.path().join("a").join("AGENTS.md"), "a").unwrap();
        let found = parents(&child, Path::new("/nowhere"));
        // Folders above the temp dir may hold files of their own.
        let n = found.len();
        assert!(n >= 2);
        assert_eq!(found[n - 1], root.path().join("a").join("AGENTS.md"));
        assert_eq!(found[n - 2], root.path().join("AGENTS.md"));
    }
}
