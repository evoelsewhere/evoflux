//! The accessibility tree as the agent reads it — `snapshot`, `find`, the
//! refs (`e12`) they hand out — and finding the elements under a point.

use super::*;

// ── The accessibility tree ──────────────────────────────────────────────

/// Attributes read for every element in one round trip to the app.
/// Read for every element in one round trip. `AXValue` is not among them:
/// for a text area it is the whole text — a Terminal's scrollback, an open
/// Xcode file — and fetching it for every element made snapshots crawl. It
/// is read afterwards, only where it is shown (see [`element_value`]).
const INFO_ATTRIBUTES: [&str; 9] = [
    "AXRole",
    "AXSubrole",
    "AXTitle",
    "AXDescription",
    "AXNumberOfCharacters",
    "AXPosition",
    "AXSize",
    "AXEnabled",
    "AXIdentifier",
];

/// Text longer than this is read only as far as a snapshot line shows it.
const LONG_TEXT_CHARS: f64 = 1_000.0;

/// Roles whose value a snapshot line shows (or names the element by).
fn shows_value(role: &str) -> bool {
    is_text_role(role)
        || matches!(
            role,
            "AXStaticText" | "AXCheckBox" | "AXRadioButton" | "AXSwitch" | "AXSlider" | "AXIncrementor"
                | "AXPopUpButton" | "AXValueIndicator" | "AXCell"
        )
}

/// The element's value, where [`shows_value`]: a long text only as its
/// first 200 characters (`AXStringForRange`), or not at all when the app
/// cannot hand out part of it.
fn element_value(element: &Ax, role: &str, characters: Option<f64>) -> Option<CFType> {
    if !shows_value(role) {
        return None;
    }
    if characters.is_some_and(|count| count > LONG_TEXT_CHARS) {
        let range = ax_range_value(0, 200)?;
        return element.parameterized("AXStringForRange", &range);
    }
    element.attribute("AXValue")
}

pub(super) struct Info {
    role: String,
    title: String,
    description: String,
    value: Option<CFType>,
    frame: Option<Rect>,
    enabled: bool,
    identifier: String,
}

impl Info {
    /// "AXButton" → "Button": the names the agent reads and searches.
    pub(super) fn short_role(&self) -> &str {
        self.role.strip_prefix("AX").unwrap_or(&self.role)
    }

    fn name(&self) -> String {
        if !self.title.trim().is_empty() {
            return self.title.clone();
        }
        if !self.description.trim().is_empty() {
            return self.description.clone();
        }
        if self.role == "AXStaticText" {
            return self.value.as_ref().and_then(cf_text).unwrap_or_default();
        }
        String::new()
    }
}

thread_local! {
    static INFO_NAMES: CFArray<CFString> =
        CFArray::from_CFTypes(&INFO_ATTRIBUTES.map(cf_string));
}

pub(super) fn info(element: &Ax) -> Info {
    let values: [Option<CFType>; INFO_ATTRIBUTES.len()] = INFO_NAMES.with(|names| element.attributes(names));
    let text = |index: usize| values[index].as_ref().and_then(cf_text).unwrap_or_default();
    let origin = values[5].as_ref().and_then(ax_point);
    let size = values[6].as_ref().and_then(ax_size);
    let role = text(0);
    let characters = values[4].as_ref().and_then(cf_number);
    Info {
        value: element_value(element, &role, characters),
        role,
        title: text(2),
        description: text(3),
        frame: origin.zip(size).map(|(origin, size)| Rect {
            x: origin.x,
            y: origin.y,
            w: size.width,
            h: size.height,
        }),
        enabled: values[7].as_ref().and_then(cf_bool).unwrap_or(true),
        identifier: text(8),
    }
}

/// Containers that carry no meaning of their own when unnamed. They are
/// walked through but not listed, which keeps a snapshot readable.
fn is_structural(role: &str) -> bool {
    matches!(
        role,
        "AXGroup" | "AXScrollArea" | "AXSplitGroup" | "AXUnknown" | "AXLayoutArea" | "AXLayoutItem"
            | "AXSplitter" | "AXWindow" | "AXMatte" | "AXGrowArea" | "AXScrollBar" | "AXValueIndicator"
            | "AXColumn" | "AXRuler" | "AXGenericElement" | ""
    )
}

pub(super) fn is_text_role(role: &str) -> bool {
    matches!(role, "AXTextField" | "AXTextArea" | "AXComboBox" | "AXSearchField")
}

pub(super) fn is_editable(element: &Ax) -> bool {
    is_text_role(&element.role()) && (element.settable("AXValue") || element.settable("AXSelectedText"))
}

fn truncate(text: &str, max: usize) -> String {
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
    target: &'a Target,
    refs: &'a mut SessionRefs,
    max_depth: u32,
    max_elements: usize,
    /// Only list elements matching this (lower-cased) text; `None` lists all.
    query: Option<String>,
    /// Keep elements outside the window (the menu bar is).
    anywhere: bool,
    lines: Vec<String>,
    visited: usize,
}

impl Walk<'_> {
    fn element_line(&mut self, element: &Ax, info: &Info, depth: u32) -> bool {
        let frame = info.frame.unwrap_or_default();
        // Judged against the window rather than the screen: a parked window
        // is nearly all off-screen, yet every control in it is usable.
        // Elements scrolled out of the window are still skipped.
        if !self.anywhere && !frame.intersects(&self.target.frame) {
            return false;
        }
        let role = info.short_role().to_string();
        let name = info.name();
        let listed = match &self.query {
            Some(query) => {
                name.to_lowercase().contains(query)
                    || info.identifier.to_lowercase().contains(query)
                    || role.to_lowercase() == *query
            }
            None => !(is_structural(&info.role) && name.trim().is_empty()),
        };
        if listed && (self.anywhere || !frame.is_empty()) {
            self.refs.next += 1;
            let reference = format!("e{}", self.refs.next);
            self.refs.elements.insert(reference.clone(), element.clone());
            let indent = if self.query.is_some() { 0 } else { depth as usize };
            let mut line = format!("{}- {role}", "  ".repeat(indent.min(24)));
            if !name.trim().is_empty() {
                line.push_str(&format!(" \"{}\"", truncate(&name, 120)));
            }
            let value = info.value.as_ref();
            match info.role.as_str() {
                "AXCheckBox" | "AXRadioButton" | "AXSwitch" => {
                    if let Some(on) = value.and_then(cf_bool) {
                        line.push_str(if on { " [checked]" } else { " [unchecked]" });
                    }
                }
                role if is_text_role(role) || matches!(role, "AXSlider" | "AXIncrementor" | "AXPopUpButton" | "AXValueIndicator" | "AXCell") => {
                    if let Some(text) = value.and_then(cf_text).filter(|text| !text.is_empty()) {
                        line.push_str(&format!(" value=\"{}\"", truncate(&text, 200)));
                    }
                }
                _ => {}
            }
            // The selection, read from the tree rather than a screenshot.
            if matches!(info.role.as_str(), "AXCell" | "AXRow") && element.flag("AXSelected") == Some(true) {
                line.push_str(" [selected]");
            }
            if !info.enabled {
                line.push_str(" [disabled]");
            }
            if frame.is_empty() || !frame.intersects(&self.target.frame) {
                line.push_str(&format!(" [ref={reference}]"));
            } else {
                let (x, y) = self.target.screenshot_point(Point { x: frame.x, y: frame.y });
                let width = (frame.w * self.target.scale).round() as i64;
                let height = (frame.h * self.target.scale).round() as i64;
                line.push_str(&format!(" [ref={reference}] @{x},{y} {width}x{height}"));
            }
            self.lines.push(line);
        }
        listed
    }

    fn walk(&mut self, element: &Ax, depth: u32) {
        if depth > self.max_depth || self.lines.len() >= self.max_elements || self.visited > 20_000 {
            return;
        }
        self.visited += 1;
        let info = info(element);
        let listed = self.element_line(element, &info, depth);
        // Closed menus hold hundreds of items; only a search goes into them.
        // An open one has a frame, and is what the agent most likely wants
        // next — wherever it is drawn, often past the window's edge.
        let open_menu = info.role == "AXMenu" && info.frame.is_some_and(|frame| !frame.is_empty());
        if info.role == "AXMenu" && self.query.is_none() && !open_menu {
            return;
        }
        let anywhere = self.anywhere;
        self.anywhere |= open_menu;
        let child_depth = if listed { depth + 1 } else { depth };
        for child in element.elements("AXChildren") {
            self.walk(&child, child_depth);
            if self.lines.len() >= self.max_elements {
                break;
            }
        }
        self.anywhere = anywhere;
    }
}

fn walk_roots(
    target: &Target,
    roots: &[Ax],
    query: Option<String>,
    anywhere: bool,
    max_depth: u32,
    max_elements: usize,
    reset: bool,
) -> (Vec<String>, bool) {
    REFS.with(|refs| {
        let mut refs = refs.borrow_mut();
        if reset {
            refs.remove(&target.session_id);
        }
        let session_refs = refs.entry(target.session_id.clone()).or_default();
        let mut walk = Walk {
            target,
            refs: session_refs,
            max_depth,
            max_elements,
            query,
            anywhere,
            lines: Vec::new(),
            visited: 0,
        };
        for root in roots {
            walk.walk(root, 0);
        }
        let truncated = walk.lines.len() >= max_elements;
        (walk.lines, truncated)
    })
}

pub(super) fn snapshot(target: &Target, params: &Value) -> Result<Value, String> {
    let max_depth = params.get("max_depth").and_then(Value::as_u64).unwrap_or(30).clamp(1, 80) as u32;
    let max_elements = params.get("max_elements").and_then(Value::as_u64).unwrap_or(400).clamp(10, 2000) as usize;
    let (lines, truncated) = walk_roots(target, &target.roots(), None, false, max_depth, max_elements, true);
    let (width, height) = target.screenshot_size();
    let mut text = format!(
        "UI of {} — \"{}\" (coordinates are screenshot pixels of a {width}x{height} screenshot)\n",
        target.app_name,
        target.title()
    );
    if lines.is_empty() {
        text.push_str("(This app exposes no accessibility tree; use screenshot and coordinates.)");
    } else {
        text.push_str(&lines.join("\n"));
    }
    if truncated {
        text.push_str("\n(Truncated: use find to search for a specific control.)");
    }
    text.push_str("\n(Menu bar commands are not listed: find them by name, e.g. find \"Save\", then invoke the ref.)");
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
    let (mut lines, _) = walk_roots(target, &target.roots(), Some(query.clone()), false, 60, limit, false);
    if lines.len() < limit {
        let menus = app_menus(&target.app);
        let (menu_lines, _) = walk_roots(target, &menus, Some(query.clone()), true, 8, limit - lines.len(), false);
        lines.extend(menu_lines.into_iter().map(|line| format!("{line} (menu bar)")));
    }
    Ok(Value::String(if lines.is_empty() {
        format!("No control matching \"{query}\" in {}.", target.app_name)
    } else {
        lines.join("\n")
    }))
}

/// The app's own menus in its menu bar. The first menu bar item is the
/// Apple menu, which belongs to the system (Log Out, Shut Down, Force Quit,
/// System Settings) and is never offered to the agent.
pub(super) fn app_menus(app: &Ax) -> Vec<Ax> {
    app.element("AXMenuBar")
        .map(|bar| bar.elements("AXChildren").into_iter().skip(1).collect())
        .unwrap_or_default()
}

pub(super) fn element_for(session_id: &str, reference: &str) -> Result<Ax, String> {
    let reference = reference.trim().trim_start_matches("ref=").trim_start_matches('@');
    REFS.with(|refs| {
        refs.borrow()
            .get(session_id)
            .and_then(|session| session.elements.get(reference).cloned())
    })
    .ok_or_else(|| format!("Unknown ref {reference:?}. Take a new snapshot or find, then use a ref from it."))
}

pub(super) fn element_center(element: &Ax) -> Option<Point> {
    element.frame().filter(|frame| !frame.is_empty()).map(|frame| frame.center())
}

/// The chain of elements under `point` in the attached window, outermost
/// first. Walks the window's own tree rather than hit-testing the screen:
/// the app may be behind other windows or parked, where a screen hit-test
/// would find something else.
/// The elements under `point`, outermost first.
///
/// The roots come topmost first — an open menu, a dialog, then the window
/// beneath it — so the first whose frame holds the point is what is drawn
/// there. Taking the deepest chain of any root instead reached through a
/// dialog to the control under it.
pub(super) fn elements_at(target: &Target, point: Point) -> Vec<Ax> {
    let roots = target.roots();
    let root = roots
        .iter()
        .find(|root| root.frame().is_some_and(|frame| frame.contains(point)))
        .cloned()
        .unwrap_or_else(|| target.window.clone());
    chain_at(root, point)
}

fn chain_at(root: Ax, point: Point) -> Vec<Ax> {
    let mut chain = vec![root.clone()];
    let mut current = root;
    let mut visited = 0usize;
    'descend: loop {
        let children = current.elements("AXChildren");
        // Later siblings draw over earlier ones.
        for child in children.into_iter().rev() {
            visited += 1;
            if visited > 20_000 {
                break 'descend;
            }
            if child.frame().is_some_and(|frame| frame.contains(point)) {
                chain.push(child.clone());
                current = child;
                continue 'descend;
            }
        }
        break;
    }
    chain
}

/// `element` and its ancestors, outermost first (the order [`elements_at`]
/// returns), so callers can look for the nearest one with a capability.
pub(super) fn with_ancestors(element: Ax) -> Vec<Ax> {
    let mut chain = vec![element];
    while chain.len() < 64 {
        match chain.last().and_then(|last| last.element("AXParent")) {
            Some(parent) if parent.role() != "AXApplication" => chain.push(parent),
            _ => break,
        }
    }
    chain.reverse();
    chain
}

pub(super) fn remember_editable(session_id: &str, element: &Ax) {
    LAST_EDITABLE.with(|last| {
        last.borrow_mut().insert(session_id.to_string(), element.clone());
    });
}
