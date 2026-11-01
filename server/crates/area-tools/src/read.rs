//! `read`: a file's text with line numbers and pagination (`read.py`).
//!
//! Images, Office files and the missing-file errors keep their Python wording.
//! PDF and HTML conversion is not ported (see `server/KNOWN_DIFFERENCES.md`).

use async_trait::async_trait;
use serde_json::{json, Value};

use crate::args::{self, Field, Kind, Val};
use crate::fsutil::{exists, is_file, read_capped, size, suffix_lower};
use crate::pyfmt::{char_prefix, rstrip, splitlines, thousands};
use crate::sandbox::Sandbox;
use crate::{definition, property, run_blocking, Tool, ToolCtx, ToolOutput};

pub(crate) struct ReadTool;

const MAX_READ_BYTES: usize = 5_242_880;
const MAX_CONTEXT_CHARS: usize = 20_000;

const DESCRIPTION: &str = "Read a file from the workspace. Supports text files, images \
(PNG, JPG, GIF, WebP), plus PDF and HTML documents. \
DOCX, XLSX, and PPTX files are view-only in the workspace UI. \
Relative paths use the primary workspace; authorized sibling repositories \
require their displayed absolute path. Text lines are prefixed with \
'NNNNN| ' line numbers — display-only metadata: NEVER include the \
prefix in edit old_string/new_string or write content. Preferred over \
shell cat, sed, head, or tail for reading files.";

const IMAGE_EXTENSIONS: [&str; 10] = [
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico", ".tiff", ".tif",
];
const DOCUMENT_EXTENSIONS: [&str; 3] = [".pdf", ".html", ".htm"];
const OFFICE_EXTENSIONS: [&str; 3] = [".docx", ".xlsx", ".pptx"];

fn fields() -> Vec<Field> {
    vec![
        Field::required("path", Kind::Str),
        Field::optional("offset", Kind::Int, Val::Int(1)),
        Field::optional("limit", Kind::OptInt, Val::None),
    ]
}

/// Prefix each line with `NNNNN| `; display-only metadata for the model.
pub(crate) fn number_lines(text: &str, start: i64) -> String {
    if text.is_empty() {
        return String::new();
    }
    let trailing_newline = text.ends_with('\n');
    let mut lines: Vec<&str> = text.split('\n').collect();
    if trailing_newline {
        lines.pop();
    }
    let numbered: Vec<String> = lines
        .iter()
        .enumerate()
        .map(|(i, line)| {
            let number = start.saturating_add(i64::try_from(i).unwrap_or(i64::MAX));
            format!("{number:05}| {line}")
        })
        .collect();
    let mut out = numbered.join("\n");
    if trailing_newline {
        out.push('\n');
    }
    out
}

/// A context-safe preview for text reads.
fn cap_text_for_context(text: String, rel: &str) -> String {
    let length = text.chars().count();
    if length <= MAX_CONTEXT_CHARS {
        return text;
    }
    let preview = rstrip(char_prefix(&text, MAX_CONTEXT_CHARS));
    format!(
        "{preview}\n\n[read output truncated for LLM context: {rel} is {} characters; \
         shown first {}. Use offset and limit to read a smaller \
         line range, or the grep tool for targeted inspection.]",
        thousands(length),
        thousands(MAX_CONTEXT_CHARS)
    )
}

/// `raw.decode("utf-8")`, else `raw.decode("latin-1")`.
fn decode(raw: Vec<u8>) -> String {
    match String::from_utf8(raw) {
        Ok(text) => text,
        Err(error) => error.into_bytes().into_iter().map(char::from).collect(),
    }
}

/// Python list slicing `items[start:end]` for `start >= 0` and any `end`.
fn py_slice<T>(items: &[T], start: i64, end: i64) -> &[T] {
    let len = i64::try_from(items.len()).unwrap_or(i64::MAX);
    let end = if end < 0 {
        (end + len).max(0)
    } else {
        end.min(len)
    };
    let start = start.min(len);
    if start >= end {
        return &[];
    }
    items
        .get(usize::try_from(start).unwrap_or(0)..usize::try_from(end).unwrap_or(0))
        .unwrap_or_default()
}

pub(crate) fn run(
    sandbox: &Sandbox,
    path: &str,
    offset: i64,
    limit: Option<i64>,
) -> Result<String, String> {
    let resolved = sandbox.validate_path(path)?;
    let rel = sandbox.display_path(&resolved);
    if !exists(&resolved) {
        return Err(format!("File not found: {rel}"));
    }
    if !is_file(&resolved) {
        return Err(format!("Path is a directory: {rel}"));
    }

    let suffix = suffix_lower(&resolved);
    if IMAGE_EXTENSIONS.contains(&suffix.as_str()) {
        return Ok(format!(
            "[Image: {rel}] ({} bytes)\n\
             The file was read successfully but the current model \
             does not support vision — image content cannot be displayed. \
             Switch to a vision-capable model to analyze this image.",
            thousands(usize::try_from(size(&resolved)).unwrap_or(usize::MAX))
        ));
    }
    if DOCUMENT_EXTENSIONS.contains(&suffix.as_str()) {
        return Err(format!(
            "Document conversion (PDF and HTML) is not available in the Rust agent runtime yet: {rel}"
        ));
    }
    if OFFICE_EXTENSIONS.contains(&suffix.as_str()) {
        return Ok(format!(
            "[Office file: {rel}] ({} bytes)\n\
             DOCX, XLSX, and PPTX files are view-only. Open this file in the \
             workspace viewer; agent-side extraction and editing are disabled.",
            thousands(usize::try_from(size(&resolved)).unwrap_or(usize::MAX))
        ));
    }

    let raw = read_capped(&resolved, MAX_READ_BYTES).map_err(|e| e.to_string())?;
    // Normalize newlines so CRLF files never leak `\r` into the numbered lines.
    let text = decode(raw).replace("\r\n", "\n").replace('\r', "\n");

    if offset == 1 && limit.is_none() {
        return Ok(cap_text_for_context(number_lines(&text, 1), &rel));
    }

    let lines = splitlines(&text);
    let total = i64::try_from(lines.len()).unwrap_or(i64::MAX);
    let start = offset.saturating_sub(1).max(0);
    let end = limit.map_or(total, |limit| total.min(start.saturating_add(limit)));
    let slice: String = py_slice(&lines, start, end)
        .iter()
        .map(|line| line.full)
        .collect();

    let header = format!("[{}-{end}/{total}]\n", start + 1);
    let numbered = number_lines(&slice, start + 1);
    Ok(cap_text_for_context(format!("{header}{numbered}"), &rel))
}

#[async_trait]
impl Tool for ReadTool {
    fn name(&self) -> &str {
        "read"
    }

    fn spec(&self) -> Value {
        definition(
            "read",
            DESCRIPTION,
            json!({
                "path": property(None, "File path. Relative paths resolve against the primary workspace. For a file in an authorized non-primary repository, use the absolute path shown by the repository map or a prior search result.", &[("type", json!("string"))]),
                "offset": property(Some(json!(1)), "Line number to start from, 1-indexed (default 1).", &[("type", json!("integer"))]),
                "limit": property(None, "Max lines to return. Omit for all lines from offset.", &[("type", json!("integer"))]),
            }),
            &["path"],
        )
    }

    async fn call(&self, args: Value, ctx: &ToolCtx) -> ToolOutput {
        let parsed = match args::parse("read", &fields(), &args) {
            Ok(parsed) => parsed,
            Err(message) => return ToolOutput::error(&message),
        };
        let root = ctx.workspace_root.clone();
        let path = parsed.str("path");
        let offset = parsed.int("offset");
        let limit = parsed.opt_int("limit");
        run_blocking("read", move || {
            run(&Sandbox::new(&root), &path, offset, limit)
        })
        .await
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

    fn workspace(files: &[(&str, &[u8])]) -> (tempfile::TempDir, Sandbox) {
        let dir = tempfile::tempdir().unwrap();
        for (name, content) in files {
            let path = dir.path().join(name);
            std::fs::create_dir_all(path.parent().unwrap()).unwrap();
            std::fs::write(path, content).unwrap();
        }
        let sandbox = Sandbox::new(dir.path());
        (dir, sandbox)
    }

    fn read(sandbox: &Sandbox, path: &str) -> String {
        run(sandbox, path, 1, None).unwrap()
    }

    #[test]
    fn number_lines_pads_to_five_and_keeps_the_trailing_newline() {
        assert_eq!(number_lines("", 1), "");
        assert_eq!(number_lines("a", 1), "00001| a");
        assert_eq!(number_lines("a\nb\n", 1), "00001| a\n00002| b\n");
        assert_eq!(number_lines("a\n\nb", 7), "00007| a\n00008| \n00009| b");
        assert_eq!(number_lines("x", 123_456), "123456| x");
        assert_eq!(number_lines("\n", 1), "00001| \n");
    }

    #[test]
    fn whole_file_read_numbers_every_line() {
        let (_d, s) = workspace(&[("a.txt", b"one\ntwo\n")]);
        assert_eq!(read(&s, "a.txt"), "00001| one\n00002| two\n");
    }

    #[test]
    fn crlf_and_cr_become_newlines() {
        let (_d, s) = workspace(&[("a.txt", b"one\r\ntwo\rthree")]);
        assert_eq!(read(&s, "a.txt"), "00001| one\n00002| two\n00003| three");
    }

    #[test]
    fn empty_file_reads_as_empty_text() {
        let (_d, s) = workspace(&[("a.txt", b"")]);
        assert_eq!(read(&s, "a.txt"), "");
    }

    #[test]
    fn latin1_fallback_decodes_invalid_utf8() {
        let (_d, s) = workspace(&[("a.txt", &[b'c', b'a', b'f', 0xe9])]);
        assert_eq!(read(&s, "a.txt"), "00001| caf\u{e9}");
    }

    #[test]
    fn bom_is_kept_like_python() {
        let (_d, s) = workspace(&[("a.txt", b"\xef\xbb\xbfx")]);
        assert_eq!(read(&s, "a.txt"), "00001| \u{feff}x");
    }

    #[test]
    fn paginated_read_has_a_range_header() {
        let (_d, s) = workspace(&[("a.txt", b"1\n2\n3\n4\n5\n")]);
        assert_eq!(
            run(&s, "a.txt", 2, Some(2)).unwrap(),
            "[2-3/5]\n00002| 2\n00003| 3\n"
        );
        assert_eq!(
            run(&s, "a.txt", 4, None).unwrap(),
            "[4-5/5]\n00004| 4\n00005| 5\n"
        );
        assert_eq!(run(&s, "a.txt", 1, Some(1)).unwrap(), "[1-1/5]\n00001| 1\n");
        assert_eq!(
            run(&s, "a.txt", 0, Some(2)).unwrap(),
            "[1-2/5]\n00001| 1\n00002| 2\n"
        );
        assert_eq!(
            run(&s, "a.txt", -5, None).unwrap(),
            "[1-5/5]\n00001| 1\n00002| 2\n00003| 3\n00004| 4\n00005| 5\n"
        );
    }

    #[test]
    fn paginating_past_the_end_is_an_empty_slice() {
        let (_d, s) = workspace(&[("a.txt", b"1\n2\n")]);
        assert_eq!(run(&s, "a.txt", 9, Some(3)).unwrap(), "[9-2/2]\n");
        assert_eq!(run(&s, "a.txt", 3, None).unwrap(), "[3-2/2]\n");
    }

    #[test]
    fn negative_limit_slices_from_the_end_like_python() {
        let (_d, s) = workspace(&[("a.txt", b"1\n2\n3\n")]);
        assert_eq!(
            run(&s, "a.txt", 1, Some(-1)).unwrap(),
            "[1--1/3]\n00001| 1\n00002| 2\n"
        );
        assert_eq!(run(&s, "a.txt", 1, Some(0)).unwrap(), "[1-0/3]\n");
        assert_eq!(run(&s, "a.txt", 1, Some(-9)).unwrap(), "[1--9/3]\n");
    }

    #[test]
    fn pagination_splits_on_python_line_separators() {
        let (_d, s) = workspace(&[("a.txt", "a\u{0c}b\u{2028}c\nd".as_bytes())]);
        assert_eq!(
            run(&s, "a.txt", 2, Some(2)).unwrap(),
            "[2-3/4]\n00002| b\u{2028}c\n"
        );
    }

    #[test]
    fn extreme_offsets_and_limits_do_not_overflow() {
        let (_d, s) = workspace(&[("a.txt", b"1\n2\n")]);
        assert_eq!(
            run(&s, "a.txt", i64::MIN, None).unwrap(),
            "[1-2/2]\n00001| 1\n00002| 2\n"
        );
        assert_eq!(
            run(&s, "a.txt", i64::MAX, None).unwrap(),
            "[9223372036854775807-2/2]\n"
        );
        assert_eq!(
            run(&s, "a.txt", 2, Some(i64::MAX)).unwrap(),
            "[2-2/2]\n00002| 2\n"
        );
        assert_eq!(
            run(&s, "a.txt", 1, Some(i64::MIN)).unwrap(),
            "[1--9223372036854775808/2]\n"
        );
    }

    #[test]
    fn py_slice_matches_python_semantics() {
        let items = [1, 2, 3, 4];
        assert_eq!(py_slice(&items, 1, 3), &[2, 3]);
        assert_eq!(py_slice(&items, 0, 99), &[1, 2, 3, 4]);
        assert_eq!(py_slice(&items, 0, -1), &[1, 2, 3]);
        assert_eq!(py_slice(&items, 0, -9), &[] as &[i32]);
        assert_eq!(py_slice(&items, 9, 12), &[] as &[i32]);
        assert_eq!(py_slice(&items, 3, 2), &[] as &[i32]);
    }

    #[test]
    fn long_text_is_cut_with_a_notice() {
        let text = format!("{}\n", "x".repeat(25_000));
        let (_d, s) = workspace(&[("big.txt", text.as_bytes())]);
        let out = read(&s, "big.txt");
        let numbered = number_lines(&text, 1);
        let total = numbered.chars().count();
        assert!(out.starts_with("00001| xxxx"));
        let (preview, notice) = out.split_once("\n\n[read output truncated").unwrap();
        assert_eq!(preview.chars().count(), 20_000);
        assert_eq!(
            notice,
            format!(" for LLM context: big.txt is {} characters; shown first 20,000. Use offset and limit to read a smaller line range, or the grep tool for targeted inspection.]", thousands(total))
        );
    }

    #[test]
    fn exactly_the_cap_is_not_truncated() {
        let line = "y".repeat(20_000 - "00001| ".len());
        let (_d, s) = workspace(&[("edge.txt", line.as_bytes())]);
        let out = read(&s, "edge.txt");
        assert_eq!(out.chars().count(), 20_000);
        assert!(!out.contains("truncated"));
        let (_d2, s2) = workspace(&[("over.txt", format!("{line}z").as_bytes())]);
        assert!(read(&s2, "over.txt")
            .contains("[read output truncated for LLM context: over.txt is 20,001 characters"));
    }

    #[test]
    fn truncation_preview_is_right_stripped() {
        let mut text = "a".repeat(19_990);
        text.push_str(&" ".repeat(30));
        text.push('b');
        let (_d, s) = workspace(&[("t.txt", text.as_bytes())]);
        let out = read(&s, "t.txt");
        let (preview, _) = out.split_once("\n\n[read output truncated").unwrap();
        assert!(preview.ends_with('a'), "{preview:?}");
    }

    #[test]
    fn text_over_five_megabytes_is_cut_at_the_cap() {
        let big = vec![b'a'; MAX_READ_BYTES + 100];
        let (_d, s) = workspace(&[("huge.txt", &big)]);
        let out = read(&s, "huge.txt");
        assert!(out.contains(&format!(
            "huge.txt is {} characters",
            thousands(MAX_READ_BYTES + "00001| ".len())
        )));
    }

    #[test]
    fn multibyte_char_cut_by_the_byte_cap_falls_back_to_latin1() {
        let mut raw = vec![b'a'; MAX_READ_BYTES - 1];
        raw.extend_from_slice("é".as_bytes());
        let (_d, s) = workspace(&[("cut.txt", &raw)]);
        let out = read(&s, "cut.txt");
        assert!(out.contains(&format!(
            "cut.txt is {} characters",
            thousands(MAX_READ_BYTES + "00001| ".len())
        )));
    }

    #[test]
    fn missing_file_and_directory_errors() {
        let (_d, s) = workspace(&[("sub/a.txt", b"x")]);
        assert_eq!(
            run(&s, "nope.txt", 1, None).unwrap_err(),
            "File not found: nope.txt"
        );
        assert_eq!(
            run(&s, "sub", 1, None).unwrap_err(),
            "Path is a directory: sub"
        );
        assert_eq!(
            run(&s, "sub/missing/deeper.txt", 1, None).unwrap_err(),
            "File not found: sub/missing/deeper.txt"
        );
    }

    #[test]
    fn denied_and_outside_paths_surface_the_sandbox_message() {
        let (_d, s) = workspace(&[(".env", b"SECRET=1")]);
        assert!(run(&s, ".env", 1, None)
            .unwrap_err()
            .contains("inside a denied sandbox root: **/.env"));
        assert!(run(&s, "../x", 1, None)
            .unwrap_err()
            .contains("outside the allowed sandbox roots"));
    }

    #[test]
    fn images_get_the_no_vision_notice() {
        let (_d, s) = workspace(&[("pic.PNG", &[0u8; 2048])]);
        assert_eq!(
            read(&s, "pic.PNG"),
            "[Image: pic.PNG] (2,048 bytes)\nThe file was read successfully but the current model does not support vision — image content cannot be displayed. Switch to a vision-capable model to analyze this image."
        );
        for name in [
            "a.jpg", "a.jpeg", "a.gif", "a.webp", "a.bmp", "a.svg", "a.ico", "a.tiff", "a.tif",
        ] {
            let (_d, s) = workspace(&[(name, b"x")]);
            assert!(
                read(&s, name).starts_with(&format!("[Image: {name}] (1 bytes)")),
                "{name}"
            );
        }
    }

    #[test]
    fn office_files_are_view_only() {
        for name in ["a.docx", "a.xlsx", "a.PPTX"] {
            let (_d, s) = workspace(&[(name, &[1u8; 1500])]);
            assert_eq!(
                read(&s, name),
                format!("[Office file: {name}] (1,500 bytes)\nDOCX, XLSX, and PPTX files are view-only. Open this file in the workspace viewer; agent-side extraction and editing are disabled.")
            );
        }
    }

    #[test]
    fn documents_report_the_missing_conversion() {
        for name in ["a.pdf", "a.html", "a.HTM"] {
            let (_d, s) = workspace(&[(name, b"x")]);
            assert_eq!(
                run(&s, name, 1, None).unwrap_err(),
                format!("Document conversion (PDF and HTML) is not available in the Rust agent runtime yet: {name}")
            );
        }
    }

    #[test]
    fn dotfile_named_like_an_extension_is_text() {
        let (_d, s) = workspace(&[(".png", b"hi")]);
        assert_eq!(read(&s, ".png"), "00001| hi");
    }

    #[test]
    fn absolute_path_inside_the_workspace_displays_relative() {
        let (d, s) = workspace(&[("sub/a.txt", b"x")]);
        let abs = s.root().join("sub").join("a.txt");
        assert_eq!(
            run(&s, &abs.display().to_string(), 1, None).unwrap(),
            "00001| x"
        );
        drop(d);
    }

    #[tokio::test]
    async fn the_tool_wraps_errors_and_validates_arguments() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("a.txt"), "hi\n").unwrap();
        let ctx = ToolCtx {
            workspace_root: dir.path().to_path_buf(),
            session_id: "s".into(),
        };
        let tool = ReadTool;
        assert_eq!(tool.name(), "read");
        let ok = tool.call(json!({"path": "a.txt"}), &ctx).await;
        assert_eq!(
            ok,
            ToolOutput {
                content: "00001| hi\n".into(),
                is_error: false
            }
        );
        let sliced = tool
            .call(json!({"path": "a.txt", "offset": "1", "limit": 1}), &ctx)
            .await;
        assert_eq!(sliced.content, "[1-1/1]\n00001| hi\n");
        let missing = tool.call(json!({"path": "zzz"}), &ctx).await;
        assert_eq!(
            missing,
            ToolOutput {
                content: "Error: File not found: zzz".into(),
                is_error: true
            }
        );
        let invalid = tool.call(json!({}), &ctx).await;
        assert!(invalid.is_error);
        assert!(invalid
            .content
            .starts_with("Error: Invalid arguments for tool 'read': 1 validation error"));
    }
}
