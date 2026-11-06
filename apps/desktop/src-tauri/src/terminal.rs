//! Side panel terminal: one pseudo-terminal per tab (ConPTY on Windows, a
//! Unix pty elsewhere) running the user's shell in the workspace folder.
//!
//! The web UI renders with xterm.js. Output goes to the window over a Tauri
//! [`Channel`] as UTF-8 text (a chunk split inside a multi-byte character waits
//! for the rest); keystrokes come back through `terminal_write`, queued to a
//! writer thread so a slow child never blocks the main thread and keys stay in
//! order. Each session keeps the tail of its output so a reloaded window can
//! re-attach (`terminal_list` + `terminal_attach`) instead of losing its
//! shells. A session belongs to the window that started it: closing the window
//! kills its shells.

use std::collections::HashMap;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::mpsc::{self, Sender};
use std::sync::{Arc, Mutex};

use portable_pty::{native_pty_system, ChildKiller, CommandBuilder, MasterPty, PtySize};
use serde::Serialize;
use tauri::ipc::Channel;
use tauri::{AppHandle, Manager, State, Window};

/// Output kept per session for re-attaching after a reload.
const BACKLOG_MAX: usize = 512 * 1024;
/// One read from the pty.
const READ_CHUNK: usize = 16 * 1024;

/// What a session sends its window.
#[derive(Clone, Serialize)]
#[serde(tag = "type", rename_all = "camelCase")]
pub enum TerminalEvent {
    Data { data: String },
    Exit { code: Option<u32> },
}

/// A shell the terminal can start.
#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ShellInfo {
    id: String,
    name: String,
    program: String,
    #[serde(skip)]
    args: Vec<String>,
}

/// A running session, as the UI lists it.
#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SessionInfo {
    id: u32,
    shell_id: String,
    shell: String,
    cwd: String,
    pid: Option<u32>,
}

struct Output {
    channel: Option<Channel<TerminalEvent>>,
    backlog: String,
}

struct Session {
    window: String,
    info: SessionInfo,
    input: Sender<Vec<u8>>,
    master: Mutex<Box<dyn MasterPty + Send>>,
    killer: Mutex<Box<dyn ChildKiller + Send + Sync>>,
    output: Arc<Mutex<Output>>,
}

#[derive(Default)]
pub struct TerminalState {
    sessions: Mutex<HashMap<u32, Arc<Session>>>,
    next_id: AtomicU32,
}

impl TerminalState {
    fn get(&self, id: u32) -> Result<Arc<Session>, String> {
        self.sessions
            .lock()
            .expect("terminal sessions lock")
            .get(&id)
            .cloned()
            .ok_or_else(|| format!("terminal {id} is not running"))
    }

    /// Kill every shell started by `window` (it closed).
    pub fn kill_window(&self, window: &str) {
        let sessions: Vec<Arc<Session>> = self
            .sessions
            .lock()
            .expect("terminal sessions lock")
            .values()
            .filter(|session| session.window == window)
            .cloned()
            .collect();
        for session in sessions {
            session.kill();
        }
    }
}

impl Session {
    fn kill(&self) {
        let _ = self.killer.lock().expect("terminal killer lock").kill();
    }
}

/// Decode what is valid UTF-8 at the front of `pending`, leaving an incomplete
/// trailing character for the next read. Invalid bytes become U+FFFD.
fn take_utf8(pending: &mut Vec<u8>) -> String {
    let mut text = String::new();
    let mut start = 0;
    loop {
        match std::str::from_utf8(&pending[start..]) {
            Ok(valid) => {
                text.push_str(valid);
                start = pending.len();
                break;
            }
            Err(error) => {
                let valid = start + error.valid_up_to();
                text.push_str(std::str::from_utf8(&pending[start..valid]).expect("valid prefix"));
                match error.error_len() {
                    Some(bad) => {
                        text.push(char::REPLACEMENT_CHARACTER);
                        start = valid + bad;
                    }
                    // Cut inside a character: keep its bytes for the next read.
                    None => {
                        start = valid;
                        break;
                    }
                }
            }
        }
    }
    pending.drain(..start);
    text
}

/// Append to the backlog, dropping whole lines from the front past the limit.
fn push_backlog(backlog: &mut String, data: &str) {
    backlog.push_str(data);
    if backlog.len() <= BACKLOG_MAX {
        return;
    }
    let mut cut = backlog.len() - BACKLOG_MAX;
    // Start the kept part on a line, so replay does not begin inside an escape sequence.
    if let Some(newline) = backlog[cut..].find('\n') {
        cut += newline + 1;
    }
    while !backlog.is_char_boundary(cut) {
        cut += 1;
    }
    backlog.drain(..cut);
}

fn home_dir(app: &AppHandle) -> PathBuf {
    app.path()
        .home_dir()
        .ok()
        .or_else(|| std::env::current_dir().ok())
        .unwrap_or_else(|| PathBuf::from("."))
}

/// `program` on PATH (with PATHEXT on Windows), as an absolute path.
fn which(program: &str) -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    let exts: Vec<String> = if cfg!(windows) {
        std::env::var("PATHEXT")
            .unwrap_or_else(|_| ".EXE;.CMD;.BAT;.COM".into())
            .split(';')
            .filter(|ext| !ext.is_empty())
            .map(|ext| ext.to_ascii_lowercase())
            .collect()
    } else {
        vec![String::new()]
    };
    std::env::split_paths(&path).find_map(|dir| {
        let has_ext = Path::new(program).extension().is_some();
        if has_ext || !cfg!(windows) {
            let candidate = dir.join(program);
            if candidate.is_file() {
                return Some(candidate);
            }
        }
        exts.iter()
            .map(|ext| dir.join(format!("{program}{ext}")))
            .find(|candidate| candidate.is_file())
    })
}

fn shell(id: &str, name: &str, program: &Path, args: &[&str]) -> ShellInfo {
    ShellInfo {
        id: id.into(),
        name: name.into(),
        program: program.to_string_lossy().into_owned(),
        args: args.iter().map(|arg| arg.to_string()).collect(),
    }
}

/// The shells found on this computer, the default first.
#[cfg(windows)]
fn discover_shells() -> Vec<ShellInfo> {
    let system_root = std::env::var_os("SystemRoot")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(r"C:\Windows"));
    let system32 = system_root.join("System32");
    let mut shells = Vec::new();
    if let Some(pwsh) = which("pwsh.exe") {
        shells.push(shell("pwsh", "PowerShell", &pwsh, &["-NoLogo"]));
    }
    let powershell = system32.join(r"WindowsPowerShell\v1.0\powershell.exe");
    if powershell.is_file() {
        shells.push(shell("powershell", "Windows PowerShell", &powershell, &["-NoLogo"]));
    }
    let cmd = std::env::var_os("ComSpec")
        .map(PathBuf::from)
        .filter(|path| path.is_file())
        .unwrap_or_else(|| system32.join("cmd.exe"));
    if cmd.is_file() {
        shells.push(shell("cmd", "Command Prompt", &cmd, &[]));
    }
    // Git Bash: next to git.exe (…\Git\cmd\git.exe → …\Git\bin\bash.exe), or the usual install folders.
    let git_bash = which("git.exe")
        .and_then(|git| git.parent()?.parent().map(|root| root.join(r"bin\bash.exe")))
        .filter(|path| path.is_file())
        .or_else(|| {
            ["ProgramFiles", "ProgramW6432", "LOCALAPPDATA"].iter().find_map(|var| {
                let base = PathBuf::from(std::env::var_os(var)?);
                [r"Git\bin\bash.exe", r"Programs\Git\bin\bash.exe"]
                    .iter()
                    .map(|rel| base.join(rel))
                    .find(|path| path.is_file())
            })
        });
    if let Some(bash) = git_bash {
        shells.push(shell("git-bash", "Git Bash", &bash, &["--login", "-i"]));
    }
    let wsl = system32.join("wsl.exe");
    if wsl.is_file() {
        shells.push(shell("wsl", "WSL", &wsl, &[]));
    }
    shells
}

#[cfg(not(windows))]
fn discover_shells() -> Vec<ShellInfo> {
    // macOS terminals start login shells (the GUI app's PATH is minimal otherwise).
    let args: &[&str] = if cfg!(target_os = "macos") { &["-l"] } else { &[] };
    let mut shells: Vec<ShellInfo> = Vec::new();
    let mut seen: Vec<PathBuf> = Vec::new();
    let mut add = |path: PathBuf| {
        if !path.is_file() {
            return;
        }
        let real = std::fs::canonicalize(&path).unwrap_or_else(|_| path.clone());
        if seen.contains(&real) {
            return;
        }
        seen.push(real);
        let file = path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
        let name = match file.as_str() {
            "zsh" => "zsh",
            "bash" => "bash",
            "fish" => "fish",
            "nu" => "Nushell",
            "pwsh" => "PowerShell",
            "sh" => "sh",
            other => other,
        };
        let id = if shells.is_empty() { "default".to_string() } else { file.clone() };
        let shell_args: &[&str] = if file == "sh" { &[] } else { args };
        shells.push(shell(&id, name, &path, shell_args));
    };
    if let Some(user) = std::env::var_os("SHELL") {
        add(PathBuf::from(user));
    }
    for candidate in ["/bin/zsh", "/bin/bash", "/usr/bin/zsh", "/usr/bin/bash", "/opt/homebrew/bin/fish", "/usr/local/bin/fish", "/usr/bin/fish", "/bin/sh"] {
        add(PathBuf::from(candidate));
    }
    for program in ["nu", "pwsh"] {
        if let Some(path) = which(program) {
            add(path);
        }
    }
    shells
}

#[tauri::command]
pub fn terminal_shells() -> Vec<ShellInfo> {
    discover_shells()
}

/// Start a shell (`shell`: an id from `terminal_shells`, else the default) in
/// `cwd` (else the home folder). Output streams to `on_event`.
#[tauri::command]
pub async fn terminal_spawn(
    app: AppHandle,
    window: Window,
    state: State<'_, TerminalState>,
    shell: Option<String>,
    cwd: Option<String>,
    cols: u16,
    rows: u16,
    on_event: Channel<TerminalEvent>,
) -> Result<SessionInfo, String> {
    let shells = discover_shells();
    let chosen = shell
        .as_deref()
        .and_then(|id| shells.iter().find(|s| s.id == id))
        .or_else(|| shells.first())
        .cloned()
        .ok_or_else(|| "no shell found on this computer".to_string())?;
    let cwd = cwd
        .filter(|dir| !dir.is_empty())
        .map(PathBuf::from)
        .filter(|dir| dir.is_dir())
        .unwrap_or_else(|| home_dir(&app));

    let pair = native_pty_system()
        .openpty(PtySize { rows: rows.max(2), cols: cols.max(2), pixel_width: 0, pixel_height: 0 })
        .map_err(|e| format!("could not open a terminal: {e}"))?;
    let mut command = CommandBuilder::new(&chosen.program);
    command.args(&chosen.args);
    command.cwd(&cwd);
    command.env("TERM", "xterm-256color");
    command.env("COLORTERM", "truecolor");
    command.env("TERM_PROGRAM", "evo");
    command.env("TERM_PROGRAM_VERSION", env!("CARGO_PKG_VERSION"));
    let mut child = pair
        .slave
        .spawn_command(command)
        .map_err(|e| format!("could not start {}: {e}", chosen.name))?;
    // The child holds the other end now; ours would keep the pty open after it exits.
    drop(pair.slave);
    let mut reader = pair.master.try_clone_reader().map_err(|e| e.to_string())?;
    let mut writer = pair.master.take_writer().map_err(|e| e.to_string())?;
    let killer = child.clone_killer();

    let id = state.next_id.fetch_add(1, Ordering::Relaxed) + 1;
    let info = SessionInfo {
        id,
        shell_id: chosen.id.clone(),
        shell: chosen.name.clone(),
        cwd: cwd.to_string_lossy().into_owned(),
        pid: child.process_id(),
    };
    let output = Arc::new(Mutex::new(Output { channel: Some(on_event), backlog: String::new() }));

    // Keys and pastes, in order, off the main thread.
    let (input, keys) = mpsc::channel::<Vec<u8>>();
    std::thread::Builder::new()
        .name(format!("terminal-{id}-in"))
        .spawn(move || {
            for bytes in keys {
                if writer.write_all(&bytes).and_then(|()| writer.flush()).is_err() {
                    break;
                }
            }
        })
        .map_err(|e| e.to_string())?;

    let reader_output = output.clone();
    let reading = std::thread::Builder::new()
        .name(format!("terminal-{id}-out"))
        .spawn(move || {
            let mut buffer = vec![0u8; READ_CHUNK];
            let mut pending = Vec::new();
            loop {
                match reader.read(&mut buffer) {
                    Ok(0) | Err(_) => break,
                    Ok(n) => {
                        pending.extend_from_slice(&buffer[..n]);
                        let data = take_utf8(&mut pending);
                        if data.is_empty() {
                            continue;
                        }
                        let mut out = reader_output.lock().expect("terminal output lock");
                        push_backlog(&mut out.backlog, &data);
                        if let Some(channel) = &out.channel {
                            // A reloaded window dropped its end; keep the backlog for re-attaching.
                            if channel.send(TerminalEvent::Data { data }).is_err() {
                                out.channel = None;
                            }
                        }
                    }
                }
            }
        })
        .map_err(|e| e.to_string())?;

    let session = Arc::new(Session {
        window: window.label().to_string(),
        info: info.clone(),
        input,
        master: Mutex::new(pair.master),
        killer: Mutex::new(killer),
        output: output.clone(),
    });
    state.sessions.lock().expect("terminal sessions lock").insert(id, session);

    // Wait for the shell to exit, then close the pty (on Windows the reader only
    // ends once the pseudo console closes), drain the output and report the exit.
    let waiter_app = app.clone();
    std::thread::Builder::new()
        .name(format!("terminal-{id}-wait"))
        .spawn(move || {
            let status = child.wait().ok();
            let session = waiter_app
                .state::<TerminalState>()
                .sessions
                .lock()
                .expect("terminal sessions lock")
                .remove(&id);
            drop(session);
            let _ = reading.join();
            let out = output.lock().expect("terminal output lock");
            if let Some(channel) = &out.channel {
                let _ = channel.send(TerminalEvent::Exit { code: status.map(|s| s.exit_code()) });
            }
        })
        .map_err(|e| e.to_string())?;

    Ok(info)
}

/// Keys or pasted text for a session.
#[tauri::command]
pub fn terminal_write(state: State<'_, TerminalState>, id: u32, data: String) -> Result<(), String> {
    state
        .get(id)?
        .input
        .send(data.into_bytes())
        .map_err(|_| format!("terminal {id} has exited"))
}

#[tauri::command]
pub fn terminal_resize(state: State<'_, TerminalState>, id: u32, cols: u16, rows: u16) -> Result<(), String> {
    let session = state.get(id)?;
    let master = session.master.lock().expect("terminal master lock");
    master
        .resize(PtySize { rows: rows.max(2), cols: cols.max(2), pixel_width: 0, pixel_height: 0 })
        .map_err(|e| e.to_string())
}

/// Stop a session's shell; its exit is reported on its channel.
#[tauri::command]
pub fn terminal_kill(state: State<'_, TerminalState>, id: u32) {
    if let Ok(session) = state.get(id) {
        session.kill();
    }
}

/// The sessions this window started that are still running (after a reload).
#[tauri::command]
pub fn terminal_list(window: Window, state: State<'_, TerminalState>) -> Vec<SessionInfo> {
    let mut sessions: Vec<SessionInfo> = state
        .sessions
        .lock()
        .expect("terminal sessions lock")
        .values()
        .filter(|session| session.window == window.label())
        .map(|session| session.info.clone())
        .collect();
    sessions.sort_by_key(|session| session.id);
    sessions
}

/// Send a running session's output to a new channel; returns the output so far.
#[tauri::command]
pub fn terminal_attach(
    state: State<'_, TerminalState>,
    id: u32,
    on_event: Channel<TerminalEvent>,
) -> Result<String, String> {
    let session = state.get(id)?;
    let mut out = session.output.lock().expect("terminal output lock");
    out.channel = Some(on_event);
    Ok(out.backlog.clone())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn utf8_split_inside_a_character_waits_for_the_rest() {
        let bytes = "héllo ✓".as_bytes();
        let split = bytes.len() - 1;
        let mut pending = bytes[..split].to_vec();
        assert_eq!(take_utf8(&mut pending), "héllo ");
        assert_eq!(pending.len(), 2);
        pending.extend_from_slice(&bytes[split..]);
        assert_eq!(take_utf8(&mut pending), "✓");
        assert!(pending.is_empty());
    }

    #[test]
    fn invalid_utf8_becomes_replacement_characters() {
        let mut pending = vec![b'a', 0xff, b'b'];
        assert_eq!(take_utf8(&mut pending), "a\u{fffd}b");
        assert!(pending.is_empty());
    }

    #[test]
    fn backlog_keeps_whole_lines_within_the_limit() {
        let mut backlog = String::new();
        let line = format!("{}\n", "x".repeat(1023));
        for _ in 0..(BACKLOG_MAX / 1024 + 10) {
            push_backlog(&mut backlog, &line);
        }
        assert!(backlog.len() <= BACKLOG_MAX);
        assert!(backlog.starts_with('x'));
        assert!(backlog.ends_with('\n'));
    }

    #[test]
    fn finds_at_least_one_shell() {
        assert!(!discover_shells().is_empty());
    }

    /// The same sequence `terminal_spawn` runs: a real shell echoes, exits, and
    /// the reader ends once the pty is dropped after the wait.
    #[test]
    fn shell_runs_echoes_and_exits() {
        let shell = discover_shells().into_iter().next().expect("a shell");
        let pair = native_pty_system()
            .openpty(PtySize { rows: 24, cols: 80, pixel_width: 0, pixel_height: 0 })
            .expect("pty");
        let mut command = CommandBuilder::new(&shell.program);
        command.args(&shell.args);
        command.cwd(std::env::temp_dir());
        let mut child = pair.slave.spawn_command(command).expect("spawn");
        drop(pair.slave);
        let mut reader = pair.master.try_clone_reader().expect("reader");
        let writer = Arc::new(Mutex::new(pair.master.take_writer().expect("writer")));
        // Never hang the suite: kill the shell if it is still running after 60s.
        let mut killer = child.clone_killer();
        let done = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let watchdog_done = done.clone();
        std::thread::spawn(move || {
            std::thread::sleep(std::time::Duration::from_secs(60));
            if !watchdog_done.load(Ordering::SeqCst) {
                let _ = killer.kill();
            }
        });
        let answer = writer.clone();
        let reading = std::thread::spawn(move || {
            let mut all = Vec::new();
            let mut pending = Vec::new();
            let mut buffer = [0u8; 4096];
            while let Ok(n) = reader.read(&mut buffer) {
                if n == 0 {
                    break;
                }
                pending.extend_from_slice(&buffer[..n]);
                let text = take_utf8(&mut pending);
                // ConPTY asks for the cursor position (DSR) and waits; xterm.js answers in the app.
                if text.contains("\x1b[6n") {
                    let mut w = answer.lock().unwrap();
                    let _ = w.write_all(b"\x1b[1;1R").and_then(|()| w.flush());
                }
                all.push(text);
            }
            all.concat()
        });
        let send = |bytes: &[u8]| {
            let mut w = writer.lock().unwrap();
            w.write_all(bytes).and_then(|()| w.flush()).expect("write");
        };
        std::thread::sleep(std::time::Duration::from_millis(1500));
        send(b"echo evo-terminal-ok\r");
        std::thread::sleep(std::time::Duration::from_millis(1500));
        send(b"exit\r");
        let status = child.wait().expect("wait");
        done.store(true, Ordering::SeqCst);
        drop(writer);
        drop(pair.master);
        let output = reading.join().expect("reader thread");
        assert!(output.contains("evo-terminal-ok"), "output: {output:?}");
        assert_eq!(status.exit_code(), 0);
    }
}
