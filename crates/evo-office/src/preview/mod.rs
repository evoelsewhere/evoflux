//! The native (built-in) document preview renderer: DOCX, PPTX and XLSX to one
//! self-contained, script-free HTML document, plus what reads it back.
//!
//! A port of v3's `app/services/document_preview/` (tag `v3.1.1`). The markup is
//! a contract shared by the desktop viewer (selection, live build, thumbnails),
//! the agent's `document_preview` tool ([`inspection`]) and the area edits:
//!
//! - every page / slide / sheet carries `data-preview-item` and
//!   `data-preview-label`;
//! - every element the agent can check carries `data-qa-label`, and its inline
//!   `style` gives `left/top/width/height` in percent of its page;
//! - PPTX shapes carry `data-shape-id` (the `cNvPr` id), `data-shape-name` and
//!   `data-source-layer` (`master` | `layout` | `slide`);
//! - XLSX cells carry `data-cell` (A1), `data-display-value` and `data-formula`;
//! - a live build wraps the body in `<main data-deck-live="true">` and marks items
//!   with `data-slide-status` (`done` | `building` | `pending`).
//!
//! Exact pages (LibreOffice → PDF) are not produced here: the engine converts with
//! [`crate::Runtime::convert_to_pdf`] and the viewer shows the PDF with pdf.js.
//!
//! Design: `docs/features/office-v3-parity/sdd.md`.

pub mod cache;
pub mod docx;
pub mod html;
pub mod inspection;
pub mod live;
pub mod package;
pub mod pdf;
pub mod pptx;
pub mod security;
pub mod xlsx;

use std::path::{Path, PathBuf};

pub use live::DeckPlan;
pub use package::Package;

/// File types the native renderer handles.
pub const SUPPORTED_EXTENSIONS: [&str; 4] = ["docx", "xlsx", "pptx", "pdf"];
/// Sources larger than this are refused.
pub const MAX_SOURCE_BYTES: u64 = 100 * 1024 * 1024;
/// Rendered documents larger than this are refused.
pub const MAX_HTML_BYTES: usize = 36 * 1024 * 1024;
/// A workbook shows at least this many rows and columns (empty ones included).
pub const MIN_XLSX_ROWS: u32 = 40;
pub const MIN_XLSX_COLUMNS: u32 = 20;
/// Bumped whenever the markup changes, so cached renders are redone.
pub const CACHE_SCHEMA_VERSION: &str = "evo-document-html-v1";

/// The CSP every rendered document carries (v3 `DOCUMENT_PREVIEW_CSP`).
pub const DOCUMENT_PREVIEW_CSP: &str = "default-src 'none'; base-uri 'none'; connect-src 'none'; \
font-src data:; form-action 'none'; frame-src 'none'; img-src data: blob:; media-src data: blob:; \
object-src 'none'; script-src 'none'; style-src 'unsafe-inline'";

/// Why a document could not be previewed. Messages are shown to the person and
/// to the agent as they are.
#[derive(Debug, thiserror::Error)]
pub enum PreviewError {
    /// The file cannot be opened by this renderer at all (wrong type, legacy
    /// binary format, password protected, too large, unsafe package).
    #[error("{0}")]
    Unsupported(String),
    /// A supported file that failed to render.
    #[error("{0}")]
    Failed(String),
    #[error("{0}")]
    Io(#[from] std::io::Error),
}

impl PreviewError {
    pub fn failed(message: impl Into<String>) -> Self {
        Self::Failed(message.into())
    }
    pub fn unsupported(message: impl Into<String>) -> Self {
        Self::Unsupported(message.into())
    }
}

/// Lower-case extension without the dot.
pub fn extension(path: &Path) -> String {
    path.extension()
        .map(|e| e.to_string_lossy().to_ascii_lowercase())
        .unwrap_or_default()
}

/// Whether `path` has a type the native renderer supports.
pub fn supports(path: &Path) -> bool {
    SUPPORTED_EXTENSIONS.contains(&extension(path).as_str())
}

/// Render `bytes` (the content of `source`) to HTML.
///
/// `live` is the build plan when the requesting chat is building the file live
/// (see [`live::DeckPlan::live_for`]); renderers then add skeletons for the
/// slides or sheets still to come. The caller has already run
/// [`security::preflight`].
pub fn render_html(source: &Path, bytes: &[u8], live: Option<&DeckPlan>) -> Result<String, PreviewError> {
    let title = source
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_default();
    match extension(source).as_str() {
        "docx" => docx::render(&Package::open(bytes)?, &title),
        "pptx" => pptx::render(&Package::open(bytes)?, &title, live),
        "xlsx" => xlsx::render(bytes, &title, live),
        "pdf" => pdf::render(bytes, &title),
        other => Err(PreviewError::unsupported(format!(
            "The viewer cannot open .{other} files."
        ))),
    }
}

/// Render `source` natively into `cache_dir` (cached) and return the HTML file.
///
/// `live_session` is the id of the chat asking, when its turn is running: a file
/// that chat is building live renders with skeletons under its own cache key.
pub fn render_document_preview(
    cache_dir: &Path,
    source: &Path,
    live_session: Option<&str>,
) -> Result<PathBuf, PreviewError> {
    cache::render_cached(cache_dir, source, live_session)
}
