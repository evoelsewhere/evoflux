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
//! access: read-only          # optional; refuse writes and state-changing commands
//! thinking: high             # optional; `inherit` (default) keeps the parent's
//! maxTurns: 40               # optional; model turns per run (1-100, default 32)
//! ---
//! You review code changes. Report bugs with file:line and a fix …
//! ```
//!
//! Found in `<cwd>/.evo/agents/*.md` (project) and `~/.evo/agent/agents/*.md`
//! (user); a project type wins over a user type of the same name, both win
//! over the built-in `general`, `explore` and `plan`.
//!
//! `access: read-only` is enforced, not just asked for: the child's tool calls
//! go through [`crate::read_only::guard`], which refuses file writes, tools
//! it does not know to be side-effect free, and shell commands outside a
//! read-only allow-list — before the call reaches an approval prompt.

use std::path::{Path, PathBuf};

use evo_ai::ThinkingLevel;
use evo_harness::agent_harness::MAX_CHILD_TURNS;
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
    /// Refuse writes and state-changing commands (see [`crate::read_only`]).
    pub read_only: bool,
    /// `None` or `inherit`: the parent's thinking level.
    pub thinking: Option<ThinkingLevel>,
    /// `None`: [`DEFAULT_MAX_TURNS`].
    pub max_turns: Option<u32>,
    /// Instructions the child starts with, before its task.
    pub prompt: String,
    /// The file it came from; `None` for built-ins.
    pub source: Option<PathBuf>,
}

pub const DEFAULT_TYPE: &str = "general";

/// Model turns per run for a type that does not set `maxTurns`.
pub const DEFAULT_MAX_TURNS: u32 = 32;

impl AgentType {
    pub fn max_turns(&self) -> u32 {
        self.max_turns.unwrap_or(DEFAULT_MAX_TURNS)
    }
}

const GENERAL_PROMPT: &str = "\
You are a delegated general-purpose agent. Do the task completely, and only the task.

How to work:
- Understand the relevant code before changing it, and follow the project's instructions and conventions.
- Stay in scope: no unrelated refactors and no new dependencies unless the task needs them. Preserve changes you did not make.
- Do not commit, push or publish anything unless the task says so.
- Verify your work: run the checks or tests that cover what you changed. If something fails, fix it or report it; never claim a result you did not see.
- If the task turns out to be impossible or ambiguous, do the safe part and say what blocked the rest instead of guessing.

Report:
**Done**: what you accomplished, in a few sentences.
**Changes**: each file changed, with its path and a line on what changed.
**Checks**: the commands you ran and their results.
**Not done**: anything left, failed or skipped, and why. Omit when empty.";

const EXPLORE_PROMPT: &str = "\
You are a read-only exploration agent. You find code and answer questions about this codebase; you never change anything.

How to work:
- Go wide, then narrow: locate candidates with fast searches (`rg` or `git grep` for content, `rg --files` or `git ls-files` for names), then read only the parts that matter (on a large file, read a range rather than the whole file).
- Run independent searches in the same turn.
- Match the thoroughness the task asks for: quick (a few targeted searches), medium (the default: the likely places and the obvious alternatives), very thorough (every location, naming convention and caller).
- Stop as soon as the question is answered. Do not speculate: when something is not found, say where you looked.
- Shell commands are limited to read-only ones (search, list, read, git log/show/diff/status/blame). Anything that writes or changes state is refused, so do not try; output redirection to a file is refused too.

Report:
**Answer**: the direct answer, in a few sentences.
**Evidence**: `path:line` for each claim, quoting only the one to three lines that matter.
**Not found / uncertain**: what you could not confirm, and where you looked. Omit when empty.";

const PLAN_PROMPT: &str = "\
You are a planning agent. You study the code and return an implementation plan; you never change anything (writes and state-changing commands are refused).

How to work:
- Find the code the goal touches and how similar things are already done here: reuse existing functions, patterns and tests rather than inventing new ones.
- Follow the project's instructions and architecture rules: layering, where logic belongs, what must change together.
- Prefer the smallest change that fully solves the goal. When there are real alternatives, choose one and say in a line why not the others.
- Do not write the implementation: signatures and short snippets only where they remove ambiguity.

Report:
**Goal**: one line.
**Approach**: the chosen design and why.
**Changes**: each file, with the functions or types to add or change and what changes.
**Steps**: numbered and in order, each small enough to check on its own.
**Risks**: what could break, edge cases, compatibility.
**Verification**: the exact commands and tests that prove it works, including new tests to write.
**Open questions**: decisions the requester must make. Omit when none.";

/// The types every session has.
pub fn builtin() -> Vec<AgentType> {
    let read_only_tools = || {
        Some(vec![
            "read".to_string(),
            "bash".to_string(),
            "powershell".to_string(),
        ])
    };
    let builtin = |name: &str, description: &str, prompt: &str| AgentType {
        name: name.into(),
        description: description.into(),
        tools: None,
        model: None,
        worktree: false,
        read_only: false,
        thinking: None,
        max_turns: None,
        prompt: prompt.into(),
        source: None,
    };
    vec![
        AgentType {
            max_turns: Some(80),
            ..builtin(
                "general",
                "General-purpose agent for multi-step work that may change files: implementing a self-contained piece of a change, investigating and fixing, running commands. Use when the steps would clutter this conversation. When several run at once and write files, give each isolation \"worktree\".",
                GENERAL_PROMPT,
            )
        },
        AgentType {
            tools: read_only_tools(),
            read_only: true,
            // Many cheap searches, little reasoning.
            thinking: Some(ThinkingLevel::Low),
            max_turns: Some(40),
            ..builtin(
                "explore",
                "Read-only search agent for finding code and answering questions about the codebase when it takes more than a few searches. Say in the prompt how thorough to be (quick, medium or very thorough). Returns conclusions with file:line references, not file dumps. It cannot change files.",
                EXPLORE_PROMPT,
            )
        },
        AgentType {
            tools: read_only_tools(),
            read_only: true,
            // Weighing designs is the point of a plan.
            thinking: Some(ThinkingLevel::High),
            max_turns: Some(40),
            ..builtin(
                "plan",
                "Read-only planning agent: studies the code and returns a step-by-step implementation plan (files and functions to change, ordered steps, risks, how to verify). Use before a change that spans several files or layers. It cannot change files.",
                PLAN_PROMPT,
            )
        },
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
        let Ok(entries) = std::fs::read_dir(dir) else {
            continue;
        };
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
        && name
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
}

/// One agent type file. `name` defaults to the file name.
pub fn parse(file: &Path) -> Result<AgentType, String> {
    let text = std::fs::read_to_string(file).map_err(|e| e.to_string())?;
    let (front, body) = evo_harness::frontmatter::parse_frontmatter(&text)?;
    let stem = file
        .file_stem()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_default();
    let name = front
        .get("name")
        .and_then(Value::as_str)
        .map(str::to_string)
        .unwrap_or(stem);
    if !valid_name(&name) {
        return Err(format!(
            "name `{name}` must be lowercase letters, digits and hyphens (at most 64)"
        ));
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
        Some(Value::Array(items)) => Some(
            items
                .iter()
                .filter_map(Value::as_str)
                .map(evo_tool_name)
                .collect(),
        ),
        Some(Value::String(list)) => Some(
            list.split(',')
                .map(evo_tool_name)
                .filter(|s| !s.is_empty())
                .collect(),
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
        .filter(|m| {
            !m.is_empty() && !matches!(*m, "inherit" | "sonnet" | "opus" | "haiku" | "fable")
        })
        .map(str::to_string);
    let worktree = front.get("isolation").and_then(Value::as_str) == Some("worktree");
    let read_only = match front.get("access") {
        None | Some(Value::Null) => false,
        Some(Value::String(access)) => match access.trim() {
            "read-only" | "readonly" => true,
            "full" => false,
            other => return Err(format!("access `{other}` must be `read-only` or `full`")),
        },
        Some(_) => return Err("access must be `read-only` or `full`".into()),
    };
    let thinking = match front.get("thinking") {
        None | Some(Value::Null) => None,
        Some(Value::String(level)) if level.trim() == "inherit" => None,
        Some(Value::String(level)) => Some(
            evo_runtime::thinking::parse_thinking_level(level.trim())
                .ok_or_else(|| format!("thinking `{}` is not a thinking level", level.trim()))?,
        ),
        Some(_) => return Err("thinking must be a thinking level or `inherit`".into()),
    };
    let max_turns = match front.get("maxTurns") {
        None | Some(Value::Null) => None,
        Some(value) => match value
            .as_u64()
            .or_else(|| value.as_str()?.trim().parse().ok())
        {
            Some(turns) if (1..=u64::from(MAX_CHILD_TURNS)).contains(&turns) => Some(turns as u32),
            _ => {
                return Err(format!(
                    "maxTurns must be a whole number from 1 to {MAX_CHILD_TURNS}"
                ))
            }
        },
    };
    let prompt = body.trim().to_string();
    Ok(AgentType {
        name,
        description: description.to_string(),
        tools,
        model,
        worktree,
        read_only,
        thinking,
        max_turns,
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
        write(
            &user,
            "reviewer.md",
            "---\ndescription: The user's reviewer.\n---\nUser version.\n",
        );
        write(&user, "writer.md", "---\nname: docs-writer\ndescription: Writes docs.\ntools: read, write\n---\nWrite docs.\n");
        write(
            &user,
            "broken.md",
            "---\nname: Bad Name\ndescription: x\n---\n",
        );
        write(&user, "nodesc.md", "no frontmatter at all\n");

        let types = load_from(&[project, user]);
        let reviewer = types.iter().find(|t| t.name == "reviewer").unwrap();
        assert_eq!(reviewer.description, "Reviews changes.");
        assert_eq!(
            reviewer.tools.as_deref(),
            Some(&["read".to_string(), "bash".to_string()][..])
        );
        assert_eq!(reviewer.model.as_deref(), Some("some-model"));
        assert!(reviewer.worktree);
        assert_eq!(reviewer.prompt, "You review code.");
        let writer = types.iter().find(|t| t.name == "docs-writer").unwrap();
        assert_eq!(
            writer.tools.as_deref(),
            Some(&["read".to_string(), "write".to_string()][..])
        );
        assert!(writer.model.is_none());
        // Invalid files are skipped; built-ins are always there.
        assert!(!types
            .iter()
            .any(|t| t.name == "Bad Name" || t.name == "nodesc"));
        for name in ["general", "explore", "plan"] {
            assert!(types.iter().any(|t| t.name == name), "missing {name}");
        }
    }

    #[test]
    fn access_thinking_and_turns_are_read_and_checked() {
        let root = tempfile::tempdir().unwrap();
        write(
            root.path(),
            "auditor.md",
            "---\ndescription: Audits.\naccess: read-only\nthinking: high\nmaxTurns: 60\n---\nAudit.\n",
        );
        write(
            root.path(),
            "plain.md",
            "---\ndescription: Plain.\nthinking: inherit\n---\nPlain.\n",
        );
        let types = load_from(&[root.path().to_path_buf()]);
        let auditor = types.iter().find(|t| t.name == "auditor").unwrap();
        assert!(auditor.read_only);
        assert_eq!(auditor.thinking, Some(ThinkingLevel::High));
        assert_eq!(auditor.max_turns(), 60);
        let plain = types.iter().find(|t| t.name == "plain").unwrap();
        assert!(!plain.read_only);
        assert_eq!(plain.thinking, None);
        assert_eq!(plain.max_turns(), DEFAULT_MAX_TURNS);

        for (file, front) in [
            ("access.md", "access: sometimes"),
            ("thinking.md", "thinking: galaxy-brain"),
            ("turns.md", "maxTurns: 0"),
            ("many.md", "maxTurns: 1000"),
        ] {
            write(
                root.path(),
                file,
                &format!("---\ndescription: x\n{front}\n---\nx\n"),
            );
            assert!(
                parse(&root.path().join(file)).is_err(),
                "{front} was accepted"
            );
        }
    }

    #[test]
    fn explore_and_plan_are_read_only_and_general_is_not() {
        let types = builtin();
        let get = |name: &str| types.iter().find(|t| t.name == name).unwrap();
        assert!(get("explore").read_only && get("plan").read_only);
        assert!(!get("general").read_only && get("general").tools.is_none());
        for agent in &types {
            assert!(
                (1..=MAX_CHILD_TURNS).contains(&agent.max_turns()),
                "{}",
                agent.name
            );
            assert!(
                agent.prompt.contains("Report:"),
                "{} has no report format",
                agent.name
            );
        }
    }

    #[test]
    fn a_file_can_replace_a_builtin() {
        let root = tempfile::tempdir().unwrap();
        write(
            root.path(),
            "explore.md",
            "---\ndescription: My explorer.\nmodel: inherit\n---\nMine.\n",
        );
        let types = load_from(&[root.path().to_path_buf()]);
        let explore: Vec<_> = types.iter().filter(|t| t.name == "explore").collect();
        assert_eq!(explore.len(), 1);
        assert_eq!(explore[0].description, "My explorer.");
        assert!(
            explore[0].model.is_none(),
            "`inherit` means the parent's model"
        );
    }
}
