//! `date`: the current local date, time and timezone.

use async_trait::async_trait;
use serde_json::{json, Value};

use crate::{definition, Tool, ToolCtx, ToolOutput};

pub(crate) struct DateTool;

const DESCRIPTION: &str =
    "Get the current local date, time, and timezone (e.g. '2026-04-06 14:30:00 ICT').";

/// `datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")`.
///
/// chrono has no timezone abbreviation for the local zone, so the zone is its
/// UTC offset (`+07:00`) rather than a name such as `ICT`.
pub(crate) fn now_text() -> String {
    chrono::Local::now()
        .format("%Y-%m-%d %H:%M:%S %Z")
        .to_string()
}

#[async_trait]
impl Tool for DateTool {
    fn name(&self) -> &str {
        "date"
    }

    fn spec(&self) -> Value {
        definition("date", DESCRIPTION, json!({}), &[])
    }

    async fn call(&self, _args: Value, _ctx: &ToolCtx) -> ToolOutput {
        ToolOutput::ok(now_text())
    }
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::panic,
    clippy::disallowed_methods
)]
mod tests {
    use super::*;

    #[test]
    fn shape_is_date_time_zone() {
        let text = now_text();
        let (stamp, zone) = text.split_at(19);
        let digits: Vec<bool> = stamp.chars().map(|c| c.is_ascii_digit()).collect();
        let pattern = "dddd-dd-dd dd:dd:dd";
        for ((c, is_digit), want) in stamp.chars().zip(digits).zip(pattern.chars()) {
            if want == 'd' {
                assert!(is_digit, "{text}");
            } else {
                assert_eq!(c, want, "{text}");
            }
        }
        assert!(zone.starts_with(' ') && zone.len() > 1, "{text}");
    }

    #[tokio::test]
    async fn call_ignores_arguments() {
        let ctx = ToolCtx {
            workspace_root: std::env::temp_dir(),
            session_id: "s".into(),
        };
        let out = DateTool.call(json!({"anything": 1}), &ctx).await;
        assert!(!out.is_error);
        assert_eq!(out.content.len(), now_text().len());
        assert_eq!(DateTool.name(), "date");
    }
}
