//! Installed plugins that are on (`evo-plugins`), and what they add to a
//! session: skills and commands named `plugin:name`, agent types named
//! `plugin:name`, hooks, and `bin/` on PATH for the shell tools. Their
//! connectors are run by the desktop's shared MCP pool.
//!
//! Read once when the session starts and again on `reload_resources`.

use std::path::{Path, PathBuf};
use std::sync::{Arc, RwLock};

use evo_harness::types::Skill;
use evo_plugins::{Plugin, Store};

static ENABLED: RwLock<Option<Arc<Vec<Plugin>>>> = RwLock::new(None);

/// `<agent dir>/plugins`.
pub fn store() -> Option<Store> {
    crate::config::agent_dir()
        .ok()
        .map(|dir| Store::in_agent_dir(&dir))
}

/// The plugins that are on (read on first use).
pub fn enabled() -> Arc<Vec<Plugin>> {
    if let Some(list) = ENABLED.read().unwrap().clone() {
        return list;
    }
    reload()
}

/// Read the installed plugins again.
pub fn reload() -> Arc<Vec<Plugin>> {
    let list = Arc::new(store().map(|s| s.enabled()).unwrap_or_default());
    *ENABLED.write().unwrap() = Some(list.clone());
    list
}

fn namespaced(plugin: &Plugin, name: &str) -> String {
    format!("{}:{name}", plugin.name)
}

/// The plugins' skills, named `plugin:skill`.
pub async fn skills(env: &Arc<dyn evo_tools::ExecutionEnv>) -> Vec<Skill> {
    let mut out = Vec::new();
    for plugin in enabled().iter() {
        if plugin.skills.is_empty() {
            continue;
        }
        let result = crate::resource_dirs::load_skills_with_precedence(env, &plugin.skills).await;
        for mut skill in result.skills {
            skill.name = namespaced(plugin, &skill.name);
            out.push(skill);
        }
    }
    out
}

/// The plugins' command files, as skills named `plugin:command`.
pub fn commands() -> Vec<Skill> {
    let mut out = Vec::new();
    for plugin in enabled().iter() {
        for mut command in crate::customize::load_commands(&plugin.commands) {
            command.name = namespaced(plugin, &command.name);
            out.push(command);
        }
    }
    out
}

/// The plugins' agent type files with the plugin's name.
pub fn agent_files() -> Vec<(String, PathBuf)> {
    let mut out = Vec::new();
    for plugin in enabled().iter() {
        for path in &plugin.agents {
            if path.is_file() {
                out.push((plugin.name.clone(), path.clone()));
            } else if let Ok(entries) = std::fs::read_dir(path) {
                let mut files: Vec<PathBuf> = entries
                    .flatten()
                    .map(|e| e.path())
                    .filter(|p| p.extension().is_some_and(|e| e == "md") && p.is_file())
                    .collect();
                files.sort();
                out.extend(files.into_iter().map(|f| (plugin.name.clone(), f)));
            }
        }
    }
    out
}

/// The plugins' hooks: `(plugin name, {Event: [groups]})`.
pub fn hooks() -> Vec<(String, serde_json::Map<String, serde_json::Value>)> {
    enabled()
        .iter()
        .filter(|p| !p.hooks.is_empty())
        .map(|p| (p.name.clone(), p.hooks.clone()))
        .collect()
}

/// The plugin a file belongs to, if any.
pub fn plugin_of(path: &Path) -> Option<String> {
    let lower = |p: &Path| p.to_string_lossy().replace('\\', "/").to_ascii_lowercase();
    let file = lower(path);
    enabled()
        .iter()
        .find(|p| file.starts_with(&format!("{}/", lower(&p.root).trim_end_matches('/'))))
        .map(|p| p.name.clone())
}

/// Put the plugins' `bin/` folders first on PATH, so the shell tools find
/// their commands. Called once when the session starts.
pub fn apply_bin_path() {
    let bins: Vec<PathBuf> = enabled().iter().filter_map(|p| p.bin.clone()).collect();
    if bins.is_empty() {
        return;
    }
    let current = std::env::var_os("PATH").unwrap_or_default();
    let mut paths: Vec<PathBuf> = bins;
    paths.extend(std::env::split_paths(&current));
    if let Ok(joined) = std::env::join_paths(paths) {
        // Set before any tool runs; the engine is a single session per process.
        std::env::set_var("PATH", joined);
    }
}
