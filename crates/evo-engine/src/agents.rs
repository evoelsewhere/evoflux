//! Agent types for the built-in `agent` tool: who a delegated child is.
//!
//! Markdown files with YAML frontmatter, like skills:
//!
//! ```markdown
//! ---
//! name: reviewer
//! description: Reviews a change for bugs. Use after editing several files.
//! tools: [read, bash]        # optional allow-list; default: the parent's tools
//! model: claude-sonnet-5-5   # optional; `inherit` (default) keeps the parent's
//! isolation: worktree        # optional; run in its own Git worktree by default
//! ---
//! You review code changes. Report bugs with file:line and a fix …
//! ```
//!
//! Found in `<cwd>/.evo/agents/*.md` (project) and `~/.evo/agent/agents/*.md`
//! (user); a project type wins over a user type of the same name, both win
//! over the built-in `general`, `explore` and `plan`.

use std::path::{Path, PathBuf};

use serde_json::Value;

#[derive(Debug, Clone, PartialEq)]
pub struct AgentType {
    pub name: String,
    pub description: String,
    /// `None`: every tool the parent has.
    pub tools: Option<Vec<String>>,
    /// `None` or `inherit`: the parent's model.
    pub model: Option<String>,
    pub worktree: bool,
    /// Instructions the child starts with, before its task.
    pub prompt: String,
    /// The file it came from; `None` for built-ins.
    pub source: Option<PathBuf>,
}

pub const DEFAULT_TYPE: &str = "general";

/// The types every session has.
pub fn builtin() -> Vec<AgentType> {
    let make = |name: &str, description: &str, tools: Option<&[&str]>, prompt: &str| AgentType {
        name: name.into(),
        description: description.into(),
        tools: tools.map(|t| t.iter().map(|s| s.to_string()).collect()),
        model: None,
        worktree: false,
        prompt: prompt.into(),
        source: None,
    };
    vec![
        make(
            "general",
            "General-purpose agent for multi-step tasks: researching, changing code, running commands. Use when a task is self-contained and its intermediate steps would clutter this conversation.",
            None,
            "You are a delegated general-purpose agent. Do the task completely, then reply with a concise report of what you found or changed (files with paths, commands run, anything left undone).",
        ),
        make(
            "explore",
            "Read-only search agent for finding code and answering questions about the codebase across many files. Returns conclusions with file:line references, not file dumps.",
            Some(&["read", "bash", "powershell"]),
            "You are a read-only exploration agent. Find what the task asks for by reading files and running read-only commands (search, list, git log/show/diff). Never modify, create or delete files and never run commands that change state. Reply with conclusions and file:line references, quoting only the lines that matter.",
        ),
        make(
            "plan",
            "Planning agent: studies the code and returns a step-by-step implementation plan with the files to change, without changing anything.",
            Some(&["read", "bash", "powershell"]),
            "You are a planning agent. Study the relevant code with read-only tools and commands, change nothing, and reply with an implementation plan: the approach, the files and functions to change, the order of steps, risks, and how to verify the result.",
        ),
    ]
}

/// The agent folders for `cwd`, project first.
pub fn dirs(cwd: &Path) -> Vec<PathBuf> {
    let mut dirs = vec![cwd.join(".evo").join("agents")];
    if let Ok(agent) = crate::config::agent_dir() {
        dirs.push(agent.join("agents"));
    }
    dirs
}

/// A tool name as evo calls it, also when written in PascalCase
/// (`Read` → `read`, `Grep`/`Glob` → `bash`, `MultiEdit` → `edit`).
fn evo_tool_name(name: &str) -> String {
    let lower = name.trim().to_ascii_lowercase();
    match lower.as_str() {
        "grep" | "glob" | "ls" | "bashoutput" | "killshell" => "bash".into(),
        "multiedit" | "notebookedit" => "edit".into(),
        "task" => "agent".into(),
        _ => lower,
    }
}

/// Every agent type for `cwd`: project, user, then built-in; first name wins.
pub fn load(cwd: &Path) -> Vec<AgentType> {
    let mut types = load_from(&dirs(cwd));
    // Enabled plugins' agent types, named `plugin:name`.
    for (plugin, file) in crate::plugins::agent_files() {
        match parse(&file) {
            Ok(mut agent) => {
                agent.name = format!("{plugin}:{}", agent.name);
                if !types.iter().any(|t| t.name == agent.name) {
                    types.push(agent);
                }
            }
            Err(error) => tracing::warn!("skipping agent type {}: {error}", file.display()),
        }
    }
    types
}

pub fn load_from(dirs: &[PathBuf]) -> Vec<AgentType> {
    let mut types: Vec<AgentType> = Vec::new();
    for dir in dirs {
        let Ok(entries) = std::fs::read_dir(dir) else { continue };
        let mut files: Vec<PathBuf> = entries
            .flatten()
            .map(|entry| entry.path())
            .filter(|path| path.extension().is_some_and(|ext| ext == "md") && path.is_file())
            .collect();
        files.sort();
        for file in files {
            match parse(&file) {
                Ok(agent) if !types.iter().any(|t| t.name == agent.name) => types.push(agent),
                Ok(_) => {}
                Err(error) => tracing::warn!("skipping agent type {}: {error}", file.display()),
            }
        }
    }
    for agent in builtin() {
        if !types.iter().any(|t| t.name == agent.name) {
            types.push(agent);
        }
    }
    types
}

fn valid_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 64
        && name.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
}

/// One agent type file. `name` defaults to the file name.
pub fn parse(file: &Path) -> Result<AgentType, String> {
    let text = std::fs::read_to_string(file).map_err(|e| e.to_string())?;
    let (front, body) = evo_harness::frontmatter::parse_frontmatter(&text)?;
    let stem = file.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
    let name = front.get("name").and_then(Value::as_str).map(str::to_string).unwrap_or(stem);
    if !valid_name(&name) {
        return Err(format!("name `{name}` must be lowercase letters, digits and hyphens (at most 64)"));
    }
    let description = front
        .get("description")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|d| !d.is_empty())
        .ok_or("a description is required")?;
    if description.len() > 1024 {
        return Err("description is longer than 1024 characters".into());
    }
    // `tools: [read, bash]` or `tools: read, bash`.
    let tools: Option<Vec<String>> = match front.get("tools") {
        None | Some(Value::Null) => None,
        Some(Value::Array(items)) => {
            Some(items.iter().filter_map(Value::as_str).map(evo_tool_name).collect())
        }
        Some(Value::String(list)) => Some(
            list.split(',').map(evo_tool_name).filter(|s| !s.is_empty()).collect(),
        ),
        Some(_) => return Err("tools must be a list of tool names".into()),
    };
    let tools = tools.map(|mut tools| {
        let mut seen = std::collections::HashSet::new();
        tools.retain(|tool| seen.insert(tool.clone()));
        tools
    });
    let model = front
        .get("model")
        .and_then(Value::as_str)
        .map(str::trim)
        // Short family aliases are not model ids: use the parent's model.
        .filter(|m| !m.is_empty() && !matches!(*m, "inherit" | "sonnet" | "opus" | "haiku" | "fable"))
        .map(str::to_string);
    let worktree = front.get("isolation").and_then(Value::as_str) == Some("worktree");
    let prompt = body.trim().to_string();
    Ok(AgentType {
        name,
        description: description.to_string(),
        tools,
        model,
        worktree,
        prompt,
        source: Some(file.to_path_buf()),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write(dir: &Path, name: &str, text: &str) {
        std::fs::create_dir_all(dir).unwrap();
        std::fs::write(dir.join(name), text).unwrap();
    }

    #[test]
    fn files_define_types_and_project_wins() {
        let root = tempfile::tempdir().unwrap();
        let project = root.path().join("project");
        let user = root.path().join("user");
        write(
            &project,
            "reviewer.md",
            "---\ndescription: Reviews changes.\ntools: [read, bash]\nmodel: some-model\nisolation: worktree\n---\nYou review code.\n",
        );
        write(&user, "reviewer.md", "---\ndescription: The user's reviewer.\n---\nUser version.\n");
        write(&user, "writer.md", "---\nname: docs-writer\ndescription: Writes docs.\ntools: read, write\n---\nWrite docs.\n");
        write(&user, "broken.md", "---\nname: Bad Name\ndescription: x\n---\n");
        write(&user, "nodesc.md", "no frontmatter at all\n");

        let types = load_from(&[project, user]);
        let reviewer = types.iter().find(|t| t.name == "reviewer").unwrap();
        assert_eq!(reviewer.description, "Reviews changes.");
        assert_eq!(reviewer.tools.as_deref(), Some(&["read".to_string(), "bash".to_string()][..]));
        assert_eq!(reviewer.model.as_deref(), Some("some-model"));
        assert!(reviewer.worktree);
        assert_eq!(reviewer.prompt, "You review code.");
        let writer = types.iter().find(|t| t.name == "docs-writer").unwrap();
        assert_eq!(writer.tools.as_deref(), Some(&["read".to_string(), "write".to_string()][..]));
        assert!(writer.model.is_none());
        // Invalid files are skipped; built-ins are always there.
        assert!(!types.iter().any(|t| t.name == "Bad Name" || t.name == "nodesc"));
        for name in ["general", "explore", "plan"] {
            assert!(types.iter().any(|t| t.name == name), "missing {name}");
        }
    }

    #[test]
    fn a_file_can_replace_a_builtin() {
        let root = tempfile::tempdir().unwrap();
        write(root.path(), "explore.md", "---\ndescription: My explorer.\nmodel: inherit\n---\nMine.\n");
        let types = load_from(&[root.path().to_path_buf()]);
        let explore: Vec<_> = types.iter().filter(|t| t.name == "explore").collect();
        assert_eq!(explore.len(), 1);
        assert_eq!(explore[0].description, "My explorer.");
        assert!(explore[0].model.is_none(), "`inherit` means the parent's model");
    }
}
