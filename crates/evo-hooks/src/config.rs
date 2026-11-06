//! Reading hooks from settings files and matching them to an event.

use std::collections::BTreeMap;
use std::path::Path;

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// One handler: run a command, or POST the event to a URL.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum Handler {
    Command {
        /// Shell form: run by the shell (`sh -c`; on Windows Git Bash when
        /// installed, else PowerShell). With `args`: run directly, no shell.
        command: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        args: Option<Vec<String>>,
        /// `bash` or `powershell`, to pick the shell explicitly.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        shell: Option<String>,
        /// Seconds.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        timeout: Option<u64>,
    },
    Http {
        url: String,
        #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
        headers: BTreeMap<String, String>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        timeout: Option<u64>,
    },
}

impl Handler {
    /// What it runs, for display and deduplication.
    pub fn summary(&self) -> String {
        match self {
            Handler::Command { command, args, .. } => match args {
                Some(args) if !args.is_empty() => format!("{command} {}", args.join(" ")),
                _ => command.clone(),
            },
            Handler::Http { url, .. } => format!("POST {url}"),
        }
    }
}

#[derive(Debug, Clone, Default, Deserialize)]
struct Group {
    #[serde(default)]
    matcher: Option<String>,
    #[serde(default)]
    hooks: Vec<Value>,
}

/// A configured hook with where it came from.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HookEntry {
    pub event: String,
    /// `None` / empty / `*`: every time the event happens.
    pub matcher: Option<String>,
    pub handler: Handler,
    /// `user` or `project`.
    pub source: String,
    /// The settings file it is in.
    pub file: String,
}

/// Every hook in effect for a session.
#[derive(Debug, Clone, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Hooks {
    pub entries: Vec<HookEntry>,
    /// `disableAllHooks` in user settings.
    pub disabled: bool,
    /// Entries that could not be read.
    pub problems: Vec<String>,
}

impl Hooks {
    /// Read user settings, then (when trusted) the project's.
    pub fn load(user_settings: Option<&Path>, project_settings: Option<&Path>) -> Hooks {
        let mut hooks = Hooks::default();
        for (path, source) in [(user_settings, "user"), (project_settings, "project")] {
            let Some(path) = path else { continue };
            let Ok(text) = std::fs::read_to_string(path) else {
                continue;
            };
            let value: Value = match parse_lenient(&text) {
                Ok(value) => value,
                Err(error) => {
                    hooks.problems.push(format!("{}: {error}", path.display()));
                    continue;
                }
            };
            if source == "user"
                && value.get("disableAllHooks").and_then(Value::as_bool) == Some(true)
            {
                hooks.disabled = true;
            }
            let Some(events) = value.get("hooks").and_then(Value::as_object) else {
                continue;
            };
            hooks.add_events(events, source, &path.display().to_string());
        }
        hooks
    }

    /// Add `{Event: [groups]}` (from a settings file or a plugin) as `source`.
    pub fn add_events(&mut self, events: &serde_json::Map<String, Value>, source: &str, file: &str) {
        for (event, groups) in events {
            let Ok(groups) = serde_json::from_value::<Vec<Group>>(groups.clone()) else {
                self.problems.push(format!("{file}: hooks.{event} must be a list"));
                continue;
            };
            for group in groups {
                for raw in group.hooks {
                    match serde_json::from_value::<Handler>(raw.clone()) {
                        Ok(handler) => self.entries.push(HookEntry {
                            event: event.clone(),
                            matcher: group.matcher.clone().filter(|m| !m.trim().is_empty()),
                            handler,
                            source: source.into(),
                            file: file.into(),
                        }),
                        Err(error) => {
                            let kind = raw.get("type").and_then(Value::as_str).unwrap_or("?");
                            self.problems.push(format!("{file}: a `{kind}` hook in {event} was skipped: {error}"));
                        }
                    }
                }
            }
        }
    }

    /// The hooks to run for `event` on `target` (a tool name for tool events),
    /// without duplicates.
    pub fn matching(&self, event: &str, target: Option<&str>) -> Vec<&HookEntry> {
        if self.disabled {
            return Vec::new();
        }
        let mut seen = Vec::new();
        let mut out = Vec::new();
        for entry in self.entries.iter().filter(|e| e.event == event) {
            if !matches(entry.matcher.as_deref(), target) {
                continue;
            }
            let key = entry.handler.summary();
            if seen.contains(&key) {
                continue;
            }
            seen.push(key);
            out.push(entry);
        }
        out
    }
}

/// Settings files may hold `//` comments.
fn parse_lenient(text: &str) -> Result<Value, String> {
    serde_json::from_str(text).or_else(|first| {
        let stripped: String = text
            .lines()
            .filter(|line| !line.trim_start().starts_with("//"))
            .collect::<Vec<_>>()
            .join("\n");
        serde_json::from_str(&stripped).map_err(|_| first.to_string())
    })
}

/// Other names a tool may be written as in a matcher: evo's own name and its
/// PascalCase form (`bash` ↔ `Bash`, `edit` ↔ `Edit`/`MultiEdit`, …).
pub fn tool_aliases(tool: &str) -> Vec<String> {
    let mut names = vec![tool.to_string()];
    let extra: &[&str] = match tool {
        "bash" => &["Bash"],
        "powershell" => &["PowerShell", "Bash"],
        "read" => &["Read"],
        "edit" => &["Edit", "MultiEdit"],
        "write" => &["Write"],
        "agent" => &["Agent", "Task"],
        "skill" => &["Skill"],
        _ => &[],
    };
    names.extend(extra.iter().map(|s| s.to_string()));
    names
}

/// `*`/empty: always. Only `A-Z a-z 0-9 _ - , | space`: a list of exact names.
/// Anything else: a regular expression searched in the name.
pub fn matches(matcher: Option<&str>, target: Option<&str>) -> bool {
    let Some(matcher) = matcher
        .map(str::trim)
        .filter(|m| !m.is_empty() && *m != "*")
    else {
        return true;
    };
    let Some(target) = target else { return true };
    let names = tool_aliases(target);
    let plain = matcher
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '-' | ',' | '|' | ' '));
    if plain {
        return matcher
            .split(['|', ','])
            .map(str::trim)
            .filter(|m| !m.is_empty())
            .any(|m| names.iter().any(|n| n == m));
    }
    match regex::Regex::new(matcher) {
        Ok(re) => names.iter().any(|n| re.is_match(n)),
        Err(_) => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn matchers() {
        assert!(matches(None, Some("bash")));
        assert!(matches(Some("*"), Some("bash")));
        assert!(matches(Some("Bash"), Some("bash")));
        assert!(matches(Some("Bash"), Some("powershell")));
        assert!(matches(Some("edit|write"), Some("write")));
        assert!(matches(Some("Edit, Write"), Some("edit")));
        assert!(!matches(Some("Edit"), Some("bash")));
        assert!(matches(
            Some("mcp__github__.*"),
            Some("mcp__github__create_issue")
        ));
        assert!(!matches(Some("mcp__github__.*"), Some("mcp__linear__list")));
        assert!(!matches(Some("(bad"), Some("bash")));
    }

    #[test]
    fn loads_user_and_project_hooks_and_skips_bad_ones() {
        let dir = tempfile::tempdir().unwrap();
        let user = dir.path().join("user.json");
        let project = dir.path().join("project.json");
        std::fs::write(
            &user,
            r#"{
              // a comment
              "hooks": {
                "PreToolUse": [ { "matcher": "bash", "hooks": [ { "type": "command", "command": "check.sh" } ] } ],
                "Stop": [ { "hooks": [ { "type": "command", "command": "notify.sh" }, { "type": "prompt", "prompt": "x" } ] } ]
              }
            }"#,
        )
        .unwrap();
        std::fs::write(
            &project,
            r#"{"hooks": {"PreToolUse": [ { "matcher": "bash", "hooks": [ { "type": "command", "command": "check.sh" }, { "type": "http", "url": "http://127.0.0.1:9/h" } ] } ]}}"#,
        )
        .unwrap();
        let hooks = Hooks::load(Some(&user), Some(&project));
        assert_eq!(hooks.entries.len(), 4);
        assert_eq!(hooks.problems.len(), 1, "{:?}", hooks.problems);
        // The project's copy of check.sh is the same handler: it runs once.
        let pre = hooks.matching("PreToolUse", Some("bash"));
        assert_eq!(pre.len(), 2);
        assert!(hooks.matching("PreToolUse", Some("read")).is_empty());
        assert_eq!(hooks.matching("Stop", None).len(), 1);
    }

    #[test]
    fn disable_all_hooks() {
        let dir = tempfile::tempdir().unwrap();
        let user = dir.path().join("user.json");
        std::fs::write(
            &user,
            r#"{"disableAllHooks": true, "hooks": {"Stop": [ { "hooks": [ { "type": "command", "command": "a" } ] } ]}}"#,
        )
        .unwrap();
        let hooks = Hooks::load(Some(&user), None);
        assert!(hooks.disabled);
        assert!(hooks.matching("Stop", None).is_empty());
    }
}
