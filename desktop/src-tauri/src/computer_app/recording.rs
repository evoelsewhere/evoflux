use serde::Serialize;

const MAX_SCREENSHOT_BASE64_BYTES: usize = 3 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum CaptureKind {
    Click,
    DoubleClick,
    Scroll,
    WindowChange,
    Focus,
    Invoked,
    Selected,
    ValueChanged,
    StateChange,
    WindowOpened,
    WindowClosed,
    Gap,
    Screenshot,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum PointerButton {
    Left,
    Middle,
    Right,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(super) struct PointerPoint {
    pub x: i32,
    pub y: i32,
    pub display_id: Option<String>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub(super) struct ScrollDelta {
    pub x: i32,
    pub y: i32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum ValueState {
    NotCaptured,
    Captured,
    OmittedSecure,
    Unavailable,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(super) struct ElementTarget {
    pub automation_id: Option<String>,
    pub control_type: Option<String>,
    pub name: Option<String>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) struct SelectedTarget {
    pub window_id: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct CaptureObservation {
    /// Top-level selected window or one of its owned dialogs, normalized to
    /// the selected root window before this observation reaches the stream.
    /// Child processes such as Chromium renderers are in scope only through
    /// this root window identity.
    pub root_window_id: u64,
    pub kind: CaptureKind,
    pub point: Option<PointerPoint>,
    pub button: Option<PointerButton>,
    pub scroll_delta: Option<ScrollDelta>,
    pub target: Option<ElementTarget>,
    pub is_password: Option<bool>,
    pub value: Option<String>,
    pub screenshot: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(super) struct SkillRecordingEvent {
    pub sequence: u64,
    pub elapsed_ms: u64,
    pub kind: CaptureKind,
    pub point: Option<PointerPoint>,
    pub button: Option<PointerButton>,
    pub scroll_delta: Option<ScrollDelta>,
    pub target: Option<ElementTarget>,
    pub value_state: ValueState,
    pub value: Option<String>,
    pub screenshot: Option<String>,
}

pub(super) fn normalize_observation(
    sequence: u64,
    elapsed_ms: u64,
    selected: &SelectedTarget,
    mut observation: CaptureObservation,
) -> Option<SkillRecordingEvent> {
    if selected.window_id != 0 && observation.root_window_id != selected.window_id {
        return None;
    }

    let pointer_fields = match observation.kind {
        CaptureKind::Click | CaptureKind::DoubleClick => {
            if observation.point.is_none()
                || observation.button.is_none()
                || observation.scroll_delta.is_some()
            {
                return None;
            }
            (observation.point.take(), observation.button.take(), None)
        }
        CaptureKind::Scroll => {
            if observation.point.is_none()
                || observation.scroll_delta.is_none()
                || observation.button.is_some()
            {
                return None;
            }
            (
                observation.point.take(),
                None,
                observation.scroll_delta.take(),
            )
        }
        _ => (None, None, None),
    };

    if let Some(target) = observation.target.as_mut() {
        let control_type = target.control_type.as_deref().unwrap_or_default();
        if observation.kind == CaptureKind::Focus
            || matches!(
                control_type.to_ascii_lowercase().as_str(),
                "edit" | "text" | "pane"
            )
        {
            target.name = None;
        }
    }

    let (value_state, value) = if observation.kind == CaptureKind::ValueChanged {
        match (observation.is_password, observation.value.take()) {
            (Some(false), Some(value)) => (ValueState::Captured, Some(value)),
            (Some(true), _) => (ValueState::OmittedSecure, None),
            (None, _) | (Some(false), None) => (ValueState::Unavailable, None),
        }
    } else {
        (ValueState::NotCaptured, None)
    };

    let screenshot = if observation.kind == CaptureKind::Screenshot {
        observation
            .screenshot
            .filter(|encoded| encoded.len() <= MAX_SCREENSHOT_BASE64_BYTES)
    } else {
        None
    };

    Some(SkillRecordingEvent {
        sequence,
        elapsed_ms,
        kind: observation.kind,
        point: pointer_fields.0,
        button: pointer_fields.1,
        scroll_delta: pointer_fields.2,
        target: observation.target,
        value_state,
        value,
        screenshot,
    })
}

#[cfg(test)]
mod tests {
    use super::{
        normalize_observation, CaptureKind, CaptureObservation, ElementTarget, PointerButton,
        PointerPoint, ScrollDelta, SelectedTarget, ValueState,
    };

    fn target() -> SelectedTarget {
        SelectedTarget { window_id: 42 }
    }

    fn observation(kind: CaptureKind) -> CaptureObservation {
        CaptureObservation {
            root_window_id: 42,
            kind,
            point: None,
            button: None,
            scroll_delta: None,
            target: Some(ElementTarget {
                automation_id: Some("field-1".into()),
                control_type: Some("edit".into()),
                name: Some("label".into()),
            }),
            is_password: Some(false),
            value: None,
            screenshot: None,
        }
    }

    #[test]
    fn focus_event_never_serializes_ui_text_or_value() {
        let mut input = observation(CaptureKind::Focus);
        input.value = Some("must-not-leak".into());
        input.target.as_mut().unwrap().name = Some("also-must-not-leak".into());

        let event = normalize_observation(1, 12, &target(), input).unwrap();
        let serialized = serde_json::to_string(&event).unwrap();

        assert!(!serialized.contains("must-not-leak"));
        assert!(!serialized.contains("also-must-not-leak"));
        assert!(event.value.is_none());
        assert_eq!(event.value_state, ValueState::NotCaptured);
        assert!(event.target.unwrap().name.is_none());
    }

    #[test]
    fn value_change_is_captured_only_when_password_property_is_false() {
        let mut input = observation(CaptureKind::ValueChanged);
        input.value = Some("ordinary value".into());

        let event = normalize_observation(2, 40, &target(), input).unwrap();

        assert_eq!(event.value.as_deref(), Some("ordinary value"));
        assert_eq!(event.value_state, ValueState::Captured);
        assert_eq!(event.sequence, 2);
        assert_eq!(event.elapsed_ms, 40);
    }

    #[test]
    fn secure_value_is_omitted_and_never_serialized() {
        let mut input = observation(CaptureKind::ValueChanged);
        input.is_password = Some(true);
        input.value = Some("must-not-leak".into());

        let event = normalize_observation(3, 50, &target(), input).unwrap();
        let serialized = serde_json::to_string(&event).unwrap();

        assert!(!serialized.contains("must-not-leak"));
        assert!(event.value.is_none());
        assert_eq!(event.value_state, ValueState::OmittedSecure);
    }

    #[test]
    fn unknown_password_state_fails_closed() {
        let mut input = observation(CaptureKind::ValueChanged);
        input.is_password = None;
        input.value = Some("must-not-leak".into());

        let event = normalize_observation(4, 60, &target(), input).unwrap();

        assert!(event.value.is_none());
        assert_eq!(event.value_state, ValueState::Unavailable);
    }

    #[test]
    fn renderer_process_observations_are_scoped_by_selected_root_window() {
        let renderer_event = observation(CaptureKind::Invoked);
        assert!(normalize_observation(1, 0, &target(), renderer_event).is_some());

        let mut wrong_window = observation(CaptureKind::Selected);
        wrong_window.root_window_id = 99;
        assert!(normalize_observation(1, 0, &target(), wrong_window).is_none());
    }

    #[test]
    fn screenshot_is_serialized_only_for_checkpoint_event() {
        let mut input = observation(CaptureKind::Screenshot);
        input.screenshot = Some("png-base64".into());

        let event = normalize_observation(5, 80, &target(), input).unwrap();
        assert_eq!(event.screenshot.as_deref(), Some("png-base64"));

        let mut non_checkpoint = observation(CaptureKind::Focus);
        non_checkpoint.screenshot = Some("must-not-leak".into());
        let event = normalize_observation(6, 90, &target(), non_checkpoint).unwrap();
        assert!(event.screenshot.is_none());
    }

    #[test]
    fn desktop_click_and_scroll_keep_negative_coordinates_and_button_details() {
        let selected_desktop = SelectedTarget { window_id: 0 };
        let click = normalize_observation(
            7,
            100,
            &selected_desktop,
            CaptureObservation {
                root_window_id: 99,
                kind: CaptureKind::DoubleClick,
                point: Some(PointerPoint {
                    x: -120,
                    y: 340,
                    display_id: Some("DISPLAY1".into()),
                }),
                button: Some(PointerButton::Left),
                scroll_delta: None,
                target: None,
                is_password: None,
                value: None,
                screenshot: None,
            },
        )
        .unwrap();
        assert_eq!(click.point.unwrap().x, -120);
        assert_eq!(click.button, Some(PointerButton::Left));

        let scroll = normalize_observation(
            8,
            120,
            &selected_desktop,
            CaptureObservation {
                root_window_id: 123,
                kind: CaptureKind::Scroll,
                point: Some(PointerPoint {
                    x: 12,
                    y: 34,
                    display_id: Some("DISPLAY2".into()),
                }),
                button: None,
                scroll_delta: Some(ScrollDelta { x: 0, y: -120 }),
                target: None,
                is_password: None,
                value: None,
                screenshot: None,
            },
        )
        .unwrap();
        assert_eq!(scroll.scroll_delta, Some(ScrollDelta { x: 0, y: -120 }));
    }

    #[test]
    fn malformed_pointer_actions_are_dropped_and_foreign_window_is_filtered() {
        let selected_desktop = SelectedTarget { window_id: 0 };
        let malformed = CaptureObservation {
            root_window_id: 99,
            kind: CaptureKind::Click,
            point: None,
            button: Some(PointerButton::Left),
            scroll_delta: None,
            target: None,
            is_password: None,
            value: None,
            screenshot: None,
        };
        assert!(normalize_observation(1, 0, &selected_desktop, malformed).is_none());

        let mut out_of_scope = observation(CaptureKind::Invoked);
        out_of_scope.root_window_id = 99;
        assert!(normalize_observation(1, 0, &target(), out_of_scope).is_none());
    }
}
