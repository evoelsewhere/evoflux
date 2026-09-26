//! Key names the agent sends ("ctrl+shift+s", "cmd+s", "Enter") and the
//! shortcuts it may never press. Shared by every backend; each one maps
//! [`KeyCombo::key`] to its own key codes.

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct KeyCombo {
    pub ctrl: bool,
    pub alt: bool,
    pub shift: bool,
    pub win: bool,
    /// ⌘ on macOS. Elsewhere "cmd" means Ctrl and this stays false.
    pub cmd: bool,
    pub key: String,
}

/// Parse "ctrl+shift+s", "Alt+F4", "cmd+s", "Enter" or "ctrl++" into a combo.
pub(crate) fn parse_key_combo(spec: &str) -> Result<KeyCombo, String> {
    let spec = spec.trim();
    if spec.is_empty() {
        return Err("key is empty".into());
    }
    let (mods, key) = if spec.len() > 1 && spec.ends_with("++") {
        (&spec[..spec.len() - 2], "+")
    } else if let Some(index) = spec.rfind('+').filter(|&i| i > 0) {
        (&spec[..index], &spec[index + 1..])
    } else {
        ("", spec)
    };
    let mut combo = KeyCombo {
        ctrl: false,
        alt: false,
        shift: false,
        win: false,
        cmd: false,
        key: key.trim().to_string(),
    };
    for part in mods.split('+').map(str::trim).filter(|part| !part.is_empty()) {
        match part.to_lowercase().as_str() {
            "ctrl" | "control" => combo.ctrl = true,
            "cmd" | "command" | "meta" => combo.cmd = true,
            "alt" | "option" | "opt" => combo.alt = true,
            "shift" => combo.shift = true,
            "win" | "windows" | "super" => combo.win = true,
            other => return Err(format!("unknown modifier {other:?} in {spec:?}")),
        }
    }
    if combo.key.is_empty() {
        return Err(format!("missing key in {spec:?}"));
    }
    #[cfg(not(target_os = "macos"))]
    {
        // Outside macOS "cmd+s" is what a Mac user calls Ctrl+S.
        combo.ctrl |= combo.cmd;
        combo.cmd = false;
    }
    Ok(combo)
}

/// Shortcuts that act on the whole desktop or session rather than the app.
pub(crate) fn blocked_combo_reason(combo: &KeyCombo) -> Option<&'static str> {
    let key = combo.key.to_lowercase();
    if combo.win || matches!(key.as_str(), "win" | "lwin" | "rwin" | "windows") {
        return Some("Windows-key shortcuts act on the desktop, not the attached app");
    }
    if combo.ctrl && combo.alt && matches!(key.as_str(), "delete" | "del") {
        return Some("Ctrl+Alt+Delete is a secure system sequence");
    }
    if combo.cmd && combo.ctrl && key == "q" {
        return Some("Control+Command+Q locks the Mac");
    }
    if combo.cmd && combo.shift && key == "q" {
        return Some("Shift+Command+Q logs the user out");
    }
    if combo.cmd && combo.alt && matches!(key.as_str(), "escape" | "esc") {
        return Some("Option+Command+Esc opens Force Quit for every app");
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_plain_and_modified_keys() {
        assert_eq!(
            parse_key_combo("Enter").unwrap(),
            KeyCombo {
                ctrl: false,
                alt: false,
                shift: false,
                win: false,
                cmd: false,
                key: "Enter".into()
            }
        );
        let combo = parse_key_combo("ctrl+Shift+s").unwrap();
        assert!(combo.ctrl && combo.shift && !combo.alt && !combo.cmd);
        assert_eq!(combo.key, "s");
        assert_eq!(parse_key_combo("ctrl++").unwrap().key, "+");
        assert_eq!(parse_key_combo("+").unwrap().key, "+");
        assert!(parse_key_combo("option+left").unwrap().alt);
        assert!(parse_key_combo("hyper+x").is_err());
        assert!(parse_key_combo("ctrl+").is_err());
    }

    #[test]
    fn cmd_is_command_on_macos_and_ctrl_elsewhere() {
        let combo = parse_key_combo("cmd+s").unwrap();
        if cfg!(target_os = "macos") {
            assert!(combo.cmd && !combo.ctrl);
        } else {
            assert!(combo.ctrl && !combo.cmd);
        }
    }

    #[test]
    fn blocks_desktop_level_shortcuts() {
        assert!(blocked_combo_reason(&parse_key_combo("win+l").unwrap()).is_some());
        assert!(blocked_combo_reason(&parse_key_combo("lwin").unwrap()).is_some());
        assert!(blocked_combo_reason(&parse_key_combo("ctrl+alt+delete").unwrap()).is_some());
        assert!(blocked_combo_reason(&parse_key_combo("alt+f4").unwrap()).is_none());
        assert!(blocked_combo_reason(&parse_key_combo("ctrl+s").unwrap()).is_none());
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn blocks_session_level_mac_shortcuts() {
        assert!(blocked_combo_reason(&parse_key_combo("ctrl+cmd+q").unwrap()).is_some());
        assert!(blocked_combo_reason(&parse_key_combo("cmd+shift+q").unwrap()).is_some());
        assert!(blocked_combo_reason(&parse_key_combo("cmd+option+esc").unwrap()).is_some());
        assert!(blocked_combo_reason(&parse_key_combo("cmd+q").unwrap()).is_none());
        assert!(blocked_combo_reason(&parse_key_combo("cmd+s").unwrap()).is_none());
    }
}
