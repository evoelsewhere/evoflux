//! `document_preview` — render a workspace document the way the viewer does and
//! report its layout (port of v3 `app/agent/tools/builtin/document_preview.py`).
//!
//! The engine owns a read-only rendering engine for Office and PDF files
//! (`evo_office::preview`). It needs no office application and no external
//! renderer binary. This tool runs it in-process (always the native renderer,
//! never a live build) and reports what the rendering says: each page with its
//! labelled elements, their text, and their geometry as percentages of the page
//! box, which is what makes "this shape hangs off the slide" an observation
//! rather than a guess. Formats, size budgets, cache policy and the markup
//! contract all come from the renderer, so the tool cannot drift from the
//! viewer.
//!
//! Paths resolve against the chat's folder and must stay inside it; the
//! sandbox's denied patterns apply as for the other file tools. The tool only
//! reads.
//!
//! Design: `docs/features/office-v3-parity/sdd.md`.

use std::path::{Component, Path, PathBuf};
use std::sync::Arc;

use async_trait::async_trait;
use evo_agent::agent_tool::AgentTool;
use evo_agent::error::AgentError;
use evo_agent::types::{AgentToolResult, ToolExecutionMode, ToolResultPartial};
use evo_ai::types::Tool;
use evo_office::preview::inspection::{PreviewItem, PreviewSummary};
use evo_office::preview::{self, PreviewError};
use serde::Deserialize;
use tokio_util::sync::CancellationToken;

pub const TOOL_NAME: &str = "document_preview";

/// `.docx, .pdf, .pptx, .xlsx` (v3 `_supported_suffixes`).
pub fn supported_suffixes() -> String {
    let mut suffixes: Vec<String> = preview::SUPPORTED_EXTENSIONS
        .iter()
        .map(|e| format!(".{e}"))
        .collect();
    suffixes.sort();
    suffixes.join(", ")
}

fn description() -> String {
    format!(
        "Render a workspace document with the host's read-only viewer engine \
         and report its laid-out pages: each element's label, text, and \
         position as a percentage of the page, with anything falling outside \
         the page flagged. Formats: {}. Needs no office \
         application and no external renderer. Use it to verify a document you \
         produced, or to inspect the layout of one you were given.",
        supported_suffixes()
    )
}

fn parameters() -> serde_json::Value {
    serde_json::json!({
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Workspace path to the document to render. Supported formats are listed in the tool description."
            },
            "verbose": {
                "type": "boolean",
                "default": false,
                "description": "Include every element. Off by default, which reports elements carrying text plus anything outside the page box."
            }
        },
        "required": ["path"],
        "additionalProperties": false
    })
}

#[derive(Debug, Deserialize)]
struct Input {
    path: String,
    #[serde(default)]
    verbose: bool,
}

pub struct DocumentPreviewTool {
    schema: Tool,
    cwd: PathBuf,
    cache_dir: PathBuf,
}

/// The tool for a chat working in `cwd`, caching under the engine's preview cache.
pub fn create_document_preview_tool(cwd: PathBuf) -> Arc<dyn AgentTool> {
    create_with_cache(cwd, crate::office::preview_cache_dir())
}

/// The tool with an explicit cache folder (tests).
pub fn create_with_cache(cwd: PathBuf, cache_dir: PathBuf) -> Arc<dyn AgentTool> {
    Arc::new(DocumentPreviewTool {
        schema: Tool {
            name: TOOL_NAME.to_string(),
            description: description(),
            parameters: evo_ai::types::Schema::new(parameters()),
            constrained_sampling: None,
        },
        cwd,
        cache_dir,
    })
}

#[async_trait]
impl AgentTool for DocumentPreviewTool {
    fn schema(&self) -> &Tool {
        &self.schema
    }

    fn label(&self) -> &str {
        TOOL_NAME
    }

    fn execution_mode(&self) -> ToolExecutionMode {
        ToolExecutionMode::Parallel
    }

    async fn execute(
        &self,
        _tool_call_id: &str,
        params: serde_json::Value,
        signal: CancellationToken,
        _on_update: Arc<dyn Fn(ToolResultPartial) + Send + Sync>,
    ) -> Result<AgentToolResult, AgentError> {
        let input: Input = serde_json::from_value(params)
            .map_err(|e| AgentError::Validation(format!("document_preview input invalid: {e}")))?;
        if signal.is_cancelled() {
            return Err(AgentError::Tool("document_preview cancelled".into()));
        }
        let report = document_preview(&self.cwd, &self.cache_dir, &input.path, input.verbose)
            .await
            .map_err(AgentError::Tool)?;
        Ok(AgentToolResult::text(report))
    }
}

/// Run the tool: `Err` is a tool error (missing file, path refused), `Ok` the
/// report text, which also carries render failures as v3 did.
pub async fn document_preview(
    cwd: &Path,
    cache_dir: &Path,
    path: &str,
    verbose: bool,
) -> Result<String, String> {
    let (resolved, rel) = validate_path(cwd, path)?;
    let meta = tokio::fs::metadata(&resolved).await.ok();
    let Some(meta) = meta else {
        return Err(format!("Document not found: {rel}"));
    };
    if !meta.is_file() {
        return Err(format!("Path is not a file: {rel}"));
    }

    if let Some(message) = crate::office::unsupported_message(&resolved) {
        return Ok(cannot_preview(&rel, &message));
    }
    // The built-in engine even when the exact renderer is installed: its
    // pages are images, which report no elements to check. No live session:
    // the agent sees the file as it is.
    let rendered = {
        let (cache_dir, source) = (cache_dir.to_path_buf(), resolved.clone());
        tokio::task::spawn_blocking(move || {
            preview::render_document_preview(&cache_dir, &source, None)
        })
        .await
        .unwrap_or_else(|error| Err(PreviewError::failed(error.to_string())))
    };
    let rendered = match rendered {
        Ok(rendered) => rendered,
        Err(PreviewError::Unsupported(message)) => return Ok(cannot_preview(&rel, &message)),
        Err(error) => return Ok(format!("[Preview failed: {rel}]\n{error}")),
    };
    // The cache root may be relative to the process directory: anchor it once
    // before reporting it.
    let preview_path = std::path::absolute(&rendered).unwrap_or(rendered);

    let read = async {
        let html = tokio::fs::read_to_string(&preview_path).await?;
        let size = tokio::fs::metadata(&preview_path).await?.len();
        Ok::<_, std::io::Error>((html, size))
    };
    let (html, size) = match read.await {
        Ok(read) => read,
        Err(error) => {
            return Ok(format!(
                "[Preview rendered but could not be read: {rel}]\n{error}"
            ))
        }
    };
    let summary = tokio::task::spawn_blocking(move || preview::inspection::summarize(&html))
        .await
        .unwrap_or_default();
    tracing::debug!(source = %resolved.display(), preview = %preview_path.display(), pages = summary.items.len(), "document_preview_rendered");
    Ok(render_report(&rel, &preview_path, size, &summary, verbose))
}

fn cannot_preview(rel: &str, message: &str) -> String {
    format!(
        "[Cannot preview: {rel}]\n{message}\nSupported formats: {}.",
        supported_suffixes()
    )
}

/// `\\?\C:\x` → `C:\x` (Windows canonical paths), so paths read as the person
/// typed them.
fn plain(path: PathBuf) -> PathBuf {
    let text = path.to_string_lossy();
    if let Some(rest) = text.strip_prefix(r"\\?\") {
        if !rest.starts_with("UNC\\") {
            return PathBuf::from(rest);
        }
    }
    path
}

/// Resolve like Python's `Path.resolve(strict=False)`: the longest existing
/// prefix canonicalized, the rest appended.
fn resolve(path: &Path) -> PathBuf {
    let mut existing = path.to_path_buf();
    let mut rest: Vec<std::ffi::OsString> = Vec::new();
    loop {
        if let Ok(canonical) = std::fs::canonicalize(&existing) {
            let mut out = plain(canonical);
            for part in rest.iter().rev() {
                match Path::new(part).components().next() {
                    Some(Component::ParentDir) => {
                        out.pop();
                    }
                    Some(Component::CurDir) => {}
                    _ => out.push(part),
                }
            }
            return out;
        }
        match (
            existing.file_name().map(|n| n.to_os_string()),
            existing.parent(),
        ) {
            (Some(name), Some(parent)) => {
                rest.push(name);
                existing = parent.to_path_buf();
            }
            _ => return path.to_path_buf(),
        }
    }
}

/// Resolve `path` inside the workspace `cwd` (v3 `sandbox.validate_path` +
/// `display_path`): the resolved file and how to name it in the report.
pub fn validate_path(cwd: &Path, path: &str) -> Result<(PathBuf, String), String> {
    if path.starts_with('~') {
        return Err(format!(
            "Tilde paths are not allowed inside the sandbox: {path}"
        ));
    }
    let candidate = Path::new(path);
    let candidate = if candidate.is_absolute() {
        candidate.to_path_buf()
    } else {
        cwd.join(candidate)
    };
    let root = resolve(cwd);
    let resolved = resolve(&candidate);
    let Ok(rel) = resolved.strip_prefix(&root) else {
        return Err(format!(
            "Path '{}' is outside the workspace ({}).",
            resolved.display(),
            root.display()
        ));
    };
    evo_tools::sandbox::policy()
        .check_path(&resolved.to_string_lossy(), Some(cwd))
        .map_err(|error| error.to_string())?;
    let display = if rel.as_os_str().is_empty() {
        root.display().to_string()
    } else {
        rel.components()
            .map(|c| c.as_os_str().to_string_lossy())
            .collect::<Vec<_>>()
            .join("/")
    };
    Ok((resolved, display))
}

/// `1234567` → `1,234,567`.
fn thousands(value: u64) -> String {
    let digits = value.to_string();
    let mut out = String::with_capacity(digits.len() + digits.len() / 3);
    for (index, digit) in digits.chars().enumerate() {
        if index > 0 && (digits.len() - index).is_multiple_of(3) {
            out.push(',');
        }
        out.push(digit);
    }
    out
}

/// Python's `value or 0`: `None`, `0.0` and `-0.0` all print as `0.0`.
fn or_zero(value: Option<f64>) -> f64 {
    value.filter(|v| *v != 0.0).unwrap_or(0.0)
}

fn format_geometry(item: &PreviewItem, verbose: bool) -> Vec<String> {
    let mut lines = Vec::new();
    for element in &item.elements {
        let text = if element.text.is_empty() {
            String::new()
        } else {
            format!(" :: {}", element.text)
        };
        let flagged = element.out_of_bounds();
        if !verbose && !flagged && element.text.is_empty() {
            continue;
        }
        let bbox = match (element.left, element.width) {
            (Some(left), Some(width)) => format!(
                " [{left:.1},{:.1} {width:.1}x{:.1}%]",
                or_zero(element.top),
                or_zero(element.height)
            ),
            _ => String::new(),
        };
        let marker = if flagged { " OUTSIDE PAGE" } else { "" };
        lines.push(format!("    {}{bbox}{marker}{text}", element.label));
    }
    lines
}

/// The report text (v3 `_render_report`, byte for byte).
pub fn render_report(
    source: &str,
    preview: &Path,
    size: u64,
    summary: &PreviewSummary,
    verbose: bool,
) -> String {
    // A dict keyed by label in v3: a repeated label keeps its first position
    // and its last list.
    let mut out_of_bounds: Vec<(String, Vec<String>)> = Vec::new();
    for item in &summary.items {
        let outside: Vec<String> = item
            .elements
            .iter()
            .filter(|e| e.out_of_bounds())
            .map(|e| e.label.clone())
            .collect();
        if outside.is_empty() {
            continue;
        }
        match out_of_bounds
            .iter_mut()
            .find(|(label, _)| *label == item.label)
        {
            Some(entry) => entry.1 = outside,
            None => out_of_bounds.push((item.label.clone(), outside)),
        }
    }

    let mut lines = vec![
        format!("[Document preview: {source}]"),
        format!(
            "Rendered by the host viewer engine: {} ({} bytes)",
            preview.display(),
            thousands(size)
        ),
        format!(
            "Pages: {}{}",
            summary.items.len(),
            if summary.items_truncated {
                " (truncated)"
            } else {
                ""
            }
        ),
    ];

    if out_of_bounds.is_empty() {
        lines.push("Every laid-out element sits inside its page box.".into());
    } else {
        lines.push(String::new());
        lines.push("Elements outside the page box:".into());
        for (label, elements) in &out_of_bounds {
            lines.push(format!("  {label}: {}", elements.join(", ")));
        }
    }

    for item in &summary.items {
        lines.push(String::new());
        lines.push(format!(
            "  {} ({} elements)",
            item.label,
            item.elements.len()
        ));
        if item.elements_truncated {
            lines.push("    … more elements than the inspection budget allows".into());
        }
        lines.extend(format_geometry(item, verbose));
    }

    lines.push(String::new());
    lines.push(
        "Geometry is a percentage of the page box, so 0–100 is inside it. This \
         is the host engine's layout, not the authoring application's: report \
         it as a rendered-layout check, and do not claim you looked at pixels."
            .into(),
    );
    lines.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use evo_office::preview::inspection::PreviewElement;

    fn element(label: &str, text: &str, geometry: Option<(f64, f64, f64, f64)>) -> PreviewElement {
        let (left, top, width, height) = match geometry {
            Some((l, t, w, h)) => (Some(l), Some(t), Some(w), Some(h)),
            None => (None, None, None, None),
        };
        PreviewElement {
            label: label.into(),
            text: text.into(),
            left,
            top,
            width,
            height,
        }
    }

    fn summary() -> PreviewSummary {
        PreviewSummary {
            items: vec![
                PreviewItem {
                    label: "Slide 1".into(),
                    elements: vec![
                        element(
                            "TextBox 1",
                            "a title that belongs here",
                            Some((10.0, 13.333, 40.0, 13.33)),
                        ),
                        element("Rectangle 2", "", Some((10.0, 40.0, 20.0, 13.33))),
                        element(
                            "TextBox 3",
                            "hangs off the edge",
                            Some((91.667, 86.667, 33.333, 26.667)),
                        ),
                    ],
                    elements_truncated: false,
                },
                PreviewItem {
                    label: "Slide 2".into(),
                    elements: vec![element("Picture 1", "", None)],
                    elements_truncated: true,
                },
            ],
            items_truncated: false,
        }
    }

    #[test]
    fn the_report_matches_v3_byte_for_byte() {
        let report = render_report(
            "deck.pptx",
            Path::new("/cache/previews/abc.html"),
            1_234_567,
            &summary(),
            false,
        );
        let expected = [
            "[Document preview: deck.pptx]",
            "Rendered by the host viewer engine: /cache/previews/abc.html (1,234,567 bytes)",
            "Pages: 2",
            "",
            "Elements outside the page box:",
            "  Slide 1: TextBox 3",
            "",
            "  Slide 1 (3 elements)",
            "    TextBox 1 [10.0,13.3 40.0x13.3%] :: a title that belongs here",
            "    TextBox 3 [91.7,86.7 33.3x26.7%] OUTSIDE PAGE :: hangs off the edge",
            "",
            "  Slide 2 (1 elements)",
            "    … more elements than the inspection budget allows",
            "",
            "Geometry is a percentage of the page box, so 0–100 is inside it. This is the host engine's layout, \
             not the authoring application's: report it as a rendered-layout check, and do not claim you looked at pixels.",
        ]
        .join("\n");
        assert_eq!(report, expected);

        let verbose = render_report("deck.pptx", Path::new("/c/a.html"), 12, &summary(), true);
        assert!(verbose.contains("    Rectangle 2 [10.0,40.0 20.0x13.3%]\n"));
        assert!(verbose.contains("    Picture 1\n"));
        assert!(verbose.contains("(12 bytes)"));
        assert!(verbose.lines().count() > report.lines().count());
    }

    #[test]
    fn a_clean_report_says_so() {
        let mut clean = summary();
        clean.items.truncate(1);
        clean.items[0].elements.truncate(1);
        clean.items_truncated = true;
        let report = render_report("a.docx", Path::new("/p.html"), 999, &clean, false);
        assert!(report.contains("Pages: 1 (truncated)\nEvery laid-out element sits inside its page box.\n\n  Slide 1 (1 elements)"));
        assert!(report.contains("(999 bytes)"));
    }

    #[test]
    fn numbers_format_like_python() {
        assert_eq!(thousands(0), "0");
        assert_eq!(thousands(999), "999");
        assert_eq!(thousands(1000), "1,000");
        assert_eq!(thousands(12_345_678), "12,345,678");
        let item = PreviewItem {
            label: "Page 1".into(),
            elements: vec![PreviewElement {
                label: "e".into(),
                text: "t".into(),
                left: Some(0.25),
                top: Some(-0.0),
                width: Some(99.7),
                height: None,
            }],
            elements_truncated: false,
        };
        assert_eq!(
            format_geometry(&item, false),
            ["    e [0.2,0.0 99.7x0.0%] :: t"]
        );
    }

    #[test]
    fn the_schema_and_description_are_v3s() {
        let tool = create_with_cache(PathBuf::from("."), PathBuf::from("cache"));
        let schema = tool.schema();
        assert_eq!(schema.name, "document_preview");
        for suffix in [".docx", ".pdf", ".pptx", ".xlsx"] {
            assert!(schema.description.contains(suffix));
        }
        assert!(schema
            .description
            .contains("Formats: .docx, .pdf, .pptx, .xlsx. Needs no office application"));
        assert_eq!(parameters()["required"], serde_json::json!(["path"]));
    }

    fn workspace() -> (tempfile::TempDir, PathBuf, PathBuf) {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().join("workspace");
        std::fs::create_dir_all(&root).unwrap();
        let cache = dir.path().join("cache");
        (dir, root, cache)
    }

    #[tokio::test]
    async fn unsupported_format_names_the_supported_ones() {
        let (_dir, root, cache) = workspace();
        std::fs::write(root.join("notes.txt"), "plain").unwrap();
        let report = document_preview(&root, &cache, "notes.txt", false)
            .await
            .unwrap();
        assert_eq!(
            report,
            "[Cannot preview: notes.txt]\n.txt is not supported for document preview.\nSupported formats: .docx, .pdf, .pptx, .xlsx."
        );
    }

    #[tokio::test]
    async fn missing_and_directory_paths_raise() {
        let (_dir, root, cache) = workspace();
        std::fs::create_dir_all(root.join("folder")).unwrap();
        assert_eq!(
            document_preview(&root, &cache, "absent.pptx", false)
                .await
                .unwrap_err(),
            "Document not found: absent.pptx"
        );
        assert_eq!(
            document_preview(&root, &cache, "folder", false)
                .await
                .unwrap_err(),
            "Path is not a file: folder"
        );
    }

    #[tokio::test]
    async fn path_outside_the_workspace_is_denied() {
        let (dir, root, cache) = workspace();
        let outside = dir.path().join("outside.pptx");
        std::fs::write(&outside, b"x").unwrap();
        let error = document_preview(&root, &cache, outside.to_str().unwrap(), false)
            .await
            .unwrap_err();
        assert!(error.contains("outside the workspace"), "{error}");
        let error = document_preview(&root, &cache, "../outside.pptx", false)
            .await
            .unwrap_err();
        assert!(error.contains("outside the workspace"), "{error}");
        assert!(document_preview(&root, &cache, "~/x.pptx", false)
            .await
            .unwrap_err()
            .starts_with("Tilde paths"));
        // An absolute path inside the workspace is named relative to it.
        std::fs::create_dir_all(root.join("sub")).unwrap();
        let (_, rel) =
            validate_path(&root, root.join("sub").join("a.pptx").to_str().unwrap()).unwrap();
        assert_eq!(rel, "sub/a.pptx");
    }

    #[tokio::test]
    async fn a_failed_render_is_reported_not_raised() {
        let (_dir, root, cache) = workspace();
        std::fs::write(root.join("broken.pptx"), b"not a zip").unwrap();
        let report = document_preview(&root, &cache, "broken.pptx", false)
            .await
            .unwrap();
        assert!(
            report.starts_with("[Preview failed: broken.pptx]\n")
                || report.starts_with("[Cannot preview: broken.pptx]\n"),
            "{report}"
        );
    }

    /// End to end with the v3 test decks (python-pptx), once the native
    /// renderer is in place.
    fn fixture(name: &str) -> Option<Vec<u8>> {
        std::fs::read(
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("tests/fixtures/document_preview")
                .join(name),
        )
        .ok()
    }

    async fn preview_fixture(
        name: &str,
        verbose: bool,
    ) -> Option<(String, tempfile::TempDir, PathBuf)> {
        let (dir, root, cache) = workspace();
        std::fs::write(root.join(name), fixture(name)?).unwrap();
        let report = document_preview(&root, &cache, name, verbose)
            .await
            .unwrap();
        if report.starts_with("[Preview failed:")
            && (report.contains("not ready") || report.contains("not ported"))
        {
            eprintln!("skipped: the native renderer is not in place yet");
            return None;
        }
        Some((report, dir, root))
    }

    #[tokio::test]
    async fn reports_pages_text_and_geometry() {
        let Some((report, _dir, _root)) = preview_fixture("deck.pptx", false).await else {
            return;
        };
        assert!(report.contains("[Document preview: deck.pptx]"), "{report}");
        assert!(report.contains("Pages: 1"), "{report}");
        assert!(report.contains("a title that belongs here"), "{report}");
        assert!(
            report.contains("Every laid-out element sits inside its page box."),
            "{report}"
        );
        // The rendered path is absolute, a file, and outside the workspace.
        let rendered = PathBuf::from(
            report
                .split("engine: ")
                .nth(1)
                .unwrap()
                .split(" (")
                .next()
                .unwrap(),
        );
        assert!(rendered.is_absolute() && rendered.is_file());
        assert!(validate_path(&_root, rendered.to_str().unwrap()).is_err());
    }

    #[tokio::test]
    async fn flags_an_element_outside_the_page() {
        let Some((report, _dir, _root)) = preview_fixture("broken.pptx", false).await else {
            return;
        };
        assert!(
            report.contains("Elements outside the page box:"),
            "{report}"
        );
        assert!(report.contains("OUTSIDE PAGE"), "{report}");
        assert!(report.contains("hangs off the edge"), "{report}");
    }

    #[tokio::test]
    async fn verbose_includes_elements_without_text() {
        let Some((quiet, _a, _ra)) = preview_fixture("mixed.pptx", false).await else {
            return;
        };
        let Some((loud, _b, _rb)) = preview_fixture("mixed.pptx", true).await else {
            return;
        };
        assert!(loud.matches('\n').count() > quiet.matches('\n').count());
        assert!(quiet.contains("has text"));
    }

    #[tokio::test]
    async fn repeated_calls_reuse_the_cache_without_failing() {
        let (_dir, root, cache) = workspace();
        let Some(bytes) = fixture("deck.pptx") else {
            return;
        };
        std::fs::write(root.join("deck.pptx"), bytes).unwrap();
        let first = document_preview(&root, &cache, "deck.pptx", false)
            .await
            .unwrap();
        let second = document_preview(&root, &cache, "deck.pptx", false)
            .await
            .unwrap();
        assert_eq!(first, second);
    }
}
