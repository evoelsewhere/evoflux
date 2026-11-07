//! Ask before a shell command stops the app that runs this chat.
//!
//! The desktop starts each chat's engine as a child process. A `bash` or
//! `powershell` call such as `Stop-Process -Name evo-desktop -Force` kills the
//! desktop (and with it every open chat and this very turn) or this engine.
//! The guard spots such commands and puts them through the same Allow / Deny
//! prompt as a `PreToolUse` hook; headless sessions have no one to ask, so the
//! call is refused.
//!
//! The desktop passes `EVO_HOST_PID` (its process id) and `EVO_HOST_EXE` (its
//! executable file name) when it starts the engine. The guard also knows the
//! app's executable names and this engine's own pid, so it works without them.
//! Detection is word based on purpose: shell syntax the read-only parser
//! rejects (method calls, `$env:` assignments) must still be caught, and a
//! false match only costs one question.

use std::sync::Arc;

use serde_json::Value;

/// Executable stems of the app and its engine, whatever the build.
const APP_NAMES: [&str; 3] = ["evo-harness", "evo-desktop", "evo-engine"];

/// Commands that end processes by name or id.
const KILL_COMMANDS: [&str; 7] = [
    "stop-process",
    "spps",
    "taskkill",
    "tskill",
    "kill",
    "pkill",
    "killall",
];

/// The processes a command must not stop without asking.
#[derive(Debug, Clone, Default)]
pub struct Protected {
    /// The desktop app's pid (`EVO_HOST_PID`).
    pub host_pid: Option<u32>,
    /// The desktop app's executable stem, lowercase (`EVO_HOST_EXE`).
    pub host_name: Option<String>,
    /// This engine's pid.
    pub engine_pid: u32,
}

impl Protected {
    pub fn from_env() -> Self {
        Self {
            host_pid: std::env::var("EVO_HOST_PID")
                .ok()
                .and_then(|pid| pid.trim().parse().ok()),
            host_name: std::env::var("EVO_HOST_EXE")
                .ok()
                .map(|name| stem(&name))
                .filter(|name| !name.is_empty()),
            engine_pid: std::process::id(),
        }
    }

    fn names(&self) -> impl Iterator<Item = &str> {
        APP_NAMES.into_iter().chain(self.host_name.as_deref())
    }

    fn pids(&self) -> impl Iterator<Item = u32> {
        self.host_pid.into_iter().chain([self.engine_pid])
    }
}

/// Why `command` needs approval, or `None` when it does not touch the app.
pub fn reason(command: &str, protected: &Protected) -> Option<String> {
    let lower = command.to_ascii_lowercase();
    let words: Vec<String> = lower
        .split(|c: char| {
            c.is_whitespace()
                || matches!(
                    c,
                    ';' | '|'
                        | '&'
                        | '('
                        | ')'
                        | '{'
                        | '}'
                        | '<'
                        | '>'
                        | ','
                        | '='
                        | '"'
                        | '\''
                        | '`'
                )
        })
        .filter(|word| !word.is_empty())
        .map(stem)
        .collect();

    let kills = words
        .iter()
        .any(|word| KILL_COMMANDS.contains(&word.as_str()))
        || lower.contains(".kill(")
        || (lower.contains("wmic") && (lower.contains("terminate") || lower.contains(" delete")))
        || lower.contains("terminate()");
    if !kills {
        return None;
    }

    let target = words.iter().find_map(|word| {
        if let Ok(pid) = word.parse::<u32>() {
            return protected.pids().any(|own| own == pid).then(|| {
                if Some(pid) == protected.host_pid {
                    format!("the app's process id {pid}")
                } else {
                    format!("this chat engine's process id {pid}")
                }
            });
        }
        protected
            .names()
            .find(|name| glob_matches(word, name))
            .map(|name| format!("`{name}`"))
    })?;

    let app = protected.host_name.as_deref().unwrap_or("evo-harness");
    Some(format!(
        "This command stops processes matching {target}. It may close the {app} app that runs \
         this chat, which ends this turn and every open chat.\n\n{command}"
    ))
}

/// A word as a lowercase executable stem: no folder, no `.exe`.
fn stem(word: &str) -> String {
    let base = word
        .rsplit(['/', '\\'])
        .next()
        .unwrap_or(word)
        .to_ascii_lowercase();
    match base.strip_suffix(".exe") {
        Some(stem) => stem.to_string(),
        None => base,
    }
}

/// `pattern` (with `*` / `?` wildcards) matches all of `name`.
fn glob_matches(pattern: &str, name: &str) -> bool {
    fn go(p: &[u8], n: &[u8]) -> bool {
        match (p.first(), n.first()) {
            (None, None) => true,
            (Some(b'*'), _) => go(&p[1..], n) || (!n.is_empty() && go(p, &n[1..])),
            (Some(b'?'), Some(_)) => go(&p[1..], &n[1..]),
            (Some(a), Some(b)) if a == b => go(&p[1..], &n[1..]),
            _ => false,
        }
    }
    // A bare `*` names every process; that is not about this app.
    !pattern.trim_matches('*').is_empty() && go(pattern.as_bytes(), name.as_bytes())
}

/// Put the guard in front of `previous` (the hooks and plugin approval).
pub fn before_tool_call(
    previous: Option<evo_agent::BeforeToolCall>,
    ui_dialog: evo_extensions::UiDialogMailbox,
) -> Option<evo_agent::BeforeToolCall> {
    let protected = Arc::new(Protected::from_env());
    Some(Arc::new(
        move |ctx: evo_agent::BeforeToolCallContext<'_>, signal| {
            let tool = ctx.tool_call.name.clone();
            let id = ctx.tool_call.id.clone();
            let reason = matches!(tool.as_str(), "bash" | "powershell")
                .then(|| ctx.args.get("command").and_then(Value::as_str))
                .flatten()
                .and_then(|command| reason(command, &protected));
            let earlier = previous.as_ref().map(|hook| hook(ctx, signal.clone()));
            let ui_dialog = ui_dialog.clone();
            Box::pin(async move {
                if let Some(reason) = reason {
                    if !crate::hooks::confirm(&ui_dialog, &id, &tool, &reason, &signal).await {
                        return Some(evo_agent::BeforeToolCallResult {
                            block: true,
                            reason: Some(
                                "Not run: this command could stop the app that runs this chat, \
                                 and the user did not allow it. Do not stop the app or its \
                                 engine; ask the user to do it."
                                    .into(),
                            ),
                            terminate: false,
                            args: None,
                        });
                    }
                }
                match earlier {
                    Some(earlier) => earlier.await,
                    None => None,
                }
            })
        },
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn protected() -> Protected {
        Protected {
            host_pid: Some(25140),
            host_name: Some("evo-harness".into()),
            engine_pid: 31356,
        }
    }

    fn asks(command: &str) -> bool {
        reason(command, &protected()).is_some()
    }

    #[test]
    fn commands_that_stop_the_app_ask() {
        for command in [
            "Stop-Process -Name evo-desktop -Force -ErrorAction SilentlyContinue; Start-Sleep 2; \
             $env:X='C:\\tmp'; (Invoke-WebRequest http://127.0.0.1:9333/json).Content.Substring(0,400)",
            "Stop-Process -Name evo* -Force",
            "Get-Process evo-harness | Stop-Process",
            "spps -Id 25140",
            "taskkill /F /IM evo-harness.exe",
            "taskkill.exe /PID 31356 /T /F",
            "cmd /c \"taskkill /IM evo-engine.exe /F\"",
            "kill -9 25140",
            "pkill -f evo-engine",
            "killall evo-desktop",
            "(Get-Process -Name 'evo-desktop').Kill()",
            "wmic process where name='evo-harness.exe' delete",
            "& \"C:\\Windows\\System32\\taskkill.exe\" /IM \"evo-harness.exe\"",
        ] {
            assert!(asks(command), "should ask: {command}");
        }
    }

    #[test]
    fn other_commands_run() {
        for command in [
            "git commit -m \"fix: build evo-harness installer\"",
            "Get-Process evo-desktop",
            "tasklist | grep -i evo",
            "Stop-Process -Name notepad",
            "taskkill /IM node.exe /F",
            "kill 4242",
            "Stop-Process -Name * -WhatIf",
            "cargo build -p evo-engine",
        ] {
            assert!(!asks(command), "should not ask: {command}");
        }
    }

    #[test]
    fn host_name_from_env_is_protected_too() {
        let mut protected = protected();
        protected.host_name = Some("my-evo-build".into());
        assert!(reason("taskkill /IM my-evo-build.exe", &protected).is_some());
    }

    async fn call(hook: &evo_agent::BeforeToolCall, command: &str) -> Option<bool> {
        let message = evo_ai::providers::faux::faux_assistant_message(
            "approval",
            evo_ai::types::StopReason::ToolUse,
        );
        let evo_ai::types::Content::ToolCall(call) = evo_ai::types::Content::tool_call(
            "call",
            "powershell",
            serde_json::json!({ "command": command }),
        ) else {
            unreachable!()
        };
        hook(
            evo_agent::BeforeToolCallContext {
                assistant_message: &message,
                tool_call: &call,
                args: &call.arguments,
                context: &evo_agent::AgentContext::default(),
            },
            tokio_util::sync::CancellationToken::new(),
        )
        .await
        .map(|result| result.block)
    }

    #[tokio::test]
    async fn headless_session_refuses_the_call() {
        let hook = before_tool_call(None, evo_extensions::UiDialogMailbox::new())
            .expect("guard is always installed");
        assert_eq!(
            call(&hook, "Stop-Process -Name evo-desktop -Force").await,
            Some(true)
        );
        assert_eq!(call(&hook, "Get-Process evo-desktop").await, None);
    }
}
