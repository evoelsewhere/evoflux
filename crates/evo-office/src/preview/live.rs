//! The build plan a deck or workbook carries while an agent generates it
//! (v3 `live_deck.py`).
//!
//! The `pptx-official` skill's `scripts/deck_live.py` (and `xlsx-official`'s
//! `scripts/workbook_live.py`) creates the file before its slides (sheets) exist
//! and stores the plan as the `evo.deck` custom document property (v3 wrote
//! `evoflux.deck`; both are read). Parts are appended one at a time and the file
//! is saved after each, so the parts present are the finished ones; the preview
//! renders skeletons for the rest until the plan says `done`. A workbook cannot
//! have zero sheets, so its plan also counts the sheets actually `added`. The
//! plan names the building chat (`EVO_CHAT_ID` in the agent's shell): only
//! that chat sees the build live, and only while its turn runs.

use super::package::Package;

/// Custom property names that hold the plan (current, then v3).
pub const PLAN_PROPERTIES: [&str; 2] = ["evo.deck", "evoflux.deck"];
const CUSTOM_PART: &str = "docProps/custom.xml";
const MAX_PLAN_BYTES: usize = 64 * 1024;
const MAX_PARTS: i64 = 500;
/// Files an agent can build live.
pub const LIVE_EXTENSIONS: [&str; 2] = ["pptx", "xlsx"];

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeckPlan {
    pub total: u32,
    pub done: bool,
    /// The chat whose agent is building the file, when known.
    pub session: Option<String>,
    /// Workbooks: sheets added so far (`None` for decks).
    pub added: Option<u32>,
}

impl DeckPlan {
    /// Whether `session_id` (a chat whose turn is running) is building it. A plan
    /// without a session belongs to any running chat.
    pub fn live_for(&self, session_id: Option<&str>) -> bool {
        let Some(session_id) = session_id.filter(|s| !s.is_empty()) else {
            return false;
        };
        if self.done {
            return false;
        }
        self.session.as_deref().is_none_or(|s| s == session_id)
    }
}

/// The plan embedded in `package`, if any.
pub fn read_plan(package: &Package) -> Option<DeckPlan> {
    let bytes = package.bytes(CUSTOM_PART)?;
    if bytes.len() > MAX_PLAN_BYTES {
        return None;
    }
    let text = String::from_utf8_lossy(bytes);
    let doc = super::html::parse_xml(&text).ok()?;
    for name in PLAN_PROPERTIES {
        let Some(prop) = doc
            .descendants()
            .find(|n| n.tag_name().name() == "property" && n.attribute("name") == Some(name))
        else {
            continue;
        };
        let raw: String = prop
            .descendants()
            .filter(|n| n.is_text())
            .filter_map(|n| n.text())
            .collect();
        return parse_plan(raw.trim());
    }
    None
}

/// The plan of the file at `bytes` (a zip), if any.
pub fn read_plan_bytes(bytes: &[u8]) -> Option<DeckPlan> {
    // Only the custom part is needed; avoid inflating the whole package.
    let mut archive = zip::ZipArchive::new(std::io::Cursor::new(bytes)).ok()?;
    let mut entry = archive.by_name(CUSTOM_PART).ok()?;
    if entry.size() as usize > MAX_PLAN_BYTES {
        return None;
    }
    let mut data = Vec::new();
    std::io::Read::read_to_end(&mut entry, &mut data).ok()?;
    read_plan(&Package::from_parts([(CUSTOM_PART.to_string(), data)]))
}

fn parse_plan(text: &str) -> Option<DeckPlan> {
    let data: serde_json::Value = serde_json::from_str(text).ok()?;
    let total = as_int(data.get("total")?)?;
    if !(1..=MAX_PARTS).contains(&total) {
        return None;
    }
    let state = data
        .get("state")
        .and_then(|s| s.as_str())
        .unwrap_or("building");
    let session = data.get("session").and_then(|s| match s {
        serde_json::Value::String(s) if !s.is_empty() => Some(s.chars().take(64).collect()),
        serde_json::Value::Number(n) => Some(n.to_string()),
        _ => None,
    });
    let added = match data.get("added") {
        None | Some(serde_json::Value::Null) => None,
        Some(v) => Some(as_int(v)?.max(0) as u32),
    };
    Some(DeckPlan {
        total: total as u32,
        done: state == "done",
        session,
        added,
    })
}

fn as_int(value: &serde_json::Value) -> Option<i64> {
    match value {
        serde_json::Value::Number(n) => n.as_i64().or_else(|| n.as_f64().map(|f| f as i64)),
        serde_json::Value::String(s) => s.trim().parse().ok(),
        serde_json::Value::Bool(b) => Some(*b as i64),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn package_with(name: &str, json: &str) -> Package {
        let xml = format!(
            r#"<?xml version="1.0"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="2" name="{name}"><vt:lpwstr>{}</vt:lpwstr></property></Properties>"#,
            super::super::html::escape(json)
        );
        Package::from_parts([(CUSTOM_PART.to_string(), xml.into_bytes())])
    }

    #[test]
    fn reads_current_and_v3_plans() {
        let plan = read_plan(&package_with(
            "evo.deck",
            r#"{"v":1,"total":3,"state":"building","session":"chat-1"}"#,
        ))
        .unwrap();
        assert_eq!(plan.total, 3);
        assert!(!plan.done);
        assert!(plan.live_for(Some("chat-1")));
        assert!(!plan.live_for(Some("chat-2")));
        assert!(!plan.live_for(None));
        let v3 = read_plan(&package_with(
            "evoflux.deck",
            r#"{"v":1,"total":2,"added":0,"state":"done"}"#,
        ))
        .unwrap();
        assert!(v3.done && v3.added == Some(0));
        assert!(!v3.live_for(Some("x")));
    }

    #[test]
    fn rejects_bad_totals() {
        assert!(read_plan(&package_with("evo.deck", r#"{"total":0}"#)).is_none());
        assert!(read_plan(&package_with("evo.deck", r#"{"total":501}"#)).is_none());
        let no_session = read_plan(&package_with("evo.deck", r#"{"total":2}"#)).unwrap();
        assert!(no_session.live_for(Some("any")));
    }
}
