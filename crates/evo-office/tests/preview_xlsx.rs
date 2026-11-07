//! XLSX native preview: the v3 markup contract (`tests/services/test_office_preview_service.py`
//! and `test_live_workbook_preview.py` at v3.1.1), on workbooks built in memory.

use std::io::{Cursor, Write};

use evo_office::preview::live::{read_plan_bytes, DeckPlan};
use evo_office::preview::xlsx::{render, visible_sheet_names};

const MAIN: &str = "http://schemas.openxmlformats.org/spreadsheetml/2006/main";
const REL: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
const PKG_REL: &str = "http://schemas.openxmlformats.org/package/2006/relationships";

/// openpyxl's default stylesheet plus extra cell formats / dxfs.
fn styles(
    extra_fonts: &str,
    extra_fills: &str,
    extra_xfs: &str,
    num_fmts: &str,
    dxfs: &str,
) -> String {
    let font_count = 1 + extra_fonts.matches("<font>").count();
    let fill_count = 2 + extra_fills.matches("<fill>").count();
    let xf_count = 1 + extra_xfs.matches("<xf ").count();
    format!(
        r#"<styleSheet xmlns="{MAIN}">{num_fmts}<fonts count="{font_count}"><font><name val="Calibri"/><family val="2"/><color theme="1"/><sz val="11"/><scheme val="minor"/></font>{extra_fonts}</fonts><fills count="{fill_count}"><fill><patternFill/></fill><fill><patternFill patternType="gray125"/></fill>{extra_fills}</fills><borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border><left style="dashed"><color rgb="FF00AA00"/></left><right style="double"/><top style="thin"><color rgb="FFFF0000"/></top><bottom style="medium"><color theme="1"/></bottom></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="{xf_count}"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>{extra_xfs}</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>{dxfs}</styleSheet>"#
    )
}

struct Sheet<'a> {
    name: &'a str,
    state: Option<&'a str>,
    xml: String,
    rels: Option<String>,
}

fn sheet<'a>(name: &'a str, body: &str) -> Sheet<'a> {
    Sheet {
        name,
        state: None,
        xml: format!(r#"<worksheet xmlns="{MAIN}" xmlns:r="{REL}">{body}</worksheet>"#),
        rels: None,
    }
}

fn workbook(
    sheets: &[Sheet],
    styles_xml: &str,
    shared: &[&str],
    extra: &[(&str, &str)],
) -> Vec<u8> {
    let mut parts: Vec<(String, String)> = Vec::new();
    let mut overrides = String::new();
    let mut sheet_entries = String::new();
    let mut rels = String::new();
    for (index, s) in sheets.iter().enumerate() {
        let n = index + 1;
        let state = s
            .state
            .map(|st| format!(r#" state="{st}""#))
            .unwrap_or_default();
        sheet_entries.push_str(&format!(
            r#"<sheet name="{}" sheetId="{n}"{state} r:id="rId{n}"/>"#,
            s.name
        ));
        let (kind, folder) = if s.xml.starts_with("<chartsheet") {
            ("chartsheet", "chartsheets")
        } else {
            ("worksheet", "worksheets")
        };
        rels.push_str(&format!(
            r#"<Relationship Id="rId{n}" Type="{REL}/{kind}" Target="{folder}/sheet{n}.xml"/>"#
        ));
        overrides.push_str(&format!(
            r#"<Override PartName="/xl/{folder}/sheet{n}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.{kind}+xml"/>"#
        ));
        parts.push((format!("xl/{folder}/sheet{n}.xml"), s.xml.clone()));
        if let Some(r) = &s.rels {
            parts.push((
                format!("xl/{folder}/_rels/sheet{n}.xml.rels"),
                format!(r#"<Relationships xmlns="{PKG_REL}">{r}</Relationships>"#),
            ));
        }
    }
    let n = sheets.len();
    rels.push_str(&format!(
        r#"<Relationship Id="rId{}" Type="{REL}/styles" Target="styles.xml"/>"#,
        n + 1
    ));
    if !shared.is_empty() {
        rels.push_str(&format!(
            r#"<Relationship Id="rId{}" Type="{REL}/sharedStrings" Target="sharedStrings.xml"/>"#,
            n + 2
        ));
        overrides.push_str(r#"<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>"#);
        let items: String = shared
            .iter()
            .map(|s| format!("<si><t>{s}</t></si>"))
            .collect();
        parts.push((
            "xl/sharedStrings.xml".into(),
            format!(r#"<sst xmlns="{MAIN}">{items}</sst>"#),
        ));
    }
    parts.push((
        "[Content_Types].xml".into(),
        format!(
            r#"<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>{overrides}</Types>"#
        ),
    ));
    parts.push((
        "_rels/.rels".into(),
        format!(r#"<Relationships xmlns="{PKG_REL}"><Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>"#),
    ));
    parts.push((
        "xl/workbook.xml".into(),
        format!(r#"<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>{sheet_entries}</sheets></workbook>"#),
    ));
    parts.push((
        "xl/_rels/workbook.xml.rels".into(),
        format!(r#"<Relationships xmlns="{PKG_REL}">{rels}</Relationships>"#),
    ));
    parts.push(("xl/styles.xml".into(), styles_xml.to_string()));
    for (name, body) in extra {
        parts.push((name.to_string(), body.to_string()));
    }
    zip_parts(
        &parts
            .iter()
            .map(|(n, b)| (n.as_str(), b.as_bytes()))
            .collect::<Vec<_>>(),
    )
}

fn zip_parts(parts: &[(&str, &[u8])]) -> Vec<u8> {
    let mut writer = zip::ZipWriter::new(Cursor::new(Vec::new()));
    for (name, body) in parts {
        writer
            .start_file(*name, zip::write::SimpleFileOptions::default())
            .unwrap();
        writer.write_all(body).unwrap();
    }
    writer.finish().unwrap().into_inner()
}

fn default_styles() -> String {
    styles("", "", "", "", "")
}

/// The `<td>` of `cell` in the first section (or the given section index).
fn td(html: &str, section: usize, cell: &str) -> String {
    let start = html
        .match_indices("<section")
        .nth(section)
        .expect("section")
        .0;
    let end = html[start..]
        .find("</section>")
        .map_or(html.len(), |e| start + e);
    let body = &html[start..end];
    let at = body
        .find(&format!("data-cell=\"{cell}\""))
        .unwrap_or_else(|| panic!("no cell {cell}"));
    let open = body[..at].rfind("<td").unwrap();
    let close = body[at..].find("</td>").unwrap() + at + 5;
    body[open..close].to_string()
}

fn labels(html: &str) -> Vec<String> {
    let re = regex::Regex::new(r#"<section[^>]*data-preview-label="([^"]+)""#).unwrap();
    re.captures_iter(html).map(|c| c[1].to_string()).collect()
}

fn statuses(html: &str) -> Vec<String> {
    let re = regex::Regex::new(r#"<section[^>]*data-slide-status="(\w+)""#).unwrap();
    re.captures_iter(html).map(|c| c[1].to_string()).collect()
}

#[test]
fn renders_the_grid_contract() {
    let book = workbook(
        &[sheet(
            "Summary",
            r#"<sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="n"><v>120</v></c></row><row r="2"><c r="B2"><f>B1*2</f><v></v></c></row></sheetData>"#,
        )],
        &default_styles(),
        &["Revenue"],
        &[],
    );
    let html = render(&book, "workbook.xlsx", None).unwrap();
    assert!(html.contains("<title>workbook.xlsx</title>"));
    assert!(html.contains("Summary") && html.contains("Revenue"));
    assert!(html.contains(r#"data-formula="=B1*2""#));
    assert!(html.contains(">240</td>"));
    assert!(!html.contains("==B1*2"));
    assert!(html.contains(r#"data-cell="A1""#));
    assert!(html.contains(r#"class="column-header" data-column="A""#));
    assert!(html.contains(r#"class="column-header" data-column="T""#));
    assert!(!html.contains(r#"data-column="U""#));
    assert!(html.contains(r#"class="row-number" data-row="1""#));
    assert!(html.contains(r#"class="row-number" data-row="40""#));
    assert!(!html.contains(r#"data-row="41""#));
    assert!(!html.contains("<h2>Summary</h2>"));
    assert!(html.contains("html,body{width:100%;height:100%;overflow:hidden}"));
    // Every default cell carries the workbook font (theme colours stay unset).
    assert!(td(&html, 0, "A1")
        .contains(r#"style="font-family:&quot;Calibri&quot;,Arial,sans-serif;font-size:11.00pt""#));
    assert!(html.contains(r#"data-preview-fit-width="162.02" data-preview-fit-height="84.00""#));
    assert!(html.contains(r#"style="width:1224.20px;height:1072.00px""#));
}

#[test]
fn uses_cached_formula_results_and_visible_fallbacks() {
    let book = workbook(
        &[sheet(
            "Sheet",
            r#"<sheetData><row r="1"><c r="A1"><v>1</v></c><c r="C1"><v>42</v></c><c r="D1"><f>XLOOKUP(1,A1:A2,C1:C2)</f><v>42</v></c></row><row r="2"><c r="A2"><v>2</v></c><c r="C2"><v>84</v></c><c r="D2"><f>UNIQUE(A1:A2)</f><v></v></c></row></sheetData>"#,
        )],
        &default_styles(),
        &[],
        &[],
    );
    let html = render(&book, "formula-cache.xlsx", None).unwrap();
    assert!(html.contains(r#"data-formula="=XLOOKUP(1,A1:A2,C1:C2)""#));
    assert!(td(&html, 0, "D1").contains(r#"data-display-value="42""#));
    assert!(td(&html, 0, "D1").ends_with(">42</td>"));
    assert!(td(&html, 0, "D2").contains(r#"data-formula="=UNIQUE(A1:A2)""#));
    assert!(td(&html, 0, "D2").contains(r#"data-display-value="=UNIQUE(A1:A2)""#));
}

#[test]
fn applies_views_conditional_formatting_links_and_comments() {
    let dxfs = r#"<dxfs count="1"><dxf><fill><patternFill patternType="solid"><bgColor rgb="FFFFC7CE"/></patternFill></fill></dxf></dxfs>"#;
    let mut rows = String::new();
    for (r, v) in [(1, 10), (2, 50), (3, 90)] {
        rows.push_str(&format!(r#"<row r="{r}"><c r="A{r}"><v>{v}</v></c><c r="B{r}"><v>{v}</v></c><c r="C{r}"><v>{v}</v></c>"#));
        match r {
            1 => rows.push_str(r#"<c r="D1" t="inlineStr"><is><t>Docs</t></is></c>"#),
            2 => rows.push_str(r#"<c r="D2" t="inlineStr"><is><t>Reviewed</t></is></c>"#),
            _ => {}
        }
        rows.push_str("</row>");
    }
    rows.push_str(
        r#"<row r="4" hidden="1"><c r="A4" t="inlineStr"><is><t>hidden row</t></is></c></row>"#,
    );
    let body = format!(
        r#"<sheetViews><sheetView showGridLines="0" workbookViewId="0"><pane xSplit="1" ySplit="1" topLeftCell="B2" activePane="bottomRight" state="frozen"/></sheetView></sheetViews><sheetData>{rows}</sheetData><conditionalFormatting sqref="A1:A3"><cfRule type="cellIs" dxfId="0" priority="1" operator="greaterThan"><formula>40</formula></cfRule></conditionalFormatting><conditionalFormatting sqref="B1:B3"><cfRule type="colorScale" priority="2"><colorScale><cfvo type="min"/><cfvo type="max"/><color rgb="FFFFFFFF"/><color rgb="FF63BE7B"/></colorScale></cfRule></conditionalFormatting><conditionalFormatting sqref="C1:C3"><cfRule type="dataBar" priority="3"><dataBar><cfvo type="min"/><cfvo type="max"/><color rgb="FF638EC6"/></dataBar></cfRule></conditionalFormatting><hyperlinks><hyperlink ref="D1" r:id="rId1"/></hyperlinks><legacyDrawing r:id="rId3"/>"#
    );
    let mut scores = sheet("Scores", &body);
    scores.rels = Some(format!(
        r#"<Relationship Id="rId1" Type="{REL}/hyperlink" Target="https://example.com/spec" TargetMode="External"/><Relationship Id="rId2" Type="{REL}/comments" Target="../comments1.xml"/>"#
    ));
    let mut lookup = sheet("Lookup", "<sheetData/>");
    lookup.state = Some("hidden");
    let mut gone = sheet("Gone", "<sheetData/>");
    gone.state = Some("veryHidden");
    let comments = format!(
        r#"<comments xmlns="{MAIN}"><authors><author>Mai</author></authors><commentList><comment ref="D2" authorId="0"><text><t>Check totals</t></text></comment></commentList></comments>"#
    );
    let book = workbook(
        &[scores, lookup, gone],
        &styles("", "", "", "", dxfs),
        &[],
        &[("xl/comments1.xml", &comments)],
    );
    let html = render(&book, "features.xlsx", None).unwrap();

    assert!(td(&html, 0, "A2").contains("background:#ffc7ce"));
    assert!(!td(&html, 0, "A1").contains("#ffc7ce"));
    assert!(td(&html, 0, "B1").contains("background:#ffffff"));
    assert!(td(&html, 0, "B3").contains("background:#63be7b"));
    assert!(td(&html, 0, "C3").contains("linear-gradient"));
    let hidden_row = html.find(r#"data-cell="A4""#).unwrap();
    let row_open = html[..hidden_row].rfind("<tr ").unwrap();
    assert!(html[row_open..hidden_row].contains("visibility:collapse"));
    assert!(td(&html, 0, "A2").contains("position:sticky;left:44.00px"));
    assert!(td(&html, 0, "B1").contains("position:sticky;top:26.00px"));
    assert!(!td(&html, 0, "B2").contains("frozen"));
    let d1 = td(&html, 0, "D1");
    assert!(d1.contains("hyperlink") && d1.contains(r#"data-href="https://example.com/spec""#));
    assert!(!d1.contains(" href="));
    let d2 = td(&html, 0, "D2");
    assert!(d2.contains("has-comment") && d2.contains(r#"title="Mai: Check totals""#));
    assert!(html.contains(r#"<section class="sheet no-gridlines""#));
    assert_eq!(labels(&html), vec!["Scores", "Lookup (hidden)"]);
    assert_eq!(visible_sheet_names(&book), vec!["Scores".to_string()]);
}

#[test]
fn draws_text_boxes_and_merges() {
    let drawing = r#"<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><xdr:twoCellAnchor><xdr:from><xdr:col>1</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>1</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from><xdr:to><xdr:col>3</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>4</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to><xdr:sp><xdr:nvSpPr><xdr:cNvPr id="2" name="TextBox 1"/><xdr:cNvSpPr txBox="1"/></xdr:nvSpPr><xdr:spPr><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:solidFill><a:srgbClr val="FFF2CC"/></a:solidFill></xdr:spPr><xdr:txBody><a:bodyPr/><a:p><a:pPr algn="ctr"/><a:r><a:rPr b="1"/><a:t>Assumptions</a:t></a:r></a:p></xdr:txBody></xdr:sp><xdr:clientData/></xdr:twoCellAnchor></xdr:wsDr>"#;
    let mut notes = sheet(
        "Notes",
        r#"<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Anchor</t></is></c></row></sheetData><mergeCells count="1"><mergeCell ref="C6:E8"/></mergeCells><drawing r:id="rIdDrawing1"/>"#,
    );
    notes.rels = Some(format!(
        r#"<Relationship Id="rIdDrawing1" Type="{REL}/drawing" Target="../drawings/drawing1.xml"/>"#
    ));
    let book = workbook(
        &[notes],
        &default_styles(),
        &[],
        &[("xl/drawings/drawing1.xml", drawing)],
    );
    let html = render(&book, "textbox.xlsx", None).unwrap();
    let at = html.find(r#"data-shape-name="TextBox 1""#).unwrap();
    let open = html[..at].rfind("<div").unwrap();
    let shape = &html[open..html[open..].find("</div>").unwrap() + open];
    assert!(shape.contains(r#"class="workbook-shape""#) && shape.contains("Assumptions"));
    assert!(shape.contains("background:#fff2cc"));
    // Column B / row 2: gutter + column A (Excel default 8.43 chars × 7px), header + one row.
    assert!(shape.contains("left:103.01px") && shape.contains("top:52.00px"));
    assert!(td(&html, 0, "C6").contains(r#"rowspan="3" colspan="3""#));
    assert!(!html.contains(r#"data-cell="D6""#));
}

#[test]
fn limits_large_sheets_and_shows_the_notice() {
    let mut rows = String::new();
    for r in 1..=600 {
        rows.push_str(&format!(r#"<row r="{r}"><c r="A{r}"><v>{r}</v></c></row>"#));
    }
    let book = workbook(
        &[sheet("Big", &format!("<sheetData>{rows}</sheetData>"))],
        &default_styles(),
        &[],
        &[],
    );
    let html = render(&book, "big.xlsx", None).unwrap();
    assert!(html.contains("Preview limited to the first 500 rows and 100 columns."));
    assert!(html.contains(r#"data-row="500""#) && !html.contains(r#"data-row="501""#));
}

#[test]
fn formats_numbers_dates_and_styles_like_v3() {
    let num_fmts = r#"<numFmts count="2"><numFmt numFmtId="164" formatCode="0.0%"/><numFmt numFmtId="165" formatCode="yyyy-mm-dd h:mm"/></numFmts>"#;
    let fonts =
        r#"<font><b/><i val="0"/><sz val="14"/><color rgb="FF112233"/><name val="Arial"/></font>"#;
    let fills =
        r#"<fill><patternFill patternType="solid"><fgColor rgb="FFFFFF00"/></patternFill></fill>"#;
    let xfs = r#"<xf numFmtId="164" fontId="0" fillId="0" borderId="0" applyNumberFormat="1"/><xf numFmtId="165" fontId="0" fillId="0" borderId="0"/><xf numFmtId="4" fontId="1" fillId="2" borderId="1"><alignment horizontal="center" vertical="top" wrapText="1"/></xf>"#;
    let book = workbook(
        &[sheet(
            "Numbers",
            r#"<sheetData><row r="1"><c r="A1" s="1"><v>0.125</v></c><c r="B1" s="2"><v>45306.5729166667</v></c><c r="C1" s="3"><v>1234567.891</v></c><c r="D1"><v>0.30000000000000004</v></c><c r="E1" t="b"><v>1</v></c><c r="F1" t="e"><v>#N/A</v></c></row></sheetData>"#,
        )],
        &styles(fonts, fills, xfs, num_fmts, ""),
        &[],
        &[],
    );
    let html = render(&book, "formats.xlsx", None).unwrap();
    assert!(td(&html, 0, "A1").contains(r#"data-display-value="12.5%""#));
    assert!(td(&html, 0, "B1").contains(r#"data-display-value="2024-01-15""#));
    let c1 = td(&html, 0, "C1");
    assert!(c1.contains(r#"data-display-value="1,234,567.89""#));
    assert!(c1.contains("background:#FFFF00;font-weight:700;font-family:&quot;Arial&quot;,Arial,sans-serif;font-size:14.00pt;color:#112233;text-align:center;vertical-align:top;white-space:normal;border-top:1px solid #FF0000;border-right:2px solid #80868b;border-bottom:2px solid #000000;border-left:1px dashed #00AA00"));
    assert!(td(&html, 0, "D1").contains(r#"data-display-value="0.3""#));
    assert!(td(&html, 0, "E1").contains(r#"data-display-value="TRUE""#));
    assert!(td(&html, 0, "F1").contains("data-display-value=\"#N/A\""));
}

#[test]
fn recovers_workbooks_openpyxl_could_not_read() {
    let styles_xml = default_styles()
        .replace(r#"<cellStyle name="Normal" xfId="0" builtinId="0"/>"#, r#"<cellStyle xfId="0" builtinId="0"/>"#)
        .replace(
            "<fonts count=\"1\">",
            "<fonts count=\"1\" xmlns:mc=\"http://schemas.openxmlformats.org/markup-compatibility/2006\"><mc:AlternateContent><mc:Choice Requires=\"x\"><font><b/></font></mc:Choice><mc:Fallback/></mc:AlternateContent>",
        );
    let book = workbook(
        &[sheet(
            "Repaired",
            r#"<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>kept</t></is></c></row></sheetData>"#,
        )],
        &styles_xml,
        &[],
        &[],
    );
    let html = render(&book, "repaired.xlsx", None).unwrap();
    assert!(html.contains(">kept</td>"));
    assert!(!td(&html, 0, "A1").contains("font-weight"));
}

fn live_book(titles: &[&str], plan: &str) -> Vec<u8> {
    let sheets: Vec<Sheet> = titles
        .iter()
        .map(|t| sheet(t, &format!(r#"<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>&gt; {t}</t></is></c></row></sheetData>"#)))
        .collect();
    let custom = format!(
        r#"<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="2" name="evo.deck"><vt:lpwstr>{plan}</vt:lpwstr></property></Properties>"#
    );
    workbook(
        &sheets,
        &default_styles(),
        &[],
        &[("docProps/custom.xml", &custom)],
    )
}

#[test]
fn live_workbook_shows_added_sheets_then_skeletons() {
    let book = live_book(
        &["Building…"],
        r#"{"v":1,"total":3,"added":0,"state":"building","session":"s"}"#,
    );
    let plan = read_plan_bytes(&book).unwrap();
    let html = render(&book, "book.xlsx", Some(&plan)).unwrap();
    assert!(html.contains(r#"<main data-deck-live="true">"#));
    assert!(!labels(&html).contains(&"Building…".to_string()));
    assert_eq!(statuses(&html), vec!["building", "pending", "pending"]);
    assert!(html.contains("Building sheet 1 of 3"));

    let book = live_book(
        &["Inputs"],
        r#"{"v":1,"total":3,"added":1,"state":"building"}"#,
    );
    let plan = read_plan_bytes(&book).unwrap();
    let html = render(&book, "book.xlsx", Some(&plan)).unwrap();
    assert_eq!(statuses(&html), vec!["done", "building", "pending"]);
    assert_eq!(labels(&html)[0], "Inputs");
    assert!(html.contains("&gt; Inputs"));
    assert_eq!(
        regex::Regex::new(r"<section[^>]*\bdata-slide-fresh\b")
            .unwrap()
            .find_iter(&html)
            .count(),
        1
    );
    assert!(html.contains(r#"<span class="done" style="width:33.33%"></span><span class="now" style="width:33.33%"></span>"#));

    let done = live_book(
        &["Inputs", "Model"],
        r#"{"v":1,"total":2,"added":2,"state":"done"}"#,
    );
    let plan = read_plan_bytes(&done).unwrap();
    let html = render(&done, "book.xlsx", Some(&plan)).unwrap();
    assert!(!html.contains("data-deck-live") && !html.contains("sheet-skeleton"));
    assert_eq!(labels(&html), vec!["Inputs", "Model"]);
    let plain = render(&book, "book.xlsx", None::<&DeckPlan>).unwrap();
    assert!(!plain.contains("sheet-skeleton"));
}

// ---------------------------------------------------------------- fixes over v3

const XDR: &str = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing";
const A: &str = "http://schemas.openxmlformats.org/drawingml/2006/main";
const C: &str = "http://schemas.openxmlformats.org/drawingml/2006/chart";

/// A chart part: `plot` is the plot-area chart element (`<c:barChart>…`).
fn chart_part(title: &str, plot: &str) -> String {
    format!(
        r#"<c:chartSpace xmlns:c="{C}" xmlns:a="{A}"><c:chart><c:title><c:tx><c:rich><a:p><a:r><a:t>{title}</a:t></a:r></a:p></c:rich></c:tx></c:title><c:plotArea>{plot}</c:plotArea></c:chart></c:chartSpace>"#
    )
}

fn literal_series(kind: &str, values: &[f64]) -> String {
    let points: String = values
        .iter()
        .enumerate()
        .map(|(i, v)| format!(r#"<c:pt idx="{i}"><c:v>{v}</c:v></c:pt>"#))
        .collect();
    format!(r#"<c:{kind}><c:ser><c:val><c:numLit>{points}</c:numLit></c:val></c:ser></c:{kind}>"#)
}

fn marker(tag: &str, col: u32, row: u32) -> String {
    format!(
        "<xdr:{tag}><xdr:col>{col}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{row}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:{tag}>"
    )
}

fn chart_frame(rel: &str) -> String {
    format!(
        r#"<xdr:graphicFrame><xdr:nvGraphicFramePr><xdr:cNvPr id="2" name="Chart"/><xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr><xdr:xfrm/><a:graphic><a:graphicData uri="{C}"><c:chart r:id="{rel}"/></a:graphicData></a:graphic></xdr:graphicFrame><xdr:clientData/>"#
    )
}

fn drawing(anchors: &str) -> String {
    format!(
        r#"<xdr:wsDr xmlns:xdr="{XDR}" xmlns:a="{A}" xmlns:c="{C}" xmlns:r="{REL}">{anchors}</xdr:wsDr>"#
    )
}

fn chart_rels(count: usize) -> String {
    let rels: String = (1..=count)
        .map(|i| {
            format!(
                r#"<Relationship Id="rIdC{i}" Type="{REL}/chart" Target="../charts/chart{i}.xml"/>"#
            )
        })
        .collect();
    format!(r#"<Relationships xmlns="{PKG_REL}">{rels}</Relationships>"#)
}

fn style_of(td: &str) -> String {
    let start = td.find(" style=\"").map(|s| s + 8).unwrap_or(0);
    td[start..]
        .split('"')
        .next()
        .unwrap_or_default()
        .to_string()
}

/// Fix 1: charts take their anchor's size; never openpyxl's 15 × 7.5 px.
/// Fix 6 (drawings part): the grid grows under anchored objects.
#[test]
fn sizes_charts_from_their_anchors() {
    let anchors = format!(
        "<xdr:twoCellAnchor>{}{}{}</xdr:twoCellAnchor><xdr:oneCellAnchor>{}<xdr:ext cx=\"1905000\" cy=\"952500\"/>{}</xdr:oneCellAnchor><xdr:oneCellAnchor>{}{}</xdr:oneCellAnchor>",
        marker("from", 1, 1),
        marker("to", 5, 11),
        chart_frame("rIdC1"),
        marker("from", 1, 30),
        chart_frame("rIdC2"),
        marker("from", 1, 60),
        chart_frame("rIdC3"),
    );
    let mut data = sheet(
        "Data",
        r#"<sheetData><row r="1"><c r="A1"><v>1</v></c></row></sheetData><drawing r:id="rIdD"/>"#,
    );
    data.rels = Some(format!(
        r#"<Relationship Id="rIdD" Type="{REL}/drawing" Target="../drawings/drawing1.xml"/>"#
    ));
    let bars = literal_series("barChart", &[1.0, 2.0]);
    let book = workbook(
        &[data],
        &default_styles(),
        &[],
        &[
            ("xl/drawings/drawing1.xml", &drawing(&anchors)),
            ("xl/drawings/_rels/drawing1.xml.rels", &chart_rels(3)),
            ("xl/charts/chart1.xml", &chart_part("Two cell", &bars)),
            ("xl/charts/chart2.xml", &chart_part("One cell", &bars)),
            ("xl/charts/chart3.xml", &chart_part("No extent", &bars)),
        ],
    );
    let html = render(&book, "charts.xlsx", None).unwrap();
    // From B2 to F12 on the rendered grid (59.01px columns, 26px rows).
    assert!(html.contains(r#"data-qa-label="Two cell" style="left:103.01px;top:52.00px;width:236.04px;height:260.00px""#));
    assert!(html.contains(r#"data-qa-label="One cell" style="left:103.01px;top:806.00px;width:200.00px;height:100.00px""#));
    // openpyxl's default 15 × 7.5 cm, at 96 dpi.
    assert!(html.contains(r#"data-qa-label="No extent" style="left:103.01px;top:1586.00px;width:566.93px;height:283.46px""#));
    assert!(!html.contains("width:15.00px"));
    assert!(html.contains(r#"data-row="71""#) && !html.contains(r#"data-row="72""#));
    assert!(!html.contains("Preview limited"));
}

/// Fix 2: `<col min max>` covers every column of the range; column and row
/// default formats apply to cells the sheet does not list.
#[test]
fn column_ranges_and_default_formats_cover_every_cell() {
    let fills =
        r#"<fill><patternFill patternType="solid"><fgColor rgb="FFFFFF00"/></patternFill></fill>"#;
    let xfs = r#"<xf numFmtId="0" fontId="0" fillId="2" borderId="0" applyFill="1"/>"#;
    let book = workbook(
        &[sheet(
            "Cols",
            r#"<cols><col min="2" max="4" width="20" customWidth="1"/><col min="6" max="8" width="9" hidden="1"/><col min="10" max="10" width="12" style="1"/><col min="12" max="12" width="0"/></cols><sheetData><row r="1"><c r="A1"><v>1</v></c></row><row r="3" s="1" customFormat="1"><c r="A3"><v>3</v></c></row><row r="4" ht="0" customHeight="1"><c r="A4"><v>4</v></c></row></sheetData>"#,
        )],
        &styles("", fills, xfs, "", ""),
        &[],
        &[],
    );
    let html = render(&book, "cols.xlsx", None).unwrap();
    assert_eq!(html.matches(r#"<col style="width:140px">"#).count(), 3);
    assert_eq!(
        html.matches(r#"<col style="width:1px;visibility:collapse">"#)
            .count(),
        4
    );
    assert!(html.contains(r#"data-column="J" style="min-width:84px""#));
    assert!(
        html.contains(r#"<col style="width:59px">"#),
        "Excel's default width"
    );
    assert!(style_of(&td(&html, 0, "J5")).starts_with("background:#FFFF00"));
    assert!(style_of(&td(&html, 0, "K3")).starts_with("background:#FFFF00"));
    assert!(
        style_of(&td(&html, 0, "A3")).starts_with("font-family"),
        "listed cells keep their own format"
    );
    assert!(!style_of(&td(&html, 0, "K5")).contains("background"));
    let row4 = html.find(r#"data-row="4""#).unwrap();
    let open = html[..row4].rfind("<tr ").unwrap();
    assert!(
        html[open..row4].contains("visibility:collapse"),
        "zero-height rows are hidden"
    );
}

/// Fix 3: theme (from the theme part, with tint) and indexed colours resolve in
/// cell formats; the default text colour stays unset.
#[test]
fn cell_formats_resolve_theme_and_indexed_colours() {
    let fonts = r#"<font><sz val="11"/><color theme="4"/><name val="Calibri"/></font>"#;
    let fills = r#"<fill><patternFill patternType="solid"><fgColor indexed="10"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor theme="0" tint="-0.5"/></patternFill></fill>"#;
    let xfs = r#"<xf numFmtId="0" fontId="1" fillId="2" borderId="0"/><xf numFmtId="0" fontId="0" fillId="3" borderId="1"/>"#;
    let theme = format!(
        r#"<a:theme xmlns:a="{A}" name="T"><a:themeElements><a:clrScheme name="T"><a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1><a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="1F497D"/></a:dk2><a:lt2><a:srgbClr val="EEECE1"/></a:lt2><a:accent1><a:srgbClr val="AA0000"/></a:accent1></a:clrScheme></a:themeElements></a:theme>"#
    );
    let book = workbook(
        &[sheet(
            "Colours",
            r#"<sheetData><row r="1"><c r="A1" s="1"><v>1</v></c><c r="B1" s="2"><v>2</v></c><c r="C1"><v>3</v></c></row></sheetData>"#,
        )],
        &styles(fonts, fills, xfs, "", ""),
        &[],
        &[("xl/theme/theme1.xml", &theme)],
    );
    let html = render(&book, "colours.xlsx", None).unwrap();
    let a1 = style_of(&td(&html, 0, "A1"));
    assert!(
        a1.contains("background:#ff0000") && a1.contains("color:#aa0000"),
        "{a1}"
    );
    let b1 = style_of(&td(&html, 0, "B1"));
    assert!(b1.contains("background:#808080"), "{b1}");
    assert!(b1.contains("border-bottom:2px solid #000000"), "{b1}");
    assert!(!style_of(&td(&html, 0, "C1")).contains("color:"));
}

/// Fix 4: a link on an empty cell keeps the cell empty (v3 showed the URL).
#[test]
fn hyperlinks_do_not_fill_empty_cells() {
    let mut links = sheet(
        "Links",
        r#"<sheetData><row r="1"><c r="A1"><v>1</v></c></row></sheetData><hyperlinks><hyperlink ref="B2" r:id="rId1"/><hyperlink ref="C3" location="Links!A1"/></hyperlinks>"#,
    );
    links.rels = Some(format!(
        r#"<Relationship Id="rId1" Type="{REL}/hyperlink" Target="https://example.com/x" TargetMode="External"/>"#
    ));
    let html = render(
        &workbook(&[links], &default_styles(), &[], &[]),
        "links.xlsx",
        None,
    )
    .unwrap();
    let b2 = td(&html, 0, "B2");
    assert!(
        b2.contains(r#"data-href="https://example.com/x""#)
            && b2.contains(r#"data-display-value="""#)
    );
    assert!(b2.ends_with("></td>"));
    let c3 = td(&html, 0, "C3");
    assert!(c3.contains(r#"data-href="Links!A1""#) && c3.contains(r#"data-display-value="""#));
}

/// Fix 5: chart sheets keep their tab position and the hidden label.
#[test]
fn chart_sheets_keep_tab_order_and_hidden_label() {
    let chart = Sheet {
        name: "Chart",
        state: Some("hidden"),
        xml: format!(
            r#"<chartsheet xmlns="{MAIN}" xmlns:r="{REL}"><drawing r:id="rIdD"/></chartsheet>"#
        ),
        rels: Some(format!(
            r#"<Relationship Id="rIdD" Type="{REL}/drawing" Target="../drawings/drawing1.xml"/>"#
        )),
    };
    let anchors = format!(
        r#"<xdr:absoluteAnchor><xdr:pos x="0" y="0"/><xdr:ext cx="9525000" cy="6191250"/>{}</xdr:absoluteAnchor>"#,
        chart_frame("rIdC1")
    );
    let book = workbook(
        &[
            sheet("Data", "<sheetData/>"),
            chart,
            sheet("Notes", "<sheetData/>"),
        ],
        &default_styles(),
        &[],
        &[
            ("xl/drawings/drawing1.xml", &drawing(&anchors)),
            ("xl/drawings/_rels/drawing1.xml.rels", &chart_rels(1)),
            (
                "xl/charts/chart1.xml",
                &chart_part("C", &literal_series("pieChart", &[2.0, 0.0])),
            ),
        ],
    );
    let html = render(&book, "chartsheet.xlsx", None).unwrap();
    assert_eq!(labels(&html), vec!["Data", "Chart (hidden)", "Notes"]);
    // A single full slice is drawn as a circle (v3 drew an empty arc).
    assert!(html.contains(r##"<circle cx="300" cy="150" r="108" fill="#2563eb"/>"##));
}

/// Fix 6: cells formulas read and conditional-format ranges do not grow the
/// grid (v3 showed 500 rows and the limit notice here).
#[test]
fn reads_and_rules_do_not_grow_the_grid() {
    let book = workbook(
        &[sheet(
            "Small",
            r#"<sheetData><row r="1"><c r="A1"><v>1</v></c><c r="B1"><f>SUM(A1:A700)</f></c></row></sheetData><conditionalFormatting sqref="C1:C900 A1:CZ2"><cfRule type="cellIs" priority="1" operator="equal"><formula>"x"</formula></cfRule></conditionalFormatting>"#,
        )],
        &default_styles(),
        &[],
        &[],
    );
    let html = render(&book, "small.xlsx", None).unwrap();
    assert!(td(&html, 0, "B1").contains(r#"data-display-value="1""#));
    assert!(html.contains(r#"data-row="40""#) && !html.contains(r#"data-row="41""#));
    assert!(html.contains(r#"data-column="T""#) && !html.contains(r#"data-column="U""#));
    assert!(!html.contains("Preview limited"));
}

/// Fix 7: negative values stay inside the chart (the baseline moves up).
#[test]
fn negative_chart_values_stay_inside_the_chart() {
    let mut data = sheet("Data", "<sheetData/><drawing r:id=\"rIdD\"/>");
    data.rels = Some(format!(
        r#"<Relationship Id="rIdD" Type="{REL}/drawing" Target="../drawings/drawing1.xml"/>"#
    ));
    let anchors = format!(
        "<xdr:oneCellAnchor>{}<xdr:ext cx=\"952500\" cy=\"952500\"/>{}</xdr:oneCellAnchor><xdr:oneCellAnchor>{}<xdr:ext cx=\"952500\" cy=\"952500\"/>{}</xdr:oneCellAnchor>",
        marker("from", 0, 0),
        chart_frame("rIdC1"),
        marker("from", 4, 0),
        chart_frame("rIdC2"),
    );
    let book = workbook(
        &[data],
        &default_styles(),
        &[],
        &[
            ("xl/drawings/drawing1.xml", &drawing(&anchors)),
            ("xl/drawings/_rels/drawing1.xml.rels", &chart_rels(2)),
            (
                "xl/charts/chart1.xml",
                &chart_part("Bars", &literal_series("barChart", &[10.0, -10.0])),
            ),
            (
                "xl/charts/chart2.xml",
                &chart_part("Line", &literal_series("lineChart", &[10.0, -30.0])),
            ),
        ],
    );
    let html = render(&book, "negative.xlsx", None).unwrap();
    assert!(html.contains(r#"<line x1="45" y1="147.00" x2="575" y2="147.00""#));
    assert!(html.contains(r#"y="42.00" width="187.20" height="105.00""#));
    assert!(html.contains(r#"y="147.00" width="187.20" height="105.00""#));
    // Line: 10 above, -30 below a baseline at 47 + 205/4.
    assert!(html.contains(r#"points="52.00,47.00 572.00,252.00""#));
}

/// Fidelity harness: render every workbook in `EVO_XLSX_PARITY_DIR` into
/// `EVO_XLSX_PARITY_OUT` (`<name>.html` and, live, `<name>.live.html`) for a
/// comparison with v3's renderer (plus `<name>.names.txt` for
/// `visible_sheet_names`). Run with `--ignored`.
///
/// Before the v3 bug fixes the output was byte-identical to v3.1.1 on every
/// fixture except array formulas' `data-formula`. Expected differences now,
/// all intended:
/// - geometry: default columns are Excel's 8.43 characters (59px, v3 91px) and
///   default rows the sheet's `defaultRowHeight` (row `height` 20px, v3 25px;
///   the rendered pitch is unchanged), so stage/fit sizes, sticky offsets and
///   object positions move; charts and pictures sit on the rendered grid
///   (v3 used raw sizes) and two-cell anchors span from/to (v3: 15×7.5px
///   charts, pictures at their pixel size); no-extent charts are 15×7.5 cm;
/// - bounds: cells read by formulas and conditional-format ranges no longer
///   grow the grid or raise the 500×100 notice; drawing anchors and notes do;
/// - `<col min max>` ranges, zero widths / heights (hidden), column and row
///   default formats apply to every covered cell;
/// - theme (from the theme part, with tint) and indexed (`indexedColors`)
///   colours resolve in cell formats, conditional formats and shapes;
/// - empty linked cells stay empty; chart sheets keep their tab position and
///   the " (hidden)" label; full pies draw a circle; negative values move the
///   chart baseline; array formulas show their formula.
#[test]
#[ignore]
fn parity_render_fixtures() {
    let (Ok(src), Ok(out)) = (
        std::env::var("EVO_XLSX_PARITY_DIR"),
        std::env::var("EVO_XLSX_PARITY_OUT"),
    ) else {
        return;
    };
    for entry in std::fs::read_dir(src).unwrap() {
        let path = entry.unwrap().path();
        if path.extension().and_then(|e| e.to_str()) != Some("xlsx") {
            continue;
        }
        let bytes = std::fs::read(&path).unwrap();
        let name = path.file_name().unwrap().to_string_lossy().to_string();
        let stem = path.file_stem().unwrap().to_string_lossy().to_string();
        std::fs::write(
            std::path::Path::new(&out).join(format!("{stem}.names.txt")),
            visible_sheet_names(&bytes).join("\n"),
        )
        .unwrap();
        let plan = read_plan_bytes(&bytes);
        for (suffix, live) in [("", None), (".live", plan.as_ref())] {
            let html = match render(&bytes, &name, live) {
                Ok(html) => html,
                Err(e) => format!("ERROR: {e}"),
            };
            std::fs::write(
                std::path::Path::new(&out).join(format!("{stem}{suffix}.html")),
                html,
            )
            .unwrap();
        }
    }
}
