//! Office documents on the wire: the native/exact preview, document versions
//! and the file-change event (design: `docs/features/office-v3-parity/spec.md`).
//!
//! Requests are ordinary JSONL commands (`{"id":…,"type":…,…}`) answered with a
//! `response` whose `data` is the shape below. `path` in a request may be
//! absolute or relative to the chat's working folder.
//!
//! ```text
//! office_preview {path, mode:"native"|"exact"|"auto"}
//!   → {kind:"html", path, renderer:"native"|"native-live", live, fallback?}
//!   | {kind:"pdf",  path, renderer:"libreoffice-<version>"}
//! document_versions_get {path} → DocumentHistory
//! document_versions_act {path, action, versionId?, label?} → DocumentHistory
//! event: {type:"office_file_changed", changes:[{kind, path}]}
//! ```
//!
//! Older engines answer the requests with an unknown-command error; older
//! clients ignore the event.

use serde::{Deserialize, Serialize};

pub const OFFICE_PREVIEW: &str = "office_preview";
pub const DOCUMENT_VERSIONS_GET: &str = "document_versions_get";
pub const DOCUMENT_VERSIONS_ACT: &str = "document_versions_act";
/// The unsolicited event type for changed Office files.
pub const OFFICE_FILE_CHANGED: &str = "office_file_changed";

/// Which renderer `office_preview` should use.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum OfficePreviewMode {
    /// The built-in HTML renderer (shapes, cells, geometry).
    Native,
    /// LibreOffice pages (PDF). Needs the runtime.
    Exact,
    /// v3's choice: live builds and workbooks native, decks and documents
    /// exact when the runtime is installed and the conversion succeeds.
    #[default]
    Auto,
}

/// `office_preview` request.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct OfficePreviewRequest {
    pub path: String,
    #[serde(default)]
    pub mode: OfficePreviewMode,
}

/// `office_preview` result.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "lowercase")]
pub enum OfficePreview {
    /// A cached, script-free HTML document (`renderer` `native` or
    /// `native-live`; `live` when it shows the chat's own build in progress).
    Html {
        path: String,
        renderer: String,
        live: bool,
        /// Present (true) when the exact renderer is installed but failed, so
        /// the native render stands in (the viewer shows the v3 banner).
        #[serde(default, skip_serializing_if = "Option::is_none")]
        fallback: Option<bool>,
    },
    /// A cached PDF of exact pages (`renderer` `libreoffice-<version>`).
    Pdf { path: String, renderer: String },
}

/// What `document_versions_act` does.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum DocumentVersionAction {
    /// Record the file as it is; its next change gets `label`.
    Checkpoint,
    Undo,
    Redo,
    /// Write `versionId` back to the file.
    Restore,
}

/// `document_versions_get` request.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DocumentVersionsGet {
    pub path: String,
}

/// `document_versions_act` request.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DocumentVersionsAct {
    pub path: String,
    pub action: DocumentVersionAction,
    #[serde(rename = "versionId", default, skip_serializing_if = "Option::is_none")]
    pub version_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub label: Option<String>,
}

/// One version in a [`DocumentHistory`].
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DocumentVersionInfo {
    pub id: String,
    pub size: u64,
    /// Seconds since the Unix epoch (fractional), as v3.
    #[serde(rename = "createdAt")]
    pub created_at: f64,
    pub label: String,
    /// `baseline`, `change` or `checkpoint`.
    pub source: String,
}

/// The answer to both version requests.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DocumentHistory {
    /// The file relative to the chat's folder, `/`-separated.
    pub path: String,
    pub head: Option<String>,
    #[serde(rename = "canUndo")]
    pub can_undo: bool,
    #[serde(rename = "canRedo")]
    pub can_redo: bool,
    pub versions: Vec<DocumentVersionInfo>,
}

/// How a file changed.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum OfficeChangeKind {
    Added,
    Modified,
    Deleted,
}

/// One changed file in an [`OfficeFileChanged`] event.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct OfficeFileChange {
    pub kind: OfficeChangeKind,
    /// Relative to the chat's folder, `/`-separated.
    pub path: String,
}

/// `{"type":"office_file_changed","changes":[…]}`: `.pptx/.docx/.xlsx` files
/// under the chat's folder changed (settled for 300 ms; paths with a segment
/// starting with `.` and `~$` lock files are left out).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", rename = "office_file_changed")]
pub struct OfficeFileChanged {
    pub changes: Vec<OfficeFileChange>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn wire_shapes() {
        let html = OfficePreview::Html {
            path: "/c/a.html".into(),
            renderer: "native".into(),
            live: false,
            fallback: None,
        };
        assert_eq!(
            serde_json::to_value(&html).unwrap(),
            json!({"kind":"html","path":"/c/a.html","renderer":"native","live":false})
        );
        let pdf = OfficePreview::Pdf {
            path: "/c/a.pdf".into(),
            renderer: "libreoffice-26.8.0".into(),
        };
        assert_eq!(
            serde_json::to_value(&pdf).unwrap(),
            json!({"kind":"pdf","path":"/c/a.pdf","renderer":"libreoffice-26.8.0"})
        );
        let event = OfficeFileChanged {
            changes: vec![OfficeFileChange {
                kind: OfficeChangeKind::Modified,
                path: "deck.pptx".into(),
            }],
        };
        assert_eq!(
            serde_json::to_value(&event).unwrap(),
            json!({"type":"office_file_changed","changes":[{"kind":"modified","path":"deck.pptx"}]})
        );
        let act: DocumentVersionsAct = serde_json::from_value(
            json!({"type":"document_versions_act","path":"d.pptx","action":"restore","versionId":"abc"}),
        )
        .unwrap();
        assert_eq!(act.action, DocumentVersionAction::Restore);
        assert_eq!(act.version_id.as_deref(), Some("abc"));
        let request: OfficePreviewRequest =
            serde_json::from_value(json!({"type":"office_preview","path":"d.pptx"})).unwrap();
        assert_eq!(request.mode, OfficePreviewMode::Auto);
    }
}
