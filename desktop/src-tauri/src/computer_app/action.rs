//! The actions an agent can ask for, parsed once at the command boundary so
//! every backend matches on the same closed set.

use std::str::FromStr;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Action {
    // Session: no window has to be attached yet.
    Status,
    ListWindows,
    Attach,
    Detach,
    // Reading the attached window.
    Screenshot,
    Snapshot,
    Find,
    // Input to the attached window.
    Click,
    Hover,
    Scroll,
    Drag,
    Type,
    Key,
    Invoke,
    SetValue,
    /// Bring a minimized window back to a capturable size.
    Restore,
    // App lifecycle: act on an app rather than on input to its window.
    /// Search the installed and running apps.
    SearchApps,
    /// Launch an app from the catalog and report its new window.
    OpenApp,
    /// Ask a window to close, as its close button would.
    CloseApp,
    /// Terminate a window's process at once.
    KillApp,
}

impl Action {
    const NAMES: [(&'static str, Action); 20] = [
        ("status", Action::Status),
        ("list_windows", Action::ListWindows),
        ("attach", Action::Attach),
        ("detach", Action::Detach),
        ("screenshot", Action::Screenshot),
        ("snapshot", Action::Snapshot),
        ("find", Action::Find),
        ("click", Action::Click),
        ("hover", Action::Hover),
        ("scroll", Action::Scroll),
        ("drag", Action::Drag),
        ("type", Action::Type),
        ("key", Action::Key),
        ("invoke", Action::Invoke),
        ("set_value", Action::SetValue),
        ("restore", Action::Restore),
        ("search_apps", Action::SearchApps),
        ("open_app", Action::OpenApp),
        ("close_app", Action::CloseApp),
        ("kill_app", Action::KillApp),
    ];

    /// Whether the action sends input to the app, as opposed to reading it
    /// or managing the session.
    #[cfg_attr(not(target_os = "windows"), allow(dead_code))]
    pub(crate) fn is_input(self) -> bool {
        matches!(
            self,
            Action::Click
                | Action::Hover
                | Action::Scroll
                | Action::Drag
                | Action::Type
                | Action::Key
                | Action::Invoke
                | Action::SetValue
        )
    }
}

impl FromStr for Action {
    type Err = String;

    fn from_str(name: &str) -> Result<Self, String> {
        Self::NAMES
            .iter()
            .find(|(known, _)| *known == name)
            .map(|(_, action)| *action)
            .ok_or_else(|| format!("Unknown Computer App Control action: {name}"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_every_wire_name_and_nothing_else() {
        for (name, action) in Action::NAMES {
            assert_eq!(name.parse::<Action>().unwrap(), action);
        }
        assert!("teleport".parse::<Action>().is_err());
        assert!("Click".parse::<Action>().is_err());
    }

    #[test]
    fn only_input_actions_count_as_input() {
        assert!(Action::Type.is_input() && Action::SetValue.is_input());
        assert!(!Action::Screenshot.is_input() && !Action::Attach.is_input());
    }
}
