//! Measures how each kind of input works on the surfaces apps are built
//! from — a grid of cells, a text document — in real apps, each started as
//! an instance of its own and parked. Opt-in, since it opens windows:
//!
//! `cargo test measures_input -- --ignored --nocapture --test-threads=1`
//!
//! Nothing here knows an app. A surface is whatever UI Automation says it
//! is (an element with the Grid pattern, a document with the Text pattern);
//! cells and words are aimed at from their own positions, so only the input
//! is measured, not the aim; every outcome is read back through the same
//! patterns. The apps at the end only say how to start each with an empty
//! surface. The cases print pass/fail and fail nothing: this is a
//! measurement, and some input has no way to work in the background.

use super::*;
use windows::Win32::System::Com::SAFEARRAY;
use windows::Win32::System::Ole::{SafeArrayAccessData, SafeArrayDestroy, SafeArrayGetUBound, SafeArrayUnaccessData};
use windows::Win32::System::Variant::VARIANT;
use windows::Win32::UI::Accessibility::{
    IUIAutomationGridPattern, IUIAutomationTextPattern, IUIAutomationTextRange, TreeScope_Descendants,
    UIA_ControlTypePropertyId, UIA_FontWeightAttributeId, UIA_GridPatternId,
    UIA_IsGridPatternAvailablePropertyId, UIA_IsTextPatternAvailablePropertyId, UIA_TextPatternId,
    UIA_PROPERTY_ID,
};

// ── Harness ─────────────────────────────────────────────────────────────

/// How to start an app with an empty surface, and leave nothing behind.
pub(super) struct Launch {
    pub(super) exe: &'static str,
    pub(super) args: &'static [&'static str],
    /// Keys that open an empty surface once the window is up.
    pub(super) blank: &'static [&'static str],
    /// Keys that leave nothing for the app to restore next time.
    pub(super) cleanup: &'static [&'static str],
}

/// Top-level windows of `exe`: (window id, pid).
pub(super) fn app_windows(exe: &str) -> Vec<(u64, u32)> {
    let stem = exe.trim_end_matches(".exe");
    list_windows("live-bench", &json!({ "query": stem }))["windows"]
        .as_array()
        .cloned()
        .unwrap_or_default()
        .iter()
        .filter(|window| window["app"].as_str().unwrap_or("").eq_ignore_ascii_case(exe))
        .map(|window| (window["id"].as_u64().unwrap_or(0), window["pid"].as_u64().unwrap_or(0) as u32))
        .collect()
}

/// Start an instance of the app of its own: its window id and pid, or
/// `None` when the app is not installed or showed no new window.
pub(super) fn start_private(launch: &Launch) -> Option<(u64, u32)> {
    let before: Vec<u32> = app_windows(launch.exe).into_iter().map(|(_, pid)| pid).collect();
    let mut args = vec!["/C", "start", "", "/min", launch.exe];
    args.extend(launch.args);
    let started = std::process::Command::new("cmd").args(&args).status().is_ok_and(|status| status.success());
    if !started {
        return None;
    }
    for _ in 0..100 {
        pause(300);
        if let Some(launched) = app_windows(launch.exe).into_iter().find(|(_, pid)| !before.contains(pid)) {
            // An app paints its first window a moment after showing it.
            pause(2500);
            return Some(launched);
        }
    }
    None
}

/// Run `body` on a private, parked instance of the app with an empty
/// surface, then end that instance only.
fn with_private_app(launch: &Launch, session: &str, body: impl FnOnce(&dyn Fn(Value))) {
    unsafe {
        let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
    }
    let Some((window_id, pid)) = start_private(launch) else {
        eprintln!("skipped: {} is not installed or did not open", launch.exe);
        return;
    };
    let emit = |_: Value| {};
    let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        act(&emit, session, "attach", json!({ "window_id": window_id, "hide": true })).unwrap();
        for key in launch.blank {
            let _ = act(&emit, session, "key", json!({ "key": key }));
        }
        pause(3000);
        body(&emit);
    }));
    for key in launch.cleanup {
        let _ = act(&emit, session, "key", json!({ "key": key }));
        pause(200);
    }
    detach(session);
    let _ = std::process::Command::new("taskkill").args(["/PID", &pid.to_string(), "/F"]).status();
    if let Err(panic) = outcome {
        std::panic::resume_unwind(panic);
    }
}

fn act(emit: &dyn Fn(Value), session: &str, action: &str, params: Value) -> Result<Value, String> {
    dispatch(emit, session, action.parse()?, &params)
}

/// Pass/fail rows, printed as they come and as a table at the end.
#[derive(Default)]
struct Rows(Vec<(String, bool)>);

impl Rows {
    fn record(&mut self, case: &str, pass: bool, detail: impl std::fmt::Display) {
        eprintln!("{} {case}: {detail}", if pass { "PASS" } else { "FAIL" });
        self.0.push((case.to_string(), pass));
    }

    fn print(&self, surface: &str, app: &str) {
        let passed = self.0.iter().filter(|(_, pass)| *pass).count();
        eprintln!("\n{surface} in {app}: {passed} of {} passed", self.0.len());
        for (case, pass) in &self.0 {
            eprintln!("  {} {case}", if *pass { "✓" } else { "✗" });
        }
    }
}

/// The first element in the attached window whose `property` is `value`
/// (and, when given, whose control type is `kind`).
fn first_element(session: &str, property: UIA_PROPERTY_ID, kind: Option<i32>) -> Option<IUIAutomationElement> {
    let target = Target::resolve(session).ok()?;
    let automation = automation().ok()?;
    let root = unsafe { automation.ElementFromHandle(target.window) }.ok()?;
    let mut condition = unsafe { automation.CreatePropertyCondition(property, &VARIANT::from(true)) }.ok()?;
    if let Some(kind) = kind {
        let of_kind = unsafe { automation.CreatePropertyCondition(UIA_ControlTypePropertyId, &VARIANT::from(kind)) }.ok()?;
        condition = unsafe { automation.CreateAndCondition(&condition, &of_kind) }.ok()?;
    }
    unsafe { root.FindFirst(TreeScope_Descendants, &condition) }.ok()
}

/// A screen rectangle's centre in the attached window's screenshot pixels.
fn aim(session: &str, rect: RECT) -> Option<(f64, f64)> {
    let target = Target::resolve(session).ok()?;
    let (x, y) = target.screenshot_point(POINT { x: (rect.left + rect.right) / 2, y: (rect.top + rect.bottom) / 2 });
    Some((x as f64, y as f64))
}

fn aim_at(session: &str, point: POINT) -> Option<(f64, f64)> {
    let (x, y) = Target::resolve(session).ok()?.screenshot_point(point);
    Some((x as f64, y as f64))
}

/// A control's text: its Value pattern, else its legacy value.
fn value_of(element: &IUIAutomationElement) -> String {
    if let Some(value) = pattern::<IUIAutomationValuePattern>(element, UIA_ValuePatternId) {
        let text = bstr(unsafe { value.CurrentValue() });
        if !text.is_empty() {
            return text;
        }
    }
    pattern::<IUIAutomationLegacyIAccessiblePattern>(element, UIA_LegacyIAccessiblePatternId)
        .map(|legacy| bstr(unsafe { legacy.CurrentValue() }))
        .unwrap_or_default()
}

fn selected(element: &IUIAutomationElement) -> bool {
    pattern::<IUIAutomationSelectionItemPattern>(element, UIA_SelectionItemPatternId)
        .and_then(|item| unsafe { item.CurrentIsSelected() }.ok())
        .is_some_and(|selected| selected.as_bool())
}

/// The formatting toggle named "Bold", if the app has one: its ref, its
/// centre, and whether it is on.
fn bold_button(emit: &dyn Fn(Value), session: &str) -> Option<(String, f64, f64, bool)> {
    let found = act(emit, session, "find", json!({ "query": "Bold" })).ok()?;
    let line = found.as_str()?.lines().find(|line| line.contains("Button \"Bold\""))?.to_string();
    let reference = line.split("[ref=").nth(1)?.split(']').next()?.to_string();
    let geometry = line.split(" @").nth(1)?;
    let (at, size) = geometry.split_once(' ')?;
    let (x, y) = at.split_once(',')?;
    let (width, height) = size.split_once('x')?;
    let centre = |start: &str, length: &str| Some(start.parse::<f64>().ok()? + length.parse::<f64>().ok()? / 2.0);
    Some((reference, centre(x, width)?, centre(y, height)?, line.contains("[checked]")))
}

/// Whether the Bold toggle turns on within a moment: it follows the
/// selection's formatting a little after the change.
fn bold_turns_on(emit: &dyn Fn(Value), session: &str) -> bool {
    (0..10).any(|_| {
        pause(150);
        bold_button(emit, session).is_some_and(|(_, _, _, on)| on)
    })
}

/// Turn Bold off for the selection. The toggle catches up with a new
/// selection a moment later, so it is only trusted once two readings half
/// a second apart agree.
fn bold_off(emit: &dyn Fn(Value), session: &str) {
    let reading = || bold_button(emit, session).map(|(_, _, _, on)| on);
    for _ in 0..4 {
        pause(500);
        let first = reading();
        pause(500);
        if reading() != first {
            continue;
        }
        if first == Some(true) {
            let _ = act(emit, session, "key", json!({ "key": "ctrl+b" }));
            continue;
        }
        return;
    }
}

/// The formatting-toggle cases, on whatever is selected by `select`, when
/// the app has a Bold toggle at all.
fn measure_bold(emit: &dyn Fn(Value), session: &str, rows: &mut Rows, select: &dyn Fn()) {
    let Some((reference, x, y, _)) = bold_button(emit, session) else {
        eprintln!("no Bold toggle: formatting cases skipped");
        return;
    };
    select();
    bold_off(emit, session);
    let result = act(emit, session, "click", json!({ "x": x, "y": y }));
    let on = bold_turns_on(emit, session);
    rows.record("click a toolbar toggle (Bold)", on, format!("{result:?}"));

    select();
    bold_off(emit, session);
    let result = act(emit, session, "invoke", json!({ "ref": reference }));
    rows.record("invoke a toolbar toggle by ref (Bold)", bold_turns_on(emit, session), format!("{result:?}"));

    select();
    bold_off(emit, session);
    let _ = act(emit, session, "key", json!({ "key": "ctrl+b" }));
    rows.record("shortcut ctrl+b", bold_turns_on(emit, session), "");
    bold_off(emit, session);
}

// ── Grids ───────────────────────────────────────────────────────────────

struct Grid<'a> {
    emit: &'a dyn Fn(Value),
    session: &'a str,
    /// The first data cell's row and column in the grid's numbering.
    origin: std::cell::Cell<(i32, i32)>,
}

impl Grid<'_> {
    fn pattern(&self) -> Option<(IUIAutomationElement, IUIAutomationGridPattern)> {
        let grid = first_element(self.session, UIA_IsGridPatternAvailablePropertyId, None)?;
        let pattern = pattern::<IUIAutomationGridPattern>(&grid, UIA_GridPatternId)?;
        Some((grid, pattern))
    }

    /// A data cell by its place from the first one (see [`Grid::find_origin`]).
    fn cell(&self, row: i32, column: i32) -> Option<IUIAutomationElement> {
        let (_, grid) = self.pattern()?;
        let (first_row, first_column) = self.origin.get();
        unsafe { grid.GetItem(first_row + row, first_column + column) }.ok()
    }

    /// Where the data starts in the grid's own numbering. A grid may hold
    /// its column and row headers as items too, of the same type as its
    /// cells; the first data cell is the one selected after going to the
    /// start of the grid, which no header ever is.
    fn find_origin(&self) -> bool {
        self.reset();
        let Some((_, grid)) = self.pattern() else { return false };
        for row in 0..4 {
            for column in 0..4 {
                if unsafe { grid.GetItem(row, column) }.is_ok_and(|cell| selected(&cell)) {
                    self.origin.set((row, column));
                    return true;
                }
            }
        }
        false
    }

    fn rect(&self, row: i32, column: i32) -> Option<RECT> {
        unsafe { self.cell(row, column)?.CurrentBoundingRectangle() }.ok()
    }

    fn at(&self, row: i32, column: i32) -> (f64, f64) {
        self.rect(row, column).and_then(|rect| aim(self.session, rect)).expect("a visible cell")
    }

    fn value(&self, row: i32, column: i32) -> String {
        self.cell(row, column).map(|cell| value_of(&cell)).unwrap_or_default()
    }

    fn selected(&self, row: i32, column: i32) -> bool {
        self.cell(row, column).is_some_and(|cell| selected(&cell))
    }

    fn act(&self, action: &str, params: Value) -> Result<Value, String> {
        act(self.emit, self.session, action, params)
    }

    /// Nothing being edited, the first cell selected alone.
    fn reset(&self) {
        let _ = self.act("key", json!({ "key": "escape" }));
        let _ = self.act("key", json!({ "key": "ctrl+home" }));
        pause(300);
    }

    /// Which of `cells` a selection covers, told by what Delete clears
    /// (then undone).
    fn cleared_by_delete(&self, cells: &[(i32, i32)]) -> Vec<bool> {
        let _ = self.act("key", json!({ "key": "delete" }));
        pause(300);
        let cleared = cells.iter().map(|(row, column)| self.value(*row, *column).is_empty()).collect();
        let _ = self.act("key", json!({ "key": "ctrl+z" }));
        pause(300);
        cleared
    }
}

fn measure_grid(launch: &Launch) {
    let session = "live-bench-grid";
    let mut rows = Rows::default();
    with_private_app(launch, session, |emit| {
        let grid = Grid { emit, session, origin: std::cell::Cell::new((0, 0)) };
        if !grid.find_origin() {
            eprintln!("no grid with a selectable first cell in {}", launch.exe);
            return;
        }
        let (x, y) = grid.at(0, 0);
        let _ = grid.act("click", json!({ "x": x, "y": y }));
        let _ = grid.act("type", json!({ "text": "a\tb\tc\n1\t2\t3\n4\t5\t6\n" }));

        grid.reset();
        rows.record("read: a cell's value", grid.value(1, 1) == "2", format!("{:?}", grid.value(1, 1)));
        rows.record("read: the selected cell", grid.selected(0, 0), "");
        let tree = act(emit, session, "snapshot", json!({})).unwrap_or_default();
        let tree = tree.as_str().unwrap_or("");
        rows.record(
            "snapshot shows cell values and the selection",
            tree.contains("value=\"2\"") && tree.contains("[selected]"),
            "",
        );

        grid.reset();
        let (x, y) = grid.at(1, 2);
        let started = std::time::Instant::now();
        let result = grid.act("click", json!({ "x": x, "y": y }));
        let took = started.elapsed().as_millis();
        pause(300);
        rows.record("click a cell", grid.selected(1, 2) && !grid.selected(0, 0), format!("{took} ms; {result:?}"));

        grid.reset();
        let (x, y) = grid.at(2, 1);
        let _ = grid.act("click", json!({ "x": x, "y": y, "clicks": 2 }));
        pause(300);
        let _ = grid.act("type", json!({ "text": "X\n" }));
        pause(300);
        // Where the caret lands in the cell is the app's: before or after.
        let value = grid.value(2, 1);
        rows.record("double-click a cell to edit it", value == "X5" || value == "5X", format!("{value:?}"));
        if value != "5" {
            let _ = grid.act("key", json!({ "key": "ctrl+z" }));
        }

        grid.reset();
        let (from_x, from_y) = grid.at(0, 0);
        let (to_x, to_y) = grid.at(2, 2);
        let _ = grid.act("drag", json!({ "x": from_x, "y": from_y, "to_x": to_x, "to_y": to_y }));
        pause(300);
        let cleared = grid.cleared_by_delete(&[(0, 0), (1, 1), (2, 2)]);
        rows.record("drag across cells selects them", cleared == [true, true, true], format!("cleared {cleared:?}"));

        grid.reset();
        let (x, y) = grid.at(2, 2);
        let result = grid.act("click", json!({ "x": x, "y": y, "modifiers": ["shift"] }));
        pause(300);
        rows.record("shift+click extends the selection", grid.selected(1, 1) && grid.selected(2, 2), format!("{result:?}"));

        grid.reset();
        let (x, y) = grid.at(2, 2);
        let _ = grid.act("click", json!({ "x": x, "y": y, "modifiers": ["ctrl"] }));
        pause(300);
        let cleared = grid.cleared_by_delete(&[(0, 0), (1, 1), (2, 2)]);
        rows.record("ctrl+click adds a cell", cleared == [true, false, true], format!("cleared {cleared:?}"));

        grid.reset();
        let _ = grid.act("key", json!({ "key": "shift+down" }));
        pause(300);
        rows.record("shift+arrow extends the selection", grid.selected(1, 0), "");

        grid.reset();
        let (x, y) = grid.at(1, 2);
        let result = grid.act("click", json!({ "x": x, "y": y, "button": "right" }));
        pause(500);
        let menu = result.as_ref().is_ok_and(|result| result["note"].as_str().unwrap_or("").contains("menu"));
        rows.record("right-click opens a context menu", menu, format!("{result:?}"));
        let _ = grid.act("key", json!({ "key": "escape" }));

        // Scrolled out of view, the first cell is no longer listed (a grid
        // may still report its old position).
        grid.reset();
        let first = grid.cell(0, 0).map(|cell| bstr(unsafe { cell.CurrentName() })).unwrap_or_default();
        let listed = |name: &str| {
            act(emit, session, "find", json!({ "query": name }))
                .ok()
                .and_then(|found| found.as_str().map(|text| text.contains(&format!("\"{name}\""))))
                .unwrap_or(false)
        };
        let (x, y) = grid.at(1, 1);
        let _ = grid.act("scroll", json!({ "x": x, "y": y, "direction": "down", "amount": 5 }));
        pause(400);
        rows.record("scroll the grid", listed(&first) == false, format!("first cell {first:?}"));

        grid.reset();
        let (x, y) = grid.at(1, 1);
        rows.record("hover a cell", grid.act("hover", json!({ "x": x, "y": y })).is_ok(), "");

        // A control the app draws itself inside the grid's window, with no
        // window of its own: pressed through its own action.
        grid.reset();
        if let Some((name, point)) = drawn_button(&grid) {
            let (x, y) = aim_at(session, point).unwrap();
            let result = grid.act("click", json!({ "x": x, "y": y }));
            let via_action = result.as_ref().is_ok_and(|result| result["delivered_via"] == "ui_automation");
            rows.record("click a button drawn inside the content window", via_action, format!("{name}: {result:?}"));
            let _ = grid.act("key", json!({ "key": "ctrl+z" }));
        }

        let select = || grid.reset();
        measure_bold(emit, session, &mut rows, &select);
    });
    rows.print("Grid", launch.exe);
}

/// An enabled button with no window of its own inside the window that
/// holds the grid — one the app draws itself — and its centre. Only that
/// window is searched: the title bar's buttons would close or minimize.
fn drawn_button(grid: &Grid) -> Option<(String, POINT)> {
    let (element, _) = grid.pattern()?;
    let area = unsafe { element.CurrentBoundingRectangle() }.ok()?;
    let target = Target::resolve(grid.session).ok()?;
    let host = child_at(target.window, POINT { x: (area.left + area.right) / 2, y: (area.top + area.bottom) / 2 });
    if host == target.window {
        return None;
    }
    let automation = automation().ok()?;
    let root = unsafe { automation.ElementFromHandle(host) }.ok()?;
    let kind = unsafe { automation.CreatePropertyCondition(UIA_ControlTypePropertyId, &VARIANT::from(50000i32)) }.ok()?;
    let buttons = unsafe { root.FindAll(TreeScope_Descendants, &kind) }.ok()?;
    for index in 0..unsafe { buttons.Length() }.unwrap_or(0) {
        let button = unsafe { buttons.GetElement(index) }.ok()?;
        let own_window = unsafe { button.CurrentNativeWindowHandle() }.ok().is_some_and(|hwnd| !hwnd.0.is_null());
        let enabled = unsafe { button.CurrentIsEnabled() }.is_ok_and(|on| on.as_bool());
        let rect = unsafe { button.CurrentBoundingRectangle() }.unwrap_or_default();
        if !own_window && enabled && rect.right > rect.left && rect.bottom > rect.top {
            let name = bstr(unsafe { button.CurrentName() });
            return Some((name, POINT { x: (rect.left + rect.right) / 2, y: (rect.top + rect.bottom) / 2 }));
        }
    }
    None
}

// ── Documents ───────────────────────────────────────────────────────────

const SENTENCE: &str = "The quick brown fox jumps over the lazy dog.";

struct Document<'a> {
    emit: &'a dyn Fn(Value),
    session: &'a str,
}

impl Document<'_> {
    fn text_pattern(&self) -> Option<(IUIAutomationElement, IUIAutomationTextPattern)> {
        // Document = 50030.
        let document = first_element(self.session, UIA_IsTextPatternAvailablePropertyId, Some(50030))?;
        let pattern = pattern::<IUIAutomationTextPattern>(&document, UIA_TextPatternId)?;
        Some((document, pattern))
    }

    fn text(&self) -> String {
        self.text_pattern()
            .and_then(|(_, text)| unsafe { text.DocumentRange() }.ok())
            .and_then(|range| unsafe { range.GetText(-1) }.ok())
            .map(|text| text.to_string())
            .unwrap_or_default()
    }

    fn selection(&self) -> String {
        self.text_pattern()
            .and_then(|(_, text)| unsafe { text.GetSelection() }.ok())
            .and_then(|ranges| unsafe { ranges.GetElement(0) }.ok())
            .and_then(|range| unsafe { range.GetText(-1) }.ok())
            .map(|text| text.to_string())
            .unwrap_or_default()
    }

    fn word(&self, word: &str) -> Option<IUIAutomationTextRange> {
        let (_, text) = self.text_pattern()?;
        let all = unsafe { text.DocumentRange() }.ok()?;
        unsafe { all.FindText(&BSTR::from(word), false, false) }.ok()
    }

    /// Where `word` is drawn, in screen pixels.
    fn word_rect(&self, word: &str) -> Option<RECT> {
        let range = self.word(word)?;
        let rects = unsafe { range.GetBoundingRectangles() }.ok()?;
        let values = unsafe { doubles(rects) };
        let [left, top, width, height] = values.get(..4)? else { return None };
        Some(RECT {
            left: *left as i32,
            top: *top as i32,
            right: (*left + *width) as i32,
            bottom: (*top + *height) as i32,
        })
    }

    fn bold(&self, word: &str) -> bool {
        self.word(word)
            .and_then(|range| unsafe { range.GetAttributeValue(UIA_FontWeightAttributeId) }.ok())
            .and_then(|weight| i32::try_from(&weight).ok())
            .is_some_and(|weight| weight >= 600)
    }

    fn act(&self, action: &str, params: Value) -> Result<Value, String> {
        act(self.emit, self.session, action, params)
    }

    fn click_at(&self, point: POINT, extra: Value) -> Result<Value, String> {
        let (x, y) = aim_at(self.session, point).expect("a point in the window");
        self.act("click", merge(json!({ "x": x, "y": y }), extra))
    }

    /// Nothing selected, the caret at the start.
    fn reset(&self) {
        let _ = self.act("key", json!({ "key": "escape" }));
        let _ = self.act("key", json!({ "key": "ctrl+home" }));
        pause(300);
    }
}

/// The `f64`s of a SAFEARRAY UI Automation handed over (and frees).
unsafe fn doubles(array: *mut SAFEARRAY) -> Vec<f64> {
    if array.is_null() {
        return Vec::new();
    }
    let mut values = Vec::new();
    unsafe {
        let upper = SafeArrayGetUBound(array, 1).unwrap_or(-1);
        let mut data: *mut core::ffi::c_void = std::ptr::null_mut();
        if upper >= 0 && SafeArrayAccessData(array, &mut data).is_ok() {
            values.extend_from_slice(std::slice::from_raw_parts(data as *const f64, (upper + 1) as usize));
            let _ = SafeArrayUnaccessData(array);
        }
        let _ = SafeArrayDestroy(array);
    }
    values
}

fn measure_document(launch: &Launch) {
    let session = "live-bench-document";
    let mut rows = Rows::default();
    with_private_app(launch, session, |emit| {
        let doc = Document { emit, session };
        let Some((element, _)) = doc.text_pattern() else {
            eprintln!("no text document in {}", launch.exe);
            return;
        };
        let body = unsafe { element.CurrentBoundingRectangle() }.unwrap_or_default();
        let _ = doc.click_at(POINT { x: (body.left + body.right) / 2, y: (body.top + body.bottom) / 2 }, json!({}));
        let _ = doc.act("type", json!({ "text": format!("{SENTENCE}\nA second line of text.\n") }));
        pause(500);
        let typed = doc.text();
        rows.record("type text", typed.contains(SENTENCE), format!("{:?}", typed.chars().take(60).collect::<String>()));
        if !typed.contains(SENTENCE) {
            // The cases below aim at its words: start them from the text as meant.
            let _ = doc.act("key", json!({ "key": "ctrl+a" }));
            let _ = doc.act("type", json!({ "text": format!("{SENTENCE}\nA second line of text.\n") }));
            pause(500);
        }
        let words = (doc.word_rect("brown"), doc.word_rect("quick"), doc.word_rect("fox"), doc.word_rect("lazy"));
        let (Some(brown), Some(quick), Some(fox), Some(lazy)) = words else {
            rows.record("find the typed words on screen", false, format!("{:?}", doc.text()));
            return;
        };

        // A click in the middle of a word puts the caret inside it.
        doc.reset();
        let clicked = doc.click_at(POINT { x: (brown.left + brown.right) / 2, y: (brown.top + brown.bottom) / 2 }, json!({}));
        pause(200);
        let _ = doc.act("type", json!({ "text": "X" }));
        pause(300);
        let text = doc.text();
        let inside = ["bXrown", "brXown", "broXwn", "browXn"].iter().any(|word| text.contains(word));
        let landed = text.split_whitespace().find(|word| word.contains('X')).unwrap_or("no X").to_string();
        rows.record("click inside a word places the caret there", inside, format!("{landed}; {clicked:?}"));
        if text.contains('X') {
            let _ = doc.act("key", json!({ "key": "ctrl+z" }));
            pause(300);
        }

        doc.reset();
        let _ = doc.click_at(POINT { x: (quick.left + quick.right) / 2, y: (quick.top + quick.bottom) / 2 }, json!({ "clicks": 2 }));
        pause(300);
        let selection = doc.selection();
        rows.record("double-click selects a word", selection.trim() == "quick", format!("{selection:?}"));

        // Just outside a word's edges: the caret goes to the boundary.
        doc.reset();
        let middle = (quick.top + quick.bottom) / 2;
        let _ = doc.click_at(POINT { x: quick.left - 1, y: middle }, json!({}));
        let _ = doc.click_at(POINT { x: fox.right + 1, y: middle }, json!({ "modifiers": ["shift"] }));
        pause(300);
        let selection = doc.selection();
        rows.record("shift+click extends the selection", selection.trim() == "quick brown fox", format!("{selection:?}"));

        doc.reset();
        let (from_x, from_y) = aim_at(session, POINT { x: quick.left - 1, y: middle }).unwrap();
        let (to_x, to_y) = aim_at(session, POINT { x: brown.right + 1, y: middle }).unwrap();
        let _ = doc.act("drag", json!({ "x": from_x, "y": from_y, "to_x": to_x, "to_y": to_y }));
        pause(300);
        let selection = doc.selection();
        rows.record("drag selects text", selection.trim() == "quick brown", format!("{selection:?}"));

        doc.reset();
        let _ = doc.act("key", json!({ "key": "shift+end" }));
        pause(300);
        let selection = doc.selection();
        rows.record("shift+end selects to the end of the line", selection.trim_end().ends_with("dog."), format!("{selection:?}"));

        doc.reset();
        let result = doc.click_at(POINT { x: (lazy.left + lazy.right) / 2, y: (lazy.top + lazy.bottom) / 2 }, json!({ "button": "right" }));
        pause(500);
        let menu = result.as_ref().is_ok_and(|result| result["note"].as_str().unwrap_or("").contains("menu"));
        rows.record("right-click opens a context menu", menu, format!("{result:?}"));
        let _ = doc.act("key", json!({ "key": "escape" }));

        let select_lazy = || {
            doc.reset();
            let _ = doc.click_at(POINT { x: (lazy.left + lazy.right) / 2, y: (lazy.top + lazy.bottom) / 2 }, json!({ "clicks": 2 }));
            pause(300);
        };
        let before = rows.0.len();
        measure_bold(emit, session, &mut rows, &select_lazy);
        if rows.0.len() > before {
            // The toggle's state says what the app shows; the text's own
            // weight says what it did to the words.
            select_lazy();
            let _ = doc.act("key", json!({ "key": "ctrl+b" }));
            pause(400);
            rows.record("the text reports the formatting applied", doc.bold("lazy"), "");
            let _ = doc.act("key", json!({ "key": "ctrl+z" }));
        }
    });
    rows.print("Document", launch.exe);
}

/// Whether typed text arrives whole and in order: the same line typed a
/// number of times, then each line of the document compared with it.
fn measure_typing(launch: &Launch) {
    let session = "live-bench-typing";
    with_private_app(launch, session, |emit| {
        let doc = Document { emit, session };
        let Some((element, _)) = doc.text_pattern() else { return };
        let body = unsafe { element.CurrentBoundingRectangle() }.unwrap_or_default();
        let _ = doc.click_at(POINT { x: (body.left + body.right) / 2, y: (body.top + body.bottom) / 2 }, json!({}));
        const LINES: usize = 8;
        let started = std::time::Instant::now();
        let _ = doc.act("type", json!({ "text": format!("{SENTENCE}\n").repeat(LINES) }));
        let took = started.elapsed().as_millis();
        pause(800);
        let text = doc.text();
        let wrong: Vec<&str> = text.split(['\r', '\n']).filter(|line| !line.is_empty() && *line != SENTENCE).collect();
        eprintln!("TYPING {}: {} of {LINES} lines wrong in {took} ms: {wrong:?}", launch.exe, wrong.len());
    });
}

#[test]
#[ignore = "opens a Notepad window on the local desktop"]
fn measures_typing_in_notepad() {
    measure_typing(&NOTEPAD);
}

#[test]
#[ignore = "opens a Word window on the local desktop"]
fn measures_typing_in_word() {
    measure_typing(&WORD);
}

/// A command that opens a modal dialog, clicked at its position: the dialog
/// must leave the user's screen with the parked window, the next action
/// must reach it promptly, and Escape must close it.
fn measure_modal_dialog(launch: &Launch, tab: &str, command: &str) {
    let session = "live-bench-dialog";
    let mut rows = Rows::default();
    with_private_app(launch, session, |emit| {
        let tabs = act(emit, session, "find", json!({ "query": tab })).unwrap_or_default();
        if let Some(reference) = tabs
            .as_str()
            .and_then(|text| text.lines().find(|line| line.contains(&format!("TabItem \"{tab}\""))))
            .and_then(|line| line.split("[ref=").nth(1))
            .and_then(|rest| rest.split(']').next())
        {
            let _ = act(emit, session, "invoke", json!({ "ref": reference }));
            pause(800);
        }
        let found = act(emit, session, "find", json!({ "query": command })).unwrap_or_default();
        let Some(line) = found.as_str().and_then(|text| text.lines().find(|line| line.contains(&format!("Button \"{command}\"")))) else {
            eprintln!("no {command:?} button");
            return;
        };
        let geometry = line.split(" @").nth(1).unwrap_or("0,0 0x0");
        let (at, size) = geometry.split_once(' ').unwrap();
        let (x, y) = at.split_once(',').unwrap();
        let (w, h) = size.split_once('x').unwrap();
        let x = x.parse::<f64>().unwrap() + w.parse::<f64>().unwrap() / 2.0;
        let y = y.parse::<f64>().unwrap() + h.parse::<f64>().unwrap() / 2.0;
        let started = std::time::Instant::now();
        let clicked = act(emit, session, "click", json!({ "x": x, "y": y }));
        eprintln!("click took {} ms: {clicked:?}", started.elapsed().as_millis());
        pause(1500);
        let started = std::time::Instant::now();
        let status = act(emit, session, "screenshot", json!({}));
        let took = started.elapsed().as_millis();
        let target = Target::resolve(session).unwrap();
        let dialog = target.window != target.top;
        rows.record("the dialog is the window acted on", dialog, window_title(target.window));
        rows.record("the dialog is off the user's screen", dialog && is_off_screen(target.window), format!("{:?}", frame_rect(target.window).left));
        rows.record("the next action is prompt", took < 3000 && status.is_ok(), format!("{took} ms"));
        let shot_size = status.as_ref().map(|shot| (shot["width"].clone(), shot["height"].clone()));
        rows.record("the screenshot shows the dialog", dialog, format!("{shot_size:?}"));
        let started = std::time::Instant::now();
        let tree = act(emit, session, "snapshot", json!({})).unwrap_or_default();
        let tree = tree.as_str().unwrap_or("");
        let buttons = tree.contains("Button \"OK\"") && tree.contains("Button \"Cancel\"");
        rows.record("a snapshot reads the dialog's buttons", buttons, format!("{} ms", started.elapsed().as_millis()));
        let _ = act(emit, session, "key", json!({ "key": "escape" }));
        pause(800);
        let target = Target::resolve(session).unwrap();
        rows.record("escape closes the dialog", target.window == target.top, "");
    });
    rows.print("Modal dialog", launch.exe);
}

#[test]
#[ignore = "opens an Excel window on the local desktop"]
fn measures_a_modal_dialog_in_excel() {
    measure_modal_dialog(&EXCEL, "Insert", "Table");
}

// ── The apps measured ───────────────────────────────────────────────────

pub(super) const EXCEL: Launch = Launch { exe: "excel.exe", args: &["/x", "/e"], blank: &["ctrl+n"], cleanup: &[] };
const WORD: Launch = Launch { exe: "winword.exe", args: &["/w", "/q"], blank: &[], cleanup: &[] };
const NOTEPAD: Launch = Launch {
    exe: "notepad.exe",
    args: &[],
    // Notepad restores the tabs of earlier sessions: work in a new one, and
    // empty and close it at the end.
    blank: &["ctrl+n"],
    cleanup: &["ctrl+a", "delete", "ctrl+w"],
};

#[test]
#[ignore = "opens an Excel window on the local desktop"]
fn measures_input_on_a_grid_in_excel() {
    measure_grid(&EXCEL);
}

#[test]
#[ignore = "opens a Word window on the local desktop"]
fn measures_input_on_a_document_in_word() {
    measure_document(&WORD);
}

#[test]
#[ignore = "opens a Notepad window on the local desktop"]
fn measures_input_on_a_document_in_notepad() {
    measure_document(&NOTEPAD);
}
