//! What happens around a skill when it runs: usage counts, the listing
//! budget, and shell lines in its body.
//!
//! * **Usage**: each run (the `skill` tool or `/name`) counts in
//!   `<agent dir>/skill-usage.json` (`{name: {uses, lastUsed}}`); Customize
//!   shows it and the listing budget uses it.
//! * **Listing budget**: the model sees each skill's name and description.
//!   Descriptions are cut to [`MAX_LISTED_DESCRIPTION`] characters, and when
//!   the whole listing passes `skillListingBudgetChars` (settings, default
//!   [`DEFAULT_BUDGET`]) the least used skills are listed by name only until
//!   it fits. `/name` and the `skill` tool still run them.
//! * **Shell lines**: `` !`command` `` in a skill's body, or a fenced block
//!   opened with ```` ```! ````, runs when the skill loads and is replaced by
//!   its output (Git Bash or PowerShell on Windows, `sh` elsewhere; in the
//!   session's folder; `${SKILL_DIR}` filled in; [`SHELL_TIMEOUT`] each).
//!   Commands come from the skill file only, before arguments are filled in,
//!   so text passed to a skill never runs. `disableSkillShellExecution: true`
//!   in settings turns this off.

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::Duration;

use evo_harness::types::Skill;
use serde::{Deserialize, Serialize};

pub const MAX_LISTED_DESCRIPTION: usize = 1536;
pub const DEFAULT_BUDGET: usize = 8000;
const SHELL_TIMEOUT: Duration = Duration::from_secs(120);
const MAX_OUTPUT: usize = 20_000;

#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct Usage {
    pub uses: u64,
    /// Milliseconds since the Unix epoch.
    pub last_used: u64,
}

fn usage_path() -> Option<PathBuf> {
    crate::config::agent_dir()
        .ok()
        .map(|dir| dir.join("skill-usage.json"))
}

pub fn usage() -> HashMap<String, Usage> {
    usage_path()
        .and_then(|path| std::fs::read_to_string(path).ok())
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_default()
}

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

/// Count one run of `name`. Best effort: a failed write loses one count.
pub fn record(name: &str) {
    let Some(path) = usage_path() else { return };
    static WRITING: Mutex<()> = Mutex::new(());
    let _guard = WRITING.lock().unwrap_or_else(|e| e.into_inner());
    let mut all = usage();
    let entry = all.entry(name.to_string()).or_default();
    entry.uses += 1;
    entry.last_used = now_ms();
    let Ok(text) = serde_json::to_string_pretty(&all) else { return };
    if let Some(dir) = path.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    // Write beside, then rename, so another engine never reads half a file.
    let temp = path.with_extension(format!("json.{}", std::process::id()));
    if std::fs::write(&temp, text).is_ok() && std::fs::rename(&temp, &path).is_err() {
        let _ = std::fs::remove_file(&temp);
    }
}

/// Skills listed by name only to fit the budget, for Customize.
static TRIMMED: Mutex<Vec<String>> = Mutex::new(Vec::new());

pub fn trimmed() -> HashSet<String> {
    TRIMMED.lock().unwrap().iter().cloned().collect()
}

fn cut(text: &str, max: usize) -> String {
    if text.chars().count() <= max {
        return text.to_string();
    }
    let mut out: String = text.chars().take(max.saturating_sub(1)).collect();
    out.push('…');
    out
}

/// Cut descriptions and, past `budget` characters, list the least used
/// model-visible skills by name only.
pub fn apply_budget(skills: &mut [Skill], budget: usize, usage: &HashMap<String, Usage>) -> Vec<String> {
    for skill in skills.iter_mut() {
        skill.description = cut(&skill.description, MAX_LISTED_DESCRIPTION);
    }
    // Roughly what one listing entry costs besides its text.
    const ENTRY: usize = 40;
    let listed = |skill: &Skill| !skill.disable_model_invocation.unwrap_or(false);
    let mut total: usize = skills
        .iter()
        .filter(|s| listed(s))
        .map(|s| s.name.len() + s.description.len() + ENTRY)
        .sum();
    let mut order: Vec<usize> = (0..skills.len())
        .filter(|&i| listed(&skills[i]) && !skills[i].description.is_empty())
        .collect();
    // Least used first; among equals, the longest description first.
    order.sort_by_key(|&i| {
        let u = usage.get(&skills[i].name).copied().unwrap_or_default();
        (u.uses, u.last_used, std::cmp::Reverse(skills[i].description.len()))
    });
    let mut trimmed = Vec::new();
    for i in order {
        if total <= budget {
            break;
        }
        total -= skills[i].description.len();
        skills[i].description.clear();
        trimmed.push(skills[i].name.clone());
    }
    trimmed
}

/// [`apply_budget`] with the settings' budget, remembered for Customize.
pub fn fit_listing(skills: &mut [Skill]) {
    let budget = crate::settings::load_settings()
        .ok()
        .and_then(|s| s.skill_listing_budget_chars)
        .unwrap_or(DEFAULT_BUDGET);
    let trimmed = apply_budget(skills, budget, &usage());
    *TRIMMED.lock().unwrap() = trimmed;
}

/// Whether `source` holds shell lines.
pub fn has_shell(source: &str) -> bool {
    source.contains("!`") || source.contains("```!")
}

fn shell_disabled() -> bool {
    crate::settings::load_settings()
        .ok()
        .and_then(|s| s.disable_skill_shell_execution)
        .unwrap_or(false)
}

async fn run(command: &str, cwd: &Path, skill_dir: &Path) -> String {
    let command = command.replace("${SKILL_DIR}", &skill_dir.to_string_lossy());
    let mut cmd = evo_hooks::run::shell_command(&command, None);
    cmd.current_dir(cwd)
        .env("SKILL_DIR", skill_dir)
        .stdin(std::process::Stdio::null())
        .kill_on_drop(true);
    #[cfg(windows)]
    {
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    match tokio::time::timeout(SHELL_TIMEOUT, cmd.output()).await {
        Err(_) => format!("[`{command}` timed out after {}s]", SHELL_TIMEOUT.as_secs()),
        Ok(Err(error)) => format!("[`{command}` could not run: {error}]"),
        Ok(Ok(output)) => {
            let mut text = String::from_utf8_lossy(&output.stdout).trim_end().to_string();
            let err = String::from_utf8_lossy(&output.stderr).trim_end().to_string();
            if !output.status.success() {
                let code = output.status.code().map_or("signal".into(), |c| c.to_string());
                if !err.is_empty() {
                    if !text.is_empty() {
                        text.push('\n');
                    }
                    text.push_str(&err);
                }
                text = format!("{text}\n[exit {code}]").trim_start().to_string();
            }
            cut(&text, MAX_OUTPUT)
        }
    }
}

/// Replace the shell lines in `source` with their output.
pub async fn expand_shell(source: &str, cwd: &Path, skill_dir: &Path) -> String {
    if !has_shell(source) {
        return source.to_string();
    }
    let disabled = shell_disabled();
    let mut out = String::with_capacity(source.len());
    let mut lines = source.split_inclusive('\n').peekable();
    while let Some(line) = lines.next() {
        // A fenced block: ```! … ```
        if line.trim_start().starts_with("```!") {
            let mut body = String::new();
            for inner in lines.by_ref() {
                if inner.trim_start().starts_with("```") {
                    break;
                }
                body.push_str(inner);
            }
            let result = if disabled {
                "[shell commands in skills are turned off]".to_string()
            } else {
                run(body.trim(), cwd, skill_dir).await
            };
            out.push_str("```\n");
            out.push_str(&result);
            out.push_str("\n```\n");
            continue;
        }
        // Inline: !`command`
        let mut rest = line;
        while let Some(start) = rest.find("!`") {
            let after = &rest[start + 2..];
            let Some(end) = after.find('`') else { break };
            let command = &after[..end];
            out.push_str(&rest[..start]);
            if command.trim().is_empty() {
                out.push_str(&rest[start..start + 3 + end]);
            } else if disabled {
                out.push_str("[shell commands in skills are turned off]");
            } else {
                out.push_str(&run(command, cwd, skill_dir).await);
            }
            rest = &after[end + 1..];
        }
        out.push_str(rest);
    }
    out
}

/// The skill's instructions for `args`, shell lines run, from the file.
pub async fn load(skill: &Skill, args: &str, cwd: &Path) -> String {
    let skill_dir = Path::new(&skill.file_path)
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| cwd.to_path_buf());
    match tokio::fs::read_to_string(&skill.file_path).await {
        Ok(source) => {
            let source = expand_shell(&source, cwd, &skill_dir).await;
            evo_harness::skills::format_skill_command(skill, &source, args)
                .unwrap_or_else(|_| evo_harness::skills::format_skill_with_arguments(skill, args))
        }
        Err(_) => evo_harness::skills::format_skill_with_arguments(skill, args),
    }
}

/// The skills as last loaded, for `/name` in the prompt path.
static LOADED: Mutex<Vec<Skill>> = Mutex::new(Vec::new());

pub fn remember(skills: &[Skill]) {
    *LOADED.lock().unwrap() = skills.to_vec();
}

/// The skill `/name` runs: an exact name, or a unique bare name of a
/// namespaced one (`/deploy` → `tools:deploy`).
pub fn find(name: &str) -> Option<Skill> {
    let skills = LOADED.lock().unwrap();
    if let Some(skill) = skills.iter().find(|s| s.name == name) {
        return Some(skill.clone());
    }
    if name.contains(':') {
        return None;
    }
    let mut found = skills
        .iter()
        .filter(|s| s.name.rsplit_once(':').is_some_and(|(_, last)| last == name));
    match (found.next(), found.next()) {
        (Some(one), None) => Some(one.clone()),
        _ => None,
    }
}

/// For a prompt `/name args` naming a skill: count the run, and when the
/// skill has shell lines, the expanded text to send instead.
pub async fn on_prompt(text: &str, cwd: &Path) -> Option<String> {
    let (name, args) = evo_harness::skills::parse_slash_command(text)
        .or_else(|| {
            // `/skill:name args`
            let rest = text.strip_prefix("/skill:")?;
            Some(match rest.split_once(char::is_whitespace) {
                Some((name, args)) => (name, args.trim()),
                None => (rest, ""),
            })
        })?;
    let skill = find(name)?;
    record(&skill.name);
    let source = tokio::fs::read_to_string(&skill.file_path).await.ok()?;
    if !has_shell(&source) {
        return None;
    }
    Some(load(&skill, args, cwd).await)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn skill(name: &str, description: &str) -> Skill {
        Skill {
            name: name.into(),
            description: description.into(),
            content: String::new(),
            file_path: String::new(),
            disable_model_invocation: None,
        }
    }

    #[test]
    fn the_least_used_skills_lose_their_descriptions_first() {
        let mut skills = vec![
            skill("often", &"a".repeat(100)),
            skill("rare", &"b".repeat(100)),
            skill("never", &"c".repeat(100)),
        ];
        let usage = HashMap::from([
            ("often".to_string(), Usage { uses: 9, last_used: 5 }),
            ("rare".to_string(), Usage { uses: 1, last_used: 5 }),
        ]);
        // About 145 each, 434 in all: 350 drops one description, 250 a second.
        let trimmed = apply_budget(&mut skills, 350, &usage);
        assert_eq!(trimmed, vec!["never".to_string()]);
        let trimmed = apply_budget(&mut skills, 250, &usage);
        assert_eq!(trimmed, vec!["rare".to_string()]);
        assert!(!skills[0].description.is_empty());
    }

    #[test]
    fn long_descriptions_are_cut() {
        let mut skills = vec![skill("long", &"x".repeat(5000))];
        apply_budget(&mut skills, usize::MAX, &HashMap::new());
        assert_eq!(skills[0].description.chars().count(), MAX_LISTED_DESCRIPTION);
    }

    #[tokio::test]
    async fn shell_lines_run_and_arguments_never_do() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("SKILL.md");
        std::fs::write(
            &file,
            "---\nname: s\ndescription: d\n---\nBranch: !`echo main`\n```!\necho block\n```\nArgs: $ARGUMENTS\n",
        )
        .unwrap();
        let s = Skill {
            file_path: file.to_string_lossy().into_owned(),
            ..skill("s", "d")
        };
        let text = load(&s, "!`echo injected`", dir.path()).await;
        assert!(text.contains("Branch: main"), "{text}");
        assert!(text.contains("block"), "{text}");
        assert!(text.contains("!`echo injected`"), "{text}");
        assert!(!text.contains("echo main"), "{text}");
    }
}
