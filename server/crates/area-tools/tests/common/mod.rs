//! Fixture workspaces for the integration tests.

#![allow(
    dead_code,
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing,
    clippy::disallowed_methods
)]

use std::path::{Path, PathBuf};

use serde_json::Value;

/// `<root>/ws` with the fixture files and `<root>/outside` beside it.
pub struct Workspace {
    pub ws: PathBuf,
    pub out: PathBuf,
    pub links_ok: bool,
}

fn base64_decode(text: &str) -> Vec<u8> {
    const ALPHABET: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = Vec::new();
    let mut buffer = 0u32;
    let mut bits = 0;
    for byte in text.bytes().filter(|b| *b != b'=') {
        let value = ALPHABET.iter().position(|c| *c == byte).unwrap() as u32;
        buffer = (buffer << 6) | value;
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            out.push(((buffer >> bits) & 0xff) as u8);
        }
    }
    out
}

fn set_mtime(path: &Path, secs: u64) {
    let file = std::fs::OpenOptions::new().write(true).open(path).unwrap();
    file.set_modified(std::time::UNIX_EPOCH + std::time::Duration::from_secs(secs))
        .unwrap();
}

/// A directory symlink, or on Windows a junction when symlinks are not allowed.
pub fn link_dir(target: &Path, link: &Path) -> bool {
    #[cfg(unix)]
    {
        std::os::unix::fs::symlink(target, link).is_ok()
    }
    #[cfg(windows)]
    {
        if std::os::windows::fs::symlink_dir(target, link).is_ok() {
            return true;
        }
        // `mklink` rejects forward slashes; rebuild both paths from components.
        let target: PathBuf = target.components().collect();
        std::process::Command::new("cmd")
            .args(["/C", "mklink", "/J"])
            .arg(link.components().collect::<PathBuf>())
            .arg(target)
            .output()
            .is_ok_and(|o| o.status.success())
    }
}

/// A file symlink; false where the platform refuses (no junction equivalent).
pub fn link_file(target: &Path, link: &Path) -> bool {
    #[cfg(unix)]
    {
        std::os::unix::fs::symlink(target, link).is_ok()
    }
    #[cfg(windows)]
    {
        std::os::windows::fs::symlink_file(target, link).is_ok()
    }
}

impl Workspace {
    pub fn build(root: &Path, fixture: &Value, outside: &Value) -> Self {
        std::fs::create_dir_all(root).unwrap();
        let root = strip_verbatim(std::fs::canonicalize(root).unwrap());
        let ws = root.join("ws");
        let out = root.join("outside");
        std::fs::create_dir_all(&ws).unwrap();
        std::fs::create_dir_all(&out).unwrap();
        for (name, text) in outside.as_object().unwrap() {
            std::fs::write(out.join(name), text.as_str().unwrap()).unwrap();
        }
        for (name, entry) in fixture["files"].as_object().unwrap() {
            let path = ws.join(name);
            std::fs::create_dir_all(path.parent().unwrap()).unwrap();
            let bytes = match entry.get("b64") {
                Some(b64) => base64_decode(b64.as_str().unwrap()),
                None => entry["text"].as_str().unwrap().as_bytes().to_vec(),
            };
            std::fs::write(&path, bytes).unwrap();
            if let Some(mtime) = entry.get("mtime") {
                set_mtime(&path, mtime.as_u64().unwrap());
            }
        }
        for name in fixture["dirs"].as_array().unwrap() {
            std::fs::create_dir_all(ws.join(name.as_str().unwrap())).unwrap();
        }
        let mut workspace = Self {
            ws,
            out,
            links_ok: true,
        };
        for link in fixture["links"].as_array().unwrap() {
            let target = workspace.substitute(link["target"].as_str().unwrap());
            let made = link_dir(
                Path::new(&target),
                &workspace.ws.join(link["path"].as_str().unwrap()),
            );
            workspace.links_ok &= made;
        }
        workspace
    }

    pub fn substitute(&self, text: &str) -> String {
        text.replace("<WS>", &self.ws.display().to_string())
            .replace("<OUT>", &self.out.display().to_string())
    }

    /// Substitute placeholders inside JSON text, escaping backslashes as JSON does.
    pub fn substitute_json(&self, value: &Value) -> String {
        let escape = |p: &Path| {
            let text = serde_json::to_string(&p.display().to_string()).unwrap();
            text[1..text.len() - 1].to_owned()
        };
        value
            .to_string()
            .replace("<WS>", &escape(&self.ws))
            .replace("<OUT>", &escape(&self.out))
    }

    pub fn normalise(&self, content: &str, slashes: bool, drive: bool) -> String {
        let mut content = content.to_owned();
        let root = self.ws.parent().unwrap().to_path_buf();
        for (real, token) in [(&self.out, "<OUT>"), (&self.ws, "<WS>"), (&root, "<ROOT>")] {
            let text = real.display().to_string();
            for variant in [
                text.replace('\\', "\\\\"),
                text.clone(),
                text.replace('\\', "/"),
            ] {
                content = content.replace(&variant, token);
            }
        }
        if slashes {
            content = content.replace('\\', "/");
        }
        // A path with a root but no drive takes the workspace's drive.
        let ws = self.ws.display().to_string();
        let letter: String = ws.chars().take(2).collect();
        if drive && letter.ends_with(':') {
            content = content.replace(&format!("{letter}/"), "<DRIVE>/");
        }
        content
    }
}

fn strip_verbatim(path: PathBuf) -> PathBuf {
    let text = path.display().to_string();
    match text.strip_prefix("\\\\?\\") {
        Some(rest) if rest.chars().nth(1) == Some(':') => PathBuf::from(rest),
        _ => path,
    }
}
