//! Processes the agent may never attach to, whatever the user's allow list
//! says. Backends consult this before attaching.

/// Processes the agent may never attach to: the shell, session and security
/// processes whose windows are the desktop itself rather than an app.
#[cfg(not(target_os = "macos"))]
const PROTECTED_PROCESS_NAMES: &[&str] = &[
    "explorer.exe",
    "csrss.exe",
    "winlogon.exe",
    "wininit.exe",
    "services.exe",
    "lsass.exe",
    "smss.exe",
    "dwm.exe",
    "logonui.exe",
    "consent.exe",
    "lockapp.exe",
    "searchhost.exe",
    "startmenuexperiencehost.exe",
    "shellexperiencehost.exe",
    "textinputhost.exe",
    "system",
];

/// The macOS counterparts, by executable name. System Settings is here
/// because it is where apps are granted Accessibility and Screen Recording
/// access — an agent must not be able to grant itself more.
#[cfg(target_os = "macos")]
const PROTECTED_PROCESS_NAMES: &[&str] = &[
    "finder",
    "dock",
    "windowserver",
    "loginwindow",
    "systemuiserver",
    "controlcenter",
    "notificationcenter",
    "spotlight",
    "securityagent",
    "coreautha",
    "screensaverengine",
    "windowmanager",
    "system settings",
    "system preferences",
    "keychain access",
    "passwords",
];

/// Apps that run commands or scripts, by executable name. Typing into one
/// runs anything at all, with that app's own permissions (a terminal often
/// has Full Disk Access; Script Editor and Shortcuts can drive every other
/// app) and outside every EvoFlux sandbox, so they are never attached.
#[cfg(target_os = "macos")]
const COMMAND_RUNNERS: &[&str] = &[
    "terminal",
    "iterm2",
    "script editor",
    "shortcuts",
    "automator",
    "alacritty",
    "kitty",
    "wezterm-gui",
    "ghostty",
    "hyper",
];

#[cfg(not(target_os = "macos"))]
const COMMAND_RUNNERS: &[&str] = &[];

fn process_key(identifier: &str) -> String {
    identifier
        .rsplit(['\\', '/'])
        .next()
        .unwrap_or(identifier)
        .to_lowercase()
}

pub(crate) fn is_protected_process_name(identifier: &str) -> bool {
    let name = process_key(identifier);
    PROTECTED_PROCESS_NAMES.contains(&name.as_str()) || COMMAND_RUNNERS.contains(&name.as_str())
}

/// Whether `identifier` is one of the [`COMMAND_RUNNERS`].
#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
pub(crate) fn is_command_runner(identifier: &str) -> bool {
    COMMAND_RUNNERS.contains(&process_key(identifier).as_str())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    #[cfg(target_os = "macos")]
    fn never_attaches_terminals_or_script_runners() {
        for app in ["Terminal", "/Applications/iTerm.app/Contents/MacOS/iTerm2", "Script Editor", "Shortcuts"] {
            assert!(is_command_runner(app), "{app}");
            assert!(is_protected_process_name(app), "{app}");
        }
        assert!(!is_command_runner("TextEdit"));
        assert!(!is_protected_process_name("TextEdit"));
    }

    #[cfg(not(target_os = "macos"))]
    #[test]
    fn protected_names_match_paths_case_insensitively() {
        assert!(is_protected_process_name("C:\\Windows\\Explorer.EXE"));
        assert!(is_protected_process_name("lsass.exe"));
        assert!(!is_protected_process_name("notepad.exe"));
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn protected_names_match_mac_executables() {
        assert!(is_protected_process_name("/System/Library/CoreServices/Finder.app/Contents/MacOS/Finder"));
        assert!(is_protected_process_name("System Settings"));
        assert!(!is_protected_process_name("TextEdit"));
    }
}
