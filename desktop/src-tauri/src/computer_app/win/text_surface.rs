//! Text surfaces — documents and edit controls with UI Automation's Text
//! pattern — where a click places the caret, and a shift+click or a drag
//! selects text.
//!
//! A background click reaches such a control, but an app may place the
//! caret from the real pointer rather than from the click: a word processor
//! left it at the start of the document, and its shift+click and drag
//! selected nothing. The Text pattern puts the caret, or the selection,
//! where the click landed, as a person's click would; for an app that took
//! the click itself this changes nothing.

use super::*;

/// The text surface under `point` in a native window: the window there when
/// it is a document or edit control with the Text pattern, or such a
/// control among its children that holds the point.
pub(super) fn text_at(target: &Target, point: POINT) -> Option<IUIAutomationTextPattern> {
    let automation = automation().ok()?;
    let element = unsafe { automation.ElementFromHandle(pointer_window(target, point)) }.ok()?;
    if let Some(text) = surface(&element) {
        return Some(text);
    }
    // Only the window's own children are looked through: a grid's cells
    // are not text surfaces, and there may be thousands of them.
    let condition =
        unsafe { automation.CreatePropertyCondition(UIA_IsTextPatternAvailablePropertyId, &VARIANT::from(true)) }.ok()?;
    let children = unsafe { element.FindAll(TreeScope_Children, &condition) }.ok()?;
    (0..unsafe { children.Length() }.unwrap_or(0)).find_map(|index| {
        let child = unsafe { children.GetElement(index) }.ok()?;
        let rect = unsafe { child.CurrentBoundingRectangle() }.ok()?;
        if contains(&rect, point) { surface(&child) } else { None }
    })
}

/// The Text pattern of a document or edit control.
fn surface(element: &IUIAutomationElement) -> Option<IUIAutomationTextPattern> {
    // Edit, Document.
    let kind = unsafe { element.CurrentControlType() }.map(|kind| kind.0).unwrap_or(0);
    if !matches!(kind, 50004 | 50030) {
        return None;
    }
    pattern::<IUIAutomationTextPattern>(element, UIA_TextPatternId)
}

fn selection(text: &IUIAutomationTextPattern) -> Option<IUIAutomationTextRange> {
    unsafe { text.GetSelection().and_then(|ranges| ranges.GetElement(0)) }.ok()
}

/// Put the caret at `point`.
pub(super) fn place_caret(text: &IUIAutomationTextPattern, point: POINT) -> bool {
    unsafe { text.RangeFromPoint(point).and_then(|range| range.Select()) }.is_ok()
}

/// Extend the selection from where it starts (or ends, for a point before
/// it) to `point`, as a shift+click does.
pub(super) fn select_to(text: &IUIAutomationTextPattern, point: POINT) -> bool {
    let (Some(range), Ok(there)) = (selection(text), unsafe { text.RangeFromPoint(point) }) else {
        return false;
    };
    unsafe {
        let after = range
            .CompareEndpoints(TextPatternRangeEndpoint_Start, &there, TextPatternRangeEndpoint_Start)
            .is_ok_and(|order| order <= 0);
        let moved = if after {
            range.MoveEndpointByRange(TextPatternRangeEndpoint_End, &there, TextPatternRangeEndpoint_Start)
        } else {
            range.MoveEndpointByRange(TextPatternRangeEndpoint_Start, &there, TextPatternRangeEndpoint_Start)
        };
        moved.and_then(|()| range.Select()).is_ok()
    }
}

/// Select the text between two points, as a drag across it does.
pub(super) fn select_between(text: &IUIAutomationTextPattern, from: POINT, to: POINT) -> bool {
    let (Ok(start), Ok(end)) = (unsafe { text.RangeFromPoint(from) }, unsafe { text.RangeFromPoint(to) }) else {
        return false;
    };
    unsafe {
        let forward = start
            .CompareEndpoints(TextPatternRangeEndpoint_Start, &end, TextPatternRangeEndpoint_Start)
            .is_ok_and(|order| order <= 0);
        let (range, other) = if forward { (start, end) } else { (end, start) };
        range
            .MoveEndpointByRange(TextPatternRangeEndpoint_End, &other, TextPatternRangeEndpoint_Start)
            .and_then(|()| range.Select())
            .is_ok()
    }
}

/// Whether `point` lies in the current selection, when there is one: a drag
/// starting there moves the selected text rather than selecting.
pub(super) fn in_selection(text: &IUIAutomationTextPattern, point: POINT) -> bool {
    let (Some(range), Ok(there)) = (selection(text), unsafe { text.RangeFromPoint(point) }) else {
        return false;
    };
    unsafe {
        let order = |source, target| {
            range.CompareEndpoints(source, &there, target).unwrap_or(0)
        };
        let empty = range
            .CompareEndpoints(TextPatternRangeEndpoint_Start, &range, TextPatternRangeEndpoint_End)
            .is_ok_and(|order| order == 0);
        !empty
            && order(TextPatternRangeEndpoint_Start, TextPatternRangeEndpoint_Start) <= 0
            && order(TextPatternRangeEndpoint_End, TextPatternRangeEndpoint_Start) > 0
    }
}
