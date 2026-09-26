use super::*;

#[test]
fn types_every_line_break_including_blank_lines() {
    let units = |text: &str| String::from_utf16(&typed_units(text)).unwrap();
    assert_eq!(units("a\nb"), "a\rb");
    assert_eq!(units("a\r\nb"), "a\rb");
    // A blank line is two Enters, whichever line breaks it is written with.
    assert_eq!(units("title\n\nhead"), "title\r\rhead");
    assert_eq!(units("title\r\n\r\nhead"), "title\r\rhead");
    assert_eq!(units("a\r\rb"), "a\r\rb");
    assert_eq!(units("x\ty\n"), "x\ty\r");
}

#[test]
fn scales_points_into_a_dpi_unaware_window() {
    // A per-monitor aware window takes physical pixels as they are.
    assert_eq!(to_logical(300, 150, 1.0), (300, 150));
    // An unaware window on a 150% display (96 / 144).
    assert_eq!(to_logical(300, 150, 96.0 / 144.0), (200, 100));
    // A system-aware window (system 120 dpi) on a 144 dpi display.
    assert_eq!(to_logical(144, 72, 120.0 / 144.0), (120, 60));
}

#[test]
fn tells_apps_running_above_evoflux() {
    use windows::Win32::System::Threading::GetCurrentProcess;
    let ours = integrity_level(unsafe { GetCurrentProcess() }).expect("own integrity level");
    assert!(ours >= 0x2000, "unexpected integrity level {ours:#x}");
    assert!(!runs_above_us(unsafe { GetCurrentProcessId() }));
    const MEDIUM: u32 = 0x2000;
    const HIGH: u32 = 0x3000;
    assert!(is_above(MEDIUM, Some(HIGH)), "an elevated app");
    assert!(is_above(MEDIUM, None), "a token EvoFlux may not read");
    assert!(!is_above(MEDIUM, Some(MEDIUM)));
    assert!(!is_above(HIGH, Some(HIGH)), "an elevated EvoFlux drives elevated apps");
}

#[test]
fn resolves_lone_modifiers_numpad_and_high_function_keys() {
    assert_eq!(resolve_key("alt"), Some((VK_MENU, false)));
    assert_eq!(resolve_key("Ctrl"), Some((VK_CONTROL, false)));
    assert_eq!(resolve_key("shift"), Some((VK_SHIFT, false)));
    assert_eq!(resolve_key("numpad0"), Some((VIRTUAL_KEY(0x60), false)));
    assert_eq!(resolve_key("Numpad9"), Some((VIRTUAL_KEY(0x69), false)));
    assert_eq!(resolve_key("f13"), Some((VIRTUAL_KEY(0x7C), false)));
    assert_eq!(resolve_key("F24"), Some((VIRTUAL_KEY(0x87), false)));
    assert_eq!(resolve_key("f12"), Some((VK_F12, false)));
    assert_eq!(resolve_key("f25"), None);
    assert_eq!(resolve_key("numpadx"), None);
}

#[test]
fn records_a_window_placement_exactly() {
    let placement = WINDOWPLACEMENT {
        length: std::mem::size_of::<WINDOWPLACEMENT>() as u32,
        flags: WPF_RESTORETOMAXIMIZED,
        showCmd: SW_SHOWMINIMIZED.0 as u32,
        ptMinPosition: POINT { x: -32000, y: -32000 },
        ptMaxPosition: POINT { x: -1, y: -1 },
        rcNormalPosition: RECT { left: -1800, top: 40, right: -600, bottom: 900 },
    };
    let back = placement_from_json(&placement_json(&placement)).unwrap();
    assert_eq!(
        (back.flags, back.showCmd, back.ptMinPosition, back.ptMaxPosition, back.rcNormalPosition),
        (placement.flags, placement.showCmd, placement.ptMinPosition, placement.ptMaxPosition, placement.rcNormalPosition)
    );
    assert!(placement_from_json(&json!({ "flags": 0 })).is_none());
}

#[test]
fn confirms_native_typing_only_when_the_text_arrived_in_order() {
    assert!(typed_landed("abc", "abc hidden ok", " hidden ok"));
    // A rich edit stores line breaks as "\r".
    assert!(typed_landed("", "one\rtwo", "one\ntwo"));
    assert!(typed_landed("ac", "abc", "b"));
    assert!(!typed_landed("abc", "abc hidden ko", " hidden ok"));
    assert!(!typed_landed("abc", "abc ihdden ok", " hidden ok"));
    assert!(!typed_landed("hidden ok", "hidden ok", "hidden ok"), "nothing changed");
}

#[test]
fn retypes_only_a_readable_field_that_did_not_change() {
    let empty = Some(String::new());
    let typed = Some("hi".to_string());
    assert!(should_retype(true, &empty, &empty, false));
    // Unreadable field: both reads are None, which is not "unchanged".
    assert!(!should_retype(true, &None, &None, false));
    assert!(!should_retype(true, &empty, &None, false));
    // It changed, or it landed, or the read-back is stale.
    assert!(!should_retype(true, &empty, &typed, false));
    assert!(!should_retype(true, &typed, &typed, true));
    assert!(!should_retype(false, &empty, &empty, false));
}
