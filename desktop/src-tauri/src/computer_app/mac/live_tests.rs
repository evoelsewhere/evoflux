//! Drives a real TextEdit window. Opt-in because it opens a window on the
//! desktop it runs on, and it needs EvoFlux's test binary (or the terminal
//! running it) to have Accessibility and Screen Recording access:
//!
//! `cargo test computer_app -- --ignored --nocapture`
//!
//! It opens its own document in TextEdit without bringing TextEdit forward,
//! and checks the claim this module is built on: the frontmost app and the
//! user's cursor do not change while the agent works.

use super::*;

/// Dispatch by wire name, the way the agent's calls arrive.
fn run_action(emit: &dyn Fn(Value), session: &str, action: &str, params: &Value) -> Result<Value, String> {
    dispatch(emit, session, action.parse()?, params)
}

fn cursor() -> CGPoint {
    CGEvent::new(CGEventSource::new(CGEventSourceStateID::CombinedSessionState).unwrap())
        .unwrap()
        .location()
}

#[test]
#[ignore = "opens a TextEdit document on the local desktop"]
fn drives_textedit_in_the_background() {
    assert!(accessibility_trusted(false), "grant Accessibility to the terminal running the tests");
    let dir = std::env::temp_dir().join(format!("evoflux-computer-app-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let file = dir.join("computer-app-probe.txt");
    std::fs::write(&file, "start\n").unwrap();
    let front_before = frontmost_pid();
    let cursor_before = cursor();
    // -g: open without bringing TextEdit to the front.
    let status = std::process::Command::new("open")
        .args(["-g", "-a", "TextEdit"])
        .arg(&file)
        .status()
        .unwrap();
    assert!(status.success());
    let session = "live-test";
    let emit = |_: Value| {};
    let mut attached = Err(String::new());
    for _ in 0..40 {
        pause(250);
        attached = run_action(&emit, session, "attach", &json!({ "title": "computer-app-probe", "hide": true }));
        if attached.is_ok() {
            break;
        }
    }
    let attached = attached.expect("attach to the TextEdit document");
    println!("attached: {attached}");
    // A second document, opened last, becomes TextEdit's main window:
    // ⌘S below must still save the attached one.
    let other = dir.join("computer-app-other.txt");
    std::fs::write(&other, "other\n").unwrap();
    let status = std::process::Command::new("open").args(["-g", "-a", "TextEdit"]).arg(&other).status().unwrap();
    assert!(status.success());
    pause(1500);

    let snapshot = run_action(&emit, session, "snapshot", &json!({})).unwrap();
    let snapshot = snapshot.as_str().unwrap().to_string();
    println!("{snapshot}");
    let text_area = snapshot
        .lines()
        .find(|line| line.contains("- TextArea"))
        .and_then(|line| line.split("[ref=").nth(1))
        .and_then(|rest| rest.split(']').next())
        .expect("the document's text area")
        .to_string();

    let typed = run_action(&emit, session, "type", &json!({ "ref": text_area, "text": "hello from evoflux" })).unwrap();
    println!("type: {typed}");
    assert_eq!(typed["confirmed"], json!(true));

    let saved = run_action(&emit, session, "key", &json!({ "key": "cmd+s" })).unwrap();
    println!("key: {saved}");
    assert_eq!(saved["delivered_via"], json!("menu"));
    pause(800);
    let contents = std::fs::read_to_string(&file).unwrap();
    assert!(contents.contains("hello from evoflux"), "saved contents: {contents:?}");

    let screenshot = run_action(&emit, session, "screenshot", &json!({})).unwrap();
    assert!(screenshot["width"].as_u64().unwrap() > 100);

    let closing = run_action(&emit, session, "find", &json!({ "query": "close" })).unwrap();
    println!("{closing}");
    run_action(&emit, session, "detach", &json!({})).unwrap();

    assert_eq!(frontmost_pid(), front_before, "the frontmost app changed");
    // Only reported: the agent never moves the real cursor, but a user
    // working while the test runs does.
    let cursor_after = cursor();
    println!(
        "cursor before ({}, {}), after ({}, {})",
        cursor_before.x, cursor_before.y, cursor_after.x, cursor_after.y
    );
    // Close the document windows the test opened.
    let app = Ax::application(
        attached["window"]["pid"].as_i64().unwrap() as i32,
    )
    .unwrap();
    for window in app.elements("AXWindows") {
        let title = window.string("AXTitle").unwrap_or_default();
        if title.contains("computer-app-probe") || title.contains("computer-app-other") {
            if let Some(close) = window.element("AXCloseButton") {
                let _ = close.perform("AXPress");
            }
        }
    }
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
#[ignore = "reads the local Applications folders and running apps"]
fn lists_apps_with_icons() {
    let apps = list_apps();
    let apps = apps["apps"].as_array().unwrap();
    println!("{} apps", apps.len());
    assert!(apps.iter().any(|app| app["exe"] == json!("textedit")));
    assert!(apps.iter().filter(|app| app["icon"].is_string()).count() > apps.len() / 2);
}
