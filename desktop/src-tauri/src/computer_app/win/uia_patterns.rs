//! UI Automation patterns — what "clicking" an element means and how it is
//! carried out without blocking on the app — and hit-testing the window's
//! own tree.

use super::*;

/// The UI Automation action that "clicking" an element means.
pub(super) enum UiAction {
    Invoke(IUIAutomationInvokePattern),
    Toggle(IUIAutomationTogglePattern),
    Select(IUIAutomationSelectionItemPattern),
    ExpandCollapse(IUIAutomationExpandCollapsePattern),
    Default(IUIAutomationLegacyIAccessiblePattern),
    /// A button, link or drop-down in web content: its MSAA default action,
    /// then the pattern's own action if the page refuses that (see
    /// [`ui_action_for`]).
    PageClick(IUIAutomationLegacyIAccessiblePattern, Box<UiAction>),
}

pub(super) fn pattern<T: Interface>(element: &IUIAutomationElement, id: windows::Win32::UI::Accessibility::UIA_PATTERN_ID) -> Option<T> {
    unsafe { element.GetCurrentPattern(id) }.ok()?.cast().ok()
}

/// What clicking `element` means.
///
/// In web content (`web`) a button, link or drop-down is clicked through its
/// MSAA default action: Chromium carries out UI Automation's Invoke and
/// Expand by focusing its widget, which activates the window and took the
/// foreground from the user's window whenever Windows let it, while the
/// default action clicks inside the page only. Other elements keep their
/// pattern: an option in a <select> popup reports a default action that
/// succeeds without picking it.
pub(super) fn ui_action_for(element: &IUIAutomationElement, web: bool) -> Option<UiAction> {
    let kind = unsafe { element.CurrentControlType() }.map(|kind| kind.0).unwrap_or(0);
    let page_default = || {
        pattern::<IUIAutomationLegacyIAccessiblePattern>(element, UIA_LegacyIAccessiblePatternId)
            .filter(|legacy| !bstr(unsafe { legacy.CurrentDefaultAction() }).trim().is_empty())
    };
    if let Some(p) = pattern::<IUIAutomationInvokePattern>(element, UIA_InvokePatternId) {
        let button_or_link = matches!(kind, 50000 | 50005 | 50031); // Button, Hyperlink, SplitButton
        if let Some(legacy) = page_default().filter(|_| web && button_or_link) {
            return Some(UiAction::PageClick(legacy, Box::new(UiAction::Invoke(p))));
        }
        return Some(UiAction::Invoke(p));
    }
    if let Some(p) = pattern(element, UIA_TogglePatternId) {
        // Office's ribbon toggles (Bold) took Toggle without turning on
        // while their window was in the background, and their default
        // action every time.
        if let Some(legacy) = page_default().filter(|_| !web) {
            return Some(UiAction::Default(legacy));
        }
        return Some(UiAction::Toggle(p));
    }
    if let Some(p) = pattern(element, UIA_SelectionItemPatternId) {
        return Some(UiAction::Select(p));
    }
    if let Some(p) = pattern(element, UIA_ExpandCollapsePatternId) {
        if let Some(legacy) = page_default().filter(|_| web && kind == 50003) { // ComboBox
            return Some(UiAction::PageClick(legacy, Box::new(UiAction::ExpandCollapse(p))));
        }
        return Some(UiAction::ExpandCollapse(p));
    }
    // Every element has the legacy pattern; only one that names a default
    // action (Chromium reports "click" for clickable page elements) counts.
    let legacy: IUIAutomationLegacyIAccessiblePattern = pattern(element, UIA_LegacyIAccessiblePatternId)?;
    let default_action = bstr(unsafe { legacy.CurrentDefaultAction() });
    (!default_action.trim().is_empty()).then_some(UiAction::Default(legacy))
}

/// How long an action may take before the app is taken to be busy with it.
const UI_ACTION_WAIT: Duration = Duration::from_millis(1500);

pub(super) const STILL_RUNNING_NOTE: &str = "The app is still handling this, most likely in a dialog it opened. Take a snapshot to see it; do not repeat the action.";

/// A Win32 push button (a WinForms one included): the window itself, when
/// `element` is one.
fn win32_push_button(element: &IUIAutomationElement) -> Option<HWND> {
    let hwnd = unsafe { element.CurrentNativeWindowHandle() }.ok()?;
    if hwnd.0.is_null() {
        return None;
    }
    let class = class_name(hwnd).to_lowercase();
    // WinForms draws its buttons itself (BS_OWNERDRAW on top of the kind),
    // so the style does not tell them apart; a check box among them offers
    // Toggle rather than the Invoke this is used for.
    if class.starts_with("windowsforms10.button") {
        return Some(hwnd);
    }
    // Push, default, owner-drawn, split and command-link buttons; not check
    // boxes, radio buttons or group boxes, which share the class.
    let kind = unsafe { GetWindowLongPtrW(hwnd, GWL_STYLE) } & 0xF;
    (class == "button" && matches!(kind, 0x0 | 0x1 | 0xB..=0xF)).then_some(hwnd)
}

/// Perform `action` on `element`. Returns the pattern used, and whether the
/// app is still busy with it.
///
/// A button that opens a modal dialog does not return from Invoke until the
/// dialog closes (WinForms clicks it synchronously), and meanwhile every
/// other UI Automation call into the app waits too, until a timeout of about
/// a minute — the click was then reported as refused, inviting a second one.
/// A Win32 push button is therefore clicked with a posted `BM_CLICK`, which
/// the app handles from its own message loop. Anything else runs on a thread
/// of its own; one still running after [`UI_ACTION_WAIT`] is left to finish
/// there and reported as delivered.
pub(super) fn perform(element: &IUIAutomationElement, action: UiAction) -> windows::core::Result<(&'static str, bool)> {
    if matches!(action, UiAction::Invoke(_) | UiAction::Default(_)) {
        if let Some(button) = win32_push_button(element) {
            let posted = unsafe { PostMessageW(Some(button), BM_CLICK, WPARAM(0), LPARAM(0)) };
            return posted.map(|_| ("click_message", false));
        }
    }
    struct Movable(UiAction);
    // UI Automation objects are free-threaded; both threads are in the MTA.
    unsafe impl Send for Movable {}
    let label = match &action {
        UiAction::Invoke(_) => "invoke",
        UiAction::Toggle(_) => "toggle",
        UiAction::Select(_) => "select",
        UiAction::ExpandCollapse(_) => "expand",
        UiAction::Default(_) | UiAction::PageClick(..) => "default_action",
    };
    let (done, outcome) = mpsc::channel();
    let action = Movable(action);
    let spawned = std::thread::Builder::new()
        .name("computer-app-ui-action".into())
        .spawn(move || {
            let action = action;
            unsafe {
                let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
            }
            let result = perform_now(&action.0);
            drop(action);
            let _ = done.send(result);
            unsafe { CoUninitialize() };
        });
    if spawned.is_err() {
        return Err(windows::core::Error::from_win32());
    }
    match outcome.recv_timeout(UI_ACTION_WAIT) {
        Ok(result) => result.map(|used| (used, false)),
        Err(_) => Ok((label, true)),
    }
}

fn perform_now(action: &UiAction) -> windows::core::Result<&'static str> {
    unsafe {
        match action {
            UiAction::Invoke(p) => p.Invoke().map(|_| "invoke"),
            UiAction::Toggle(p) => p.Toggle().map(|_| "toggle"),
            UiAction::Select(p) => p.Select().map(|_| "select"),
            UiAction::ExpandCollapse(p) => {
                let state = p.CurrentExpandCollapseState().unwrap_or(ExpandCollapseState_Collapsed);
                if state == ExpandCollapseState_Collapsed || state == ExpandCollapseState_PartiallyExpanded {
                    p.Expand().map(|_| "expand")
                } else {
                    p.Collapse().map(|_| "collapse")
                }
            }
            UiAction::Default(p) => p.DoDefaultAction().map(|_| "default_action"),
            UiAction::PageClick(legacy, fallback) => match legacy.DoDefaultAction() {
                Ok(()) => Ok("default_action"),
                Err(_) => perform_now(fallback),
            },
        }
    }
}

pub(super) fn is_editable(element: &IUIAutomationElement) -> bool {
    pattern::<IUIAutomationValuePattern>(element, UIA_ValuePatternId)
        .map(|value| !unsafe { value.CurrentIsReadOnly() }.map(|ro| ro.as_bool()).unwrap_or(true))
        .unwrap_or(false)
}

/// The control under `point` in a native window, when it is one a person
/// presses — a button, tab, link, check box, radio button or menu item —
/// rather than content (a cell, a text body, a canvas), where the exact
/// point and the mouse matter.
///
/// The app is asked first through MSAA's hit test, which answers from its
/// own layout (so also while parked off-screen) in a call or two; it knows
/// Office's ribbon, for one. Where it knows nothing finer than the window —
/// Excel's workbook area answers only through UI Automation — the UI
/// Automation tree is walked to the point instead, reading each level in
/// one call and never entering a grid or table: listing every cell of
/// Excel's grid added 350–400 ms to each click on one.
pub(super) fn pressable_at(target: &Target, point: POINT) -> Option<IUIAutomationElement> {
    let hwnd = pointer_window(target, point);
    match msaa_hit(hwnd, point) {
        Some(Some(element)) => Some(element),
        Some(None) => None,
        None => automation_hit(hwnd, point),
    }
}

/// MSAA's answer at `point`: a pressable control, something else
/// (`Some(None)`), or nothing finer than the window itself (`None`).
fn msaa_hit(hwnd: HWND, point: POINT) -> Option<Option<IUIAutomationElement>> {
    use windows::Win32::System::Com::IDispatch;
    use windows::Win32::System::Variant::VARIANT;
    use windows::Win32::UI::HiDpi::PhysicalToLogicalPointForPerMonitorDPI;
    let mut object: *mut core::ffi::c_void = std::ptr::null_mut();
    unsafe { AccessibleObjectFromWindow(hwnd, 0xFFFF_FFFC, &IAccessible::IID, &mut object) }.ok()?; // OBJID_CLIENT
    if object.is_null() {
        return None;
    }
    let mut accessible = unsafe { IAccessible::from_raw(object) };
    // MSAA takes the coordinates the app sees (logical for a DPI-unaware one).
    let mut at = point;
    unsafe {
        let _ = PhysicalToLogicalPointForPerMonitorDPI(Some(hwnd), &mut at);
    }
    let mut child = 0; // CHILDID_SELF
    let mut deeper = false;
    for _ in 0..16 {
        let Ok(hit) = (unsafe { accessible.accHitTest(at.x, at.y) }) else {
            break;
        };
        if let Ok(inner) = IDispatch::try_from(&hit).and_then(|dispatch| dispatch.cast::<IAccessible>()) {
            if inner.as_raw() == accessible.as_raw() {
                break;
            }
            // A child object of its own: ask it in turn.
            accessible = inner;
            child = 0;
            deeper = true;
            continue;
        }
        // A simple child, or the object itself (0); empty when nothing is there.
        child = i32::try_from(&hit).unwrap_or(0);
        deeper |= child != 0;
        break;
    }
    if !deeper {
        return None;
    }
    let role = unsafe { accessible.get_accRole(&VARIANT::from(child)) }.ok()?;
    // ROLE_SYSTEM_ MENUITEM, LINK, PAGETAB, PUSHBUTTON, CHECKBUTTON,
    // RADIOBUTTON, BUTTONDROPDOWN, BUTTONMENU, SPLITBUTTON.
    let pressable = matches!(i32::try_from(&role).unwrap_or(0), 0x0C | 0x1E | 0x25 | 0x2B | 0x2C | 0x2D | 0x38 | 0x39 | 0x3E);
    Some(pressable.then(|| unsafe { automation().ok()?.ElementFromIAccessible(&accessible, child) }.ok()).flatten())
}

/// The cell under `point` of a grid (an element with the Grid pattern) in a
/// native window, with whether the point is in the cell's body rather than
/// on its edge, where a grid's handles are (moving or filling the
/// selection). Found like [`pressable_at`]'s walk, one level per call; only
/// the grid holding the point is listed.
pub(super) fn grid_cell_at(target: &Target, point: POINT) -> Option<(IUIAutomationElement, bool)> {
    const EDGE: i32 = 4;
    let automation = automation().ok()?;
    let request = unsafe { automation.CreateCacheRequest() }.ok()?;
    unsafe {
        for property in [UIA_BoundingRectanglePropertyId, UIA_IsGridPatternAvailablePropertyId] {
            request.AddProperty(property).ok()?;
        }
    }
    let controls = unsafe { automation.ControlViewCondition() }.ok()?;
    let mut current = unsafe { automation.ElementFromHandle(pointer_window(target, point)) }.ok()?;
    let mut in_grid = false;
    for _ in 0..32 {
        let children = unsafe { current.FindAllBuildCache(TreeScope_Children, &controls, &request) }.ok()?;
        let count = unsafe { children.Length() }.unwrap_or(0);
        let hit = (0..count).rev().find_map(|index| {
            let child = unsafe { children.GetElement(index) }.ok()?;
            let rect = unsafe { child.CachedBoundingRectangle() }.ok()?;
            contains(&rect, point).then_some((child, rect))
        });
        let Some((child, rect)) = hit else { break };
        if in_grid {
            // A child of the grid that can be selected: its cell.
            pattern::<IUIAutomationSelectionItemPattern>(&child, UIA_SelectionItemPatternId)?;
            let body = point.x >= rect.left + EDGE
                && point.x < rect.right - EDGE
                && point.y >= rect.top + EDGE
                && point.y < rect.bottom - EDGE;
            return Some((child, body));
        }
        in_grid = unsafe { child.GetCachedPropertyValue(UIA_IsGridPatternAvailablePropertyId) }
            .ok()
            .and_then(|value| bool::try_from(&value).ok())
            .unwrap_or(false);
        current = child;
    }
    None
}

/// The innermost UI Automation control under `point` in `hwnd`, when it is
/// pressable. Grids and tables are content and are not entered.
fn automation_hit(hwnd: HWND, point: POINT) -> Option<IUIAutomationElement> {
    let automation = automation().ok()?;
    let request = unsafe { automation.CreateCacheRequest() }.ok()?;
    unsafe {
        for property in [
            UIA_BoundingRectanglePropertyId,
            UIA_ControlTypePropertyId,
            UIA_IsGridPatternAvailablePropertyId,
            UIA_IsTablePatternAvailablePropertyId,
        ] {
            request.AddProperty(property).ok()?;
        }
    }
    let controls = unsafe { automation.ControlViewCondition() }.ok()?;
    let mut current = unsafe { automation.ElementFromHandle(hwnd) }.ok()?;
    for _ in 0..32 {
        let children = unsafe { current.FindAllBuildCache(TreeScope_Children, &controls, &request) }.ok()?;
        let count = unsafe { children.Length() }.unwrap_or(0);
        // Later siblings are drawn over earlier ones.
        let hit = (0..count).rev().find_map(|index| {
            let child = unsafe { children.GetElement(index) }.ok()?;
            let rect = unsafe { child.CachedBoundingRectangle() }.ok()?;
            contains(&rect, point).then_some(child)
        });
        let Some(child) = hit else { break };
        let is = |property| {
            unsafe { child.GetCachedPropertyValue(property) }
                .ok()
                .and_then(|value| bool::try_from(&value).ok())
                .unwrap_or(false)
        };
        if is(UIA_IsGridPatternAvailablePropertyId) || is(UIA_IsTablePatternAvailablePropertyId) {
            return None;
        }
        current = child;
    }
    let kind = unsafe { current.CachedControlType() }.map(|kind| kind.0).unwrap_or(0);
    // Button, CheckBox, Hyperlink, MenuItem, RadioButton, TabItem, SplitButton.
    matches!(kind, 50000 | 50002 | 50005 | 50011 | 50013 | 50019 | 50031).then_some(current)
}

pub(super) fn contains(rect: &RECT, point: POINT) -> bool {
    rect.right > rect.left
        && rect.bottom > rect.top
        && point.x >= rect.left
        && point.x < rect.right
        && point.y >= rect.top
        && point.y < rect.bottom
}

/// The chain of elements under `point` in the attached window, outermost
/// first. Walks the window's own tree rather than asking UI Automation what
/// is on screen there: the app may be behind other windows or parked
/// off-screen, where a screen hit-test would find something else.
pub(super) fn elements_at(target: &Target, point: POINT) -> Result<Vec<IUIAutomationElement>, String> {
    let automation = automation()?;
    // A popup covers whatever is under it in the window: only its own tree
    // counts there.
    let roots = match target.popup_at(point) {
        Some(popup) => automation_roots(&automation, popup)?,
        None => automation_roots(&automation, target.window)?,
    };
    let walker = unsafe { automation.ControlViewWalker() }
        .map_err(|error| format!("UI Automation walker unavailable: {error}"))?;
    // The deepest chain wins: a page's own tree (under its render host) goes
    // further down than the window frame around it.
    let chains = roots.into_iter().map(|root| chain_at(&walker, root, point));
    Ok(chains.max_by_key(Vec::len).unwrap_or_default())
}

fn chain_at(
    walker: &IUIAutomationTreeWalker,
    root: IUIAutomationElement,
    point: POINT,
) -> Vec<IUIAutomationElement> {
    let mut visited = 0usize;
    deepest_chain(walker, root, point, &mut visited)
}

/// The deepest chain of elements under `point` starting at `element`.
///
/// Every child containing the point is explored, not just the first: a
/// container that covers the whole window (a frame view, an overlay host)
/// can come before or after the one that holds the content. Among equally
/// deep chains the later sibling wins, since later siblings are drawn over
/// earlier ones — a modal or a menu covers what it was opened over.
fn deepest_chain(
    walker: &IUIAutomationTreeWalker,
    element: IUIAutomationElement,
    point: POINT,
    visited: &mut usize,
) -> Vec<IUIAutomationElement> {
    let mut best: Vec<IUIAutomationElement> = Vec::new();
    let mut child = unsafe { walker.GetFirstChildElement(&element) }.ok();
    while let Some(current) = child {
        *visited += 1;
        if *visited > 20_000 {
            break;
        }
        let rect = unsafe { current.CurrentBoundingRectangle() }.unwrap_or_default();
        let next = unsafe { walker.GetNextSiblingElement(&current) }.ok();
        if contains(&rect, point) {
            let chain = deepest_chain(walker, current, point, visited);
            if chain.len() >= best.len() {
                best = chain;
            }
        }
        child = next;
    }
    let mut chain = Vec::with_capacity(best.len() + 1);
    chain.push(element);
    chain.extend(best);
    chain
}

thread_local! {
    /// The editable element each session last clicked, where `type` goes in
    /// web content that has no keyboard focus we can address.
    pub(super) static LAST_EDITABLE: RefCell<HashMap<String, IUIAutomationElement>> = RefCell::new(HashMap::new());
}

pub(super) fn remember_editable(session_id: &str, element: &IUIAutomationElement) {
    LAST_EDITABLE.with(|last| {
        last.borrow_mut().insert(session_id.to_string(), element.clone());
    });
}

/// Focus went somewhere other than the remembered field — a click on a
/// button, Tab, Enter — so a `type` without a ref must go where the page's
/// focus now is, not back into that field.
pub(super) fn forget_editable(session_id: &str) {
    LAST_EDITABLE.with(|last| {
        last.borrow_mut().remove(session_id);
    });
}

/// Keys that move focus to another control (or submit and close a form).
pub(super) fn moves_focus(combo: &KeyCombo) -> bool {
    matches!(
        combo.key.to_lowercase().as_str(),
        "tab" | "enter" | "return" | "escape" | "esc" | "f6"
    )
}

/// `element` and its ancestors, outermost first (the order [`elements_at`]
/// returns), so callers can look for the nearest one with a capability.
pub(super) fn with_ancestors(element: IUIAutomationElement) -> Vec<IUIAutomationElement> {
    let mut chain = vec![element];
    if let Ok(walker) = automation().and_then(|automation| {
        unsafe { automation.ControlViewWalker() }.map_err(|error| error.to_string())
    }) {
        while chain.len() < 64 {
            match unsafe { walker.GetParentElement(chain.last().unwrap()) } {
                Ok(parent) => chain.push(parent),
                Err(_) => break,
            }
        }
    }
    chain.reverse();
    chain
}
