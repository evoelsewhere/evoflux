//! Running servers: one per (server, project root), started on first use and
//! kept while the engine runs.

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use crate::catalog::{self, Server};
use crate::client::Client;
use crate::install;

pub struct Pool {
    pub lsp_dir: PathBuf,
    clients: tokio::sync::Mutex<HashMap<(String, PathBuf), Arc<Client>>>,
    disabled: Mutex<HashSet<String>>,
}

fn marker_in(dir: &Path, marker: &str) -> bool {
    match marker.strip_prefix('*') {
        Some(suffix) => std::fs::read_dir(dir)
            .map(|entries| {
                entries
                    .flatten()
                    .any(|e| e.file_name().to_string_lossy().ends_with(suffix))
            })
            .unwrap_or(false),
        None => dir.join(marker).exists(),
    }
}

/// The project root for `file`: the nearest folder with one of `markers`, not
/// above `cwd` when the file is inside it; else `cwd` (or the file's folder).
pub fn find_root(file: &Path, markers: &[&str], cwd: &Path) -> PathBuf {
    let inside = file.starts_with(cwd);
    // The chat's folder wins when it is a project itself (a Cargo or npm
    // workspace): one server for all of it, not one per member.
    if inside && markers.iter().any(|m| marker_in(cwd, m)) {
        return cwd.to_path_buf();
    }
    let mut dir = file.parent();
    while let Some(d) = dir {
        if markers.iter().any(|m| marker_in(d, m)) {
            return d.to_path_buf();
        }
        if inside && d == cwd {
            break;
        }
        dir = d.parent();
    }
    if inside {
        cwd.to_path_buf()
    } else {
        file.parent().unwrap_or(cwd).to_path_buf()
    }
}

#[derive(Debug, Clone, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Running {
    pub server: &'static str,
    pub root: PathBuf,
    pub indexing: bool,
    pub alive: bool,
}

impl Pool {
    pub fn new(lsp_dir: PathBuf) -> Self {
        Pool {
            lsp_dir,
            clients: tokio::sync::Mutex::new(HashMap::new()),
            disabled: Mutex::new(HashSet::new()),
        }
    }

    pub fn set_disabled(&self, ids: impl IntoIterator<Item = String>) {
        *self.disabled.lock().unwrap() = ids.into_iter().collect();
    }

    pub fn is_disabled(&self, id: &str) -> bool {
        self.disabled.lock().unwrap().contains(id)
    }

    /// The server for `file`, started when needed.
    pub async fn client_for(&self, file: &Path, cwd: &Path) -> Result<Arc<Client>, String> {
        let server: &'static Server = catalog::for_file(file).ok_or_else(|| {
            format!(
                "no language server handles {} files",
                file.extension()
                    .map(|e| format!(".{}", e.to_string_lossy()))
                    .unwrap_or_else(|| "these".into())
            )
        })?;
        if self.is_disabled(server.id) {
            return Err(format!(
                "{} is switched off in Customize → Code intelligence",
                server.name
            ));
        }
        let located = install::locate(server, &self.lsp_dir).ok_or_else(|| {
            format!(
                "{} ({}) is not installed. Install it in Customize → Code intelligence{}",
                server.name,
                server.language,
                match &server.install {
                    catalog::Install::System { hint } => format!(" — {hint}"),
                    _ => String::new(),
                }
            )
        })?;
        let root = find_root(file, server.root_markers, cwd);
        let key = (server.id.to_string(), root.clone());
        let mut clients = self.clients.lock().await;
        if let Some(client) = clients.get(&key) {
            if client.alive() {
                return Ok(client.clone());
            }
            clients.remove(&key);
        }
        let env = install::env_for(server, &self.lsp_dir);
        let client = Client::start(server, &located.path, env, &root).await?;
        clients.insert(key, client.clone());
        Ok(client)
    }

    /// Every running server.
    pub async fn running(&self) -> Vec<Running> {
        self.clients
            .lock()
            .await
            .values()
            .map(|c| Running {
                server: c.server.id,
                root: c.root.clone(),
                indexing: c.indexing(),
                alive: c.alive(),
            })
            .collect()
    }

    pub async fn clients(&self) -> Vec<Arc<Client>> {
        self.clients
            .lock()
            .await
            .values()
            .filter(|c| c.alive())
            .cloned()
            .collect()
    }

    /// Stop the servers of `id` (after an uninstall), or all.
    pub async fn stop(&self, id: Option<&str>) {
        let mut clients = self.clients.lock().await;
        let keys: Vec<_> = clients
            .keys()
            .filter(|(s, _)| id.is_none_or(|i| i == s))
            .cloned()
            .collect();
        for key in keys {
            if let Some(client) = clients.remove(&key) {
                client.shutdown().await;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roots_are_the_nearest_marker_folder() {
        let dir = tempfile::tempdir().unwrap();
        let cwd = dir.path();
        std::fs::create_dir_all(cwd.join("crates/a/src")).unwrap();
        std::fs::write(cwd.join("crates/a/Cargo.toml"), "").unwrap();
        let file = cwd.join("crates/a/src/lib.rs");
        assert_eq!(find_root(&file, &["Cargo.toml"], cwd), cwd.join("crates/a"));
        // A workspace at the chat's folder covers its members.
        std::fs::write(cwd.join("Cargo.toml"), "").unwrap();
        assert_eq!(find_root(&file, &["Cargo.toml"], cwd), cwd.to_path_buf());
        assert_eq!(
            find_root(&cwd.join("x.py"), &["pyproject.toml"], cwd),
            cwd.to_path_buf()
        );
        std::fs::create_dir_all(cwd.join("app")).unwrap();
        std::fs::write(cwd.join("app/App.csproj"), "").unwrap();
        assert_eq!(
            find_root(&cwd.join("app/Program.cs"), &["*.csproj"], cwd),
            cwd.join("app")
        );
    }
}
