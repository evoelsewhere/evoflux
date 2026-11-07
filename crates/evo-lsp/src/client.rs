//! A small Language Server Protocol client over stdio: requests and
//! responses, the server's own requests answered with defaults, published
//! diagnostics and work-done progress (so callers can wait for indexing).

use std::collections::{HashMap, HashSet, VecDeque};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicI64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::process::Child;
use tokio::sync::{mpsc, oneshot, Notify};
use url::Url;

use crate::catalog::Server;

const REQUEST_TIMEOUT: Duration = Duration::from_secs(60);

pub fn uri_of(path: &Path) -> String {
    Url::from_file_path(path)
        .map(|u| u.to_string())
        .unwrap_or_else(|_| format!("file://{}", path.display()))
}

/// One spelling per file: servers write the same file as `file:///C:/a` or
/// `file:///c%3A/a`.
pub fn uri_key(uri: &str) -> String {
    match path_of(uri) {
        Some(path) if cfg!(windows) => path.to_string_lossy().to_lowercase(),
        Some(path) => path.to_string_lossy().into_owned(),
        None => uri.to_string(),
    }
}

pub fn path_of(uri: &str) -> Option<PathBuf> {
    Url::parse(uri).ok()?.to_file_path().ok()
}

struct Open {
    version: i64,
    text: String,
}

pub struct Client {
    pub server: &'static Server,
    pub root: PathBuf,
    /// Frames to write; one task owns the server's stdin.
    writer: mpsc::UnboundedSender<Vec<u8>>,
    child: Mutex<Option<Child>>,
    next_id: AtomicI64,
    pending: Mutex<HashMap<i64, oneshot::Sender<Result<Value, String>>>>,
    /// uri → (version the server reported, diagnostics, when they arrived).
    diagnostics: Mutex<HashMap<String, (Option<i64>, Vec<Value>, Instant, String)>>,
    diagnostics_changed: Notify,
    progress: Mutex<HashSet<String>>,
    progress_changed: Notify,
    /// Any work-done progress began since start.
    progress_seen: AtomicBool,
    /// rust-analyzer's `experimental/serverStatus`: idle when `true`.
    quiescent: Mutex<Option<bool>>,
    started: Instant,
    open: tokio::sync::Mutex<HashMap<String, Open>>,
    alive: AtomicBool,
    stderr: Mutex<VecDeque<String>>,
    pub capabilities: Mutex<Value>,
}

impl Client {
    /// Start `binary` for `server` in `root` and initialize it.
    pub async fn start(
        server: &'static Server,
        binary: &Path,
        env: Vec<(String, String)>,
        root: &Path,
    ) -> Result<Arc<Client>, String> {
        let mut cmd = tokio::process::Command::new(binary);
        cmd.args(server.args)
            .current_dir(root)
            .envs(env)
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .kill_on_drop(true);
        #[cfg(windows)]
        {
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }
        let mut child = cmd
            .spawn()
            .map_err(|e| format!("{} could not start: {e}", server.name))?;
        let mut stdin = child.stdin.take().ok_or("no stdin")?;
        let (writer, mut frames) = mpsc::unbounded_channel::<Vec<u8>>();
        let stdout = child.stdout.take().ok_or("no stdout")?;
        let stderr = child.stderr.take();
        let client = Arc::new(Client {
            server,
            root: root.to_path_buf(),
            writer,
            child: Mutex::new(Some(child)),
            next_id: AtomicI64::new(1),
            pending: Mutex::new(HashMap::new()),
            diagnostics: Mutex::new(HashMap::new()),
            diagnostics_changed: Notify::new(),
            progress: Mutex::new(HashSet::new()),
            progress_changed: Notify::new(),
            progress_seen: AtomicBool::new(false),
            quiescent: Mutex::new(None),
            started: Instant::now(),
            open: tokio::sync::Mutex::new(HashMap::new()),
            alive: AtomicBool::new(true),
            stderr: Mutex::new(VecDeque::new()),
            capabilities: Mutex::new(Value::Null),
        });
        tokio::spawn(read_loop(Arc::downgrade(&client), stdout));
        {
            let weak = Arc::downgrade(&client);
            tokio::spawn(async move {
                while let Some(frame) = frames.recv().await {
                    if stdin.write_all(&frame).await.is_err() || stdin.flush().await.is_err() {
                        if let Some(c) = weak.upgrade() {
                            c.alive.store(false, Ordering::Release);
                        }
                        break;
                    }
                }
            });
        }
        if let Some(stderr) = stderr {
            let weak = Arc::downgrade(&client);
            tokio::spawn(async move {
                let mut lines = BufReader::new(stderr).lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    let Some(client) = weak.upgrade() else { break };
                    let mut tail = client.stderr.lock().unwrap();
                    tail.push_back(line);
                    if tail.len() > 30 {
                        tail.pop_front();
                    }
                }
            });
        }
        let root_uri = uri_of(root);
        let name = root
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_default();
        let init_options: Value = server
            .init_options
            .and_then(|o| serde_json::from_str(o).ok())
            .unwrap_or(Value::Null);
        let result = client
            .request(
                "initialize",
                json!({
                    "processId": std::process::id(),
                    "clientInfo": { "name": "evo", "version": env!("CARGO_PKG_VERSION") },
                    "rootUri": root_uri,
                    "rootPath": root,
                    "workspaceFolders": [{ "uri": root_uri, "name": name }],
                    "initializationOptions": init_options,
                    "capabilities": {
                        "general": { "positionEncodings": ["utf-16"] },
                        "textDocument": {
                            "synchronization": { "didSave": true, "dynamicRegistration": false },
                            "publishDiagnostics": { "relatedInformation": false, "versionSupport": true },
                            "definition": { "linkSupport": true },
                            "typeDefinition": { "linkSupport": true },
                            "implementation": { "linkSupport": true },
                            "references": {},
                            "hover": { "contentFormat": ["markdown", "plaintext"] },
                            "documentSymbol": { "hierarchicalDocumentSymbolSupport": true }
                        },
                        "workspace": {
                            "configuration": true,
                            "workspaceFolders": true,
                            "symbol": {}
                        },
                        "window": { "workDoneProgress": true },
                        "experimental": { "serverStatusNotification": true }
                    }
                }),
                Duration::from_secs(90),
            )
            .await
            .map_err(|e| format!("{} did not initialize: {e}", server.name))?;
        *client.capabilities.lock().unwrap() =
            result.get("capabilities").cloned().unwrap_or(Value::Null);
        client.notify("initialized", json!({})).await?;
        Ok(client)
    }

    pub fn alive(&self) -> bool {
        self.alive.load(Ordering::Acquire)
    }

    /// The server's last stderr lines, for error messages.
    pub fn stderr_tail(&self) -> String {
        self.stderr
            .lock()
            .unwrap()
            .iter()
            .cloned()
            .collect::<Vec<_>>()
            .join("\n")
    }

    fn write(&self, message: &Value) -> Result<(), String> {
        let body = serde_json::to_string(message).map_err(|e| e.to_string())?;
        let frame = format!("Content-Length: {}\r\n\r\n{body}", body.len());
        self.writer
            .send(frame.into_bytes())
            .map_err(|_| format!("{} stopped", self.server.name))
    }

    pub async fn notify(&self, method: &str, params: Value) -> Result<(), String> {
        self.write(&json!({ "jsonrpc": "2.0", "method": method, "params": params }))
    }

    pub async fn request(
        &self,
        method: &str,
        params: Value,
        timeout: Duration,
    ) -> Result<Value, String> {
        if !self.alive() {
            return Err(format!("{} is not running", self.server.name));
        }
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let (tx, rx) = oneshot::channel();
        self.pending.lock().unwrap().insert(id, tx);
        if let Err(e) =
            self.write(&json!({ "jsonrpc": "2.0", "id": id, "method": method, "params": params }))
        {
            self.pending.lock().unwrap().remove(&id);
            return Err(e);
        }
        match tokio::time::timeout(timeout, rx).await {
            Ok(Ok(result)) => result,
            Ok(Err(_)) => Err(format!(
                "{} stopped while answering {method}",
                self.server.name
            )),
            Err(_) => {
                self.pending.lock().unwrap().remove(&id);
                let _ = self.notify("$/cancelRequest", json!({ "id": id })).await;
                Err(format!(
                    "{} did not answer {method} within {}s",
                    self.server.name,
                    timeout.as_secs()
                ))
            }
        }
    }

    pub async fn request_default(&self, method: &str, params: Value) -> Result<Value, String> {
        self.request(method, params, REQUEST_TIMEOUT).await
    }

    /// Open `path` (or send its new text when it changed). Returns its uri and
    /// the version sent.
    pub async fn sync_file(&self, path: &Path) -> Result<(String, i64), String> {
        let text = tokio::fs::read_to_string(path)
            .await
            .map_err(|e| format!("could not read {}: {e}", path.display()))?;
        let uri = uri_of(path);
        let mut open = self.open.lock().await;
        match open.get_mut(&uri) {
            Some(doc) if doc.text == text => Ok((uri, doc.version)),
            Some(doc) => {
                doc.version += 1;
                doc.text = text.clone();
                let version = doc.version;
                drop(open);
                self.notify(
                    "textDocument/didChange",
                    json!({ "textDocument": { "uri": uri, "version": version }, "contentChanges": [{ "text": text }] }),
                )
                .await?;
                self.notify(
                    "textDocument/didSave",
                    json!({ "textDocument": { "uri": uri } }),
                )
                .await?;
                Ok((uri, version))
            }
            None => {
                let ext = if path.file_name().is_some_and(|n| {
                    n.to_string_lossy()
                        .to_ascii_lowercase()
                        .starts_with("dockerfile")
                }) {
                    "dockerfile".to_string()
                } else {
                    path.extension()
                        .map(|e| e.to_string_lossy().into_owned())
                        .unwrap_or_default()
                };
                let language = self.server.language_id(&ext).unwrap_or("plaintext");
                open.insert(
                    uri.clone(),
                    Open {
                        version: 1,
                        text: text.clone(),
                    },
                );
                drop(open);
                self.notify(
                    "textDocument/didOpen",
                    json!({ "textDocument": { "uri": uri, "languageId": language, "version": 1, "text": text } }),
                )
                .await?;
                // Servers that check on save (rust-analyzer runs `cargo check`)
                // report their full diagnostics after a save.
                self.notify(
                    "textDocument/didSave",
                    json!({ "textDocument": { "uri": uri } }),
                )
                .await?;
                Ok((uri, 1))
            }
        }
    }

    /// The text last sent for `uri`.
    pub async fn text_of(&self, uri: &str) -> Option<String> {
        self.open.lock().await.get(uri).map(|d| d.text.clone())
    }

    pub fn indexing(&self) -> bool {
        !self.progress.lock().unwrap().is_empty() || *self.quiescent.lock().unwrap() == Some(false)
    }

    /// Wait until no work-done progress is running (indexing), up to `max`.
    /// Just after start, it first gives the server a moment to begin: a
    /// request sent before indexing starts would find nothing.
    pub async fn wait_idle(&self, max: Duration) -> bool {
        let deadline = Instant::now() + max;
        const WARMUP: Duration = Duration::from_secs(5);
        while !self.progress_seen.load(Ordering::Acquire)
            && self.quiescent.lock().unwrap().is_none()
            && self.started.elapsed() < WARMUP
            && self.alive()
        {
            let _ =
                tokio::time::timeout(Duration::from_millis(200), self.progress_changed.notified())
                    .await;
        }
        loop {
            if !self.indexing() {
                return true;
            }
            let left = deadline.saturating_duration_since(Instant::now());
            if left.is_zero() {
                return false;
            }
            let _ = tokio::time::timeout(
                left.min(Duration::from_millis(500)),
                self.progress_changed.notified(),
            )
            .await;
        }
    }

    /// Diagnostics for `uri` at `version` (or newer), waiting up to `max`;
    /// `None` when none arrived in time.
    pub async fn diagnostics_for(
        &self,
        uri: &str,
        version: i64,
        sent_at: Instant,
        max: Duration,
    ) -> Option<Vec<Value>> {
        let deadline = Instant::now() + max;
        loop {
            if let Some((v, list, at, _)) = self.diagnostics.lock().unwrap().get(&uri_key(uri)) {
                let fresh = match v {
                    Some(v) => *v >= version,
                    None => *at >= sent_at,
                };
                if fresh {
                    return Some(list.clone());
                }
            }
            let left = deadline.saturating_duration_since(Instant::now());
            if left.is_zero() {
                return None;
            }
            let _ = tokio::time::timeout(
                left.min(Duration::from_millis(300)),
                self.diagnostics_changed.notified(),
            )
            .await;
        }
    }

    /// The last diagnostics for every file the server reported on.
    pub fn all_diagnostics(&self) -> Vec<(String, Vec<Value>)> {
        self.diagnostics
            .lock()
            .unwrap()
            .values()
            .filter(|(_, list, _, _)| !list.is_empty())
            .map(|(_, list, _, uri)| (uri.clone(), list.clone()))
            .collect()
    }

    pub async fn shutdown(&self) {
        if self.alive() {
            let _ = self
                .request("shutdown", Value::Null, Duration::from_secs(3))
                .await;
            let _ = self.notify("exit", Value::Null).await;
        }
        self.alive.store(false, Ordering::Release);
        if let Some(mut child) = self.child.lock().unwrap().take() {
            let _ = child.start_kill();
        }
    }

    fn handle(&self, message: Value) {
        let method = message
            .get("method")
            .and_then(Value::as_str)
            .map(str::to_string);
        let id = message.get("id").cloned();
        match (method, id) {
            // A response to one of our requests.
            (None, Some(id)) => {
                let Some(id) = id.as_i64() else { return };
                if let Some(tx) = self.pending.lock().unwrap().remove(&id) {
                    let result = match message.get("error") {
                        Some(error) => Err(error
                            .get("message")
                            .and_then(Value::as_str)
                            .unwrap_or("error")
                            .to_string()),
                        None => Ok(message.get("result").cloned().unwrap_or(Value::Null)),
                    };
                    let _ = tx.send(result);
                }
            }
            // The server asks us something: answer with defaults.
            (Some(method), Some(id)) => {
                let params = message.get("params").cloned().unwrap_or(Value::Null);
                let result = match method.as_str() {
                    "workspace/configuration" => {
                        let n = params
                            .get("items")
                            .and_then(Value::as_array)
                            .map_or(1, Vec::len);
                        Value::Array(vec![Value::Null; n])
                    }
                    "workspace/workspaceFolders" => json!([{
                        "uri": uri_of(&self.root),
                        "name": self.root.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default()
                    }]),
                    _ => Value::Null,
                };
                let _ = self.write(&json!({ "jsonrpc": "2.0", "id": id, "result": result }));
            }
            // A notification.
            (Some(method), None) => {
                let params = message.get("params").cloned().unwrap_or(Value::Null);
                match method.as_str() {
                    "textDocument/publishDiagnostics" => {
                        let uri = params
                            .get("uri")
                            .and_then(Value::as_str)
                            .unwrap_or("")
                            .to_string();
                        let version = params.get("version").and_then(Value::as_i64);
                        let list = params
                            .get("diagnostics")
                            .and_then(Value::as_array)
                            .cloned()
                            .unwrap_or_default();
                        self.diagnostics
                            .lock()
                            .unwrap()
                            .insert(uri_key(&uri), (version, list, Instant::now(), uri));
                        self.diagnostics_changed.notify_waiters();
                    }
                    "$/progress" => {
                        let token = params
                            .get("token")
                            .map(|t| t.to_string())
                            .unwrap_or_default();
                        match params.pointer("/value/kind").and_then(Value::as_str) {
                            Some("begin") => {
                                self.progress.lock().unwrap().insert(token);
                                self.progress_seen.store(true, Ordering::Release);
                                self.progress_changed.notify_waiters();
                            }
                            Some("end") => {
                                self.progress.lock().unwrap().remove(&token);
                                self.progress_changed.notify_waiters();
                            }
                            _ => {}
                        }
                    }
                    // rust-analyzer says when it has nothing left to do.
                    "experimental/serverStatus" => {
                        let quiescent = params.get("quiescent").and_then(Value::as_bool);
                        *self.quiescent.lock().unwrap() = quiescent;
                        self.progress_changed.notify_waiters();
                    }
                    _ => {}
                }
            }
            (None, None) => {}
        }
    }
}

async fn read_loop(client: std::sync::Weak<Client>, stdout: tokio::process::ChildStdout) {
    let mut reader = BufReader::new(stdout);
    loop {
        let mut length: Option<usize> = None;
        loop {
            let mut line = String::new();
            match reader.read_line(&mut line).await {
                Ok(0) | Err(_) => {
                    if let Some(c) = client.upgrade() {
                        c.alive.store(false, Ordering::Release);
                        for (_, tx) in c.pending.lock().unwrap().drain() {
                            let _ = tx.send(Err(format!("{} stopped", c.server.name)));
                        }
                        c.progress.lock().unwrap().clear();
                        c.progress_changed.notify_waiters();
                    }
                    return;
                }
                Ok(_) => {}
            }
            let line = line.trim_end();
            if line.is_empty() {
                break;
            }
            if let Some(value) = line.strip_prefix("Content-Length:") {
                length = value.trim().parse().ok();
            }
        }
        let Some(length) = length else { continue };
        let mut body = vec![0u8; length];
        if reader.read_exact(&mut body).await.is_err() {
            continue;
        }
        let Ok(message) = serde_json::from_slice::<Value>(&body) else {
            continue;
        };
        let Some(c) = client.upgrade() else { return };
        c.handle(message);
    }
}
