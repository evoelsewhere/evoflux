//! A plugin folder and what it contributes.

use std::path::{Path, PathBuf};

use serde_json::{Map, Value};

/// A loaded plugin: where its parts are, with paths resolved and variables
/// filled in.
#[derive(Debug, Clone, Default, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Plugin {
    /// `name@marketplace`.
    pub id: String,
    pub name: String,
    pub version: Option<String>,
    pub description: Option<String>,
    pub author: Option<String>,
    pub homepage: Option<String>,
    pub repository: Option<String>,
    pub license: Option<String>,
    pub keywords: Vec<String>,
    pub root: PathBuf,
    /// Kept across updates (`${PLUGIN_DATA}`).
    pub data: PathBuf,
    /// Folders of skill folders.
    pub skills: Vec<PathBuf>,
    /// Folders of command files.
    pub commands: Vec<PathBuf>,
    /// Agent files and folders of agent files.
    pub agents: Vec<PathBuf>,
    /// `{Event: [groups]}`, as in settings.
    pub hooks: Map<String, Value>,
    /// `{name: server}`, as in the connectors file.
    pub mcp_servers: Map<String, Value>,
    /// Added to PATH for the shell tools.
    pub bin: Option<PathBuf>,
    /// The options the plugin asks for (`userConfig`).
    pub user_config: Map<String, Value>,
    pub problems: Vec<String>,
}

/// `.evo-plugin/plugin.json`, else `.claude-plugin/plugin.json`, else
/// `plugin.json` at the root; `None` when none exists.
pub fn manifest_path(root: &Path) -> Option<PathBuf> {
    [
        root.join(".evo-plugin").join("plugin.json"),
        root.join(".claude-plugin").join("plugin.json"),
        root.join("plugin.json"),
    ]
    .into_iter()
    .find(|p| p.is_file())
}

pub fn read_json(path: &Path) -> Result<Value, String> {
    let text = std::fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
    serde_json::from_str(&text).map_err(|e| format!("{}: {e}", path.display()))
}

/// The manifest, or `{}` when the folder has none.
pub fn read_manifest(root: &Path) -> Result<Value, String> {
    match manifest_path(root) {
        Some(path) => read_json(&path),
        None => Ok(Value::Object(Map::new())),
    }
}

fn text(manifest: &Value, key: &str) -> Option<String> {
    manifest
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
}

/// `./x` (or `x`) inside `root`; `None` when it leaves the folder.
fn inside(root: &Path, relative: &str) -> Option<PathBuf> {
    let clean = relative.trim().trim_start_matches("./");
    if clean.is_empty() || clean == "." {
        return Some(root.to_path_buf());
    }
    if clean.split(['/', '\\']).any(|part| part == "..") || Path::new(clean).is_absolute() {
        return None;
    }
    Some(root.join(clean))
}

/// A manifest field that is a path, a list of paths, or (for hooks and
/// servers) inline objects.
fn entries(value: Option<&Value>) -> Vec<Value> {
    match value {
        None | Some(Value::Null) => Vec::new(),
        Some(Value::Array(items)) => items.clone(),
        Some(other) => vec![other.clone()],
    }
}

/// Fill in `${PLUGIN_ROOT}`, `${PLUGIN_DATA}` (also spelled
/// `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}`) and `${user_config.KEY}`
/// in every string of `value`.
fn substitute(value: &mut Value, root: &Path, data: &Path, config: &Map<String, Value>) {
    match value {
        Value::String(s) => {
            if s.contains("${") {
                let (root, data) = (root.to_string_lossy(), data.to_string_lossy());
                let mut out = s
                    .replace("${PLUGIN_ROOT}", &root)
                    .replace("${CLAUDE_PLUGIN_ROOT}", &root)
                    .replace("${PLUGIN_DATA}", &data)
                    .replace("${CLAUDE_PLUGIN_DATA}", &data);
                for (key, v) in config {
                    let shown = match v {
                        Value::String(t) => t.clone(),
                        other => other.to_string(),
                    };
                    out = out.replace(&format!("${{user_config.{key}}}"), &shown);
                }
                *s = out;
            }
        }
        Value::Array(items) => items
            .iter_mut()
            .for_each(|v| substitute(v, root, data, config)),
        Value::Object(map) => map
            .values_mut()
            .for_each(|v| substitute(v, root, data, config)),
        _ => {}
    }
}

/// Load the plugin in `root`. `name_fallback` names it when the manifest
/// does not; `config` holds the values set for its `userConfig`.
pub fn load(
    root: &Path,
    id: &str,
    name_fallback: &str,
    data: &Path,
    config: &Map<String, Value>,
) -> Plugin {
    let mut plugin = Plugin {
        id: id.to_string(),
        name: name_fallback.to_string(),
        root: root.to_path_buf(),
        data: data.to_path_buf(),
        ..Default::default()
    };
    let manifest = match read_manifest(root) {
        Ok(m) => m,
        Err(error) => {
            plugin.problems.push(error);
            Value::Object(Map::new())
        }
    };
    if let Some(name) = text(&manifest, "name") {
        plugin.name = name;
    }
    plugin.version = text(&manifest, "version");
    plugin.description = text(&manifest, "description");
    plugin.homepage = text(&manifest, "homepage");
    plugin.license = text(&manifest, "license");
    plugin.repository = match manifest.get("repository") {
        Some(Value::String(s)) => Some(s.clone()),
        Some(Value::Object(o)) => o.get("url").and_then(Value::as_str).map(str::to_string),
        _ => None,
    };
    plugin.author = match manifest.get("author") {
        Some(Value::String(s)) => Some(s.clone()),
        Some(Value::Object(o)) => o.get("name").and_then(Value::as_str).map(str::to_string),
        _ => None,
    };
    plugin.keywords = manifest
        .get("keywords")
        .and_then(Value::as_array)
        .map(|k| {
            k.iter()
                .filter_map(Value::as_str)
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default();
    plugin.user_config = manifest
        .get("userConfig")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();

    let paths = |plugin: &mut Plugin, field: &str| -> Vec<PathBuf> {
        let mut out = Vec::new();
        for entry in entries(manifest.get(field)) {
            match entry.as_str().map(|p| (p, inside(root, p))) {
                Some((_, Some(path))) => out.push(path),
                Some((raw, None)) => plugin
                    .problems
                    .push(format!("{field}: `{raw}` is outside the plugin")),
                None => plugin.problems.push(format!("{field}: expected a path")),
            }
        }
        out
    };

    // Skills: the default folder plus any listed.
    let default_skills = root.join("skills");
    if default_skills.is_dir() {
        plugin.skills.push(default_skills);
    }
    let listed = paths(&mut plugin, "skills");
    plugin.skills.extend(listed);
    // A root SKILL.md without skills/: the plugin is one skill.
    if plugin.skills.is_empty() && root.join("SKILL.md").is_file() {
        plugin.skills.push(root.to_path_buf());
    }
    // Commands and agents: listed ones replace the default folder.
    let listed = paths(&mut plugin, "commands");
    plugin.commands = if manifest.get("commands").is_some() {
        listed
    } else {
        vec![root.join("commands")]
    };
    plugin.commands.retain(|p| p.exists());
    let listed = paths(&mut plugin, "agents");
    plugin.agents = if manifest.get("agents").is_some() {
        listed
    } else {
        vec![root.join("agents")]
    };
    plugin.agents.retain(|p| p.exists());

    // Hooks: hooks/hooks.json, then listed files or inline objects.
    let mut hook_sources: Vec<Value> = Vec::new();
    let default_hooks = root.join("hooks").join("hooks.json");
    if default_hooks.is_file() {
        match read_json(&default_hooks) {
            Ok(v) => hook_sources.push(v.get("hooks").cloned().unwrap_or(v)),
            Err(e) => plugin.problems.push(e),
        }
    }
    for entry in entries(manifest.get("hooks")) {
        match entry {
            Value::String(p) => match inside(root, &p).map(|path| read_json(&path)) {
                Some(Ok(v)) => hook_sources.push(v.get("hooks").cloned().unwrap_or(v)),
                Some(Err(e)) => plugin.problems.push(e),
                None => plugin
                    .problems
                    .push(format!("hooks: `{p}` is outside the plugin")),
            },
            Value::Object(_) => hook_sources.push(entry),
            _ => plugin
                .problems
                .push("hooks: expected a path or an object".into()),
        }
    }
    for source in hook_sources {
        if let Value::Object(events) = source {
            for (event, groups) in events {
                let list = plugin
                    .hooks
                    .entry(event)
                    .or_insert_with(|| Value::Array(Vec::new()));
                if let (Value::Array(list), Value::Array(more)) = (list, groups) {
                    list.extend(more);
                }
            }
        }
    }

    // Connectors: .mcp.json, then listed files or inline maps.
    let mut server_sources: Vec<Value> = Vec::new();
    let default_mcp = root.join(".mcp.json");
    if default_mcp.is_file() {
        match read_json(&default_mcp) {
            Ok(v) => server_sources.push(v.get("mcpServers").cloned().unwrap_or(v)),
            Err(e) => plugin.problems.push(e),
        }
    }
    for entry in entries(manifest.get("mcpServers")) {
        match entry {
            Value::String(p) => match inside(root, &p).map(|path| read_json(&path)) {
                Some(Ok(v)) => server_sources.push(v.get("mcpServers").cloned().unwrap_or(v)),
                Some(Err(e)) => plugin.problems.push(e),
                None => plugin
                    .problems
                    .push(format!("mcpServers: `{p}` is outside the plugin")),
            },
            Value::Object(_) => server_sources.push(entry),
            _ => plugin
                .problems
                .push("mcpServers: expected a path or an object".into()),
        }
    }
    for source in server_sources {
        if let Value::Object(servers) = source {
            plugin.mcp_servers.extend(servers);
        }
    }

    let bin = root.join("bin");
    plugin.bin = bin.is_dir().then_some(bin);

    let mut hooks = Value::Object(std::mem::take(&mut plugin.hooks));
    substitute(&mut hooks, root, data, config);
    plugin.hooks = hooks.as_object().cloned().unwrap_or_default();
    let mut servers = Value::Object(std::mem::take(&mut plugin.mcp_servers));
    substitute(&mut servers, root, data, config);
    plugin.mcp_servers = servers.as_object().cloned().unwrap_or_default();
    plugin
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write(path: &Path, text: &str) {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, text).unwrap();
    }

    #[test]
    fn layout_without_a_manifest() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().join("deploy-tools");
        write(
            &root.join("skills/release/SKILL.md"),
            "---\nname: release\ndescription: d\n---\n",
        );
        write(&root.join("commands/ship.md"), "Ship it");
        write(
            &root.join("agents/reviewer.md"),
            "---\ndescription: r\n---\n",
        );
        write(
            &root.join("hooks/hooks.json"),
            r#"{"hooks": {"PostToolUse": [{"matcher": "edit", "hooks": [{"type": "command", "command": "${PLUGIN_ROOT}/fmt.sh"}]}]}}"#,
        );
        write(
            &root.join(".mcp.json"),
            r#"{"mcpServers": {"db": {"command": "${PLUGIN_ROOT}/bin/db", "args": ["--data", "${PLUGIN_DATA}"]}}}"#,
        );
        std::fs::create_dir_all(root.join("bin")).unwrap();
        let data = dir.path().join("data");
        let plugin = load(
            &root,
            "deploy-tools@local",
            "deploy-tools",
            &data,
            &Map::new(),
        );
        assert_eq!(plugin.name, "deploy-tools");
        assert_eq!(plugin.skills, vec![root.join("skills")]);
        assert_eq!(plugin.commands, vec![root.join("commands")]);
        assert_eq!(plugin.agents, vec![root.join("agents")]);
        let command = plugin.hooks["PostToolUse"][0]["hooks"][0]["command"]
            .as_str()
            .unwrap();
        assert!(command.starts_with(&*root.to_string_lossy()) && command.ends_with("/fmt.sh"));
        assert_eq!(
            plugin.mcp_servers["db"]["args"][1],
            Value::String(data.to_string_lossy().into())
        );
        assert!(plugin.bin.is_some());
        assert!(plugin.problems.is_empty(), "{:?}", plugin.problems);
    }

    #[test]
    fn manifest_fields_paths_and_config() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().join("p");
        write(
            &root.join(".evo-plugin/plugin.json"),
            r#"{
              "name": "notes", "version": "1.2.0", "description": "Note tools",
              "author": {"name": "Ann"}, "keywords": ["notes"],
              "commands": ["./cmds/"], "agents": "../escape",
              "mcpServers": {"notes": {"url": "https://x/${user_config.workspace}"}},
              "userConfig": {"workspace": {"type": "string", "title": "Workspace"}}
            }"#,
        );
        std::fs::create_dir_all(root.join("cmds")).unwrap();
        std::fs::create_dir_all(root.join("commands")).unwrap();
        let mut config = Map::new();
        config.insert("workspace".into(), Value::String("team-a".into()));
        let plugin = load(&root, "notes@m", "p", &dir.path().join("d"), &config);
        assert_eq!(plugin.name, "notes");
        assert_eq!(plugin.version.as_deref(), Some("1.2.0"));
        assert_eq!(plugin.author.as_deref(), Some("Ann"));
        // `commands` listed: replaces commands/.
        assert_eq!(plugin.commands, vec![root.join("cmds/")]);
        assert!(plugin.agents.is_empty());
        assert!(plugin.problems.iter().any(|p| p.contains("outside")));
        assert_eq!(plugin.mcp_servers["notes"]["url"], "https://x/team-a");
        assert!(plugin.user_config.contains_key("workspace"));
    }

    #[test]
    fn claude_plugin_manifest_folder() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().join("p");
        write(
            &root.join(".claude-plugin/plugin.json"),
            r#"{"name": "fleet", "mcpServers": {"s": {"command": "${CLAUDE_PLUGIN_ROOT}/run", "args": ["${CLAUDE_PLUGIN_DATA}"]}}}"#,
        );
        let data = dir.path().join("d");
        let plugin = load(&root, "fleet@m", "p", &data, &Map::new());
        assert_eq!(plugin.name, "fleet");
        let command = plugin.mcp_servers["s"]["command"].as_str().unwrap();
        assert!(command.starts_with(&*root.to_string_lossy()) && command.ends_with("/run"));
        assert_eq!(
            plugin.mcp_servers["s"]["args"][0],
            Value::String(data.to_string_lossy().into())
        );
        assert!(plugin.problems.is_empty(), "{:?}", plugin.problems);
    }
}
