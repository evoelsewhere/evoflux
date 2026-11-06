//! The connectors file: `{"mcpServers": {name: server}}`.
//!
//! A server is either a command (`command`, `args`, `env`, `cwd`) or a URL
//! (`type: "http"` — the default for a URL — or `"sse"`, with `headers`).
//! `${VAR}` and `${VAR:-default}` in commands, arguments, env values, URLs
//! and headers expand from the environment when connecting. evo adds
//! `disabled` and `toolPermissions` (`allow`, `ask`, `block` per tool).
//! Keys it does not know are kept when the file is written back.

use std::collections::BTreeMap;
use std::path::Path;

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

/// What happens when the agent calls a tool.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Permission {
    /// Runs without asking.
    Allow,
    /// Asks the person each time (they can switch it to `allow`).
    Ask,
    /// Never offered to the agent.
    Block,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ServerConfig {
    /// `stdio`, `http` or `sse`; inferred from `command` / `url` when absent.
    #[serde(rename = "type", default, skip_serializing_if = "Option::is_none")]
    pub kind: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub command: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub args: Vec<String>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub env: BTreeMap<String, String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cwd: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub url: Option<String>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub headers: BTreeMap<String, String>,
    /// Kept in the list but not connected.
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub disabled: bool,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub tool_permissions: BTreeMap<String, Permission>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// How to reach a server, with variables expanded.
#[derive(Debug, Clone, PartialEq)]
pub enum Transport {
    Stdio {
        command: String,
        args: Vec<String>,
        env: BTreeMap<String, String>,
        cwd: Option<String>,
    },
    Http {
        url: String,
        headers: BTreeMap<String, String>,
    },
    Sse {
        url: String,
        headers: BTreeMap<String, String>,
    },
}

impl ServerConfig {
    pub fn transport(&self) -> Result<Transport, String> {
        let kind = self.kind.clone().unwrap_or_else(|| {
            if self.url.is_some() {
                "http".into()
            } else {
                "stdio".into()
            }
        });
        let headers = || {
            self.headers
                .iter()
                .map(|(k, v)| (k.clone(), expand(v)))
                .collect()
        };
        match kind.as_str() {
            "stdio" => {
                let command = self
                    .command
                    .as_deref()
                    .map(str::trim)
                    .filter(|c| !c.is_empty());
                let command = command.ok_or("a command is required")?;
                Ok(Transport::Stdio {
                    command: expand(command),
                    args: self.args.iter().map(|a| expand(a)).collect(),
                    env: self
                        .env
                        .iter()
                        .map(|(k, v)| (k.clone(), expand(v)))
                        .collect(),
                    cwd: self.cwd.as_deref().map(expand),
                })
            }
            "http" | "streamable-http" | "sse" => {
                let url = self.url.as_deref().map(str::trim).filter(|u| !u.is_empty());
                let url = expand(url.ok_or("a URL is required")?);
                if !(url.starts_with("http://") || url.starts_with("https://")) {
                    return Err("the URL must start with http:// or https://".into());
                }
                if kind == "sse" {
                    Ok(Transport::Sse {
                        url,
                        headers: headers(),
                    })
                } else {
                    Ok(Transport::Http {
                        url,
                        headers: headers(),
                    })
                }
            }
            other => Err(format!("unknown server type `{other}`")),
        }
    }

    /// The command or URL, for display (variables not expanded, no secrets).
    pub fn summary(&self) -> String {
        match (&self.command, &self.url) {
            (Some(command), _) => std::iter::once(command.as_str())
                .chain(self.args.iter().map(String::as_str))
                .collect::<Vec<_>>()
                .join(" "),
            (None, Some(url)) => url.clone(),
            _ => String::new(),
        }
    }
}

/// The whole file. Other top-level keys are kept.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct ConfigFile {
    #[serde(rename = "mcpServers", default)]
    pub servers: BTreeMap<String, ServerConfig>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

impl ConfigFile {
    /// Read `path`; a missing file is an empty list.
    pub fn load(path: &Path) -> Result<Self, String> {
        match std::fs::read_to_string(path) {
            Ok(text) if text.trim().is_empty() => Ok(Self::default()),
            Ok(text) => serde_json::from_str(&text).map_err(|e| format!("{}: {e}", path.display())),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(Self::default()),
            Err(e) => Err(format!("{}: {e}", path.display())),
        }
    }

    pub fn save(&self, path: &Path) -> Result<(), String> {
        if let Some(dir) = path.parent() {
            std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
        }
        let text = serde_json::to_string_pretty(self).map_err(|e| e.to_string())?;
        let tmp = path.with_extension("json.tmp");
        std::fs::write(&tmp, text + "\n").map_err(|e| e.to_string())?;
        std::fs::rename(&tmp, path).map_err(|e| e.to_string())
    }
}

/// A server name: letters, digits, `-` and `_`, at most 48 characters (it
/// becomes part of tool names, which models limit to 64).
pub fn valid_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 48
        && name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
}

/// `${VAR}` and `${VAR:-default}` from the environment; an unknown variable
/// without a default is left as written.
pub fn expand(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut rest = text;
    while let Some(start) = rest.find("${") {
        out.push_str(&rest[..start]);
        let after = &rest[start + 2..];
        let Some(end) = after.find('}') else {
            out.push_str(&rest[start..]);
            return out;
        };
        let inner = &after[..end];
        let (name, default) = match inner.split_once(":-") {
            Some((name, default)) => (name, Some(default)),
            None => (inner, None),
        };
        match (std::env::var(name).ok().filter(|v| !v.is_empty()), default) {
            (Some(value), _) => out.push_str(&value),
            (None, Some(default)) => out.push_str(default),
            (None, None) => out.push_str(&rest[start..start + 3 + end]),
        }
        rest = &after[end + 1..];
    }
    out.push_str(rest);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_both_kinds_and_keeps_unknown_keys() {
        let text = r#"{
            "mcpServers": {
                "files": {"command": "npx", "args": ["-y", "server-files", "${HOME_TEST_MISSING:-/tmp}"], "note": "kept"},
                "remote": {"type": "http", "url": "https://example.com/mcp", "headers": {"Authorization": "Bearer x"},
                           "toolPermissions": {"delete": "block"}, "disabled": true}
            },
            "other": 1
        }"#;
        let file: ConfigFile = serde_json::from_str(text).unwrap();
        let files = &file.servers["files"];
        assert_eq!(
            files.transport().unwrap(),
            Transport::Stdio {
                command: "npx".into(),
                args: vec!["-y".into(), "server-files".into(), "/tmp".into()],
                env: BTreeMap::new(),
                cwd: None
            }
        );
        let remote = &file.servers["remote"];
        assert!(matches!(
            remote.transport().unwrap(),
            Transport::Http { .. }
        ));
        assert_eq!(remote.tool_permissions["delete"], Permission::Block);
        let back = serde_json::to_value(&file).unwrap();
        assert_eq!(back["other"], 1);
        assert_eq!(back["mcpServers"]["files"]["note"], "kept");
        assert_eq!(back["mcpServers"]["remote"]["disabled"], true);
        assert!(back["mcpServers"]["files"].get("disabled").is_none());
    }

    #[test]
    fn expands_variables() {
        std::env::set_var("EVO_MCP_TEST_TOKEN", "abc");
        assert_eq!(expand("Bearer ${EVO_MCP_TEST_TOKEN}"), "Bearer abc");
        assert_eq!(expand("${EVO_MCP_TEST_NOPE:-fallback}/x"), "fallback/x");
        assert_eq!(expand("${EVO_MCP_TEST_NOPE}"), "${EVO_MCP_TEST_NOPE}");
        assert_eq!(expand("no vars"), "no vars");
    }

    #[test]
    fn rejects_bad_urls_and_names() {
        let bad = ServerConfig {
            url: Some("ftp://x".into()),
            ..Default::default()
        };
        assert!(bad.transport().is_err());
        assert!(valid_name("github_2"));
        assert!(!valid_name("has space"));
    }
}
