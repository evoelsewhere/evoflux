//! Every configured server, connected once and shared by all chats.
//!
//! The pool reads the connectors file, connects each enabled server in the
//! background and keeps its status (`connecting`, `connected`, `needs-auth`,
//! `failed`, `off`), its tools and prompts, and the last lines of its log.
//! Chats see a connected server's tools as `mcp__<server>__<tool>`; a
//! tool's permission (`allow` / `ask` / `block`) defaults to `allow` for
//! tools the server marks read-only and `ask` for the rest. Every change
//! calls `on_change`, so the host can tell its UI and its chats.

use std::collections::{BTreeMap, VecDeque};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use serde_json::{json, Map, Value};

use crate::auth;
use crate::client::{self, ConnectError, Connection};
use crate::config::{valid_name, ConfigFile, Permission, ServerConfig};

/// Log lines kept per server.
const LOG_LINES: usize = 200;
/// A tool result's text beyond this many characters is cut.
const MAX_RESULT_CHARS: usize = 100_000;
/// Model APIs limit tool names to 64 characters.
const MAX_TOOL_NAME: usize = 64;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Status {
    Off,
    Connecting,
    Connected,
    NeedsAuth,
    Failed,
}

impl Status {
    pub fn as_str(self) -> &'static str {
        match self {
            Status::Off => "off",
            Status::Connecting => "connecting",
            Status::Connected => "connected",
            Status::NeedsAuth => "needs-auth",
            Status::Failed => "failed",
        }
    }
}

struct Entry {
    /// The server's name as people and models see it (tool names use it).
    label: String,
    /// The project root whose `.mcp.json` it comes from; `None`: your own.
    project: Option<String>,
    /// The plugin that brought it; `None`: not a plugin's.
    plugin: Option<String>,
    config: ServerConfig,
    status: Status,
    error: Option<String>,
    tools: Vec<Value>,
    prompts: Vec<Value>,
    resources: Vec<Value>,
    info: Value,
    conn: Option<Arc<Connection>>,
    log: VecDeque<String>,
    /// Bumped on every (re)connect, so a slow old attempt cannot win.
    generation: u64,
}

impl Entry {
    fn new(label: String, config: ServerConfig, project: Option<String>) -> Self {
        Self {
            label,
            project,
            plugin: None,
            resources: Vec::new(),
            status: if config.disabled {
                Status::Off
            } else {
                Status::Connecting
            },
            config,
            error: None,
            tools: Vec::new(),
            prompts: Vec::new(),
            info: Value::Null,
            conn: None,
            log: VecDeque::new(),
            generation: 0,
        }
    }
}

type OnChange = Arc<dyn Fn() + Send + Sync>;

struct Shared {
    path: PathBuf,
    /// Where stdio servers run when their config names no folder.
    cwd: Option<PathBuf>,
    servers: Mutex<BTreeMap<String, Entry>>,
    on_change: OnChange,
}

#[derive(Clone)]
pub struct Pool {
    shared: Arc<Shared>,
}

/// `mcp__<server>__<tool>` with characters models accept, at most 64 long.
pub fn exposed_name(server: &str, tool: &str) -> String {
    let clean = |s: &str| -> String {
        s.chars()
            .map(|c| {
                if c.is_ascii_alphanumeric() || c == '_' || c == '-' {
                    c
                } else {
                    '_'
                }
            })
            .collect()
    };
    let mut name = format!("mcp__{}__{}", clean(server), clean(tool));
    name.truncate(MAX_TOOL_NAME);
    name
}

fn tool_name(tool: &Value) -> &str {
    tool.get("name").and_then(Value::as_str).unwrap_or("")
}

/// `allow` for tools the server marks read-only, else `ask`.
fn default_permission(tool: &Value) -> Permission {
    let read_only = tool
        .pointer("/annotations/readOnlyHint")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if read_only {
        Permission::Allow
    } else {
        Permission::Ask
    }
}

fn permission_of(config: &ServerConfig, tool: &Value) -> Permission {
    config
        .tool_permissions
        .get(tool_name(tool))
        .copied()
        .unwrap_or_else(|| default_permission(tool))
}

/// Cut very long text parts of a tool result, with a note.
fn trim_result(mut result: Value) -> Value {
    if let Some(parts) = result.get_mut("content").and_then(Value::as_array_mut) {
        for part in parts {
            if let Some(text) = part.get_mut("text") {
                if let Some(s) = text.as_str() {
                    if s.chars().count() > MAX_RESULT_CHARS {
                        let cut: String = s.chars().take(MAX_RESULT_CHARS).collect();
                        *text = Value::String(format!("{cut}\n\n[cut: the tool returned more than {MAX_RESULT_CHARS} characters]"));
                    }
                }
            }
        }
    }
    result
}

/// The folder whose `.mcp.json` applies to `cwd`: the nearest one from
/// `cwd` up to the repository root.
pub fn project_root(cwd: &Path) -> Option<PathBuf> {
    for dir in cwd.ancestors() {
        if dir.join(".mcp.json").is_file() {
            return Some(dir.to_path_buf());
        }
        if dir.join(".git").exists() {
            return None;
        }
    }
    None
}

/// A project root as a stable key (forward slashes; lower case on Windows).
fn root_key(root: &Path) -> String {
    let text = root.to_string_lossy().replace('\\', "/");
    if cfg!(windows) {
        text.to_lowercase()
    } else {
        text
    }
}

/// Your own connectors first, then the servers of `root`'s project whose
/// names your own do not take.
fn ordered<'a>(
    servers: &'a BTreeMap<String, Entry>,
    root: Option<&str>,
) -> Vec<(&'a String, &'a Entry)> {
    let mut list: Vec<(&String, &Entry)> = servers
        .iter()
        .filter(|(_, e)| e.project.is_none())
        .collect();
    for (key, entry) in servers.iter() {
        let Some(project) = entry.project.as_deref() else {
            continue;
        };
        if Some(project) == root && !list.iter().any(|(_, e)| e.label == entry.label) {
            list.push((key, entry));
        }
    }
    list
}

/// The pool key of a project server.
fn project_entry_key(label: &str, root: &str) -> String {
    format!("{label}#{root}")
}

impl Pool {
    pub fn new(
        path: PathBuf,
        cwd: Option<PathBuf>,
        on_change: impl Fn() + Send + Sync + 'static,
    ) -> Self {
        Self {
            shared: Arc::new(Shared {
                path,
                cwd,
                servers: Mutex::new(BTreeMap::new()),
                on_change: Arc::new(on_change),
            }),
        }
    }

    pub fn path(&self) -> &Path {
        &self.shared.path
    }

    /// Where sign-in tokens live: `mcp-auth.json` next to the connectors file.
    fn auth_path(&self) -> PathBuf {
        self.shared.path.with_file_name("mcp-auth.json")
    }

    fn changed(&self) {
        (self.shared.on_change)();
    }

    /// Read the file and connect every enabled server (in the background).
    pub fn start(&self) -> Result<(), String> {
        let file = ConfigFile::load(&self.shared.path)?;
        let names: Vec<String> = {
            let mut servers = self.shared.servers.lock().unwrap();
            servers.clear();
            for (name, config) in file.servers {
                servers.insert(name.clone(), Entry::new(name, config, None));
            }
            servers
                .iter()
                .filter(|(_, e)| !e.config.disabled)
                .map(|(n, _)| n.clone())
                .collect()
        };
        self.changed();
        for name in names {
            self.spawn_connect(name);
        }
        Ok(())
    }

    fn spawn_connect(&self, name: String) {
        let pool = self.clone();
        tokio::spawn(async move { pool.connect(&name).await });
    }

    /// (Re)connect `name` now; returns once it is connected or has failed.
    pub async fn connect(&self, name: &str) {
        let (transport, generation, old, disabled) = {
            let mut servers = self.shared.servers.lock().unwrap();
            let Some(entry) = servers.get_mut(name) else {
                return;
            };
            entry.generation += 1;
            let old = entry.conn.take();
            let disabled = entry.config.disabled;
            entry.error = None;
            if disabled {
                entry.status = Status::Off;
                entry.tools.clear();
                entry.prompts.clear();
            } else {
                entry.status = Status::Connecting;
            }
            (entry.config.transport(), entry.generation, old, disabled)
        };
        self.changed();
        if let Some(old) = old.and_then(|c| Arc::try_unwrap(c).ok()) {
            old.close().await;
        }
        if disabled {
            return;
        }
        let transport = match transport {
            Ok(transport) => transport,
            Err(error) => return self.finish(name, generation, Err(ConnectError::Failed(error))),
        };
        let log_pool = self.clone();
        let log_name = name.to_string();
        let log = Arc::new(move |line: String| log_pool.log(&log_name, line));
        // A URL server someone signed in to gets its token (refreshed as needed).
        let auth = match &transport {
            crate::config::Transport::Http { url, .. }
            | crate::config::Transport::Sse { url, .. } => {
                match auth::authorized_client(url, &self.auth_path(), name).await {
                    Ok(client) => client,
                    Err(error) => {
                        self.log(name, format!("[evo] saved sign-in unusable: {error}"));
                        None
                    }
                }
            }
            _ => None,
        };
        let result = client::connect(&transport, self.shared.cwd.as_deref(), log, auth).await;
        let result = match result {
            Ok(conn) => {
                let tools = conn.tools().await;
                let prompts = conn.prompts().await.unwrap_or_default();
                let resources = conn.resources().await.unwrap_or_default();
                match tools {
                    Ok(tools) => Ok((conn, tools, prompts, resources)),
                    Err(error) => Err(ConnectError::Failed(format!("tools/list failed: {error}"))),
                }
            }
            Err(error) => Err(error),
        };
        self.finish(name, generation, result);
    }

    fn finish(
        &self,
        name: &str,
        generation: u64,
        result: Result<(Connection, Vec<Value>, Vec<Value>, Vec<Value>), ConnectError>,
    ) {
        {
            let mut servers = self.shared.servers.lock().unwrap();
            let Some(entry) = servers.get_mut(name) else {
                return;
            };
            if entry.generation != generation {
                return;
            }
            match result {
                Ok((conn, tools, prompts, resources)) => {
                    entry.status = Status::Connected;
                    entry.error = None;
                    entry.info = conn.info.clone();
                    entry.tools = tools;
                    entry.prompts = prompts;
                    entry.resources = resources;
                    entry.conn = Some(Arc::new(conn));
                }
                Err(ConnectError::NeedsAuth(error)) => {
                    entry.status = Status::NeedsAuth;
                    entry.error = Some(error);
                }
                Err(ConnectError::Failed(error)) => {
                    entry.status = Status::Failed;
                    entry.error = Some(error);
                }
            }
        }
        self.changed();
    }

    fn log(&self, name: &str, line: String) {
        let mut servers = self.shared.servers.lock().unwrap();
        if let Some(entry) = servers.get_mut(name) {
            if entry.log.len() >= LOG_LINES {
                entry.log.pop_front();
            }
            entry.log.push_back(line);
        }
    }

    fn save(&self, change: impl FnOnce(&mut ConfigFile)) -> Result<(), String> {
        let mut file = ConfigFile::load(&self.shared.path)?;
        change(&mut file);
        file.save(&self.shared.path)
    }

    /// Add or replace a server (renaming it when `previous` differs) and connect it.
    pub async fn upsert(
        &self,
        name: &str,
        config: ServerConfig,
        previous: Option<&str>,
    ) -> Result<(), String> {
        if !valid_name(name) {
            return Err("the name may use letters, digits, - and _ (at most 48)".into());
        }
        config.transport()?;
        let renamed = previous.filter(|p| *p != name);
        {
            let servers = self.shared.servers.lock().unwrap();
            if servers.contains_key(name) && previous != Some(name) {
                return Err(format!("a connector named `{name}` already exists"));
            }
        }
        self.save(|file| {
            if let Some(old) = renamed {
                file.servers.remove(old);
            }
            file.servers.insert(name.to_string(), config.clone());
        })?;
        let old = {
            let mut servers = self.shared.servers.lock().unwrap();
            let old = renamed.and_then(|old| servers.remove(old));
            let entry = servers
                .entry(name.to_string())
                .or_insert_with(|| Entry::new(name.to_string(), config.clone(), None));
            entry.config = config;
            old
        };
        if let Some(conn) = old
            .and_then(|e| e.conn)
            .and_then(|c| Arc::try_unwrap(c).ok())
        {
            conn.close().await;
        }
        self.connect(name).await;
        Ok(())
    }

    pub async fn remove(&self, name: &str) -> Result<(), String> {
        if self.plugin_of_key(name).is_some() {
            return Err(
                "this connector comes with a plugin: turn the plugin off or remove it".into(),
            );
        }
        if let Some((label, root)) = self.project_key(name) {
            return self.set_project_approval_at(&root, &label, false).await;
        }
        self.save(|file| {
            file.servers.remove(name);
        })?;
        let _ = auth::sign_out(&self.auth_path(), name);
        let entry = self.shared.servers.lock().unwrap().remove(name);
        self.changed();
        if let Some(conn) = entry
            .and_then(|e| e.conn)
            .and_then(|c| Arc::try_unwrap(c).ok())
        {
            conn.close().await;
        }
        Ok(())
    }

    pub async fn set_enabled(&self, name: &str, on: bool) -> Result<(), String> {
        if self.plugin_of_key(name).is_some() {
            return Err("this connector comes with a plugin: turn the plugin off instead".into());
        }
        if let Some((label, root)) = self.project_key(name) {
            return self.set_project_approval_at(&root, &label, on).await;
        }
        self.save(|file| {
            if let Some(server) = file.servers.get_mut(name) {
                server.disabled = !on;
            }
        })?;
        {
            let mut servers = self.shared.servers.lock().unwrap();
            let entry = servers
                .get_mut(name)
                .ok_or_else(|| format!("no connector `{name}`"))?;
            entry.config.disabled = !on;
        }
        self.connect(name).await;
        Ok(())
    }

    /// Sign in to the URL server `name` (`open` shows the provider's page in
    /// the browser), then connect with the new token.
    pub async fn sign_in(&self, name: &str, open: impl FnOnce(String)) -> Result<(), String> {
        let url = {
            let servers = self.shared.servers.lock().unwrap();
            let entry = servers
                .get(name)
                .ok_or_else(|| format!("no connector `{name}`"))?;
            match entry.config.transport()? {
                crate::config::Transport::Http { url, .. }
                | crate::config::Transport::Sse { url, .. } => url,
                _ => return Err("only URL connectors sign in".into()),
            }
        };
        self.log(name, "[evo] signing in…".into());
        let result = auth::sign_in(&url, &self.auth_path(), name, open).await;
        if let Err(error) = &result {
            self.log(name, format!("[evo] sign-in failed: {error}"));
            self.changed();
            return result;
        }
        self.connect(name).await;
        Ok(())
    }

    /// Forget `name`'s sign-in and reconnect without it.
    pub async fn sign_out(&self, name: &str) -> Result<(), String> {
        auth::sign_out(&self.auth_path(), name)?;
        self.connect(name).await;
        Ok(())
    }

    pub fn set_permission(
        &self,
        name: &str,
        tool: &str,
        permission: Permission,
    ) -> Result<(), String> {
        if let Some((plugin, server)) = self.plugin_of_key(name) {
            self.save(|file| {
                let all = file
                    .extra
                    .entry("pluginServers")
                    .or_insert_with(|| json!({}));
                if !all.is_object() {
                    *all = json!({});
                }
                let perms = &mut all[&plugin][&server]["toolPermissions"];
                if !perms.is_object() {
                    *perms = json!({});
                }
                perms[tool] = json!(permission);
            })?;
        } else if let Some((label, root)) = self.project_key(name) {
            self.save_approval(&root, &label, |entry| {
                entry["toolPermissions"][tool] = json!(permission);
            })?;
        } else {
            self.save(|file| {
                if let Some(server) = file.servers.get_mut(name) {
                    server.tool_permissions.insert(tool.to_string(), permission);
                }
            })?;
        }
        {
            let mut servers = self.shared.servers.lock().unwrap();
            let entry = servers
                .get_mut(name)
                .ok_or_else(|| format!("no connector `{name}`"))?;
            entry
                .config
                .tool_permissions
                .insert(tool.to_string(), permission);
        }
        self.changed();
        Ok(())
    }

    /// Every server for the Connectors view.
    pub fn snapshot(&self) -> Value {
        let auth_path = self.auth_path();
        let servers = self.shared.servers.lock().unwrap();
        let list: Vec<Value> = servers
            .iter()
            .map(|(key, entry)| {
                let name = &entry.label;
                let transport = entry.config.transport();
                let kind = match &transport {
                    Ok(crate::config::Transport::Stdio { .. }) => "stdio",
                    Ok(crate::config::Transport::Http { .. }) => "http",
                    Ok(crate::config::Transport::Sse { .. }) => "sse",
                    Err(_) => "invalid",
                };
                let tools: Vec<Value> = entry
                    .tools
                    .iter()
                    .map(|tool| {
                        json!({
                            "name": tool_name(tool),
                            "title": tool.get("title").or_else(|| tool.pointer("/annotations/title")),
                            "description": tool.get("description"),
                            "readOnly": tool.pointer("/annotations/readOnlyHint").and_then(Value::as_bool).unwrap_or(false),
                            "permission": permission_of(&entry.config, tool),
                            "exposedName": exposed_name(name, tool_name(tool)),
                        })
                    })
                    .collect();
                let resources: Vec<Value> = entry
                    .resources
                    .iter()
                    .map(|r| json!({
                        "uri": r.get("uri"),
                        "name": r.get("name"),
                        "description": r.get("description"),
                        "mimeType": r.get("mimeType"),
                    }))
                    .collect();
                json!({
                    "key": key,
                    "name": name,
                    "project": entry.project,
                    "plugin": entry.plugin,
                    "resources": resources,
                    "kind": kind,
                    "summary": entry.config.summary(),
                    "config": entry.config,
                    "status": entry.status.as_str(),
                    "signedIn": kind != "stdio" && auth::signed_in(&auth_path, key),
                    "error": entry.error.clone().or_else(|| transport.err()),
                    "server": entry.info.get("serverInfo").cloned().unwrap_or(Value::Null),
                    "instructions": entry.info.get("instructions").cloned().unwrap_or(Value::Null),
                    "tools": tools,
                    "prompts": entry.prompts,
                    "log": entry.log.iter().collect::<Vec<_>>(),
                })
            })
            .collect();
        json!({ "servers": list, "path": self.shared.path })
    }

    /// The tools a chat working in `cwd` gets: every connected server's tools
    /// but blocked ones — your own connectors, plus the approved servers of
    /// that project's `.mcp.json` (yours win on a name clash) — as
    /// `{name, description, inputSchema, permission, server, tool}`.
    pub fn chat_tools(&self, cwd: Option<&Path>) -> Vec<Value> {
        let root = cwd.and_then(project_root).map(|r| root_key(&r));
        let servers = self.shared.servers.lock().unwrap();
        let mut out = Vec::new();
        for (key, entry) in ordered(&servers, root.as_deref())
            .into_iter()
            .filter(|(_, e)| e.status == Status::Connected)
        {
            let name = &entry.label;
            for tool in &entry.tools {
                let permission = permission_of(&entry.config, tool);
                if permission == Permission::Block {
                    continue;
                }
                let description = tool
                    .get("description")
                    .and_then(Value::as_str)
                    .unwrap_or("");
                out.push(json!({
                    "name": exposed_name(name, tool_name(tool)),
                    "description": format!("[{name}] {description}").trim_end().to_string(),
                    "inputSchema": tool.get("inputSchema").cloned().unwrap_or_else(|| json!({"type": "object"})),
                    "permission": permission,
                    "server": key,
                    "tool": tool_name(tool),
                }));
            }
        }
        out
    }

    /// Which server and tool a chat's tool name stands for.
    fn resolve(
        &self,
        exposed: &str,
        cwd: Option<&Path>,
    ) -> Option<(String, String, Arc<Connection>, Permission)> {
        let root = cwd.and_then(project_root).map(|r| root_key(&r));
        let servers = self.shared.servers.lock().unwrap();
        for (key, entry) in ordered(&servers, root.as_deref()) {
            for tool in &entry.tools {
                if exposed_name(&entry.label, tool_name(tool)) == exposed {
                    let conn = entry.conn.clone()?;
                    return Some((
                        key.clone(),
                        tool_name(tool).to_string(),
                        conn,
                        permission_of(&entry.config, tool),
                    ));
                }
            }
        }
        None
    }

    /// Call a tool by the name chats see. A blocked tool is refused; asking
    /// the person first is the host's job (see `chat_tools`' `permission`).
    pub async fn call(
        &self,
        exposed: &str,
        arguments: Option<Map<String, Value>>,
        cwd: Option<&Path>,
    ) -> Result<Value, String> {
        let (server, tool, conn, permission) = self
            .resolve(exposed, cwd)
            .ok_or_else(|| format!("`{exposed}` is not available (is its connector connected?)"))?;
        if permission == Permission::Block {
            return Err(format!(
                "`{tool}` of {server} is blocked in Customize → Connectors"
            ));
        }
        if conn.is_closed() {
            self.spawn_connect(server.clone());
            return Err(format!(
                "{server} disconnected; reconnecting — try again in a moment"
            ));
        }
        conn.call_tool(&tool, arguments).await.map(trim_result)
    }

    /// A prompt's messages as one text (for the composer's `/server:prompt`).
    pub async fn get_prompt(
        &self,
        server: &str,
        prompt: &str,
        arguments: Map<String, Value>,
    ) -> Result<String, String> {
        let conn = {
            let servers = self.shared.servers.lock().unwrap();
            servers
                .get(server)
                .or_else(|| {
                    servers
                        .values()
                        .find(|e| e.label == server && e.project.is_none())
                })
                .and_then(|e| e.conn.clone())
                .ok_or_else(|| format!("{server} is not connected"))?
        };
        let result = conn.get_prompt(prompt, arguments).await?;
        let texts: Vec<String> = result
            .get("messages")
            .and_then(Value::as_array)
            .map(|messages| {
                messages
                    .iter()
                    .filter_map(|m| {
                        let content = m.get("content")?;
                        let parts = match content {
                            Value::Array(parts) => parts.clone(),
                            other => vec![other.clone()],
                        };
                        let text: Vec<String> = parts
                            .iter()
                            .filter_map(|p| {
                                p.get("text")
                                    .and_then(Value::as_str)
                                    .map(str::to_string)
                                    .or_else(|| {
                                        p.pointer("/resource/text")
                                            .and_then(Value::as_str)
                                            .map(str::to_string)
                                    })
                            })
                            .collect();
                        (!text.is_empty()).then(|| text.join("\n"))
                    })
                    .collect()
            })
            .unwrap_or_default();
        Ok(texts.join("\n\n"))
    }

    /// `(plugin, server)` when `key` names a plugin's server.
    fn plugin_of_key(&self, key: &str) -> Option<(String, String)> {
        let rest = key.strip_prefix("plugin:")?;
        let (plugin, server) = rest.split_once(':')?;
        Some((plugin.to_string(), server.to_string()))
    }

    /// Make the pool's plugin servers exactly `servers` (`(plugin, server,
    /// config)` of the plugins that are on): new ones connect, gone ones
    /// close, changed ones reconnect. Their tools reach every chat as
    /// `mcp__plugin_<plugin>_<server>__<tool>`.
    pub async fn set_plugin_servers(&self, servers: Vec<(String, String, ServerConfig)>) {
        let saved: Map<String, Value> = ConfigFile::load(&self.shared.path)
            .ok()
            .and_then(|f| {
                f.extra
                    .get("pluginServers")
                    .and_then(Value::as_object)
                    .cloned()
            })
            .unwrap_or_default();
        let wanted: Vec<(String, String, String, ServerConfig)> = servers
            .into_iter()
            .map(|(plugin, server, mut config)| {
                config.disabled = false;
                if let Some(perms) = saved
                    .get(&plugin)
                    .and_then(|p| p.get(&server))
                    .and_then(|s| s.get("toolPermissions"))
                    .and_then(Value::as_object)
                {
                    for (tool, p) in perms {
                        if let Ok(p) = serde_json::from_value::<Permission>(p.clone()) {
                            config.tool_permissions.insert(tool.clone(), p);
                        }
                    }
                }
                (
                    format!("plugin:{plugin}:{server}"),
                    format!("plugin_{plugin}_{server}"),
                    plugin,
                    config,
                )
            })
            .collect();
        let (connect, close) = {
            let mut entries = self.shared.servers.lock().unwrap();
            let mut close = Vec::new();
            let stale: Vec<String> = entries
                .iter()
                .filter(|(key, e)| e.plugin.is_some() && !wanted.iter().any(|(k, ..)| k == *key))
                .map(|(key, _)| key.clone())
                .collect();
            for key in stale {
                if let Some(conn) = entries.remove(&key).and_then(|e| e.conn) {
                    close.push(conn);
                }
            }
            let mut connect = Vec::new();
            for (key, label, plugin, config) in wanted {
                let changed = entries.get(&key).is_none_or(|e| e.config != config);
                if changed {
                    let mut entry = Entry::new(label, config, None);
                    entry.plugin = Some(plugin);
                    if let Some(old) = entries.insert(key.clone(), entry).and_then(|e| e.conn) {
                        close.push(old);
                    }
                    connect.push(key);
                }
            }
            (connect, close)
        };
        self.changed();
        for conn in close {
            if let Ok(conn) = Arc::try_unwrap(conn) {
                conn.close().await;
            }
        }
        for key in connect {
            self.spawn_connect(key);
        }
    }

    /// `(label, root)` when `key` names a project server.
    fn project_key(&self, key: &str) -> Option<(String, String)> {
        let servers = self.shared.servers.lock().unwrap();
        let entry = servers.get(key)?;
        Some((entry.label.clone(), entry.project.clone()?))
    }

    /// Change a project server's saved decision (`projectServers[root][name]`
    /// in the connectors file).
    fn save_approval(
        &self,
        root: &str,
        name: &str,
        change: impl FnOnce(&mut Value),
    ) -> Result<(), String> {
        self.save(|file| {
            let all = file
                .extra
                .entry("projectServers")
                .or_insert_with(|| json!({}));
            if !all.is_object() {
                *all = json!({});
            }
            let project = all
                .as_object_mut()
                .unwrap()
                .entry(root.to_string())
                .or_insert_with(|| json!({}));
            if !project.is_object() {
                *project = json!({});
            }
            let entry = project
                .as_object_mut()
                .unwrap()
                .entry(name.to_string())
                .or_insert_with(|| json!({}));
            if !entry.is_object() {
                *entry = json!({});
            }
            if entry.get("toolPermissions").is_none_or(|p| !p.is_object()) {
                entry["toolPermissions"] = json!({});
            }
            change(entry);
        })
    }

    fn approvals(&self, root: &str) -> Map<String, Value> {
        ConfigFile::load(&self.shared.path)
            .ok()
            .and_then(|file| {
                file.extra
                    .get("projectServers")?
                    .get(root)?
                    .as_object()
                    .cloned()
            })
            .unwrap_or_default()
    }

    /// The servers in the `.mcp.json` that applies to `cwd`, each with your
    /// decision: `approved`, `denied` or `pending`.
    pub fn project_state(&self, cwd: &Path) -> Value {
        let Some(root) = project_root(cwd) else {
            return json!({ "root": null, "servers": [] });
        };
        let key = root_key(&root);
        let file = ConfigFile::load(&root.join(".mcp.json"));
        let approvals = self.approvals(&key);
        let servers = self.shared.servers.lock().unwrap();
        let list: Vec<Value> = match &file {
            Ok(file) => file
                .servers
                .iter()
                .map(|(name, config)| {
                    let decision = approvals.get(name).and_then(|a| a.get("approved")).and_then(Value::as_bool);
                    json!({
                        "name": name,
                        "summary": config.summary(),
                        "kind": if config.url.is_some() { "http" } else { "stdio" },
                        "approval": match decision { Some(true) => "approved", Some(false) => "denied", None => "pending" },
                        "key": project_entry_key(name, &key),
                        "shadowed": servers.values().any(|e| e.project.is_none() && &e.label == name),
                    })
                })
                .collect(),
            Err(_) => Vec::new(),
        };
        json!({
            "root": root,
            "file": root.join(".mcp.json"),
            "error": file.err(),
            "servers": list,
        })
    }

    /// Load and connect the approved servers of the project `cwd` is in
    /// (when a chat starts there). Already loaded ones are left alone.
    pub async fn open_project(&self, cwd: &Path) -> Result<(), String> {
        let Some(root) = project_root(cwd) else {
            return Ok(());
        };
        let key = root_key(&root);
        let file = ConfigFile::load(&root.join(".mcp.json"))?;
        let approvals = self.approvals(&key);
        let mut start = Vec::new();
        {
            let mut servers = self.shared.servers.lock().unwrap();
            for (name, config) in file.servers {
                let approval = approvals.get(&name);
                if approval
                    .and_then(|a| a.get("approved"))
                    .and_then(Value::as_bool)
                    != Some(true)
                {
                    continue;
                }
                let entry_key = project_entry_key(&name, &key);
                if servers.contains_key(&entry_key) {
                    continue;
                }
                let mut config = config;
                config.disabled = false;
                if let Some(perms) = approval
                    .and_then(|a| a.get("toolPermissions"))
                    .and_then(Value::as_object)
                {
                    for (tool, p) in perms {
                        if let Ok(p) = serde_json::from_value::<Permission>(p.clone()) {
                            config.tool_permissions.insert(tool.clone(), p);
                        }
                    }
                }
                if config.cwd.is_none() && config.command.is_some() {
                    config.cwd = Some(root.to_string_lossy().into_owned());
                }
                servers.insert(
                    entry_key.clone(),
                    Entry::new(name, config, Some(key.clone())),
                );
                start.push(entry_key);
            }
        }
        if !start.is_empty() {
            self.changed();
        }
        for key in start {
            self.spawn_connect(key);
        }
        Ok(())
    }

    /// Approve (connect) or deny (disconnect) a server of the project `cwd` is in.
    pub async fn set_project_approval(
        &self,
        cwd: &Path,
        name: &str,
        approved: bool,
    ) -> Result<(), String> {
        let root = project_root(cwd).ok_or("no .mcp.json applies to this folder")?;
        self.set_project_approval_at(&root_key(&root), name, approved)
            .await?;
        if approved {
            self.open_project(cwd).await?;
        }
        Ok(())
    }

    async fn set_project_approval_at(
        &self,
        root: &str,
        name: &str,
        approved: bool,
    ) -> Result<(), String> {
        self.save_approval(root, name, |entry| entry["approved"] = json!(approved))?;
        if !approved {
            let entry = self
                .shared
                .servers
                .lock()
                .unwrap()
                .remove(&project_entry_key(name, root));
            self.changed();
            if let Some(conn) = entry
                .and_then(|e| e.conn)
                .and_then(|c| Arc::try_unwrap(c).ok())
            {
                conn.close().await;
            }
        }
        Ok(())
    }

    /// Read one of `server`'s resources: its text parts joined.
    pub async fn read_resource(&self, server: &str, uri: &str) -> Result<String, String> {
        let conn = {
            let servers = self.shared.servers.lock().unwrap();
            servers
                .get(server)
                .or_else(|| {
                    servers
                        .values()
                        .find(|e| e.label == server && e.project.is_none())
                })
                .and_then(|e| e.conn.clone())
                .ok_or_else(|| format!("{server} is not connected"))?
        };
        let result = conn.read_resource(uri).await?;
        let texts: Vec<String> = result
            .get("contents")
            .and_then(Value::as_array)
            .map(|parts| {
                parts
                    .iter()
                    .map(|p| match p.get("text").and_then(Value::as_str) {
                        Some(text) => text.to_string(),
                        None => format!(
                            "[{} content, {} bytes base64]",
                            p.get("mimeType")
                                .and_then(Value::as_str)
                                .unwrap_or("binary"),
                            p.get("blob").and_then(Value::as_str).map_or(0, str::len)
                        ),
                    })
                    .collect()
            })
            .unwrap_or_default();
        let text = texts.join("\n\n");
        Ok(if text.chars().count() > MAX_RESULT_CHARS {
            text.chars().take(MAX_RESULT_CHARS).collect::<String>() + "\n[cut]"
        } else {
            text
        })
    }

    /// Close every connection (the app is quitting).
    pub async fn shutdown(&self) {
        let conns: Vec<Arc<Connection>> = {
            let mut servers = self.shared.servers.lock().unwrap();
            servers.values_mut().filter_map(|e| e.conn.take()).collect()
        };
        for conn in conns {
            if let Ok(conn) = Arc::try_unwrap(conn) {
                conn.close().await;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exposed_names_are_safe_and_short() {
        assert_eq!(
            exposed_name("github", "create_issue"),
            "mcp__github__create_issue"
        );
        assert_eq!(exposed_name("my server", "a.b"), "mcp__my_server__a_b");
        assert_eq!(exposed_name("s", &"x".repeat(100)).len(), 64);
    }

    #[test]
    fn read_only_tools_are_allowed_by_default() {
        let read = json!({"name": "list", "annotations": {"readOnlyHint": true}});
        let write = json!({"name": "delete"});
        assert_eq!(default_permission(&read), Permission::Allow);
        assert_eq!(default_permission(&write), Permission::Ask);
        let mut config = ServerConfig::default();
        config
            .tool_permissions
            .insert("list".into(), Permission::Block);
        assert_eq!(permission_of(&config, &read), Permission::Block);
    }

    #[tokio::test]
    async fn a_bad_server_fails_and_the_config_round_trips() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("mcp.json");
        let changes = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let seen = changes.clone();
        let pool = Pool::new(path.clone(), None, move || {
            seen.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        });
        pool.start().unwrap();
        let config = ServerConfig {
            command: Some("evo-no-such-mcp-server-xyz".into()),
            ..Default::default()
        };
        pool.upsert("broken", config, None).await.unwrap();
        let snap = pool.snapshot();
        assert_eq!(snap["servers"][0]["name"], "broken");
        assert_eq!(snap["servers"][0]["status"], "failed");
        assert!(snap["servers"][0]["error"]
            .as_str()
            .unwrap()
            .contains("could not start"));
        assert!(changes.load(std::sync::atomic::Ordering::SeqCst) > 0);
        // Saved, and turning it off is remembered.
        pool.set_enabled("broken", false).await.unwrap();
        let file = ConfigFile::load(&path).unwrap();
        assert!(file.servers["broken"].disabled);
        assert_eq!(pool.snapshot()["servers"][0]["status"], "off");
        assert!(pool
            .upsert("bad name", ServerConfig::default(), None)
            .await
            .is_err());
        pool.remove("broken").await.unwrap();
        assert!(ConfigFile::load(&path).unwrap().servers.is_empty());
    }

    #[tokio::test]
    async fn project_servers_wait_for_approval_and_stay_in_their_project() {
        let dir = tempfile::tempdir().unwrap();
        let project = dir.path().join("proj");
        std::fs::create_dir_all(project.join("src")).unwrap();
        std::fs::write(
            project.join(".mcp.json"),
            r#"{"mcpServers": {"tooling": {"command": "evo-no-such-mcp-server-xyz"}}}"#,
        )
        .unwrap();
        let pool = Pool::new(dir.path().join("agent").join("mcp.json"), None, || {});
        pool.start().unwrap();
        // Found from a subfolder; pending until approved, and not loaded.
        let state = pool.project_state(&project.join("src"));
        assert_eq!(state["servers"][0]["name"], "tooling");
        assert_eq!(state["servers"][0]["approval"], "pending");
        pool.open_project(&project).await.unwrap();
        assert_eq!(pool.snapshot()["servers"].as_array().unwrap().len(), 0);
        // Approved: loaded (it fails to start here, which is fine), remembered.
        pool.set_project_approval(&project, "tooling", true)
            .await
            .unwrap();
        assert_eq!(
            pool.project_state(&project)["servers"][0]["approval"],
            "approved"
        );
        let snap = pool.snapshot();
        assert_eq!(snap["servers"][0]["name"], "tooling");
        assert!(snap["servers"][0]["project"].is_string());
        // Not offered to chats in other folders (nor here, as it is not connected).
        assert!(pool.chat_tools(Some(dir.path())).is_empty());
        // Denied: unloaded and remembered.
        pool.set_project_approval(&project, "tooling", false)
            .await
            .unwrap();
        assert_eq!(
            pool.project_state(&project)["servers"][0]["approval"],
            "denied"
        );
        assert_eq!(pool.snapshot()["servers"].as_array().unwrap().len(), 0);
        // Outside any project: nothing.
        assert!(pool.project_state(dir.path())["root"].is_null());
    }
}
