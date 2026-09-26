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
