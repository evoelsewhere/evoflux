//! Native preview core: package preflight (v3 `test_document_preview_security.py`),
//! the render cache, PDF pages and the inspection reader
//! (v3 `test_document_preview_inspection.py`).

use std::fs;
use std::io::{Cursor, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};

use evo_office::preview::cache::{self, CacheLimits};
use evo_office::preview::inspection::{
    self, ELEMENT_LABEL_ATTRIBUTE, PREVIEW_ITEM_ATTRIBUTE, PREVIEW_LABEL_ATTRIBUTE,
};
use evo_office::preview::security::{self, Limits};
use evo_office::preview::{render_document_preview, DeckPlan, PreviewError};

// ── fixtures ────────────────────────────────────────────────────────────────

fn main_part(suffix: &str) -> &'static str {
    match suffix {
        "docx" => "word/document.xml",
        "xlsx" => "xl/workbook.xml",
        "pptx" => "ppt/presentation.xml",
        _ => unreachable!(),
    }
}

fn zip(parts: &[(&str, &[u8])]) -> Vec<u8> {
    let mut writer = zip::ZipWriter::new(Cursor::new(Vec::new()));
    let options = zip::write::SimpleFileOptions::default()
        .compression_method(zip::CompressionMethod::Deflated);
    for (name, data) in parts {
        if name.ends_with('/') {
            writer
                .add_directory(name.trim_end_matches('/'), options)
                .unwrap();
        } else {
            writer.start_file(*name, options).unwrap();
            writer.write_all(data).unwrap();
        }
    }
    writer.finish().unwrap().into_inner()
}

fn minimal_ooxml(suffix: &str, extra: &[(&str, &[u8])], content_types: &[u8]) -> Vec<u8> {
    let mut parts: Vec<(&str, &[u8])> = vec![
        ("[Content_Types].xml", content_types),
        ("_rels/.rels", b"<Relationships></Relationships>"),
        (main_part(suffix), b"<root></root>"),
    ];
    parts.extend_from_slice(extra);
    zip(&parts)
}

fn docx(extra: &[(&str, &[u8])]) -> Vec<u8> {
    minimal_ooxml("docx", extra, b"<Types></Types>")
}

fn preflight(name: &str, bytes: &[u8]) -> Result<(), PreviewError> {
    security::preflight(Path::new(name), bytes)
}

fn unsupported_message(result: Result<(), PreviewError>) -> String {
    match result {
        Err(PreviewError::Unsupported(message)) => message,
        other => panic!("expected an unsupported error, got {other:?}"),
    }
}

/// Patch the first central directory header of `bytes`.
fn patch_central(bytes: &mut [u8], offset: usize, value: u16) {
    let header = bytes
        .windows(4)
        .position(|w| w == b"PK\x01\x02")
        .expect("central header");
    bytes[header + offset..header + offset + 2].copy_from_slice(&value.to_le_bytes());
}

fn pdf(pages: usize) -> Vec<u8> {
    let kids: Vec<String> = (0..pages).map(|i| format!("{} 0 R", 3 + i)).collect();
    let mut text = format!(
        "%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [{}] /Count {pages} >>\nendobj\n",
        kids.join(" ")
    );
    for i in 0..pages {
        text.push_str(&format!(
            "{} 0 obj\n<< /Type /Page /Parent 2 0 R >>\nendobj\n",
            3 + i
        ));
    }
    text.push_str("trailer\n<< /Root 1 0 R >>\n%%EOF\n");
    text.into_bytes()
}

// ── preflight ───────────────────────────────────────────────────────────────

#[test]
fn ooxml_preflight_accepts_bounded_package() {
    preflight("safe.docx", &docx(&[])).unwrap();
    preflight("safe.xlsx", &minimal_ooxml("xlsx", &[], b"<Types/>")).unwrap();
    preflight("safe.pptx", &minimal_ooxml("pptx", &[], b"<Types/>")).unwrap();
}

#[test]
fn ooxml_preflight_rejects_excessive_entry_count() {
    let bytes = docx(&[("word/extra.xml", b"<extra/>")]);
    let limits = Limits {
        max_entries: 3,
        ..Limits::default()
    };
    let message = unsupported_message(security::preflight_with(
        Path::new("parts.docx"),
        &bytes,
        &limits,
    ));
    assert!(message.contains("too many parts"), "{message}");
}

#[test]
fn ooxml_preflight_rejects_expanded_size() {
    let bytes = docx(&[("word/large.xml", &[b'x'; 64])]);
    let limits = Limits {
        max_expanded_bytes: 32,
        ..Limits::default()
    };
    let message = unsupported_message(security::preflight_with(
        Path::new("expanded.docx"),
        &bytes,
        &limits,
    ));
    assert!(message.contains("expands beyond"), "{message}");
}

#[test]
fn ooxml_preflight_rejects_compression_bomb() {
    let payload = vec![b'x'; 256 * 1024];
    let bytes = docx(&[("word/repeated.xml", &payload)]);
    let limits = Limits {
        max_compression_ratio: 10.0,
        ..Limits::default()
    };
    let message = unsupported_message(security::preflight_with(
        Path::new("compressed.docx"),
        &bytes,
        &limits,
    ));
    assert!(message.contains("unsafe compression ratio"), "{message}");
    // The default ratio (200) still rejects a highly repetitive part.
    let bomb = vec![b'x'; 8 * 1024 * 1024];
    let message = unsupported_message(preflight("bomb.docx", &docx(&[("word/bomb.xml", &bomb)])));
    assert!(message.contains("unsafe compression ratio"), "{message}");
}

#[test]
fn ooxml_preflight_rejects_unsafe_or_active_parts() {
    for (part, message) in [
        ("../escape.xml", "unsafe part name"),
        ("word/./x.xml", "unsafe part name"),
        ("word/vbaProject.bin", "macros or active controls"),
        ("xl/activeX/activeX1.xml", "macros or active controls"),
        ("customUI/customUI14.xml", "macros or active controls"),
        ("word/embeddings/payload.exe", "executable embedded content"),
        ("word/embeddings/Script.VBS", "executable embedded content"),
    ] {
        let bytes = docx(&[(part, b"payload")]);
        let got = unsupported_message(preflight("unsafe.docx", &bytes));
        assert!(got.contains(message), "{part}: {got}");
    }
    preflight(
        "ok.docx",
        &docx(&[("word/embeddings/oleObject1.bin", b"payload")]),
    )
    .unwrap();
}

#[test]
fn ooxml_preflight_rejects_duplicate_names_and_backslashes() {
    let bytes = docx(&[("WORD/DOCUMENT.XML", b"<x/>")]);
    assert!(unsupported_message(preflight("dup.docx", &bytes)).contains("duplicate part names"));
    let bytes = docx(&[("word\\x.xml", b"<x/>")]);
    assert!(unsupported_message(preflight("slash.docx", &bytes)).contains("unsafe part name"));
}

#[test]
fn ooxml_preflight_rejects_active_content_type() {
    let bytes = minimal_ooxml(
        "docx",
        &[],
        br#"<Types><Default ContentType="application/vnd.ms-office.vbaProject"/></Types>"#,
    );
    let message = unsupported_message(preflight("macro.docx", &bytes));
    assert!(
        message.contains("macros, OLE objects, or active controls"),
        "{message}"
    );
    let bytes = minimal_ooxml(
        "pptx",
        &[],
        br#"<Types><Override ContentType="application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml"/></Types>"#,
    );
    assert!(unsupported_message(preflight("macro.pptx", &bytes)).contains("macros, OLE objects"));
}

#[test]
fn ooxml_preflight_rejects_encrypted_member() {
    let mut bytes = docx(&[]);
    let header = bytes.windows(4).position(|w| w == b"PK\x01\x02").unwrap();
    let flags = u16::from_le_bytes([bytes[header + 8], bytes[header + 9]]);
    patch_central(&mut bytes, 8, flags | 0x1);
    let message = unsupported_message(preflight("encrypted.docx", &bytes));
    assert!(message.contains("Encrypted OpenXML"), "{message}");
}

#[test]
fn ooxml_preflight_rejects_other_compression_methods_and_symlinks() {
    let mut bytes = docx(&[]);
    patch_central(&mut bytes, 10, 12);
    let message = unsupported_message(preflight("bzip.docx", &bytes));
    assert_eq!(
        message,
        "This OpenXML package uses an unsupported compression method."
    );

    let mut writer = zip::ZipWriter::new(Cursor::new(Vec::new()));
    let options = zip::write::SimpleFileOptions::default();
    for (name, data) in [
        ("[Content_Types].xml", &b"<Types/>"[..]),
        ("_rels/.rels", b"<Relationships/>"),
        ("word/document.xml", b"<root/>"),
    ] {
        writer.start_file(name, options).unwrap();
        writer.write_all(data).unwrap();
    }
    writer
        .add_symlink("word/link.xml", "/etc/passwd", options)
        .unwrap();
    let bytes = writer.finish().unwrap().into_inner();
    let message = unsupported_message(preflight("link.docx", &bytes));
    assert!(message.contains("unsafe symbolic link"), "{message}");
}

#[test]
fn ooxml_preflight_rejects_invalid_container() {
    let message = unsupported_message(preflight("broken.pptx", b"not a zip package"));
    assert_eq!(
        message,
        "This file has a .pptx name but is not a PowerPoint presentation."
    );
    let message = unsupported_message(preflight("empty.xlsx", b""));
    assert_eq!(
        message,
        "This file has a .xlsx name but is not a Excel workbook."
    );
}

#[test]
fn ooxml_preflight_still_reports_truncated_packages_as_damaged() {
    let complete = docx(&[]);
    let truncated = &complete[..complete.len() - 40];
    match preflight("truncated.docx", truncated) {
        Err(PreviewError::Failed(message)) => assert_eq!(
            message,
            "Could not render this document: invalid or damaged OpenXML package."
        ),
        other => panic!("{other:?}"),
    }
}

#[test]
fn ooxml_preflight_names_a_plain_zip_with_an_office_extension() {
    let bytes = zip(&[
        ("jira-docs/", b""),
        ("jira-docs/00-overview.md", b"# Overview"),
        ("jira-docs/01-issue-crud.md", b"# CRUD"),
    ]);
    let message = unsupported_message(preflight("jira-docs.docx", &bytes));
    assert_eq!(
        message,
        "This file is a ZIP archive with a .docx name, not a Word document. It contains 2 files \
(for example 00-overview.md, 01-issue-crud.md)."
    );
    let single = zip(&[("notes.txt", b"x")]);
    assert!(unsupported_message(preflight("a.xlsx", &single))
        .ends_with("It contains 1 file (for example notes.txt)."));
}

#[test]
fn ooxml_preflight_names_the_real_format_of_a_misnamed_package() {
    let deck = minimal_ooxml("pptx", &[], b"<Types></Types>");
    let message = unsupported_message(preflight("report.docx", &deck));
    assert_eq!(
        message,
        "This file is a PowerPoint presentation saved with a .docx name. Rename it to .pptx to preview it."
    );
}

#[test]
fn ooxml_preflight_explains_legacy_or_password_protected_files() {
    let mut bytes = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1".to_vec();
    bytes.extend_from_slice(&[0; 512]);
    let message = unsupported_message(preflight("budget.xlsx", &bytes));
    assert_eq!(
        message,
        "This .xlsx file is password-protected or was saved in the legacy Office 97–2003 format. \
Open it in Office and save it without a password as .xlsx to preview it here."
    );
}

#[test]
fn ooxml_preflight_rejects_multi_volume_and_zip64_trailers() {
    let mut bytes = docx(&[]);
    let eocd = bytes.windows(4).rposition(|w| w == b"PK\x05\x06").unwrap();
    bytes[eocd + 4] = 1;
    assert!(unsupported_message(preflight("split.docx", &bytes)).contains("Multi-volume"));
    let mut bytes = docx(&[]);
    let eocd = bytes.windows(4).rposition(|w| w == b"PK\x05\x06").unwrap();
    bytes[eocd + 8..eocd + 12].copy_from_slice(&[0xFF; 4]);
    assert!(unsupported_message(preflight("big.docx", &bytes)).contains("ZIP64"));
}

#[test]
fn pdf_preflight_checks_the_header_and_other_types_pass() {
    preflight("ok.pdf", &pdf(1)).unwrap();
    let message = unsupported_message(preflight("fake.pdf", b"PK\x03\x04 not a pdf"));
    assert_eq!(
        message,
        "This file has a .pdf name but is not a PDF document."
    );
    preflight("notes.txt", b"anything").unwrap();
}

// ── cache ───────────────────────────────────────────────────────────────────

#[test]
fn renders_a_pdf_into_the_cache_and_reuses_it() {
    let tmp = tempfile::tempdir().unwrap();
    let cache_dir = tmp.path().join("cache").join("office").join("previews");
    let source = tmp.path().join("report.pdf");
    fs::write(&source, pdf(3)).unwrap();

    let output = render_document_preview(&cache_dir, &source, None).unwrap();
    assert_eq!(output.parent().unwrap(), cache_dir);
    let html = fs::read_to_string(&output).unwrap();
    assert!(html.contains("<main data-preview-renderer=\"pdf\">"));
    let summary = inspection::summarize(&html);
    let labels: Vec<&str> = summary.items.iter().map(|i| i.label.as_str()).collect();
    assert_eq!(labels, ["Page 1", "Page 2", "Page 3"]);

    assert_eq!(
        render_document_preview(&cache_dir, &source, None).unwrap(),
        output
    );
    fs::write(&source, pdf(2)).unwrap();
    let changed = render_document_preview(&cache_dir, &source, None).unwrap();
    assert_ne!(changed, output);
}

#[test]
fn refuses_unsupported_types_and_oversized_sources() {
    let tmp = tempfile::tempdir().unwrap();
    let cache_dir = tmp.path().join("previews");
    let text = tmp.path().join("notes.txt");
    fs::write(&text, "x").unwrap();
    let error = render_document_preview(&cache_dir, &text, None).unwrap_err();
    assert_eq!(
        error.to_string(),
        ".txt is not supported for document preview."
    );
    let bare = tmp.path().join("README");
    fs::write(&bare, "x").unwrap();
    let error = render_document_preview(&cache_dir, &bare, None).unwrap_err();
    assert_eq!(
        error.to_string(),
        "This file type is not supported for document preview."
    );

    let big = tmp.path().join("big.pdf");
    fs::File::create(&big)
        .unwrap()
        .set_len(evo_office::preview::MAX_SOURCE_BYTES + 1)
        .unwrap();
    let error = render_document_preview(&cache_dir, &big, None).unwrap_err();
    assert!(matches!(error, PreviewError::Unsupported(_)));
    assert_eq!(error.to_string(), "Document preview is limited to 100 MB.");
}

#[test]
fn preflight_runs_before_anything_is_cached() {
    let tmp = tempfile::tempdir().unwrap();
    let cache_dir = tmp.path().join("previews");
    let source = tmp.path().join("deck.pptx");
    fs::write(&source, b"not a zip").unwrap();
    let error = render_document_preview(&cache_dir, &source, None).unwrap_err();
    assert!(error
        .to_string()
        .contains("is not a PowerPoint presentation"));
    assert!(!cache_dir.exists());
}

fn workbook_with_plan(plan: &str) -> Vec<u8> {
    let custom = format!(
        r#"<?xml version="1.0"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="2" name="evo.deck"><vt:lpwstr>{}</vt:lpwstr></property></Properties>"#,
        plan.replace('"', "&quot;")
    );
    minimal_ooxml(
        "xlsx",
        &[("docProps/custom.xml", custom.as_bytes())],
        b"<Types/>",
    )
}

#[test]
fn live_plans_render_only_for_the_building_chat_under_their_own_key() {
    let tmp = tempfile::tempdir().unwrap();
    let cache_dir = tmp.path().join("previews");
    let source = tmp.path().join("book.xlsx");
    fs::write(
        &source,
        workbook_with_plan(r#"{"v":1,"total":3,"added":1,"state":"building","session":"chat-1"}"#),
    )
    .unwrap();
    let renders = AtomicUsize::new(0);
    let render = |plan_expected: bool| {
        let renders = &renders;
        move |_: &Path, _: &[u8], plan: Option<&DeckPlan>| {
            renders.fetch_add(1, Ordering::SeqCst);
            assert_eq!(plan.is_some(), plan_expected);
            Ok(format!("<p>live={}</p>", plan.is_some()))
        }
    };
    let limits = CacheLimits::default();
    let live =
        cache::render_cached_with(&cache_dir, &source, Some("chat-1"), &limits, render(true))
            .unwrap();
    let other =
        cache::render_cached_with(&cache_dir, &source, Some("chat-2"), &limits, render(false))
            .unwrap();
    let idle =
        cache::render_cached_with(&cache_dir, &source, None, &limits, render(false)).unwrap();
    assert_ne!(live, other);
    assert_eq!(other, idle);
    assert_eq!(renders.load(Ordering::SeqCst), 2);
    assert_eq!(fs::read_to_string(&live).unwrap(), "<p>live=true</p>");
}

#[test]
fn marking_a_cached_preview_survives_a_second_use_and_ignores_others() {
    let tmp = tempfile::tempdir().unwrap();
    let cached = tmp.path().join("cached.html");
    fs::write(&cached, "<html></html>").unwrap();
    cache::mark_cached_preview_used(&cached);
    cache::mark_cached_preview_used(&cached);
    assert!(cached.exists());

    let directory = tmp.path().join("a-directory");
    fs::create_dir(&directory).unwrap();
    cache::mark_cached_preview_used(&directory);
    assert!(directory.is_dir());

    cache::mark_cached_preview_used(&tmp.path().join("absent.html"));
}

#[test]
fn a_directory_at_the_cache_entry_is_refused() {
    let tmp = tempfile::tempdir().unwrap();
    let cache_dir = tmp.path().join("previews");
    let source = tmp.path().join("a.pdf");
    fs::write(&source, pdf(1)).unwrap();
    let output: PathBuf = render_document_preview(&cache_dir, &source, None).unwrap();
    fs::remove_file(&output).unwrap();
    fs::create_dir(&output).unwrap();
    let error = render_document_preview(&cache_dir, &source, None).unwrap_err();
    assert_eq!(
        error.to_string(),
        "The document preview cache entry is unsafe."
    );
}

// ── inspection ──────────────────────────────────────────────────────────────

fn page(body: &str) -> String {
    format!("<html><body>{body}</body></html>")
}

#[test]
fn reads_items_elements_text_and_geometry() {
    let html = page(&format!(
        "<article {PREVIEW_ITEM_ATTRIBUTE} {PREVIEW_LABEL_ATTRIBUTE}=\"Slide 1 — Intro\">\
<div {ELEMENT_LABEL_ATTRIBUTE}=\"Title\" style=\"left:6.0%;top:16.0%;width:45.0%;height:10.0%\">\
<span>Hello   world</span></div></article>"
    ));
    let summary = inspection::summarize(&html);
    let labels: Vec<&str> = summary.items.iter().map(|i| i.label.as_str()).collect();
    assert_eq!(labels, ["Slide 1 — Intro"]);
    let element = &summary.items[0].elements[0];
    assert_eq!(element.label, "Title");
    assert_eq!(element.text, "Hello world");
    assert_eq!(
        (element.left, element.top, element.width, element.height),
        (Some(6.0), Some(16.0), Some(45.0), Some(10.0))
    );
    assert!(!element.out_of_bounds());
}

#[test]
fn flags_elements_outside_the_page_box() {
    for style in [
        "left:110.0%;top:5.0%;width:20.0%;height:10.0%",
        "left:5.0%;top:95.0%;width:20.0%;height:20.0%",
        "left:-20.0%;top:5.0%;width:30.0%;height:10.0%",
        "top:-1%",
    ] {
        let html = page(&format!(
            "<article {PREVIEW_ITEM_ATTRIBUTE} {PREVIEW_LABEL_ATTRIBUTE}=\"Slide 1\">\
<div {ELEMENT_LABEL_ATTRIBUTE}=\"Stray\" style=\"{style}\">text</div></article>"
        ));
        let summary = inspection::summarize(&html);
        let stray: Vec<&str> = summary.items[0]
            .out_of_bounds()
            .iter()
            .map(|e| e.label.as_str())
            .collect();
        assert_eq!(stray, ["Stray"], "{style}");
    }
}

#[test]
fn elements_without_geometry_are_never_flagged() {
    let html = page(&format!(
        "<article {PREVIEW_ITEM_ATTRIBUTE} {PREVIEW_LABEL_ATTRIBUTE}=\"Sheet1\">\
<td {ELEMENT_LABEL_ATTRIBUTE}=\"A1\">42</td></article>"
    ));
    let summary = inspection::summarize(&html);
    assert!(summary.items[0].out_of_bounds().is_empty());
    assert_eq!(summary.items[0].elements[0].text, "42");
}

#[test]
fn budgets_bound_items_elements_and_text() {
    let items: String = (0..4)
        .map(|index| {
            format!(
                "<article {PREVIEW_ITEM_ATTRIBUTE} {PREVIEW_LABEL_ATTRIBUTE}=\"Slide {index}\">\
<div {ELEMENT_LABEL_ATTRIBUTE}=\"A\">{}</div><div {ELEMENT_LABEL_ATTRIBUTE}=\"B\">second</div></article>",
                "x".repeat(50)
            )
        })
        .collect();
    let summary = inspection::summarize_with(&page(&items), 2, 1, 10);
    assert_eq!(summary.items.len(), 2);
    assert!(summary.items_truncated);
    assert!(summary.items[0].elements_truncated);
    assert_eq!(summary.items[0].elements.len(), 1);
    let text = &summary.items[0].elements[0].text;
    assert!(text.ends_with('…'));
    assert!(text.chars().count() <= 11);
}

#[test]
fn only_the_outermost_label_counts_and_labels_fall_back() {
    let html = page(&format!(
        "<section {PREVIEW_ITEM_ATTRIBUTE}><div {ELEMENT_LABEL_ATTRIBUTE}=\" Outer \" style=\"left:1%\">\
a<b {ELEMENT_LABEL_ATTRIBUTE}=\"Inner\">b</b> &amp; c<img src=\"x\"><br>d</div>\
<p {ELEMENT_LABEL_ATTRIBUTE}=\"Next\">e<!-- comment --></p></section>\
<section {PREVIEW_ITEM_ATTRIBUTE} {PREVIEW_LABEL_ATTRIBUTE}=\"  \"></section>"
    ));
    let summary = inspection::summarize(&html);
    assert_eq!(summary.items[0].label, "Item 1");
    assert_eq!(summary.items[1].label, "Item 2");
    let elements = &summary.items[0].elements;
    assert_eq!(elements.len(), 2);
    assert_eq!(
        (elements[0].label.as_str(), elements[0].text.as_str()),
        ("Outer", "ab & cd")
    );
    assert_eq!(elements[0].left, Some(1.0));
    assert_eq!(elements[0].width, None);
    assert_eq!(summary.items[0].text(), "ab & cd\ne");
}

#[test]
fn a_pdf_render_reads_back_as_pages() {
    let html = evo_office::preview::render_html(Path::new("x.pdf"), &pdf(2), None).unwrap();
    let summary = inspection::summarize(&html);
    assert_eq!(summary.items.len(), 2);
    assert!(summary.items.iter().all(|i| i.elements.is_empty()));
}
