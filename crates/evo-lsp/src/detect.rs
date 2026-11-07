//! Which languages a project uses: files by extension and root markers, a few
//! levels deep, skipping dependency and build folders.

use std::collections::HashMap;
use std::path::Path;

use serde::Serialize;

use crate::catalog::{self, SERVERS};

const MAX_DEPTH: usize = 4;
const MAX_FILES: usize = 20_000;
const SKIP: &[&str] = &[
    "node_modules", "target", ".git", "dist", "build", "out", ".next", "vendor", "venv", ".venv", "__pycache__",
    "bin", "obj", ".gradle", ".idea", ".vscode", "coverage", ".turbo", ".cache",
];

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Detected {
    pub server: &'static str,
    pub files: usize,
    /// Root markers found (`Cargo.toml`, …).
    pub markers: Vec<String>,
}

fn marker_matches(marker: &str, name: &str) -> bool {
    match marker.strip_prefix('*') {
        Some(suffix) => name.ends_with(suffix),
        None => name == marker,
    }
}

/// Languages in `root`, most files first. A language counts with a root
/// marker, or with at least two files of it.
pub fn detect(root: &Path) -> Vec<Detected> {
    let mut counts: HashMap<&'static str, usize> = HashMap::new();
    let mut markers: HashMap<&'static str, Vec<String>> = HashMap::new();
    let mut seen = 0usize;
    let mut stack = vec![(root.to_path_buf(), 0usize)];
    while let Some((dir, depth)) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&dir) else { continue };
        for entry in entries.flatten() {
            let path = entry.path();
            let name = entry.file_name().to_string_lossy().into_owned();
            let Ok(kind) = entry.file_type() else { continue };
            if kind.is_dir() {
                if depth < MAX_DEPTH && !SKIP.contains(&name.as_str()) && !name.starts_with('.') {
                    stack.push((path, depth + 1));
                }
                continue;
            }
            seen += 1;
            if seen > MAX_FILES {
                break;
            }
            if let Some(server) = catalog::for_file(&path) {
                *counts.entry(server.id).or_default() += 1;
            }
            if depth <= 1 {
                for server in SERVERS {
                    if server.root_markers.iter().any(|m| marker_matches(m, &name)) {
                        markers.entry(server.id).or_default().push(name.clone());
                    }
                }
            }
        }
    }
    let mut out: Vec<Detected> = SERVERS
        .iter()
        .filter_map(|server| {
            let files = counts.get(server.id).copied().unwrap_or(0);
            let found = markers.remove(server.id).unwrap_or_default();
            // Markers alone count only with at least one file (package.json
            // also marks HTML/CSS/JSON projects otherwise).
            let counts = files >= 2 || (files >= 1 && !found.is_empty());
            counts.then(|| Detected { server: server.id, files, markers: found })
        })
        .collect();
    out.sort_by(|a, b| b.files.cmp(&a.files));
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_mixed_project_is_detected() {
        let dir = tempfile::tempdir().unwrap();
        let d = dir.path();
        std::fs::write(d.join("Cargo.toml"), "[package]").unwrap();
        std::fs::create_dir_all(d.join("src")).unwrap();
        std::fs::write(d.join("src/main.rs"), "fn main(){}").unwrap();
        std::fs::create_dir_all(d.join("web/src")).unwrap();
        std::fs::write(d.join("web/src/a.ts"), "").unwrap();
        std::fs::write(d.join("web/src/b.tsx"), "").unwrap();
        std::fs::create_dir_all(d.join("node_modules/x")).unwrap();
        for i in 0..5 {
            std::fs::write(d.join(format!("node_modules/x/{i}.js")), "").unwrap();
        }
        std::fs::write(d.join("README.md"), "").unwrap();
        let found = detect(d);
        let ids: Vec<_> = found.iter().map(|x| x.server).collect();
        assert!(ids.contains(&"rust-analyzer"), "{ids:?}");
        assert!(ids.contains(&"typescript"), "{ids:?}");
        // One markdown file, no marker: not enough.
        assert!(!ids.contains(&"marksman"), "{ids:?}");
        let rust = found.iter().find(|x| x.server == "rust-analyzer").unwrap();
        assert_eq!(rust.markers, vec!["Cargo.toml".to_string()]);
    }
}
