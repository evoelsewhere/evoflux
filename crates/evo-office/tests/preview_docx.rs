//! DOCX → HTML parity with v3's python-docx renderer.

use std::io::{Cursor, Write};
use std::path::Path;

use evo_office::preview::{inspection, render_html, security};

const W_NS: &str = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
const R_NS: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
const DOC_REL: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";

fn zip(parts: &[(&str, &[u8])]) -> Vec<u8> {
    let mut writer = zip::ZipWriter::new(Cursor::new(Vec::new()));
    let options = zip::write::SimpleFileOptions::default()
        .compression_method(zip::CompressionMethod::Deflated);
    for (name, data) in parts {
        writer.start_file(*name, options).unwrap();
        writer.write_all(data).unwrap();
    }
    writer.finish().unwrap().into_inner()
}

const CONTENT_TYPES: &str = r#"<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>"#;

const PACKAGE_RELS: &str = r#"<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>"#;

const STYLES: &str = r#"<?xml version="1.0"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:pPr><w:spacing w:after="300" w:line="240" w:lineRule="auto"/></w:pPr><w:rPr><w:color w:val="17365D"/><w:sz w:val="52"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:pPr><w:spacing w:before="480"/></w:pPr><w:rPr><w:b/><w:color w:val="365F91"/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading4"><w:name w:val="heading 4"/></w:style>
<w:style w:type="paragraph" w:styleId="ListNumber"><w:name w:val="List Number"/></w:style>
<w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/></w:style>
<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:rPr><w:rFonts w:ascii="Georgia"/><w:i/></w:rPr></w:style>
<w:style w:type="character" w:styleId="Strong"><w:name w:val="Strong"/></w:style>
</w:styles>"#;

const PNG: &[u8] = b"\x89PNG\r\n\x1a\nfake";

fn document_package(body: &str, extra: &[(&str, &[u8])], extra_rels: &str) -> Vec<u8> {
    let document = format!(
        r#"<?xml version="1.0"?><w:document xmlns:w="{W_NS}" xmlns:r="{R_NS}" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"><w:body>{body}</w:body></w:document>"#
    );
    let rels = format!(
        r#"<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rIdStyles" Type="{DOC_REL}/styles" Target="styles.xml"/>{extra_rels}</Relationships>"#
    );
    let mut parts: Vec<(&str, &[u8])> = vec![
        ("[Content_Types].xml", CONTENT_TYPES.as_bytes()),
        ("_rels/.rels", PACKAGE_RELS.as_bytes()),
        ("word/document.xml", document.as_bytes()),
        ("word/_rels/document.xml.rels", rels.as_bytes()),
        ("word/styles.xml", STYLES.as_bytes()),
    ];
    parts.extend_from_slice(extra);
    zip(&parts)
}

fn render(bytes: &[u8]) -> String {
    let source = Path::new("report.docx");
    security::preflight(source, bytes).expect("preflight");
    render_html(source, bytes, None).expect("render")
}

fn body_of(html: &str) -> &str {
    let start = html.find("<body>").unwrap() + "<body>".len();
    &html[start..html.rfind("</body>").unwrap()]
}

fn paragraph(style: Option<&str>, runs: &str) -> String {
    let ppr = style.map_or(String::new(), |s| {
        format!(r#"<w:pPr><w:pStyle w:val="{s}"/></w:pPr>"#)
    });
    format!("<w:p>{ppr}{runs}</w:p>")
}

fn run(text: &str) -> String {
    format!(r#"<w:r><w:t xml:space="preserve">{text}</w:t></w:r>"#)
}

#[test]
fn page_geometry_headings_and_style_properties_match_v3() {
    let body = [
        paragraph(Some("Title"), &run("The Title")),
        paragraph(Some("Heading1"), &run("Heading one")),
        paragraph(Some("Heading4"), &run("Heading four")),
        paragraph(None, ""),
        r#"<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="720" w:right="1800" w:bottom="1440" w:left="1080"/></w:sectPr>"#.to_string(),
    ]
    .concat();
    let html = render(&document_package(&body, &[], ""));
    let body = body_of(&html);
    assert!(body.starts_with(
        r#"<main class="document" style="--page-width:793.73px;--page-height:1122.53px;--margin-top:48.00px;--margin-right:120.00px;--margin-bottom:96.00px;--margin-left:72.00px"><div class="document-header-template"></div><div class="document-footer-template"></div><div class="document-flow" data-preview-item data-preview-label="Document">"#
    ), "{body}");
    assert!(body.contains(r#"<h1 style="font-size:26.00pt;color:#17365D;margin-bottom:15.00pt;line-height:1.000" data-page-break-before="false" data-qa-label="The Title"><span>The Title</span></h1>"#));
    assert!(body.contains(r#"<h2 style="font-size:14.00pt;font-weight:700;color:#365F91;margin-top:24.00pt" data-page-break-before="false" data-qa-label="Heading one"><span>Heading one</span></h2>"#));
    assert!(body.contains(r#"<p data-page-break-before="false" data-qa-label="Heading four"><span>Heading four</span></p>"#));
    assert!(body.contains(r#"<p data-page-break-before="false" data-qa-label="">&nbsp;</p>"#));
    assert!(html.contains("<title>report.docx</title>"));
    assert!(html.contains("script-src &#x27;none&#x27;"));
}

#[test]
fn runs_carry_their_formatting() {
    let runs = concat!(
        r#"<w:r><w:t xml:space="preserve">Plain </w:t></w:r>"#,
        r#"<w:r><w:rPr><w:b/></w:rPr><w:t>bold</w:t></w:r>"#,
        r#"<w:r><w:rPr><w:b w:val="0"/><w:i w:val="true"/></w:rPr><w:t>italic</w:t></w:r>"#,
        r#"<w:r><w:rPr><w:u w:val="double"/></w:rPr><w:t>under</w:t></w:r>"#,
        r#"<w:r><w:rPr><w:u w:val="none"/></w:rPr><w:t>plain</w:t></w:r>"#,
        r#"<w:r><w:rPr><w:sz w:val="31"/></w:rPr><w:t>big</w:t></w:r>"#,
        r#"<w:r><w:rPr><w:rFonts w:ascii="Times &quot;New&quot; Roman" w:hAnsi="x"/></w:rPr><w:t>font</w:t></w:r>"#,
        r#"<w:r><w:rPr><w:color w:val="ff0011"/></w:rPr><w:t>red</w:t></w:r>"#,
        r#"<w:r><w:rPr><w:color w:val="auto"/></w:rPr><w:t>auto</w:t></w:r>"#,
        r#"<w:r><w:t xml:space="preserve"> &lt;tag&gt; &amp; 'q'</w:t><w:br/><w:t>next</w:t><w:tab/><w:t>Tab</w:t><w:br w:type="column"/><w:noBreakHyphen/></w:r>"#,
        r#"<w:hyperlink r:id="rIdX"><w:r><w:t> link</w:t></w:r></w:hyperlink>"#,
    );
    let body = format!(
        r#"<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:before="120" w:after="60" w:line="360"/><w:ind w:left="720" w:right="200" w:hanging="240"/></w:pPr>{runs}</w:p>"#
    );
    let html = render(&document_package(&body, &[], ""));
    let expected = concat!(
        r#"<p style="text-align:center;margin-top:6.00pt;margin-bottom:3.00pt;line-height:1.500;margin-left:36.00pt;margin-right:10.00pt;text-indent:-12.00pt" data-page-break-before="false" "#,
        "data-qa-label=\"Plain bolditalicunderplainbigfontredauto &lt;tag&gt; &amp; &#x27;q&#x27;\nnext\tTab- link\">",
        r#"<span>Plain </span><span style="font-weight:700">bold</span><span style="font-style:italic">italic</span>"#,
        r#"<span style="text-decoration:underline">under</span><span>plain</span><span style="font-size:15.50pt">big</span>"#,
        r#"<span style="font-family:&quot;Times \&quot;New\&quot; Roman&quot;,Arial,sans-serif">font</span>"#,
        r#"<span style="color:#FF0011">red</span><span>auto</span>"#,
        "<span> &lt;tag&gt; &amp; &#x27;q&#x27;<br>next\tTab-</span></p>",
    );
    assert!(html.contains(expected), "{}", body_of(&html));
}

#[test]
fn lists_number_and_reset_like_v3() {
    let body = [
        paragraph(Some("ListNumber"), &run("one")),
        paragraph(Some("ListNumber"), &run("two")),
        paragraph(Some("ListBullet"), &run("bullet")),
        paragraph(Some("ListNumber"), &run("three")),
        paragraph(None, &run("break")),
        paragraph(Some("ListNumber"), &run("again")),
    ]
    .concat();
    let html = render(&document_package(&body, &[], ""));
    let item = |marker: &str, text: &str| {
        format!(
            r#"<div class="list-item" data-page-break-before="false" data-qa-label="{text}"><span class="list-marker">{marker}</span><span class="list-content"><span>{text}</span></span></div>"#
        )
    };
    for (marker, text) in [
        ("1.", "one"),
        ("2.", "two"),
        ("•", "bullet"),
        ("3.", "three"),
        ("1.", "again"),
    ] {
        assert!(html.contains(&item(marker, text)), "{marker} {text}");
    }
}

#[test]
fn tables_repeat_spanned_and_merged_cells() {
    let cell = |props: &str, text: &str| {
        format!(
            "<w:tc><w:tcPr>{props}</w:tcPr>{}</w:tc>",
            paragraph(None, &run(text))
        )
    };
    let table = format!(
        "<w:tbl><w:tr>{}{}{}</w:tr><w:tr>{}{}</w:tr><w:tr>{}{}{}</w:tr></w:tbl>",
        cell("", "a"),
        cell("", "b"),
        cell("", "c"),
        cell(r#"<w:gridSpan w:val="2"/>"#, "wide"),
        cell(r#"<w:vMerge w:val="restart"/>"#, "tall"),
        cell("", "d"),
        cell("", "e"),
        cell("<w:vMerge/>", "hidden"),
    );
    let html = render(&document_package(&table, &[], ""));
    let p = |t: &str| {
        format!(r#"<p data-page-break-before="false" data-qa-label="{t}"><span>{t}</span></p>"#)
    };
    let expected = format!(
        "<table><tr><th>{a}</th><th>{b}</th><th>{c}</th></tr><tr><td>{wide}</td><td>{wide}</td><td>{tall}</td></tr><tr><td>{d}</td><td>{e}</td><td>{tall}</td></tr></table>",
        a = p("a"),
        b = p("b"),
        c = p("c"),
        wide = p("wide"),
        tall = p("tall"),
        d = p("d"),
        e = p("e"),
    );
    assert!(html.contains(&expected), "{}", body_of(&html));
}

#[test]
fn images_headers_footers_and_page_breaks() {
    let picture = r#"<w:r><w:drawing><wp:inline><wp:extent cx="1143000" cy="571500"/><a:graphic><a:graphicData><a:blip r:embed="rIdImg"/></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>"#;
    let body = [
        paragraph(None, &format!("{}{picture}", run("Picture: "))),
        paragraph(None, &format!(r#"{}<w:r><w:br w:type="page"/></w:r>"#, run("before break"))),
        r#"<w:p><w:pPr><w:pageBreakBefore/></w:pPr><w:r><w:t>next page</w:t></w:r></w:p>"#.to_string(),
        r#"<w:sectPr><w:headerReference w:type="even" r:id="rIdHdrEven"/><w:headerReference w:type="default" r:id="rIdHdr"/><w:footerReference w:type="default" r:id="rIdFtr"/></w:sectPr>"#.to_string(),
    ]
    .concat();
    let header =
        format!(r#"<w:hdr xmlns:w="{W_NS}"><w:p><w:r><w:t>Header text</w:t></w:r></w:p></w:hdr>"#);
    let even = format!(r#"<w:hdr xmlns:w="{W_NS}"><w:p><w:r><w:t>Even</w:t></w:r></w:p></w:hdr>"#);
    let footer = format!(
        r#"<w:ftr xmlns:w="{W_NS}"><w:p><w:r><w:t>Footer &amp; co</w:t></w:r></w:p></w:ftr>"#
    );
    let rels = format!(
        r#"<Relationship Id="rIdImg" Type="{DOC_REL}/image" Target="media/image1.png"/><Relationship Id="rIdHdr" Type="{DOC_REL}/header" Target="header1.xml"/><Relationship Id="rIdHdrEven" Type="{DOC_REL}/header" Target="header2.xml"/><Relationship Id="rIdFtr" Type="{DOC_REL}/footer" Target="footer1.xml"/>"#
    );
    let html = render(&document_package(
        &body,
        &[
            ("word/media/image1.png", PNG),
            ("word/header1.xml", header.as_bytes()),
            ("word/header2.xml", even.as_bytes()),
            ("word/footer1.xml", footer.as_bytes()),
        ],
        &rels,
    ));
    let encoded = base64::Engine::encode(&base64::engine::general_purpose::STANDARD, PNG);
    assert!(html.contains(&format!(
        r#"<p data-page-break-before="false" data-qa-label="Picture: "><span>Picture: </span><span></span><img class="inline-image" style="max-width:100%;height:auto;width:120.00px" src="data:image/png;base64,{encoded}" alt=""></p>"#
    )), "{}", body_of(&html));
    assert!(html.contains(r#"<p data-page-break-before="true" data-qa-label="before break"><span>before break</span><span></span></p>"#));
    assert!(html.contains(
        r#"<p data-page-break-before="true" data-qa-label="next page"><span>next page</span></p>"#
    ));
    assert!(html.contains(r#"<div class="document-header-template"><p data-page-break-before="false" data-qa-label="Header text"><span>Header text</span></p></div>"#));
    assert!(html.contains(r#"<div class="document-footer-template"><p data-page-break-before="false" data-qa-label="Footer &amp; co"><span>Footer &amp; co</span></p></div>"#));
    assert!(!html.contains("Even"));
}

#[test]
fn labels_are_the_first_80_characters_and_feed_inspection() {
    let long = "x".repeat(120);
    let body = [
        paragraph(None, &run(&long)),
        paragraph(
            None,
            &format!("{}<w:r><w:br/></w:r>{}", run("line one"), run("line two")),
        ),
        paragraph(Some("Quote"), &run("Quote \"here\"")),
    ]
    .concat();
    let html = render(&document_package(&body, &[], ""));
    assert!(html.contains(&format!("data-qa-label=\"{}\"", "x".repeat(80))));
    assert!(html.contains(r#"<p style="font-family:&quot;Georgia&quot;,Arial,sans-serif" data-page-break-before="false" data-qa-label="Quote &quot;here&quot;">"#));

    let summary = inspection::summarize(&html);
    assert_eq!(summary.items.len(), 1);
    assert_eq!(summary.items[0].label, "Document");
    let texts: Vec<&str> = summary.items[0]
        .elements
        .iter()
        .map(|e| e.text.as_str())
        .collect();
    // A `<br>` no longer swallows the elements after it (a v3 reader defect).
    assert_eq!(texts, [long.as_str(), "line oneline two", "Quote \"here\""]);
}

#[test]
fn exact_line_spacing_is_a_height() {
    let body = r#"<w:p><w:pPr><w:spacing w:line="360" w:lineRule="exact"/></w:pPr><w:r><w:t>exact</w:t></w:r></w:p>"#;
    let html = render(&document_package(body, &[], ""));
    assert!(html.contains(
        r#"<p style="line-height:18.00pt" data-page-break-before="false" data-qa-label="exact">"#
    ));
}

/// Byte-for-byte comparison with HTML rendered by v3 (`_render_docx`, python-docx
/// 1.2.0) for `*.docx` fixtures in `EVO_DOCX_GOLDEN_DIR` (each beside a
/// `<name>.v3.html`). The only expected difference is exact line spacing, which
/// v3 printed as a unitless EMU count.
#[test]
#[ignore = "needs EVO_DOCX_GOLDEN_DIR with v3-rendered fixtures"]
fn matches_v3_golden_renders() {
    let dir = std::env::var("EVO_DOCX_GOLDEN_DIR").expect("EVO_DOCX_GOLDEN_DIR");
    let line_height = regex::Regex::new(r"line-height:(\d{4,})\.000").unwrap();
    let mut compared = 0;
    for entry in std::fs::read_dir(&dir).unwrap() {
        let path = entry.unwrap().path();
        if path.extension().is_none_or(|e| e != "docx") {
            continue;
        }
        let bytes = std::fs::read(&path).unwrap();
        security::preflight(&path, &bytes).unwrap();
        let ours = render_html(&path, &bytes, None).unwrap();
        let golden = std::fs::read_to_string(path.with_extension("v3.html")).unwrap();
        let golden = line_height.replace_all(&golden, |c: &regex::Captures| {
            let emu: f64 = c[1].parse().unwrap();
            format!("line-height:{:.2}pt", emu / 12_700.0)
        });
        if ours != golden {
            let at = ours
                .bytes()
                .zip(golden.bytes())
                .position(|(a, b)| a != b)
                .unwrap_or(ours.len().min(golden.len()));
            let from = at.saturating_sub(120);
            panic!(
                "{} differs at byte {at}:\n ours: {}\n   v3: {}",
                path.display(),
                &ours[from..(at + 120).min(ours.len())],
                &golden[from..(at + 120).min(golden.len())],
            );
        }
        compared += 1;
    }
    assert!(compared > 0, "no fixtures in {dir}");
}
