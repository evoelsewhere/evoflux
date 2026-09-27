//! The UI Automation tree as the agent reads it: `snapshot`, `find`, and
//! the refs (`e12`) they hand out.

use super::*;

fn control_type_name(id: i32) -> &'static str {
    match id {
        50000 => "Button", 50001 => "Calendar", 50002 => "CheckBox", 50003 => "ComboBox",
        50004 => "Edit", 50005 => "Hyperlink", 50006 => "Image", 50007 => "ListItem",
        50008 => "List", 50009 => "Menu", 50010 => "MenuBar", 50011 => "MenuItem",
        50012 => "ProgressBar", 50013 => "RadioButton", 50014 => "ScrollBar",
        50015 => "Slider", 50016 => "Spinner", 50017 => "StatusBar", 50018 => "Tab",
        50019 => "TabItem", 50020 => "Text", 50021 => "ToolBar", 50022 => "ToolTip",
        50023 => "Tree", 50024 => "TreeItem", 50025 => "Custom", 50026 => "Group",
        50027 => "Thumb", 50028 => "DataGrid", 50029 => "DataItem", 50030 => "Document",
        50031 => "SplitButton", 50032 => "Window", 50033 => "Pane", 50034 => "Header",
        50035 => "HeaderItem", 50036 => "Table", 50037 => "TitleBar", 50038 => "Separator",
        50039 => "SemanticZoom", 50040 => "AppBar",
        _ => "Element",
    }
}

/// Containers that carry no meaning of their own when unnamed. They are
/// walked through but not listed, which keeps a snapshot readable.
fn is_structural(role: &str) -> bool {
    matches!(role, "Pane" | "Group" | "Custom" | "Element" | "Window" | "TitleBar" | "ScrollBar" | "Thumb" | "Separator")
}

pub(super) fn bstr(value: windows::core::Result<BSTR>) -> String {
    value.map(|text| text.to_string()).unwrap_or_default()
}

/// The value a control shows. A grid cell (`DataItem`) has its content here:
/// read back from the tree, the agent need not select each cell and read
/// whichever field shows the selected one.
fn element_value(element: &IUIAutomationElement, role: &str) -> Option<String> {
    if !matches!(role, "Edit" | "ComboBox" | "Document" | "Spinner" | "Slider" | "DataItem") {
        return None;
    }
    let pattern = unsafe { element.GetCurrentPattern(UIA_ValuePatternId) }.ok()?;
    let value: IUIAutomationValuePattern = pattern.cast().ok()?;
    let text = bstr(unsafe { value.CurrentValue() });
    (!text.is_empty()).then_some(text)
}

/// Whether an item that can be selected — a cell, a list, tree or tab
/// item — is: the selection read from the tree, not from a screenshot.
fn is_selected_item(element: &IUIAutomationElement, role: &str) -> bool {
    if !matches!(role, "DataItem" | "ListItem" | "TreeItem" | "TabItem") {
        return false;
    }
    unsafe { element.GetCurrentPattern(UIA_SelectionItemPatternId) }
        .ok()
        .and_then(|pattern| pattern.cast::<IUIAutomationSelectionItemPattern>().ok())
        .and_then(|item| unsafe { item.CurrentIsSelected() }.ok())
        .is_some_and(|selected| selected.as_bool())
}

fn toggle_state(element: &IUIAutomationElement, role: &str) -> Option<bool> {
    if !matches!(role, "CheckBox" | "Button" | "MenuItem" | "RadioButton") {
        return None;
    }
    let pattern = unsafe { element.GetCurrentPattern(UIA_TogglePatternId) }.ok()?;
    let toggle: IUIAutomationTogglePattern = pattern.cast().ok()?;
    unsafe { toggle.CurrentToggleState() }.ok().map(|state| state == ToggleState_On)
}

pub(super) fn truncate(text: &str, max: usize) -> String {
    let clean: String = text.chars().map(|ch| if ch.is_control() { ' ' } else { ch }).collect();
    if clean.chars().count() <= max {
        clean
    } else {
        let mut cut: String = clean.chars().take(max).collect();
        cut.push('…');
        cut
    }
}

struct Walk<'a> {
    walker: IUIAutomationTreeWalker,
    target: &'a Target,
    refs: &'a mut SessionRefs,
    /// The window the root being walked belongs to.
    root_window: HWND,
    max_depth: u32,
    max_elements: usize,
    /// Only list elements matching this (lower-cased) text; `None` lists all.
    query: Option<String>,
    lines: Vec<String>,
    visited: usize,
}

impl Walk<'_> {
    fn element_line(&mut self, element: &IUIAutomationElement, depth: u32) -> bool {
        let role = unsafe { element.CurrentControlType() }
            .map(|id| control_type_name(id.0))
            .unwrap_or("Element");
        let name = bstr(unsafe { element.CurrentName() });
        let rect = unsafe { element.CurrentBoundingRectangle() }.unwrap_or_default();
        // Judged against the window rather than IsOffscreen: a parked window
        // is entirely off-screen, yet every control in it is usable. Elements
        // scrolled out of the window are still skipped.
        let frame = &self.target.frame;
        if rect.right <= frame.left
            || rect.left >= frame.right
            || rect.bottom <= frame.top
            || rect.top >= frame.bottom
        {
            return false;
        }
        let listed = match &self.query {
            Some(query) => {
                let automation_id = bstr(unsafe { element.CurrentAutomationId() });
                name.to_lowercase().contains(query)
                    || automation_id.to_lowercase().contains(query)
                    || role.to_lowercase() == *query
            }
            None => !(is_structural(role) && name.trim().is_empty()),
        };
        if listed && rect.right > rect.left && rect.bottom > rect.top {
            let reference = format!("e{}", NEXT_REF.fetch_add(1, Ordering::Relaxed) + 1);
            self.refs
                .elements
                .insert(reference.clone(), (element.clone(), self.root_window.0 as isize));
            let (x, y) = self.target.screenshot_point(POINT { x: rect.left, y: rect.top });
            let width = (f64::from(rect.right - rect.left) * self.target.scale).round() as i64;
            let height = (f64::from(rect.bottom - rect.top) * self.target.scale).round() as i64;
            let indent = if self.query.is_some() { 0 } else { depth as usize };
            let mut line = format!("{}- {role}", "  ".repeat(indent.min(24)));
            if !name.trim().is_empty() {
                line.push_str(&format!(" \"{}\"", truncate(&name, 120)));
            }
            if let Some(value) = element_value(element, role) {
                line.push_str(&format!(" value=\"{}\"", truncate(&value, 200)));
            }
            if let Some(on) = toggle_state(element, role) {
                line.push_str(if on { " [checked]" } else { " [unchecked]" });
            }
            if is_selected_item(element, role) {
                line.push_str(" [selected]");
            }
            if !unsafe { element.CurrentIsEnabled() }.map(|on| on.as_bool()).unwrap_or(true) {
                line.push_str(" [disabled]");
            }
            line.push_str(&format!(" [ref={reference}] @{x},{y} {width}x{height}"));
            self.lines.push(line);
        }
        listed
    }

    fn walk(&mut self, element: &IUIAutomationElement, depth: u32) {
        if depth > self.max_depth || self.lines.len() >= self.max_elements || self.visited > 20_000 {
            return;
        }
        self.visited += 1;
        let listed = self.element_line(element, depth);
        let child_depth = if listed { depth + 1 } else { depth };
        let Ok(mut child) = (unsafe { self.walker.GetFirstChildElement(element) }) else {
            return;
        };
        loop {
            self.walk(&child, child_depth);
            if self.lines.len() >= self.max_elements {
                return;
            }
            match unsafe { self.walker.GetNextSiblingElement(&child) } {
                Ok(next) => child = next,
                Err(_) => return,
            }
        }
    }
}

fn walk_window(target: &Target, query: Option<String>, max_depth: u32, max_elements: usize, reset: bool) -> Result<(Vec<String>, bool), String> {
    let automation = automation()?;
    // Open menus and dropdowns first: they are on top, and what the agent
    // most likely wants next.
    let mut roots = Vec::new();
    for popup in &target.popups {
        if let Ok(element) = unsafe { automation.ElementFromHandle(*popup) } {
            roots.push((element, *popup));
        }
    }
    roots.extend(
        automation_roots(&automation, target.window)?
            .into_iter()
            .map(|root| (root, target.window)),
    );
    let walker = unsafe { automation.ControlViewWalker() }
        .map_err(|error| format!("UI Automation walker unavailable: {error}"))?;
    REFS.with(|refs| {
        let mut refs = refs.borrow_mut();
        let session_refs = refs.entry(target.session_id.clone()).or_default();
        if reset {
            session_refs.elements.clear();
        }
        let mut walk = Walk {
            walker,
            target,
            refs: session_refs,
            root_window: target.window,
            max_depth,
            max_elements,
            query,
            lines: Vec::new(),
            visited: 0,
        };
        for (root, window) in &roots {
            walk.root_window = *window;
            walk.walk(root, 0);
        }
        let truncated = walk.lines.len() >= max_elements;
        Ok((walk.lines, truncated))
    })
}

pub(super) fn snapshot(target: &Target, params: &Value) -> Result<Value, String> {
    let max_depth = params.get("max_depth").and_then(Value::as_u64).unwrap_or(30).clamp(1, 80) as u32;
    let max_elements = params.get("max_elements").and_then(Value::as_u64).unwrap_or(400).clamp(10, 2000) as usize;
    let (lines, truncated) = walk_window(target, None, max_depth, max_elements, true)?;
    let (width, height) = target.screenshot_size();
    let mut text = format!(
        "UI of {} — \"{}\" (coordinates are screenshot pixels of a {width}x{height} screenshot)\n",
        target.app,
        window_title(target.window)
    );
    if lines.is_empty() {
        text.push_str("(This app exposes no accessibility tree; use screenshot and coordinates.)");
    } else {
        text.push_str(&lines.join("\n"));
    }
    if truncated {
        text.push_str("\n(Truncated: use find to search for a specific control.)");
    }
    Ok(Value::String(text))
}

pub(super) fn find(target: &Target, params: &Value) -> Result<Value, String> {
    let query = params
        .get("query")
        .and_then(Value::as_str)
        .map(|query| query.trim().to_lowercase())
        .filter(|query| !query.is_empty())
        .ok_or("find needs a query.")?;
    let limit = params.get("limit").and_then(Value::as_u64).unwrap_or(20).clamp(1, 100) as usize;
    let (lines, _) = walk_window(target, Some(query.clone()), 60, limit, false)?;
    Ok(Value::String(if lines.is_empty() {
        format!("No control matching \"{query}\" in {}.", target.app)
    } else {
        lines.join("\n")
    }))
}

/// The element a ref names, if it can still be acted on: it lives in the
/// window the agent is driving now (not the main window behind a modal
/// dialog, nor a dialog or menu since closed), and the app has not
/// destroyed it.
pub(super) fn element_for(target: &Target, reference: &str) -> Result<IUIAutomationElement, String> {
    let reference = reference.trim().trim_start_matches("ref=").trim_start_matches('@');
    let (element, listed_in) = REFS
        .with(|refs| {
            refs.borrow()
                .get(&target.session_id)
                .and_then(|session| session.elements.get(reference).cloned())
        })
        .ok_or_else(|| format!("Unknown ref {reference:?}. Take a new snapshot or find, then use a ref from it."))?;
    let listed_in = to_hwnd(listed_in);
    if listed_in != target.window && !target.popups.contains(&listed_in) {
        return Err(if unsafe { IsWindow(Some(listed_in)) }.as_bool() {
            format!(
                "{reference} is in \"{}\", which is waiting on the dialog \"{}\". Take a new snapshot and use the dialog's controls first.",
                window_title(listed_in),
                window_title(target.window)
            )
        } else {
            format!("{reference} was in a dialog or menu that has closed. Take a new snapshot or find.")
        });
    }
    if unsafe { element.CurrentProcessId() }.is_err() {
        return Err(format!(
            "{reference} no longer exists: the app removed or replaced that control. Take a new snapshot or find."
        ));
    }
    Ok(element)
}

pub(super) fn element_center(element: &IUIAutomationElement) -> Option<POINT> {
    let rect = unsafe { element.CurrentBoundingRectangle() }.ok()?;
    (rect.right > rect.left && rect.bottom > rect.top).then_some(POINT {
        x: (rect.left + rect.right) / 2,
        y: (rect.top + rect.bottom) / 2,
    })
}
