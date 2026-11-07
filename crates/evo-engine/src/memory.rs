//! Memory: what the agent keeps across chats.
//!
//! * **Where**: personal memories (every project) in `<agent dir>/memory/`;
//!   a project's in `<agent dir>/projects/<folder slug>/memory/`, outside the
//!   repository so they stay private.
//! * **Shape**: one markdown file per memory, `<name>.md`, with frontmatter
//!   `name`, `description` (one line, used to judge relevance), `type`
//!   (`user`, `feedback`, `project` or `reference`) and `updated`, then the
//!   memory itself. `MEMORY.md` in each folder is the index, one line per
//!   memory, rewritten on every change.
//! * **In a chat**: the system prompt carries how to use memory and both
//!   indexes ([`prompt_block`], re-read on reload); the `memory` tool saves,
//!   reads, lists and deletes ([`create_memory_tool`]).
//! * **In the app**: the Memory panel lists, edits, adds and deletes, and
//!   switches memory off (`memoryEnabled: false` in settings) — RPC
//!   `list_memories`, `save_memory`, `delete_memory`, `set_memory_enabled`.

use std::path::{Path, PathBuf};
use std::sync::Arc;

use async_trait::async_trait;
use evo_agent::agent_tool::AgentTool;
use evo_agent::error::AgentError;
use evo_agent::types::{AgentToolResult, TextContentOrImage, ToolExecutionMode, ToolResultPartial};
use evo_ai::types::{Schema, Tool};
use evo_harness::frontmatter::parse_frontmatter;
use serde_json::{json, Value};
use tokio_util::sync::CancellationToken;

pub const TYPES: &[&str] = &["user", "feedback", "project", "reference"];
/// Index lines put in the system prompt per scope.
const MAX_INDEX_LINES: usize = 200;
const MAX_CONTENT: usize = 20_000;
const MAX_DESCRIPTION: usize = 200;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Scope {
    Personal,
    Project,
}

impl Scope {
    pub fn parse(text: &str) -> Result<Self, String> {
        match text {
            "personal" | "user" | "global" => Ok(Scope::Personal),
            "project" => Ok(Scope::Project),
            other => Err(format!("unknown scope `{other}` (personal or project)")),
        }
    }

    fn label(self) -> &'static str {
        match self {
            Scope::Personal => "personal",
            Scope::Project => "project",
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct Memory {
    pub name: String,
    pub description: String,
    pub kind: String,
    pub content: String,
    pub updated: u64,
    pub path: PathBuf,
}

pub fn enabled() -> bool {
    crate::settings::load_settings()
        .ok()
        .and_then(|s| s.memory_enabled)
        .unwrap_or(true)
}

pub fn set_enabled(on: bool) -> Result<(), String> {
    crate::settings::update_settings_value(|settings| {
        if on {
            settings.remove("memoryEnabled");
        } else {
            settings.insert("memoryEnabled".into(), json!(false));
        }
    })
}

/// A folder path as one folder name: `C:\work\app` → `C--work-app`.
pub fn slug(cwd: &Path) -> String {
    cwd.to_string_lossy()
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() { c } else { '-' })
        .collect()
}

pub fn dir_in(agent_dir: &Path, scope: Scope, cwd: &Path) -> PathBuf {
    match scope {
        Scope::Personal => agent_dir.join("memory"),
        Scope::Project => agent_dir.join("projects").join(slug(cwd)).join("memory"),
    }
}

fn dir(scope: Scope, cwd: &Path) -> Result<PathBuf, String> {
    let agent = crate::config::agent_dir().map_err(|e| e.to_string())?;
    Ok(dir_in(&agent, scope, cwd))
}

/// `Prefers Tabs!` → `prefers-tabs`.
pub fn clean_name(name: &str) -> Result<String, String> {
    let mut out = String::new();
    for c in name.trim().chars() {
        if c.is_ascii_alphanumeric() {
            out.push(c.to_ascii_lowercase());
        } else if !out.ends_with('-') && !out.is_empty() {
            out.push('-');
        }
    }
    let out: String = out.trim_end_matches('-').chars().take(64).collect();
    if out.is_empty() || out == "memory" {
        return Err("a memory needs a short name (letters, digits, dashes)".into());
    }
    Ok(out)
}

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

fn one_line(text: &str, max: usize) -> String {
    let line = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if line.chars().count() <= max {
        line
    } else {
        let mut cut: String = line.chars().take(max - 1).collect();
        cut.push('…');
        cut
    }
}

fn read(path: &Path) -> Option<Memory> {
    let source = std::fs::read_to_string(path).ok()?;
    let stem = path.file_stem()?.to_string_lossy().into_owned();
    let (front, body) = parse_frontmatter(source.trim_start_matches('\u{feff}'))
        .unwrap_or((json!({}), source.clone()));
    let text = |key: &str| front.get(key).and_then(Value::as_str).map(str::to_string);
    Some(Memory {
        name: text("name").unwrap_or_else(|| stem.clone()),
        description: text("description").unwrap_or_else(|| one_line(&body, 120)),
        kind: text("type")
            .or_else(|| {
                front
                    .pointer("/metadata/type")
                    .and_then(Value::as_str)
                    .map(str::to_string)
            })
            .unwrap_or_else(|| "project".into()),
        content: body.trim().to_string(),
        updated: front
            .get("updated")
            .and_then(Value::as_u64)
            .unwrap_or_else(|| {
                std::fs::metadata(path)
                    .and_then(|m| m.modified())
                    .ok()
                    .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                    .map_or(0, |d| d.as_millis() as u64)
            }),
        path: path.to_path_buf(),
    })
}

/// The memories in `dir`, newest first.
pub fn list_dir(dir: &Path) -> Vec<Memory> {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return Vec::new();
    };
    let mut out: Vec<Memory> = entries
        .flatten()
        .map(|e| e.path())
        .filter(|p| {
            p.extension().is_some_and(|e| e == "md")
                && p.file_name().is_some_and(|n| n != "MEMORY.md")
        })
        .filter_map(|p| read(&p))
        .collect();
    out.sort_by(|a, b| b.updated.cmp(&a.updated).then(a.name.cmp(&b.name)));
    out
}

fn write_index(dir: &Path) -> Result<(), String> {
    let memories = list_dir(dir);
    let index = dir.join("MEMORY.md");
    if memories.is_empty() {
        let _ = std::fs::remove_file(index);
        return Ok(());
    }
    let mut text = String::new();
    for m in &memories {
        text.push_str(&format!(
            "- [{}]({}.md) — {}\n",
            m.name, m.name, m.description
        ));
    }
    std::fs::write(index, text).map_err(|e| e.to_string())
}

/// Save (or replace) a memory; `previous` renames one.
pub fn save_in(
    dir: &Path,
    name: &str,
    description: &str,
    kind: &str,
    content: &str,
    previous: Option<&str>,
) -> Result<Memory, String> {
    let name = clean_name(name)?;
    if !TYPES.contains(&kind) {
        return Err(format!("type must be one of {}", TYPES.join(", ")));
    }
    let content = content.trim();
    if content.is_empty() {
        return Err("a memory needs content".into());
    }
    if content.chars().count() > MAX_CONTENT {
        return Err(format!(
            "keep a memory under {MAX_CONTENT} characters; split it"
        ));
    }
    let description = one_line(
        if description.trim().is_empty() {
            content
        } else {
            description
        },
        MAX_DESCRIPTION,
    );
    std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    let path = dir.join(format!("{name}.md"));
    let updated = now_ms();
    let front = format!(
        "---\nname: {name}\ndescription: {}\ntype: {kind}\nupdated: {updated}\n---\n\n",
        serde_json::to_string(&description).unwrap_or_default()
    );
    std::fs::write(&path, format!("{front}{}\n", content.replace("\r\n", "\n")))
        .map_err(|e| e.to_string())?;
    if let Some(old) = previous.and_then(|p| clean_name(p).ok()) {
        if old != name {
            let _ = std::fs::remove_file(dir.join(format!("{old}.md")));
        }
    }
    write_index(dir)?;
    read(&path).ok_or_else(|| "could not read the memory back".into())
}

pub fn delete_in(dir: &Path, name: &str) -> Result<(), String> {
    let name = clean_name(name)?;
    match std::fs::remove_file(dir.join(format!("{name}.md"))) {
        Ok(()) => write_index(dir),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            Err(format!("no memory named `{name}`"))
        }
        Err(e) => Err(e.to_string()),
    }
}

fn find_in(dir: &Path, name: &str) -> Option<Memory> {
    let name = clean_name(name).ok()?;
    read(&dir.join(format!("{name}.md")))
}

fn index_lines(memories: &[Memory]) -> String {
    let mut lines: Vec<String> = memories
        .iter()
        .take(MAX_INDEX_LINES)
        .map(|m| format!("- {} ({}): {}", m.name, m.kind, m.description))
        .collect();
    if memories.len() > MAX_INDEX_LINES {
        lines.push(format!(
            "- … {} more; `memory` with action `list` shows them all",
            memories.len() - MAX_INDEX_LINES
        ));
    }
    if lines.is_empty() {
        "(none yet)".into()
    } else {
        lines.join("\n")
    }
}

/// How to use memory, and what is in it, for the system prompt.
pub fn prompt_block(cwd: &Path) -> Option<String> {
    if !enabled() {
        return None;
    }
    let personal = list_dir(&dir(Scope::Personal, cwd).ok()?);
    let project = list_dir(&dir(Scope::Project, cwd).ok()?);
    Some(format!(
        "# Memory\n\n\
You have a memory that lasts across chats, kept with the `memory` tool. Use it to build up \
what makes you more useful to this person over time.\n\n\
Save a memory when you learn something that will matter in later chats and is not in the code \
or the project's files:\n\
- `user`: who they are, their role, expertise and preferences;\n\
- `feedback`: how they want you to work — corrections and approaches they confirmed, with the \
reason, so you can apply it to new cases;\n\
- `project`: goals, decisions, deadlines and constraints of ongoing work (write dates in full);\n\
- `reference`: where things live outside the code (dashboards, docs, tickets).\n\
Use scope `personal` for what holds in every project and `project` for this one. Update a \
memory that already covers the fact (same name) rather than adding a near-duplicate; delete \
one that turns out wrong. Do not save secrets, one-off details of this chat, or what the \
repository or its history already records. When the person asks you to remember or forget \
something, do it right away.\n\n\
The lists below are names and one-line descriptions. Read a memory (`action: read`) before \
relying on it: it may be out of date — check what it names still exists.\n\n\
## Personal memories\n{}\n\n## Memories for this project ({})\n{}",
        index_lines(&personal),
        cwd.display(),
        index_lines(&project),
    ))
}

fn entry(m: &Memory, scope: Scope) -> Value {
    json!({
        "name": m.name,
        "description": m.description,
        "type": m.kind,
        "content": m.content,
        "updated": m.updated,
        "path": m.path,
        "scope": scope.label(),
    })
}

/// Everything for the Memory panel.
pub fn describe(cwd: &Path) -> Result<Value, String> {
    let personal = dir(Scope::Personal, cwd)?;
    let project = dir(Scope::Project, cwd)?;
    Ok(json!({
        "enabled": enabled(),
        "personal": {
            "dir": personal,
            "items": list_dir(&personal).iter().map(|m| entry(m, Scope::Personal)).collect::<Vec<_>>(),
        },
        "project": {
            "dir": project,
            "folder": cwd,
            "items": list_dir(&project).iter().map(|m| entry(m, Scope::Project)).collect::<Vec<_>>(),
        },
    }))
}

pub fn save(
    cwd: &Path,
    scope: Scope,
    name: &str,
    description: &str,
    kind: &str,
    content: &str,
    previous: Option<&str>,
) -> Result<Value, String> {
    let m = save_in(
        &dir(scope, cwd)?,
        name,
        description,
        kind,
        content,
        previous,
    )?;
    Ok(entry(&m, scope))
}

pub fn delete(cwd: &Path, scope: Scope, name: &str) -> Result<(), String> {
    delete_in(&dir(scope, cwd)?, name)
}

// ── The `memory` tool ───────────────────────────────────────────────────────

pub struct MemoryTool {
    schema: Tool,
    cwd: PathBuf,
}

pub fn create_memory_tool(cwd: PathBuf) -> Arc<dyn AgentTool> {
    Arc::new(MemoryTool {
        schema: Tool {
            name: "memory".into(),
            description: "Your memory across chats (see # Memory in the system prompt). Actions: \
                 `save` (name, description, type, content, scope; the same name replaces it), \
                 `read` (name, scope), `list` (scope, optional), `delete` (name, scope)."
                .into(),
            parameters: Schema::new(json!({
                "type": "object",
                "properties": {
                    "action": { "type": "string", "enum": ["save", "read", "list", "delete"] },
                    "scope": { "type": "string", "enum": ["personal", "project"], "description": "personal: every project; project: this one. Default project." },
                    "name": { "type": "string", "description": "Short kebab-case name, e.g. prefers-small-commits." },
                    "description": { "type": "string", "description": "One line saying what it holds, used to judge relevance later." },
                    "type": { "type": "string", "enum": TYPES },
                    "content": { "type": "string", "description": "The memory. For feedback and project memories, add why and how to apply it." }
                },
                "required": ["action"],
                "additionalProperties": false
            })),
            constrained_sampling: None,
        },
        cwd,
    })
}

fn arg<'a>(params: &'a Value, key: &str) -> &'a str {
    params.get(key).and_then(Value::as_str).unwrap_or("")
}

impl MemoryTool {
    fn run(&self, params: &Value) -> Result<(String, Value), String> {
        if !enabled() {
            return Err("memory is switched off in the app".into());
        }
        let action = arg(params, "action");
        let scope_text = arg(params, "scope");
        let scope = if scope_text.is_empty() {
            Scope::Project
        } else {
            Scope::parse(scope_text)?
        };
        let folder = dir(scope, &self.cwd)?;
        match action {
            "save" => {
                let kind = match arg(params, "type") {
                    "" => "project",
                    k => k,
                };
                let existed = find_in(&folder, arg(params, "name")).is_some();
                let m = save_in(
                    &folder,
                    arg(params, "name"),
                    arg(params, "description"),
                    kind,
                    arg(params, "content"),
                    None,
                )?;
                let verb = if existed { "Updated" } else { "Saved" };
                Ok((
                    format!("{verb} {} memory `{}`.", scope.label(), m.name),
                    json!({ "memory": entry(&m, scope), "action": if existed { "updated" } else { "saved" } }),
                ))
            }
            "read" => {
                let m = find_in(&folder, arg(params, "name")).ok_or_else(|| {
                    format!(
                        "no {} memory named `{}`",
                        scope.label(),
                        arg(params, "name")
                    )
                })?;
                Ok((
                    format!(
                        "{} ({}, {}): {}\n\n{}",
                        m.name,
                        m.kind,
                        scope.label(),
                        m.description,
                        m.content
                    ),
                    json!({ "memory": entry(&m, scope), "action": "read" }),
                ))
            }
            "list" => {
                let scopes: Vec<Scope> = if scope_text.is_empty() {
                    vec![Scope::Personal, Scope::Project]
                } else {
                    vec![scope]
                };
                let mut text = String::new();
                for s in scopes {
                    let items = list_dir(&dir(s, &self.cwd)?);
                    text.push_str(&format!("## {}\n{}\n\n", s.label(), index_lines(&items)));
                }
                Ok((text.trim_end().to_string(), json!({ "action": "list" })))
            }
            "delete" => {
                delete_in(&folder, arg(params, "name"))?;
                Ok((
                    format!(
                        "Deleted {} memory `{}`.",
                        scope.label(),
                        arg(params, "name")
                    ),
                    json!({ "action": "deleted", "memory": { "name": arg(params, "name"), "scope": scope.label() } }),
                ))
            }
            other => Err(format!("unknown action `{other}`")),
        }
    }
}

#[async_trait]
impl AgentTool for MemoryTool {
    fn schema(&self) -> &Tool {
        &self.schema
    }

    fn label(&self) -> &str {
        "memory"
    }

    fn execution_mode(&self) -> ToolExecutionMode {
        ToolExecutionMode::Sequential
    }

    async fn execute(
        &self,
        _tool_call_id: &str,
        params: Value,
        _signal: CancellationToken,
        _on_update: Arc<dyn Fn(ToolResultPartial) + Send + Sync>,
    ) -> Result<AgentToolResult, AgentError> {
        let (text, details) = self.run(&params).map_err(AgentError::Validation)?;
        Ok(AgentToolResult {
            content: vec![TextContentOrImage::text(text)],
            details,
            ..Default::default()
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn names_are_cleaned() {
        assert_eq!(clean_name(" Prefers Tabs! ").unwrap(), "prefers-tabs");
        assert!(clean_name("  !! ").is_err());
        assert!(clean_name("MEMORY").is_err());
    }

    #[test]
    fn save_list_rename_and_delete_keep_the_index() {
        let dir = tempfile::tempdir().unwrap();
        let d = dir.path();
        save_in(
            d,
            "prefers-tabs",
            "Uses tabs",
            "user",
            "Tabs, width 4.",
            None,
        )
        .unwrap();
        save_in(
            d,
            "release-freeze",
            "",
            "project",
            "Freeze from 2026-12-01.\nWhy: launch.",
            None,
        )
        .unwrap();
        let all = list_dir(d);
        assert_eq!(all.len(), 2);
        let index = std::fs::read_to_string(d.join("MEMORY.md")).unwrap();
        assert!(
            index.contains("[prefers-tabs](prefers-tabs.md) — Uses tabs"),
            "{index}"
        );
        // An empty description falls back to the content's first words.
        assert!(index.contains("Freeze from 2026-12-01."), "{index}");
        // Saving under a new name with `previous` renames.
        save_in(
            d,
            "indent-style",
            "Indent",
            "user",
            "Tabs.",
            Some("prefers-tabs"),
        )
        .unwrap();
        assert!(!d.join("prefers-tabs.md").exists());
        assert!(find_in(d, "indent-style").is_some());
        assert!(save_in(d, "x", "", "secret", "y", None).is_err());
        delete_in(d, "indent-style").unwrap();
        delete_in(d, "release-freeze").unwrap();
        assert!(!d.join("MEMORY.md").exists());
        assert!(delete_in(d, "gone").is_err());
    }

    #[test]
    fn project_memories_live_outside_the_project() {
        let agent = Path::new("/home/me/.evo/agent");
        let p = dir_in(agent, Scope::Project, Path::new("/work/app"));
        assert!(p.starts_with(agent));
        assert!(p.ends_with("memory"));
        assert_eq!(slug(Path::new("C:\\work\\app")), "C--work-app");
    }
}
