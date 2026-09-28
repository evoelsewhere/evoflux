use super::*;

#[test]
fn finds_menu_shortcuts_on_special_keys() {
    assert_eq!(menu_key_equivalents("s"), Some((vec!["s".to_string()], vec![])));
    let (chars, glyphs) = menu_key_equivalents("backspace").unwrap();
    assert!(chars.contains(&"\u{7f}".to_string()) && glyphs == vec![0x17]);
    assert_eq!(menu_key_equivalents("left"), Some((vec!["\u{f702}".to_string()], vec![0x64])));
    assert_eq!(menu_key_equivalents("f1"), Some((vec!["\u{f704}".to_string()], vec![0x6F])));
    assert_eq!(menu_key_equivalents("f12"), Some((vec!["\u{f70f}".to_string()], vec![0x7A])));
    assert_eq!(menu_key_equivalents("f13"), None);
    assert_eq!(menu_key_equivalents("nosuchkey"), None);
}

fn window_row(app: &str, title: &str) -> WindowRow {
    WindowRow {
        id: 7,
        pid: 42,
        app: app.to_string(),
        title: title.to_string(),
        minimized: false,
        frame: Rect { x: 0.0, y: 0.0, w: 800.0, h: 600.0 },
        owner: None,
        focused: false,
    }
}

#[test]
fn name_attach_explains_protected_apps_instead_of_claiming_no_match() {
    let error = matching_window(
        vec![window_row("System Settings", "Privacy & Security")],
        Some("system settings"),
        None,
    )
    .err()
    .unwrap();

    assert!(error.contains("macOS system or its security settings"), "{error}");
}

#[test]
fn name_attach_still_selects_a_controllable_match() {
    let row = matching_window(
        vec![window_row("System Settings", "Settings"), window_row("TextEdit", "notes.txt")],
        None,
        Some("notes"),
    )
    .unwrap();

    assert_eq!(row.app, "TextEdit");
}

#[test]
fn parked_windows_survive_a_round_trip_through_the_file() {
    let list = vec![
        Stranded { window_id: 4242, pid: 99, parked: Parked { origin: (120.0, -35.5), minimized: false }, web: true },
        Stranded { window_id: 7, pid: 1, parked: Parked { origin: (0.0, 25.0), minimized: true }, web: false },
    ];
    let text = stranded_json(&list).to_string();
    assert_eq!(stranded_from_json(&text), list);
}

#[test]
fn unreadable_parked_records_are_skipped() {
    assert!(stranded_from_json("not json").is_empty());
    let text = r#"[{"window_id": 1, "pid": 2}, {"window_id": 3, "pid": 4, "origin": [5, 6], "minimized": false}]"#;
    let list = stranded_from_json(text);
    assert_eq!(list.len(), 1);
    assert_eq!(list[0].window_id, 3);
    assert!(!list[0].web);
}

#[test]
fn options_match_by_title_then_by_a_unique_start() {
    let titles: Vec<String> = ["Red", "Green", "Greenish", "Blue"].iter().map(|title| title.to_string()).collect();
    assert_eq!(matching_option(&titles, " blue "), Some(3));
    assert_eq!(matching_option(&titles, "Green"), Some(1));
    assert_eq!(matching_option(&titles, "gre"), None, "two options start with it");
    assert_eq!(matching_option(&titles, "bl"), Some(3));
    assert_eq!(matching_option(&titles, "purple"), None);
}
