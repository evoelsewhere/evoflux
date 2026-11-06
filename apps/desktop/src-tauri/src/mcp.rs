//! Connectors (MCP servers) for every chat: one shared pool (`evo-mcp`) for
//! the whole app, so a server runs once however many chats are open.
//!
//! The pool reads `<agent dir>/mcp.json` (`~/.evo/agent/mcp.json`), connects
//! the enabled servers in the background and emits `mcp://changed` whenever
//! a status, tool list or setting changes; the UI then asks for `mcp_state`
//! again and hands chats `mcp_chat_tools`. Chats call tools through
//! `mcp_call` (the UI asks the person first for tools set to "ask").

use std::path::{Path, PathBuf};

use evo_mcp::{Permission, Pool, ServerConfig};
use serde_json::{Map, Value};
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_opener::OpenerExt;

pub struct McpState(pub Pool);

/// `EVO_CODING_AGENT_DIR`, else `~/.evo/agent` (the engine's agent dir).
pub(crate) fn agent_dir() -> PathBuf {
    if let Some(dir) = std::env::var_os("EVO_CODING_AGENT_DIR").filter(|d| !d.is_empty()) {
        return PathBuf::from(dir);
    }
    let home = std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
        .unwrap_or_default();
    home.join(".evo").join("agent")
}

/// Create the pool and connect the enabled servers.
pub fn setup(app: &AppHandle) {
    let handle = app.clone();
    let home = std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from);
    let pool = Pool::new(agent_dir().join("mcp.json"), home, move || {
        let _ = handle.emit("mcp://changed", ());
    });
    app.manage(McpState(pool.clone()));
    tauri::async_runtime::spawn(async move {
        if let Err(error) = pool.start() {
            eprintln!("[warn] connectors: {error}");
        }
    });
}

/// Close every connection (stdio servers stop with it).
pub fn shutdown(app: &AppHandle) {
    if let Some(state) = app.try_state::<McpState>() {
        let pool = state.0.clone();
        tauri::async_runtime::block_on(async move { pool.shutdown().await });
    }
}

#[tauri::command]
pub fn mcp_state(state: State<'_, McpState>) -> Value {
    state.0.snapshot()
}

#[tauri::command]
pub async fn mcp_upsert(
    state: State<'_, McpState>,
    name: String,
    config: ServerConfig,
    previous: Option<String>,
) -> Result<(), String> {
    state
        .0
        .upsert(name.trim(), config, previous.as_deref())
        .await
}

#[tauri::command]
pub async fn mcp_remove(state: State<'_, McpState>, name: String) -> Result<(), String> {
    state.0.remove(&name).await
}

#[tauri::command]
pub async fn mcp_set_enabled(
    state: State<'_, McpState>,
    name: String,
    on: bool,
) -> Result<(), String> {
    state.0.set_enabled(&name, on).await
}

#[tauri::command]
pub async fn mcp_reconnect(state: State<'_, McpState>, name: String) -> Result<(), String> {
    state.0.connect(&name).await;
    Ok(())
}

#[tauri::command]
pub fn mcp_set_permission(
    state: State<'_, McpState>,
    name: String,
    tool: String,
    permission: Permission,
) -> Result<(), String> {
    state.0.set_permission(&name, &tool, permission)
}

/// The tools a chat in `cwd` gets (`mcp__<server>__<tool>`), with each one's
/// permission: your connectors plus that project's approved servers.
#[tauri::command]
pub fn mcp_chat_tools(state: State<'_, McpState>, cwd: Option<String>) -> Vec<Value> {
    state.0.chat_tools(cwd.as_deref().map(Path::new))
}

#[tauri::command]
pub async fn mcp_call(
    state: State<'_, McpState>,
    name: String,
    arguments: Option<Map<String, Value>>,
    cwd: Option<String>,
) -> Result<Value, String> {
    state
        .0
        .call(&name, arguments, cwd.as_deref().map(Path::new))
        .await
}

/// Sign in to a URL connector: the provider's page opens in the browser;
/// this returns once the browser came back (or after five minutes).
#[tauri::command]
pub async fn mcp_sign_in(
    app: AppHandle,
    state: State<'_, McpState>,
    name: String,
) -> Result<(), String> {
    let pool = state.0.clone();
    pool.sign_in(&name, move |url| {
        let _ = app.opener().open_url(url, None::<&str>);
    })
    .await
}

#[tauri::command]
pub async fn mcp_sign_out(state: State<'_, McpState>, name: String) -> Result<(), String> {
    state.0.sign_out(&name).await
}

/// The `.mcp.json` that applies to `cwd` and your decision on each server.
#[tauri::command]
pub fn mcp_project_state(state: State<'_, McpState>, cwd: String) -> Value {
    state.0.project_state(Path::new(&cwd))
}

/// Connect the approved servers of `cwd`'s project (a chat started there).
#[tauri::command]
pub async fn mcp_open_project(state: State<'_, McpState>, cwd: String) -> Result<(), String> {
    state.0.open_project(Path::new(&cwd)).await
}

#[tauri::command]
pub async fn mcp_set_project_approval(
    state: State<'_, McpState>,
    cwd: String,
    name: String,
    approved: bool,
) -> Result<(), String> {
    state
        .0
        .set_project_approval(Path::new(&cwd), &name, approved)
        .await
}

/// A connector's resource as text (for `@server:uri` in a message).
#[tauri::command]
pub async fn mcp_read_resource(
    state: State<'_, McpState>,
    server: String,
    uri: String,
) -> Result<String, String> {
    state.0.read_resource(&server, &uri).await
}

#[tauri::command]
pub async fn mcp_get_prompt(
    state: State<'_, McpState>,
    server: String,
    prompt: String,
    arguments: Option<Map<String, Value>>,
) -> Result<String, String> {
    state
        .0
        .get_prompt(&server, &prompt, arguments.unwrap_or_default())
        .await
}
