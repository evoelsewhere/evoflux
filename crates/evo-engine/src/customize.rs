//! Skills, command files and their overrides, from evo's own folders and
//! the cross-client Agent Skills folder `.agents/skills`.
//!
//! * **Skill folders**: besides `.evo/skills` and `~/.evo/agent/skills`, the
//!   cross-client Agent Skills folder `.agents/skills` (project: the working
//!   folder and the repository root; user: `~/.agents/skills`). These load
//!   through the normal skill loader.
//! * **Commands**: `.evo/commands/**/*.md` and `~/.evo/agent/commands` hold
//!   command files, a single-file form of a skill. Each becomes a
//!   skill named after its path (`frontend/component.md` →
//!   `frontend:component`); a skill of the same name wins. The description
//!   falls back to the first line of the body.
//! * **Overrides**: `skillOverrides` in `~/.evo/agent/settings.json`, set from
//!   the desktop's Customize view: `off` drops a skill, `user-invocable-only`
//!   keeps it out of the model's list (only `/name` runs it), `name-only` lists
//!   it without its description.
//! * **Listing**: [`describe`] is what the Customize view and the composer's
//!   `/` menu show (RPC `list_customizations`).

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use evo_harness::frontmatter::parse_frontmatter;
use evo_harness::types::{PromptTemplate, Skill};
use serde_json::{json, Value};

const MAX_DESCRIPTION: usize = 1024;
/// Command folders are walked at most this deep.
const MAX_DEPTH: usize = 6;

/// Skills switched off in Customize, kept so the view can still list them.
static SWITCHED_OFF: Mutex<Vec<Skill>> = Mutex::new(Vec::new());

fn settings() -> crate::settings::Settings {
    crate::settings::load_settings().unwrap_or_default()
}

fn home() -> Option<PathBuf> {
    dirs::home_dir()
}

/// The repository root above `cwd` (the folder holding `.git`), if any.
fn repo_root(cwd: &Path) -> Option<PathBuf> {
    cwd.ancestors()
        .find(|dir| dir.join(".git").exists())
        .map(Path::to_path_buf)
}

/// `cwd`, then the repository root when it differs.
fn project_roots(cwd: &Path) -> Vec<PathBuf> {
    let mut roots = vec![cwd.to_path_buf()];
    if let Some(root) = repo_root(cwd) {
        if root != cwd {
            roots.push(root);
        }
    }
    roots
}

/// Project Agent Skills folders (`.agents/skills`, the cross-client layout).
pub fn project_skill_dirs(cwd: &Path) -> Vec<PathBuf> {
    project_roots(cwd)
        .into_iter()
        .map(|root| root.join(".agents").join("skills"))
        .collect()
}

/// User Agent Skills folder (`~/.agents/skills`).
pub fn global_skill_dirs() -> Vec<PathBuf> {
    home()
        .map(|home| vec![home.join(".agents").join("skills")])
        .unwrap_or_default()
}

/// Command folders: project `.evo/commands` (when trusted), then
/// `~/.evo/agent/commands`.
pub fn command_dirs(cwd: &Path, project_trusted: bool) -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    if project_trusted {
        dirs.push(crate::resource_dirs::project_dir(cwd, "commands"));
    }
    if let Some(global) = crate::resource_dirs::global_dir("commands") {
        dirs.push(global);
    }
    dirs
}

/// Every command in `dirs`, as skills; the first of a name wins.
pub fn load_commands(dirs: &[PathBuf]) -> Vec<Skill> {
    let mut out: Vec<Skill> = Vec::new();
    for dir in dirs {
        let mut files = Vec::new();
        walk(dir, dir, 0, &mut files);
        files.sort();
        for (file, name) in files {
            if out.iter().any(|skill| skill.name == name) {
                continue;
            }
            if let Some(skill) = command(&file, &name) {
                out.push(skill);
            }
        }
    }
    out
}

fn walk(root: &Path, dir: &Path, depth: usize, out: &mut Vec<(PathBuf, String)>) {
    if depth > MAX_DEPTH {
        return;
    }
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let file_name = entry.file_name().to_string_lossy().into_owned();
        if file_name.starts_with('.') || file_name == "node_modules" {
            continue;
        }
        if path.is_dir() {
            walk(root, &path, depth + 1, out);
        } else if path
            .extension()
            .is_some_and(|ext| ext.eq_ignore_ascii_case("md"))
        {
            let Ok(relative) = path.strip_prefix(root) else {
                continue;
            };
            let name = relative
                .with_extension("")
                .components()
                .map(|part| part.as_os_str().to_string_lossy().into_owned())
                .collect::<Vec<_>>()
                .join(":");
            if !name.is_empty() && !name.contains(char::is_whitespace) {
                out.push((path, name));
            }
        }
    }
}

fn command(file: &Path, name: &str) -> Option<Skill> {
    let source = std::fs::read_to_string(file).ok()?;
    let (frontmatter, body) = parse_frontmatter(source.trim_start_matches('\u{feff}')).ok()?;
    let body = body.trim().to_string();
    let description = frontmatter
        .get("description")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|d| !d.is_empty())
        .map(str::to_string)
        .or_else(|| first_line(&body))
        .unwrap_or_else(|| format!("Run /{name}"));
    Some(Skill {
        name: name.to_string(),
        description: truncate(&description, MAX_DESCRIPTION),
        content: body,
        file_path: file.to_string_lossy().into_owned(),
        disable_model_invocation: flag(&frontmatter, "disable-model-invocation"),
    })
}

fn first_line(body: &str) -> Option<String> {
    body.lines()
        .map(|line| line.trim().trim_start_matches('#').trim())
        .find(|line| !line.is_empty())
        .map(str::to_string)
}

fn truncate(text: &str, max: usize) -> String {
    if text.chars().count() <= max {
        text.to_string()
    } else {
        text.chars().take(max - 1).collect::<String>() + "…"
    }
}

/// Lenient YAML booleans: true/false, yes/no, on/off, 1/0.
fn flag(frontmatter: &Value, key: &str) -> Option<bool> {
    match frontmatter.get(key)? {
        Value::Bool(b) => Some(*b),
        Value::Number(n) => Some(n.as_i64() == Some(1)),
        Value::String(s) => match s.trim().to_ascii_lowercase().as_str() {
            "true" | "yes" | "on" | "1" => Some(true),
            "false" | "no" | "off" | "0" => Some(false),
            _ => None,
        },
        _ => None,
    }
}

/// After the skill folders are loaded: add command files (a skill of
/// the same name wins) and apply the overrides from Customize.
pub fn finish_skills(cwd: &Path, project_trusted: bool, skills: Vec<Skill>) -> Vec<Skill> {
    let mut skills = skills;
    for command in load_commands(&command_dirs(cwd, project_trusted))
        .into_iter()
        .chain(crate::plugins::commands())
    {
        if !skills.iter().any(|skill| skill.name == command.name) {
            skills.push(command);
        }
    }
    let overrides = settings().skill_overrides.unwrap_or_default();
    let mut off = Vec::new();
    let mut kept = Vec::with_capacity(skills.len());
    for mut skill in skills {
        match overrides.get(&skill.name).map(String::as_str) {
            Some("off") => off.push(skill),
            Some("user-invocable-only") => {
                skill.disable_model_invocation = Some(true);
                kept.push(skill);
            }
            Some("name-only") => {
                skill.description = String::new();
                kept.push(skill);
            }
            _ => kept.push(skill),
        }
    }
    *SWITCHED_OFF.lock().unwrap() = off;
    crate::skill_runtime::remember(&kept);
    crate::skill_runtime::fit_listing(&mut kept);
    kept
}

/// Save a skill's override (`on` removes it).
pub fn set_override(name: &str, state: &str) -> Result<(), String> {
    if !matches!(state, "on" | "off" | "name-only" | "user-invocable-only") {
        return Err(format!("unknown state `{state}`"));
    }
    crate::settings::update_settings_value(|settings| {
        let entry = settings
            .entry("skillOverrides")
            .or_insert_with(|| json!({}));
        if !entry.is_object() {
            *entry = json!({});
        }
        let map = entry.as_object_mut().unwrap();
        if state == "on" {
            map.remove(name);
        } else {
            map.insert(name.to_string(), json!(state));
        }
        if map.is_empty() {
            settings.remove("skillOverrides");
        }
    })
}

/// Usage counts and budget trims for [`skill_entry`].
struct Extra {
    usage: HashMap<String, crate::skill_runtime::Usage>,
    trimmed: std::collections::HashSet<String>,
}

/// Save the skill settings given (a budget of 0 restores the default).
pub fn set_skill_settings(listing_budget: Option<u64>, shell_disabled: Option<bool>) -> Result<(), String> {
    crate::settings::update_settings_value(|settings| {
        match listing_budget {
            Some(0) => {
                settings.remove("skillListingBudgetChars");
            }
            Some(budget) => {
                settings.insert("skillListingBudgetChars".into(), json!(budget.clamp(500, 200_000)));
            }
            None => {}
        }
        match shell_disabled {
            Some(true) => {
                settings.insert("disableSkillShellExecution".into(), json!(true));
            }
            Some(false) => {
                settings.remove("disableSkillShellExecution");
            }
            None => {}
        }
    })
}

/// Where a file sits: `project` or `user` scope, and which folder family.
fn origin(cwd: &Path, path: &str) -> (&'static str, &'static str) {
    if crate::plugins::plugin_of(Path::new(path)).is_some() {
        return ("user", "plugin");
    }
    let normalized = path.replace('\\', "/");
    let lower = normalized.to_ascii_lowercase();
    let in_project = project_roots(cwd).iter().any(|root| {
        let root = root
            .to_string_lossy()
            .replace('\\', "/")
            .to_ascii_lowercase();
        lower.starts_with(&format!("{}/", root.trim_end_matches('/')))
    });
    let family = if lower.contains("/.agents/") {
        "agents"
    } else if lower.contains("/packages/") {
        "package"
    } else {
        "evo"
    };
    (if in_project { "project" } else { "user" }, family)
}

fn text(frontmatter: &Value, key: &str) -> Option<String> {
    match frontmatter.get(key)? {
        Value::String(s) if !s.trim().is_empty() => Some(s.trim().to_string()),
        Value::Array(items) => Some(
            items
                .iter()
                .filter_map(Value::as_str)
                .collect::<Vec<_>>()
                .join(" "),
        )
        .filter(|s| !s.is_empty()),
        _ => None,
    }
}

fn skill_entry(cwd: &Path, skill: &Skill, state: &str, extra: &Extra) -> Value {
    let (scope, family) = origin(cwd, &skill.file_path);
    let frontmatter = std::fs::read_to_string(&skill.file_path)
        .ok()
        .and_then(|source| parse_frontmatter(source.trim_start_matches('\u{feff}')).ok())
        .map(|(frontmatter, _)| frontmatter)
        .unwrap_or_else(|| json!({}));
    let command = !skill.file_path.ends_with("SKILL.md");
    let description = if skill.description.is_empty() {
        text(&frontmatter, "description").unwrap_or_default()
    } else {
        skill.description.clone()
    };
    json!({
        "name": skill.name,
        "kind": if command { "command" } else { "skill" },
        "description": description,
        "whenToUse": text(&frontmatter, "when_to_use"),
        "argumentHint": text(&frontmatter, "argument-hint"),
        "userInvocable": flag(&frontmatter, "user-invocable").unwrap_or(true),
        "modelInvocable": !flag(&frontmatter, "disable-model-invocation").unwrap_or(false),
        "allowedTools": text(&frontmatter, "allowed-tools"),
        "model": text(&frontmatter, "model"),
        "license": text(&frontmatter, "license"),
        "compatibility": text(&frontmatter, "compatibility"),
        // The spec's free-form string map (author, version, …).
        "metadata": frontmatter.get("metadata").filter(|m| m.is_object()).cloned(),
        "files": if command { Vec::new() } else { skill_files(&skill.file_path) },
        "plugin": crate::plugins::plugin_of(Path::new(&skill.file_path)),
        "path": skill.file_path,
        "scope": scope,
        "origin": family,
        "state": state,
        "uses": extra.usage.get(&skill.name).map_or(0, |u| u.uses),
        "lastUsed": extra.usage.get(&skill.name).map(|u| u.last_used).filter(|t| *t > 0),
        // Listed by name only to fit the listing budget.
        "nameOnlyForBudget": extra.trimmed.contains(&skill.name),
        "content": truncate(&skill.content, 40_000),
    })
}

/// Files a skill folder holds besides `SKILL.md` (`references/`, `assets/`,
/// `scripts/`, …), relative and with `/`, at most [`MAX_SKILL_FILES`].
fn skill_files(skill_md: &str) -> Vec<String> {
    const MAX_SKILL_FILES: usize = 100;
    let Some(root) = Path::new(skill_md).parent() else {
        return Vec::new();
    };
    let mut found = Vec::new();
    let mut stack = vec![(root.to_path_buf(), 0usize)];
    while let Some((dir, depth)) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&dir) else { continue };
        for entry in entries.flatten() {
            let path = entry.path();
            let name = entry.file_name().to_string_lossy().into_owned();
            if name.starts_with('.') || name == "node_modules" {
                continue;
            }
            if path.is_dir() {
                if depth < MAX_DEPTH {
                    stack.push((path, depth + 1));
                }
            } else if let Ok(relative) = path.strip_prefix(root) {
                let relative = relative.to_string_lossy().replace('\\', "/");
                if relative != "SKILL.md" {
                    found.push(relative);
                }
            }
            if found.len() >= MAX_SKILL_FILES {
                break;
            }
        }
    }
    found.sort();
    found.truncate(MAX_SKILL_FILES);
    found
}

/// Skills (incl. commands, and those switched off), prompt templates and
/// agent types, for the Customize view and the composer's `/` menu.
pub fn describe(cwd: &Path, skills: &[Skill], templates: &[PromptTemplate]) -> Value {
    let settings = settings();
    let overrides: HashMap<String, String> = settings.skill_overrides.clone().unwrap_or_default();
    let extra = Extra {
        usage: crate::skill_runtime::usage(),
        trimmed: crate::skill_runtime::trimmed(),
    };
    let mut list: Vec<Value> = skills
        .iter()
        .map(|skill| {
            let state = overrides
                .get(&skill.name)
                .map(String::as_str)
                .unwrap_or("on");
            skill_entry(cwd, skill, state, &extra)
        })
        .collect();
    for skill in SWITCHED_OFF.lock().unwrap().iter() {
        list.push(skill_entry(cwd, skill, "off", &extra));
    }
    let templates: Vec<Value> = templates
        .iter()
        .map(|template| {
            json!({
                "name": template.name,
                "kind": "template",
                "description": template.description.clone().unwrap_or_default(),
            })
        })
        .collect();
    let agents: Vec<Value> = crate::agents::load(cwd)
        .iter()
        .map(|agent| {
            let path = agent
                .source
                .as_ref()
                .map(|p| p.to_string_lossy().into_owned());
            let (scope, family) = match &path {
                Some(path) => origin(cwd, path),
                None => ("builtin", "evo"),
            };
            json!({
                "name": agent.name,
                "description": agent.description,
                "tools": agent.tools,
                "model": agent.model,
                "worktree": agent.worktree,
                "plugin": path.as_deref().and_then(|p| crate::plugins::plugin_of(Path::new(p))),
                "path": path,
                "scope": scope,
                "origin": family,
                "content": truncate(&agent.prompt, 40_000),
            })
        })
        .collect();
    json!({
        "skills": list,
        "templates": templates,
        "agents": agents,
        "settings": {
            "listingBudget": settings.skill_listing_budget_chars.unwrap_or(crate::skill_runtime::DEFAULT_BUDGET),
            "shellDisabled": settings.disable_skill_shell_execution.unwrap_or(false),
        },
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_skill_lists_the_files_of_its_folder() {
        let dir = std::env::temp_dir().join(format!("evo-skill-files-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(dir.join("references")).unwrap();
        std::fs::create_dir_all(dir.join("scripts")).unwrap();
        std::fs::write(dir.join("SKILL.md"), "---\nname: x\ndescription: y\n---\n").unwrap();
        std::fs::write(dir.join("references").join("guide.md"), "g").unwrap();
        std::fs::write(dir.join("scripts").join("run.py"), "p").unwrap();
        std::fs::write(dir.join(".hidden"), "h").unwrap();
        let files = skill_files(&dir.join("SKILL.md").to_string_lossy());
        assert_eq!(files, ["references/guide.md", "scripts/run.py"]);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn commands_take_their_path_as_name_and_first_line_as_description() {
        let dir = std::env::temp_dir().join(format!("evo-commands-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(dir.join("frontend")).unwrap();
        std::fs::write(
            dir.join("review.md"),
            "# Review the diff\n\nLook at $ARGUMENTS",
        )
        .unwrap();
        std::fs::write(
            dir.join("frontend").join("component.md"),
            "---\ndescription: Make a component\nargument-hint: <name>\ndisable-model-invocation: yes\n---\nCreate $0",
        )
        .unwrap();
        let commands = load_commands(&[dir.clone()]);
        let names: Vec<_> = commands.iter().map(|c| c.name.as_str()).collect();
        assert_eq!(names, ["frontend:component", "review"]);
        assert_eq!(commands[0].description, "Make a component");
        assert_eq!(commands[0].disable_model_invocation, Some(true));
        assert_eq!(commands[1].description, "Review the diff");
        let _ = std::fs::remove_dir_all(&dir);
    }
}
