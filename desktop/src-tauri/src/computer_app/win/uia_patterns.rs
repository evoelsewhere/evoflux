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
