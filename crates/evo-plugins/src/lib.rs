//! Plugins: folders that bundle skills, commands, agent types, hooks and
//! connectors (MCP servers), installed from marketplaces.
//!
//! * [`manifest`]: a plugin folder. `.evo-plugin/plugin.json` (or
//!   `.claude-plugin/plugin.json`, or `plugin.json`) is optional;
//!   without it the folder's layout says what it holds (`skills/`,
//!   `commands/`, `agents/`, `hooks/hooks.json`, `.mcp.json`, `bin/`).
//!   `${PLUGIN_ROOT}`, `${PLUGIN_DATA}` and `${user_config.KEY}` are filled in
//!   in hooks and connector settings.
//! * [`marketplace`]: a catalog of plugins (`.evo-plugin/marketplace.json`,
//!   `.claude-plugin/marketplace.json` or `marketplace.json`) in a git repository — `owner/repo` on GitHub or any
//!   git URL, optionally `#ref` — or a local folder.
//! * [`store`]: what is installed (`<agent dir>/plugins`): marketplace clones,
//!   installed plugin copies per version, each plugin's data folder, and
//!   `installed.json` (version, where, on/off, settings).
//!
//! The engine reads [`store::Store::enabled`] to add the plugins' parts to a
//! session; the desktop shell manages installs.

pub mod manifest;
pub mod marketplace;
pub mod store;

pub use manifest::Plugin;
pub use marketplace::{Marketplace, MarketplaceSource};
pub use store::{Installed, Store};

/// Run `git` without a console window and without prompting for passwords.
pub(crate) fn git(args: &[&str], cwd: Option<&std::path::Path>) -> Result<String, String> {
    let mut cmd = std::process::Command::new("git");
    cmd.args(args).env("GIT_TERMINAL_PROMPT", "0");
    if let Some(dir) = cwd {
        cmd.current_dir(dir);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    let output = cmd
        .output()
        .map_err(|e| format!("could not run git: {e}"))?;
    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
    } else {
        let err = String::from_utf8_lossy(&output.stderr);
        Err(format!(
            "git {}: {}",
            args.first().copied().unwrap_or(""),
            err.trim()
        ))
    }
}

/// Copy a folder, leaving out `.git`.
pub(crate) fn copy_dir(from: &std::path::Path, to: &std::path::Path) -> Result<(), String> {
    std::fs::create_dir_all(to).map_err(|e| format!("{}: {e}", to.display()))?;
    for entry in std::fs::read_dir(from).map_err(|e| format!("{}: {e}", from.display()))? {
        let entry = entry.map_err(|e| e.to_string())?;
        let name = entry.file_name();
        if name == ".git" {
            continue;
        }
        let target = to.join(&name);
        if entry.file_type().map_err(|e| e.to_string())?.is_dir() {
            copy_dir(&entry.path(), &target)?;
        } else {
            std::fs::copy(entry.path(), &target)
                .map_err(|e| format!("{}: {e}", target.display()))?;
        }
    }
    Ok(())
}

/// A name for files and folders: letters, digits, `-`, `_`, `.`.
pub fn valid_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 64
        && !name.starts_with('.')
        && name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'))
}
