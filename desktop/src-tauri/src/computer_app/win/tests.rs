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
fn sizes_the_stage_for_the_display() {
    // 100% and 125%: 1280×800, screenshotted without scaling.
    assert_eq!(stage_size(96), (1280, 800));
    assert_eq!(stage_size(120), (1280, 800));
    assert_eq!(screenshot_scale(1280, 800), 1.0);
    // Past 125%, never less than 1024×640 logical pixels.
    assert_eq!(stage_size(144), (1536, 960));
    assert_eq!(stage_size(192), (2048, 1280));
    // A DPI that could not be read counts as 100%.
    assert_eq!(stage_size(0), (1280, 800));
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
fn tells_toolkits_that_drop_posted_input() {
    assert_eq!(toolkit_of_class("HwndWrapper[Notes.exe;;6b3f]"), Some(Toolkit::Wpf));
    assert_eq!(toolkit_of_class("gdkWindowToplevel"), Some(Toolkit::Gtk));
    assert_eq!(toolkit_of_class("gdkSurfaceToplevel"), Some(Toolkit::Gtk));
    assert_eq!(toolkit_of_class("TkTopLevel"), Some(Toolkit::Tk));
    assert_eq!(toolkit_of_class("SALFRAME"), Some(Toolkit::Vcl));
    assert_eq!(toolkit_of_class("Notepad"), None);
    assert_eq!(toolkit_of_class("SALAD"), None);
    // Only the kinds cua measured as dropped get a note.
    assert!(dropped_input_note(Toolkit::Wpf, PostedInput::Pointer).is_some());
    assert!(dropped_input_note(Toolkit::Gtk, PostedInput::Keys).is_none());
    assert!(dropped_input_note(Toolkit::Vcl, PostedInput::Keys).is_some());
    assert!(dropped_input_note(Toolkit::Vcl, PostedInput::Pointer).is_none());
    assert!(dropped_input_note(Toolkit::Tk, PostedInput::Text).is_some());

    let mut result = json!({ "note": "A menu opened." });
    add_note(&mut result, "It may not have landed.");
    assert_eq!(result["note"], "A menu opened. It may not have landed.");
    let mut plain = json!({});
    add_note(&mut plain, "Only this.");
    assert_eq!(plain["note"], "Only this.");
}

#[test]
fn presses_plus_as_the_plus_character() {
    // "=" is the key itself, "plus" and "+" the character on it.
    assert_eq!(resolve_key("="), Some((VK_OEM_PLUS, false)));
    assert_eq!(resolve_key("plus"), resolve_key("+"));
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
