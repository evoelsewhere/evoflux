//! Child-process bridge to `evo-engine`, one process per open chat.
//!
//! Every chat runs in its own engine (`evo-engine --mode rpc --session-db
//! <transcripts>/<chat>.db --session-id <chat>`), so chats run in parallel and
//! a crash takes down one chat, not the window. The engine writes the chat's
//! transcript into that file, which no other process writes (ADR 0007), so
//! chats never wait on one another's write lock; reopening a chat starts an
//! engine on the same file and session id.
//!
//! Each stdout line is parsed and emitted as `engine://message`, stderr lines
//! as `engine://stderr` and the exit as `engine://exit`, all tagged with the
//! chat id and the generation of the process (restarting a chat's engine bumps
//! it, so the UI drops events from the old one). Lifecycle, stderr and failed
//! commands also go to the run log.
//!
//! Every stdout line also goes to the session mesh hub (`crate::mesh`), which
//! routes mail between chats' engines whichever window shows them.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::atomic::{AtomicU64, Ordering};

use evo_store::logs::NewLog;
use serde::Serialize;
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager, State};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, Command};
use tokio::sync::Mutex;

use crate::db::Db;

/// Extra engine arguments for development, whitespace separated — for example
/// `--provider anthropic --model claude-sonnet-5` to pin a model.
const ENGINE_ARGS_ENV: &str = "EVO_DESKTOP_ENGINE_ARGS";
/// Absolute path override for the engine binary.
const ENGINE_BIN_ENV: &str = "EVO_ENGINE_BIN";

struct EngineProcess {
    child: Child,
    stdin: ChildStdin,
    generation: u64,
}

#[derive(Default)]
pub struct EngineState {
    processes: Mutex<HashMap<String, EngineProcess>>,
    generation: AtomicU64,
}

#[derive(Clone, Serialize)]
struct ExitPayload<'a> {
    chat: &'a str,
    generation: u64,
    code: Option<i32>,
}

#[derive(Clone, Serialize)]
struct LinePayload<'a> {
    chat: &'a str,
    generation: u64,
    line: String,
}

#[derive(Serialize)]
pub struct EngineInfo {
    binary: String,
    exists: bool,
    extra_args: Vec<String>,
}

/// Where the engine binary lives: an explicit override, then the sidecar next
/// to this executable (Tauri places `externalBin` there, in `tauri dev` and in
/// bundles), then — debug builds only — the engine workspace's build output.
fn engine_binary() -> PathBuf {
    if let Some(path) = std::env::var_os(ENGINE_BIN_ENV) {
        return PathBuf::from(path);
    }
    let file = format!("evo-engine{}", std::env::consts::EXE_SUFFIX);
    let sidecar = std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(|dir| dir.join(&file)));
    if let Some(sidecar) = sidecar.as_ref().filter(|path| path.exists()) {
        return sidecar.clone();
    }
    if cfg!(debug_assertions) {
        let dev = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../target/debug")
            .join(&file);
        if dev.exists() {
            return dev;
        }
    }
    sidecar.unwrap_or_else(|| PathBuf::from(file))
}

/// Settings → Sandbox, as saved under this key (camelCase fields of
/// `evo_tools::sandbox::SandboxConfig`).
pub const SANDBOX_KEY: &str = "sandbox";

/// What a chat's engine runs with when nothing is saved yet.
pub fn sandbox_defaults() -> Value {
    json!({
        "inheritEnv": true,
        "loadProfile": false,
        "maxTimeoutSecs": 600,
        "maxOutputKib": 50,
        "deniedPatterns": ["**/.env", "**/.env.*"],
        "worktreeLocation": "userData",
    })
}

/// The saved sandbox settings over the defaults, for `--sandbox-config`.
fn sandbox_config(db: &Db) -> Value {
    let mut config = sandbox_defaults();
    let saved = db
        .with(|conn| evo_store::settings::all(conn))
        .ok()
        .and_then(|settings| settings.get(SANDBOX_KEY).cloned());
    if let (Some(Value::Object(saved)), Value::Object(config)) = (saved, &mut config) {
        for (key, value) in saved {
            config.insert(key, value);
        }
    }
    config
}

fn extra_args() -> Vec<String> {
    std::env::var(ENGINE_ARGS_ENV)
        .map(|value| value.split_whitespace().map(str::to_owned).collect())
        .unwrap_or_default()
}

/// A stderr line's level, by the words engines and Rust's tracing use.
fn stderr_level(line: &str) -> &'static str {
    let lower = line.to_ascii_lowercase();
    if lower.contains("panicked") || lower.contains("error") {
        "error"
    } else if lower.contains("warn") {
        "warn"
    } else {
        "info"
    }
}

/// How a run ended, for an `agent_end` that carries no outcome: the run's
/// last assistant message says (`stopReason` `aborted` when it was stopped,
/// also while a tool ran; `error` when the model failed).
fn run_end_outcome(message: &Value) -> &'static str {
    if message.get("aborted") == Some(&Value::Bool(true)) {
        return "aborted";
    }
    let last = message
        .get("messages")
        .and_then(Value::as_array)
        .and_then(|messages| messages.iter().rev().find(|m| m.get("role").and_then(Value::as_str) == Some("assistant")));
    match last.and_then(|m| m.get("stopReason")).and_then(Value::as_str) {
        Some("aborted") => "aborted",
        Some("error") => "failed",
        _ => "completed",
    }
}

/// The protocol events worth keeping in the run log.
fn log_message(db: &Db, chat: &str, message: &Value) {
    let kind = message.get("type").and_then(Value::as_str).unwrap_or("");
    let entry = match kind {
        "response" if message.get("success") == Some(&Value::Bool(false)) => NewLog::new(
            "warn",
            "engine",
            format!(
                "{} failed: {}",
                message.get("command").and_then(Value::as_str).unwrap_or("command"),
                message.get("error").and_then(Value::as_str).unwrap_or("unknown error")
            ),
        ),
        "ready" => NewLog::new("info", "engine", "ready"),
        "agent_start" => NewLog::new("debug", "engine", "run started"),
        "agent_end" => {
            let outcome = message.get("outcome").and_then(Value::as_str).unwrap_or_else(|| run_end_outcome(message));
            let level = if outcome == "failed" { "error" } else { "info" };
            let mut entry = NewLog::new(level, "engine", format!("run {outcome}"));
            if let Some(error) = message.get("error").filter(|e| !e.is_null()) {
                entry = entry.data(json!({ "error": error }));
            }
            entry
        }
        "message_end" => {
            let msg = message.get("message");
            if msg.and_then(|m| m.get("stopReason")).and_then(Value::as_str) != Some("error") {
                return;
            }
            NewLog::new(
                "error",
                "provider",
                msg.and_then(|m| m.get("errorMessage"))
                    .and_then(Value::as_str)
                    .unwrap_or("the model returned an error")
                    .to_string(),
            )
            .data(json!({
                "provider": msg.and_then(|m| m.get("provider")),
                "model": msg.and_then(|m| m.get("model")),
            }))
        }
        "auto_retry_start" | "auto_compaction_start" | "providers_changed" | "extension_error" => {
            let level = if kind == "extension_error" { "error" } else { "info" };
            NewLog::new(level, "engine", kind.replace('_', " ")).data(message.clone())
        }
        _ => return,
    };
    db.log(entry.chat(Some(chat)));
}

#[tauri::command]
pub fn engine_info() -> EngineInfo {
    let binary = engine_binary();
    EngineInfo {
        exists: binary.exists(),
        binary: binary.display().to_string(),
        extra_args: extra_args(),
    }
}

/// The chats whose engine is running.
#[tauri::command]
pub async fn engine_running(state: State<'_, EngineState>) -> Result<Vec<String>, String> {
    Ok(state.running().await)
}

/// Start (or restart) the engine of `chat` with `cwd` as the project
/// directory. Returns the generation number; events from older generations
/// are stale and the UI ignores them.
#[tauri::command]
pub async fn engine_start(
    app: AppHandle,
    state: State<'_, EngineState>,
    db: State<'_, Db>,
    chat: String,
    cwd: Option<String>,
) -> Result<u64, String> {
    let mut processes = state.processes.lock().await;
    if let Some(mut old) = processes.remove(&chat) {
        let _ = old.child.kill().await;
        db.log(NewLog::new("info", "shell", "engine restarted").chat(Some(&chat)));
    }
    // Nothing of an older process is ready for mail or waiting on an answer.
    app.state::<crate::mesh::MeshHub>().0.on_start(&chat);
    let generation = state.generation.fetch_add(1, Ordering::Relaxed) + 1;

    let binary = engine_binary();
    if !binary.exists() {
        let error = format!(
            "engine binary not found at {} — build it with `cargo build -p evo-engine` or set {ENGINE_BIN_ENV}",
            binary.display()
        );
        db.log(NewLog::new("error", "shell", error.clone()).chat(Some(&chat)));
        return Err(error);
    }
    // After the old process is gone: moving a transcript left in evo.db by
    // an older build may set aside a file it had open.
    let transcript = db.transcript_for_engine(&chat).inspect_err(|error| {
        db.log(NewLog::new("error", "shell", error.clone()).chat(Some(&chat)));
    })?;

    let mut command = Command::new(&binary);
    command
        .args(["--mode", "rpc", "--session-id", &chat])
        .arg("--session-db")
        .arg(&transcript)
        // Process security for the chat's shell and file tools (Settings → Sandbox).
        .arg("--sandbox-config")
        .arg(sandbox_config(&db).to_string())
        .args(extra_args())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    if let Some(dir) = cwd.as_deref().filter(|dir| !dir.is_empty()) {
        command.current_dir(dir);
    }
    // Lets the engine's shell tools recognise a command that would kill this
    // app (and with it every chat) and ask before running it.
    command.env("EVO_HOST_PID", std::process::id().to_string());
    if let Some(name) = std::env::current_exe()
        .ok()
        .and_then(|exe| exe.file_name().map(|name| name.to_string_lossy().into_owned()))
    {
        command.env("EVO_HOST_EXE", name);
    }
    #[cfg(windows)]
    {
        // Do not flash a console window for the child process.
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }

    let mut child = command.spawn().map_err(|error| {
        let message = format!("could not start {}: {error}", binary.display());
        db.log(NewLog::new("error", "shell", message.clone()).chat(Some(&chat)));
        message
    })?;
    db.log(
        NewLog::new("info", "shell", "engine started")
            .chat(Some(&chat))
            .data(json!({
                "pid": child.id(),
                "generation": generation,
                "cwd": cwd,
                "binary": binary.display().to_string(),
                "running": processes.len() + 1,
            })),
    );
    let stdin = child.stdin.take().ok_or("engine stdin unavailable")?;
    let stdout = child.stdout.take().ok_or("engine stdout unavailable")?;
    let stderr = child.stderr.take().ok_or("engine stderr unavailable")?;

    let out_app = app.clone();
    let out_chat = chat.clone();
    tauri::async_runtime::spawn(async move {
        let mut lines = BufReader::new(stdout).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            if line.trim().is_empty() {
                continue;
            }
            match serde_json::from_str::<Value>(&line) {
                Ok(message) => {
                    log_message(&out_app.state::<Db>(), &out_chat, &message);
                    let _ = out_app.emit(
                        "engine://message",
                        json!({ "chat": out_chat, "generation": generation, "message": message }),
                    );
                    crate::mesh::on_line(&out_app, &out_chat, &message).await;
                }
                Err(_) => {
                    out_app
                        .state::<Db>()
                        .log(NewLog::new(stderr_level(&line), "engine", line.clone()).chat(Some(&out_chat)));
                    let _ = out_app.emit(
                        "engine://stderr",
                        LinePayload { chat: &out_chat, generation, line },
                    );
                }
            }
        }
    });

    let err_app = app.clone();
    let err_chat = chat.clone();
    tauri::async_runtime::spawn(async move {
        let mut lines = BufReader::new(stderr).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            if line.trim().is_empty() {
                continue;
            }
            err_app
                .state::<Db>()
                .log(NewLog::new(stderr_level(&line), "engine", line.clone()).chat(Some(&err_chat)));
            let _ = err_app.emit(
                "engine://stderr",
                LinePayload { chat: &err_chat, generation, line },
            );
        }
    });

    processes.insert(
        chat.clone(),
        EngineProcess {
            child,
            stdin,
            generation,
        },
    );
    drop(processes);

    // Report the exit of this generation once it happens.
    let exit_app = app.clone();
    tauri::async_runtime::spawn(async move {
        loop {
            tokio::time::sleep(std::time::Duration::from_millis(250)).await;
            let state = exit_app.state::<EngineState>();
            let mut processes = state.processes.lock().await;
            let Some(process) = processes.get_mut(&chat) else {
                // Stopped on purpose: its mail waits for the next start.
                drop(processes);
                crate::mesh::on_exit(&exit_app, &chat).await;
                break;
            };
            if process.generation != generation {
                break;
            }
            if let Ok(Some(status)) = process.child.try_wait() {
                processes.remove(&chat);
                drop(processes);
                crate::mesh::on_exit(&exit_app, &chat).await;
                let code = status.code();
                exit_app.state::<Db>().log(
                    NewLog::new(if code == Some(0) { "info" } else { "error" }, "shell", "engine exited")
                        .chat(Some(&chat))
                        .data(json!({ "code": code, "generation": generation })),
                );
                let _ = exit_app.emit(
                    "engine://exit",
                    ExitPayload { chat: &chat, generation, code },
                );
                break;
            }
        }
    });

    Ok(generation)
}

/// Write one protocol command to `chat`'s engine as a JSON line.
#[tauri::command]
pub async fn engine_send(state: State<'_, EngineState>, chat: String, message: Value) -> Result<(), String> {
    state.write(&chat, &message).await
}

impl EngineState {
    /// Write `message` to `chat`'s engine as one JSON line.
    pub async fn write(&self, chat: &str, message: &Value) -> Result<(), String> {
        let mut processes = self.processes.lock().await;
        let process = processes.get_mut(chat).ok_or("engine is not running")?;
        let mut line = serde_json::to_vec(message).map_err(|error| error.to_string())?;
        line.push(b'\n');
        process
            .stdin
            .write_all(&line)
            .await
            .map_err(|error| format!("engine write failed: {error}"))?;
        process
            .stdin
            .flush()
            .await
            .map_err(|error| format!("engine write failed: {error}"))
    }

    /// The chats whose engine runs now.
    pub async fn running(&self) -> Vec<String> {
        self.processes.lock().await.keys().cloned().collect()
    }

    /// Kill `chat`'s engine if it runs; true when there was one.
    pub async fn stop(&self, chat: &str) -> bool {
        match self.processes.lock().await.remove(chat) {
            Some(mut process) => {
                let _ = process.child.kill().await;
                true
            }
            None => false,
        }
    }
}

/// Stop `chat`'s engine (no exit event follows: the UI asked for it).
#[tauri::command]
pub async fn engine_stop(
    state: State<'_, EngineState>,
    db: State<'_, Db>,
    chat: String,
) -> Result<(), String> {
    if state.stop(&chat).await {
        db.log(NewLog::new("info", "shell", "engine stopped").chat(Some(&chat)));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_run_stopped_while_a_tool_ran_is_logged_as_aborted() {
        let end = |stop: &str| {
            json!({ "type": "agent_end", "messages": [
                { "role": "assistant", "stopReason": "toolUse" },
                { "role": "toolResult" },
                { "role": "assistant", "stopReason": stop },
            ]})
        };
        assert_eq!(run_end_outcome(&end("aborted")), "aborted");
        assert_eq!(run_end_outcome(&end("error")), "failed");
        assert_eq!(run_end_outcome(&end("stop")), "completed");
        assert_eq!(run_end_outcome(&json!({ "type": "agent_end", "aborted": true })), "aborted");
        assert_eq!(run_end_outcome(&json!({ "type": "agent_end" })), "completed");
    }
}
