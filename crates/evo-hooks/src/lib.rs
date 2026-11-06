//! Hooks: commands (or web requests) that run when something happens in a
//! session, and can steer it.
//!
//! Configured under `hooks` in `~/.evo/agent/settings.json` and a trusted
//! project's `.evo/settings.json`:
//!
//! ```json
//! { "hooks": { "PreToolUse": [ { "matcher": "bash|edit",
//!     "hooks": [ { "type": "command", "command": "./check.sh", "timeout": 30 } ] } ] } }
//! ```
//!
//! A hook gets the event as JSON on stdin (`session_id`, `cwd`,
//! `hook_event_name` and the event's own fields). Exit 0 succeeds (stdout may
//! be a JSON object of decisions, or plain text that becomes context for
//! `UserPromptSubmit` and `SessionStart`); exit 2 blocks, with stderr as the
//! reason; any other exit is an error that does not block. JSON output:
//! `continue: false` + `stopReason`, `systemMessage`, `decision: "block"` +
//! `reason`, and `hookSpecificOutput` with `permissionDecision`
//! (`allow`/`deny`/`ask`), `permissionDecisionReason`, `updatedInput` and
//! `additionalContext`. Matching hooks of one event run in parallel.
//!
//! [`config`] reads and merges the settings; [`run`] executes them.

pub mod config;
pub mod run;

pub use config::{Handler, HookEntry, Hooks};
pub use run::{run_event, Outcome, RunRecord};

/// Events evo raises.
pub const EVENTS: &[&str] = &[
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "Stop",
    "SessionEnd",
];
