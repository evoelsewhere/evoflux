//! Plugins and marketplaces (`evo-plugins`) for Customize → Plugins.
//!
//! Installs live in `<agent dir>/plugins`. After every change the shell
//! gives the connector pool the enabled plugins' MCP servers and emits
//! `plugins://changed`; the UI then has every chat's engine re-read its
//! skills, commands, agent types and hooks.

use std::path::{Path, PathBuf};

use evo_mcp::ServerConfig;
use evo_plugins::{Installed, Plugin, Store};
use serde_json::{json, Map, Value};
use tauri::{AppHandle, Emitter, Manager};

use crate::mcp::McpState;

fn store() -> Store {
    Store::in_agent_dir(&crate::mcp::agent_dir())
}

async fn blocking<T: Send + 'static>(
    work: impl FnOnce() -> Result<T, String> + Send + 'static,
) -> Result<T, String> {
    tauri::async_runtime::spawn_blocking(work)
        .await
        .map_err(|e| e.to_string())?
}

/// Give the pool the enabled plugins' servers, then tell the UI.
async fn changed(app: &AppHandle) {
    let plugins = tauri::async_runtime::spawn_blocking(|| store().enabled())
        .await
        .unwrap_or_default();
    let servers: Vec<(String, String, ServerConfig)> = plugins
        .iter()
        .flat_map(|plugin| {
            plugin.mcp_servers.iter().filter_map(|(name, config)| {
                serde_json::from_value::<ServerConfig>(config.clone())
                    .ok()
                    .map(|config| (plugin.name.clone(), name.clone(), config))
            })
        })
        .collect();
    if let Some(state) = app.try_state::<McpState>() {
        state.0.set_plugin_servers(servers).await;
    }
    let _ = app.emit("plugins://changed", ());
}

/// Connect the enabled plugins' servers at launch.
pub fn setup(app: &AppHandle) {
    let app = app.clone();
    tauri::async_runtime::spawn(async move { changed(&app).await });
}

fn count_files(dir: &Path, depth: usize, wanted: &dyn Fn(&Path) -> bool) -> usize {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return 0;
    };
    entries
        .flatten()
        .map(|e| e.path())
        .map(|p| {
            if p.is_dir() {
                if depth > 0
                    && p.file_name()
                        .is_some_and(|n| n != ".git" && n != "node_modules")
                {
                    count_files(&p, depth - 1, wanted)
                } else {
                    0
                }
            } else {
                usize::from(wanted(&p))
            }
        })
        .sum()
}

fn names_in(dir: &Path, wanted: &dyn Fn(&Path) -> Option<String>) -> Vec<String> {
    let mut out = Vec::new();
    let Ok(entries) = std::fs::read_dir(dir) else {
        return out;
    };
    for entry in entries.flatten() {
        if let Some(name) = wanted(&entry.path()) {
            out.push(name);
        }
    }
    out.sort();
    out
}

/// What a plugin holds, for its page.
fn describe(installed: &Installed, plugin: &Plugin) -> Value {
    let skills: Vec<String> = plugin
        .skills
        .iter()
        .flat_map(|dir| {
            if dir.join("SKILL.md").is_file() {
                vec![dir
                    .file_name()
                    .map(|n| n.to_string_lossy().into_owned())
                    .unwrap_or_default()]
            } else {
                names_in(dir, &|p| {
                    p.join("SKILL.md")
                        .is_file()
                        .then(|| p.file_name().unwrap().to_string_lossy().into_owned())
                })
            }
        })
        .collect();
    let commands: usize = plugin
        .commands
        .iter()
        .map(|d| count_files(d, 4, &|p| p.extension().is_some_and(|e| e == "md")))
        .sum();
    let agents: Vec<String> = plugin
        .agents
        .iter()
        .flat_map(|p| {
            if p.is_file() {
                vec![p
                    .file_stem()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .into_owned()]
            } else {
                names_in(p, &|f| {
                    (f.extension().is_some_and(|e| e == "md"))
                        .then(|| f.file_stem().unwrap().to_string_lossy().into_owned())
                })
            }
        })
        .collect();
    let hooks: Vec<Value> = plugin
        .hooks
        .iter()
        .map(|(event, groups)| json!({ "event": event, "count": groups.as_array().map_or(0, |g| g.iter().map(|x| x.get("hooks").and_then(Value::as_array).map_or(0, Vec::len)).sum::<usize>()) }))
        .collect();
    json!({
        "id": installed.id,
        "name": plugin.name,
        "marketplace": installed.marketplace,
        "version": installed.version,
        "enabled": installed.enabled,
        "path": installed.path,
        "installedAt": installed.installed_at,
        "config": installed.config,
        "description": plugin.description,
        "author": plugin.author,
        "homepage": plugin.homepage,
        "repository": plugin.repository,
        "license": plugin.license,
        "keywords": plugin.keywords,
        "userConfig": plugin.user_config,
        "skills": skills,
        "commands": commands,
        "agents": agents,
        "hooks": hooks,
        "connectors": plugin.mcp_servers.keys().collect::<Vec<_>>(),
        "bin": plugin.bin.is_some(),
        "problems": plugin.problems,
    })
}

#[tauri::command]
pub async fn plugins_state() -> Result<Value, String> {
    blocking(|| {
        let store = store();
        let installed: Vec<Value> = store.installed().iter().map(|i| describe(i, &store.load(i))).collect();
        let marketplaces: Vec<Value> = store
            .marketplaces()
            .iter()
            .map(|m| {
                json!({
                    "name": m.name,
                    "source": m.source.display(),
                    "kind": match m.source { evo_plugins::MarketplaceSource::Git { .. } => "git", _ => "folder" },
                    "location": m.location,
                    "description": m.description,
                    "owner": m.owner,
                    "updatedAt": m.updated_at,
                    "plugins": m.entries().map(|e| e.len()).unwrap_or(0),
                    "error": m.entries().err(),
                })
            })
            .collect();
        Ok(json!({
            "installed": installed,
            "marketplaces": marketplaces,
            "catalog": store.catalog(),
            "root": store.root(),
        }))
    })
    .await
}

#[tauri::command]
pub async fn plugin_marketplace_add(app: AppHandle, source: String) -> Result<Value, String> {
    let added = blocking(move || store().add_marketplace(&source)).await?;
    changed(&app).await;
    Ok(json!({ "name": added.name }))
}

#[tauri::command]
pub async fn plugin_marketplace_update(app: AppHandle, name: String) -> Result<(), String> {
    blocking(move || store().update_marketplace(&name).map(|_| ())).await?;
    changed(&app).await;
    Ok(())
}

#[tauri::command]
pub async fn plugin_marketplace_remove(app: AppHandle, name: String) -> Result<(), String> {
    blocking(move || store().remove_marketplace(&name)).await?;
    changed(&app).await;
    Ok(())
}

#[tauri::command]
pub async fn plugin_install(
    app: AppHandle,
    marketplace: String,
    name: String,
) -> Result<Value, String> {
    let installed = blocking(move || store().install(&marketplace, &name)).await?;
    changed(&app).await;
    Ok(json!({ "id": installed.id, "version": installed.version }))
}

#[tauri::command]
pub async fn plugin_install_folder(app: AppHandle, path: String) -> Result<Value, String> {
    let installed = blocking(move || store().install_folder(&PathBuf::from(path))).await?;
    changed(&app).await;
    Ok(json!({ "id": installed.id }))
}

#[tauri::command]
pub async fn plugin_uninstall(app: AppHandle, id: String) -> Result<(), String> {
    blocking(move || store().uninstall(&id)).await?;
    changed(&app).await;
    Ok(())
}

#[tauri::command]
pub async fn plugin_update(app: AppHandle, id: String) -> Result<Value, String> {
    let installed = blocking(move || store().update(&id)).await?;
    changed(&app).await;
    Ok(json!({ "id": installed.id, "version": installed.version }))
}

#[tauri::command]
pub async fn plugin_set_enabled(app: AppHandle, id: String, on: bool) -> Result<(), String> {
    blocking(move || store().set_enabled(&id, on)).await?;
    changed(&app).await;
    Ok(())
}

#[tauri::command]
pub async fn plugin_set_config(
    app: AppHandle,
    id: String,
    config: Map<String, Value>,
) -> Result<(), String> {
    blocking(move || store().set_config(&id, config)).await?;
    changed(&app).await;
    Ok(())
}
