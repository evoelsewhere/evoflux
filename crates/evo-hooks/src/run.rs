//! Running the hooks of one event and combining what they decide.

use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::{Duration, Instant};

use serde::Serialize;
use serde_json::{json, Value};
use tokio::io::AsyncWriteExt;

use crate::config::{Handler, HookEntry, Hooks};

/// Default limits, in seconds.
const COMMAND_TIMEOUT: u64 = 600;
const HTTP_TIMEOUT: u64 = 60;
/// A prompt waits at most this long for its hooks.
const PROMPT_TIMEOUT: u64 = 30;
/// Context a hook adds is cut to this many characters.
const MAX_CONTEXT: usize = 10_000;

/// What the hooks of one event decided, together.
#[derive(Debug, Clone, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Outcome {
    /// Blocked (exit 2, `decision: "block"` or `permissionDecision: "deny"`), with why.
    pub block: Option<String>,
    /// A hook asked to confirm with the person first (`permissionDecision: "ask"`).
    pub ask: Option<String>,
    /// A hook allowed it outright (`permissionDecision: "allow"`).
    pub allow: bool,
    /// A hook rewrote the tool's input.
    pub updated_input: Option<Value>,
    /// Context for the model (`additionalContext`, or plain output where allowed).
    pub context: Vec<String>,
    /// Messages for the person (`systemMessage`, errors).
    pub messages: Vec<String>,
    /// A hook said to stop (`continue: false`), with its `stopReason`.
    pub stop: Option<String>,
    pub records: Vec<RunRecord>,
}

/// One hook run, for Customize → Hooks.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RunRecord {
    pub event: String,
    pub hook: String,
    pub source: String,
    pub target: Option<String>,
    /// `ok`, `blocked`, `error`, `timeout`.
    pub result: String,
    pub exit: Option<i32>,
    pub ms: u64,
    pub detail: Option<String>,
    /// Milliseconds since the Unix epoch.
    pub at: u64,
}

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

/// Plain stdout becomes context for these events.
fn plain_output_is_context(event: &str) -> bool {
    matches!(event, "UserPromptSubmit" | "SessionStart")
}

/// Run every hook of `event` matching `target` (the tool name for tool
/// events) with `input` (the event's fields; `hook_event_name` and `cwd` are
/// added), in parallel, and combine the results.
pub async fn run_event(
    hooks: &Hooks,
    event: &str,
    target: Option<&str>,
    mut input: Value,
    cwd: &Path,
) -> Outcome {
    let entries = hooks.matching(event, target);
    let mut outcome = Outcome::default();
    if entries.is_empty() {
        return outcome;
    }
    if let Some(object) = input.as_object_mut() {
        object.insert("hook_event_name".into(), json!(event));
        object.entry("cwd").or_insert_with(|| json!(cwd));
    }
    let payload = input.to_string();
    let cap = if event == "UserPromptSubmit" {
        Some(PROMPT_TIMEOUT)
    } else {
        None
    };
    let runs = entries
        .iter()
        .map(|entry| run_one(entry, &payload, cwd, cap));
    let results = futures::future::join_all(runs).await;
    for (entry, result) in entries.iter().zip(results) {
        apply(&mut outcome, entry, event, target, result);
    }
    outcome
}

/// What one handler produced.
struct Raw {
    exit: Option<i32>,
    stdout: String,
    stderr: String,
    ms: u64,
    timed_out: bool,
    failed_to_start: Option<String>,
}

fn apply(outcome: &mut Outcome, entry: &HookEntry, event: &str, target: Option<&str>, raw: Raw) {
    let mut record = RunRecord {
        event: event.into(),
        hook: entry.handler.summary(),
        source: entry.source.clone(),
        target: target.map(str::to_string),
        result: "ok".into(),
        exit: raw.exit,
        ms: raw.ms,
        detail: None,
        at: now_ms(),
    };
    let first_line = |s: &str| {
        s.lines()
            .map(str::trim)
            .find(|l| !l.is_empty())
            .unwrap_or("")
            .to_string()
    };
    if let Some(error) = raw.failed_to_start {
        record.result = "error".into();
        record.detail = Some(error.clone());
        outcome
            .messages
            .push(format!("Hook `{}` could not run: {error}", record.hook));
    } else if raw.timed_out {
        record.result = "timeout".into();
        outcome.messages.push(format!(
            "Hook `{}` timed out after {} ms",
            record.hook, raw.ms
        ));
    } else if raw.exit == Some(2) {
        let reason = Some(raw.stderr.trim().to_string())
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| "blocked by a hook".into());
        record.result = "blocked".into();
        record.detail = Some(first_line(&reason));
        outcome.block.get_or_insert(reason);
    } else if raw.exit != Some(0) {
        record.result = "error".into();
        let detail = first_line(&raw.stderr);
        record.detail = Some(detail.clone());
        outcome.messages.push(format!(
            "Hook `{}` failed (exit {}){}",
            record.hook,
            raw.exit.map_or("?".into(), |c| c.to_string()),
            if detail.is_empty() {
                String::new()
            } else {
                format!(": {detail}")
            }
        ));
    } else {
        let stdout = raw.stdout.trim();
        match serde_json::from_str::<Value>(stdout)
            .ok()
            .filter(Value::is_object)
        {
            Some(json) => apply_json(outcome, &mut record, &json),
            None if !stdout.is_empty() && plain_output_is_context(event) => {
                outcome.context.push(cut(stdout))
            }
            None => {}
        }
    }
    outcome.records.push(record);
}

fn apply_json(outcome: &mut Outcome, record: &mut RunRecord, json: &Value) {
    let text = |v: Option<&Value>| {
        v.and_then(Value::as_str)
            .map(str::to_string)
            .filter(|s| !s.trim().is_empty())
    };
    if json.get("continue").and_then(Value::as_bool) == Some(false) {
        outcome.stop.get_or_insert(
            text(json.get("stopReason")).unwrap_or_else(|| "stopped by a hook".into()),
        );
        record.result = "blocked".into();
    }
    if let Some(message) = text(json.get("systemMessage")) {
        outcome.messages.push(message);
    }
    if json.get("decision").and_then(Value::as_str) == Some("block") {
        let reason = text(json.get("reason")).unwrap_or_else(|| "blocked by a hook".into());
        record.result = "blocked".into();
        record.detail = Some(reason.clone());
        outcome.block.get_or_insert(reason);
    }
    let Some(specific) = json.get("hookSpecificOutput") else {
        return;
    };
    let reason = text(specific.get("permissionDecisionReason"));
    match specific.get("permissionDecision").and_then(Value::as_str) {
        Some("deny") => {
            record.result = "blocked".into();
            record.detail = reason.clone();
            outcome
                .block
                .get_or_insert(reason.unwrap_or_else(|| "denied by a hook".into()));
        }
        Some("ask") => {
            outcome
                .ask
                .get_or_insert(reason.unwrap_or_else(|| "a hook asks you to confirm".into()));
        }
        Some("allow") => outcome.allow = true,
        _ => {}
    }
    if let Some(input) = specific.get("updatedInput").filter(|v| v.is_object()) {
        outcome.updated_input = Some(input.clone());
    }
    if let Some(context) = text(specific.get("additionalContext")) {
        outcome.context.push(cut(&context));
    }
}

fn cut(text: &str) -> String {
    if text.chars().count() > MAX_CONTEXT {
        text.chars().take(MAX_CONTEXT).collect::<String>() + "\n[cut]"
    } else {
        text.to_string()
    }
}

async fn run_one(entry: &HookEntry, payload: &str, cwd: &Path, cap: Option<u64>) -> Raw {
    let started = Instant::now();
    match &entry.handler {
        Handler::Command {
            command,
            args,
            shell,
            timeout,
        } => {
            let limit = Duration::from_secs(
                cap.unwrap_or(u64::MAX)
                    .min(timeout.unwrap_or(COMMAND_TIMEOUT)),
            );
            run_command(
                command,
                args.as_deref(),
                shell.as_deref(),
                payload,
                cwd,
                limit,
                started,
            )
            .await
        }
        Handler::Http {
            url,
            headers,
            timeout,
        } => {
            let limit =
                Duration::from_secs(cap.unwrap_or(u64::MAX).min(timeout.unwrap_or(HTTP_TIMEOUT)));
            run_http(url, headers, payload, limit, started).await
        }
    }
}

/// `command` run by `shell` (`powershell`), else Git Bash or PowerShell on
/// Windows and `sh` elsewhere.
pub fn shell_command(command: &str, shell: Option<&str>) -> tokio::process::Command {
    let powershell = |cmd: &str| {
        let exe = if cfg!(windows) { "powershell" } else { "pwsh" };
        let mut c = tokio::process::Command::new(exe);
        c.args(["-NoProfile", "-NonInteractive", "-Command", cmd]);
        c
    };
    if shell == Some("powershell") {
        return powershell(command);
    }
    if cfg!(windows) {
        // Git Bash when installed (never the WSL launcher in System32).
        if let Some(bash) = find_bash() {
            let mut c = tokio::process::Command::new(bash);
            c.args(["-c", command]);
            return c;
        }
        return powershell(command);
    }
    let mut c = tokio::process::Command::new("sh");
    c.args(["-c", command]);
    c
}

fn find_bash() -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    std::env::split_paths(&path)
        .filter(|dir| {
            !dir.to_string_lossy()
                .to_ascii_lowercase()
                .contains("system32")
        })
        .map(|dir| dir.join(if cfg!(windows) { "bash.exe" } else { "bash" }))
        .find(|candidate| candidate.is_file())
        .or_else(|| {
            let git = PathBuf::from(r"C:\Program Files\Git\bin\bash.exe");
            git.is_file().then_some(git)
        })
}

async fn run_command(
    command: &str,
    args: Option<&[String]>,
    shell: Option<&str>,
    payload: &str,
    cwd: &Path,
    limit: Duration,
    started: Instant,
) -> Raw {
    let mut cmd = match args {
        Some(args) => {
            let mut c = tokio::process::Command::new(command);
            c.args(args);
            c
        }
        None => shell_command(command, shell),
    };
    cmd.current_dir(cwd)
        .env("EVO_PROJECT_DIR", cwd)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    #[cfg(windows)]
    {
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    let mut child = match cmd.spawn() {
        Ok(child) => child,
        Err(error) => {
            return Raw {
                exit: None,
                stdout: String::new(),
                stderr: String::new(),
                ms: started.elapsed().as_millis() as u64,
                timed_out: false,
                failed_to_start: Some(error.to_string()),
            }
        }
    };
    if let Some(mut stdin) = child.stdin.take() {
        let payload = payload.to_string();
        tokio::spawn(async move {
            let _ = stdin.write_all(payload.as_bytes()).await;
            let _ = stdin.shutdown().await;
        });
    }
    match tokio::time::timeout(limit, child.wait_with_output()).await {
        Ok(Ok(output)) => Raw {
            exit: output.status.code(),
            stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
            stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
            ms: started.elapsed().as_millis() as u64,
            timed_out: false,
            failed_to_start: None,
        },
        Ok(Err(error)) => Raw {
            exit: None,
            stdout: String::new(),
            stderr: String::new(),
            ms: started.elapsed().as_millis() as u64,
            timed_out: false,
            failed_to_start: Some(error.to_string()),
        },
        // Dropping the future kills the child (kill_on_drop).
        Err(_) => Raw {
            exit: None,
            stdout: String::new(),
            stderr: String::new(),
            ms: started.elapsed().as_millis() as u64,
            timed_out: true,
            failed_to_start: None,
        },
    }
}

/// `${VAR}` from the environment in header values.
fn expand(text: &str) -> String {
    let mut out = String::new();
    let mut rest = text;
    while let Some(start) = rest.find("${") {
        out.push_str(&rest[..start]);
        let Some(end) = rest[start..].find('}') else {
            break;
        };
        let name = &rest[start + 2..start + end];
        out.push_str(&std::env::var(name).unwrap_or_default());
        rest = &rest[start + end + 1..];
    }
    out.push_str(rest);
    out
}

async fn run_http(
    url: &str,
    headers: &std::collections::BTreeMap<String, String>,
    payload: &str,
    limit: Duration,
    started: Instant,
) -> Raw {
    let client = reqwest::Client::new();
    let mut request = client
        .post(url)
        .timeout(limit)
        .header("content-type", "application/json")
        .body(payload.to_string());
    for (name, value) in headers {
        request = request.header(name, expand(value));
    }
    let ms = || started.elapsed().as_millis() as u64;
    match request.send().await {
        Ok(response) => {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            Raw {
                // 2xx is success; anything else is an error that does not block.
                exit: Some(if status.is_success() { 0 } else { 1 }),
                stdout: if status.is_success() {
                    body.clone()
                } else {
                    String::new()
                },
                stderr: if status.is_success() {
                    String::new()
                } else {
                    format!("HTTP {status}: {body}")
                },
                ms: ms(),
                timed_out: false,
                failed_to_start: None,
            }
        }
        Err(error) if error.is_timeout() => Raw {
            exit: None,
            stdout: String::new(),
            stderr: String::new(),
            ms: ms(),
            timed_out: true,
            failed_to_start: None,
        },
        Err(error) => Raw {
            exit: None,
            stdout: String::new(),
            stderr: String::new(),
            ms: ms(),
            timed_out: false,
            failed_to_start: Some(error.to_string()),
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::HookEntry;

    fn hooks(entries: Vec<(&str, Option<&str>, Handler)>) -> Hooks {
        Hooks {
            entries: entries
                .into_iter()
                .map(|(event, matcher, handler)| HookEntry {
                    event: event.into(),
                    matcher: matcher.map(str::to_string),
                    handler,
                    source: "user".into(),
                    file: "settings.json".into(),
                })
                .collect(),
            ..Default::default()
        }
    }

    /// A hook that prints `out` and exits with `code`, run without a shell
    /// (PowerShell on Windows, sh elsewhere) so the test needs nothing else.
    fn script(out: &str, err: &str, code: i32) -> Handler {
        if cfg!(windows) {
            let out = out.replace('\'', "''");
            let err = err.replace('\'', "''");
            Handler::Command {
                command: "powershell".into(),
                args: Some(vec![
                    "-NoProfile".into(),
                    "-NonInteractive".into(),
                    "-Command".into(),
                    format!("$null = [Console]::In.ReadToEnd(); [Console]::Out.Write('{out}'); [Console]::Error.Write('{err}'); exit {code}"),
                ]),
                shell: None,
                timeout: Some(60),
            }
        } else {
            Handler::Command {
                command: "sh".into(),
                args: Some(vec![
                    "-c".into(),
                    format!(
                        "cat >/dev/null; printf '%s' '{out}'; printf '%s' '{err}' >&2; exit {code}"
                    ),
                ]),
                shell: None,
                timeout: Some(60),
            }
        }
    }

    #[tokio::test]
    async fn exit_codes_and_json_decisions() {
        let dir = tempfile::tempdir().unwrap();
        let input = json!({"tool_name": "bash", "tool_input": {"command": "rm -rf /"}});

        // Exit 2 blocks with stderr.
        let h = hooks(vec![(
            "PreToolUse",
            Some("Bash"),
            script("", "no rm please", 2),
        )]);
        let out = run_event(&h, "PreToolUse", Some("bash"), input.clone(), dir.path()).await;
        assert_eq!(out.block.as_deref(), Some("no rm please"));
        assert_eq!(out.records[0].result, "blocked");

        // Not matching: nothing runs.
        let out = run_event(&h, "PreToolUse", Some("read"), input.clone(), dir.path()).await;
        assert!(out.block.is_none() && out.records.is_empty());

        // JSON: ask with a reason, rewritten input, context and a message.
        let json = r#"{"systemMessage":"checked","hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"looks risky","updatedInput":{"command":"ls"},"additionalContext":"cwd is the repo"}}"#;
        let h = hooks(vec![("PreToolUse", None, script(json, "", 0))]);
        let out = run_event(&h, "PreToolUse", Some("bash"), input.clone(), dir.path()).await;
        assert_eq!(out.ask.as_deref(), Some("looks risky"));
        assert_eq!(out.updated_input, Some(json!({"command": "ls"})));
        assert_eq!(out.context, vec!["cwd is the repo".to_string()]);
        assert_eq!(out.messages, vec!["checked".to_string()]);

        // Another exit code: an error that does not block.
        let h = hooks(vec![("PostToolUse", None, script("", "oops", 1))]);
        let out = run_event(&h, "PostToolUse", Some("bash"), input.clone(), dir.path()).await;
        assert!(out.block.is_none());
        assert!(out.messages[0].contains("oops"), "{:?}", out.messages);

        // Plain output is context for a prompt, ignored for tool events.
        let h = hooks(vec![(
            "UserPromptSubmit",
            None,
            script("today is Friday", "", 0),
        )]);
        let out = run_event(
            &h,
            "UserPromptSubmit",
            None,
            json!({"prompt": "hi"}),
            dir.path(),
        )
        .await;
        assert_eq!(out.context, vec!["today is Friday".to_string()]);
    }

    #[tokio::test]
    async fn the_event_arrives_on_stdin_and_hooks_run_in_parallel() {
        let dir = tempfile::tempdir().unwrap();
        // Echo stdin back as additionalContext.
        let echo = if cfg!(windows) {
            Handler::Command {
                command: "powershell".into(),
                args: Some(vec![
                    "-NoProfile".into(),
                    "-NonInteractive".into(),
                    "-Command".into(),
                    "$in = [Console]::In.ReadToEnd() | ConvertFrom-Json; @{hookSpecificOutput=@{additionalContext=\"$($in.hook_event_name):$($in.tool_name)\"}} | ConvertTo-Json -Compress".into(),
                ]),
                shell: None,
                timeout: Some(60),
            }
        } else {
            Handler::Command {
                command: "sh".into(),
                args: Some(vec!["-c".into(), "read -r line; case \"$line\" in *PostToolUse*) printf '{\"hookSpecificOutput\":{\"additionalContext\":\"PostToolUse:bash\"}}';; esac".into()]),
                shell: None,
                timeout: Some(60),
            }
        };
        let h = hooks(vec![
            ("PostToolUse", None, echo),
            ("PostToolUse", None, script("", "", 0)),
        ]);
        let out = run_event(
            &h,
            "PostToolUse",
            Some("bash"),
            json!({"tool_name": "bash"}),
            dir.path(),
        )
        .await;
        assert_eq!(out.records.len(), 2);
        assert_eq!(out.context, vec!["PostToolUse:bash".to_string()]);
    }

    #[tokio::test]
    async fn a_missing_command_is_an_error_not_a_block() {
        let dir = tempfile::tempdir().unwrap();
        let h = hooks(vec![(
            "Stop",
            None,
            Handler::Command {
                command: "evo-no-such-hook-xyz".into(),
                args: Some(vec![]),
                shell: None,
                timeout: None,
            },
        )]);
        let out = run_event(&h, "Stop", None, json!({}), dir.path()).await;
        assert!(out.block.is_none());
        assert_eq!(out.records[0].result, "error");
    }
}
