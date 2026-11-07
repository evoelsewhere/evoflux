//! PPTX native preview: small hand-written decks rendered end to end.

use std::io::Write as _;

use evo_office::preview::{pptx, DeckPlan, Package};

const CT: &str = r#"<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/></Types>"#;
const NS: &str = r#"xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main""#;
const REL: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";

fn rels(items: &[(&str, &str, &str)]) -> String {
    let body: String = items
        .iter()
        .map(|(id, kind, target)| {
            format!(r#"<Relationship Id="{id}" Type="{REL}/{kind}" Target="{target}"/>"#)
        })
        .collect();
    format!(
        r#"<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{body}</Relationships>"#
    )
}

fn sp(id: u32, name: &str, ph: &str, xfrm: &str, body: &str) -> String {
    format!(
        r#"<p:sp><p:nvSpPr><p:cNvPr id="{id}" name="{name}"/><p:cNvSpPr/><p:nvPr>{ph}</p:nvPr></p:nvSpPr><p:spPr>{xfrm}</p:spPr>{body}</p:sp>"#
    )
}

fn xfrm(x: i64, y: i64, cx: i64, cy: i64) -> String {
    format!(r#"<a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>"#)
}

fn tree(shapes: &str) -> String {
    format!(
        r#"<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>{shapes}</p:spTree></p:cSld>"#
    )
}

const THEME: &str = r#"<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="T"><a:themeElements><a:clrScheme name="c"><a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1><a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="1F497D"/></a:dk2><a:lt2><a:srgbClr val="EEECE1"/></a:lt2><a:accent1><a:srgbClr val="4F81BD"/></a:accent1><a:accent2><a:srgbClr val="C0504D"/></a:accent2><a:accent3><a:srgbClr val="9BBB59"/></a:accent3><a:accent4><a:srgbClr val="8064A2"/></a:accent4><a:accent5><a:srgbClr val="4BACC6"/></a:accent5><a:accent6><a:srgbClr val="F79646"/></a:accent6><a:hlink><a:srgbClr val="0000FF"/></a:hlink><a:folHlink><a:srgbClr val="800080"/></a:folHlink></a:clrScheme><a:fontScheme name="f"><a:majorFont><a:latin typeface="Calibri Light"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme><a:fmtScheme name="m"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst><a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst><a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst><a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>"#;

/// A one-master, one-layout deck whose slides are `slides` (spTree contents).
fn deck(slides: &[String], extra: &[(&str, Vec<u8>)]) -> Package {
    deck_with_layout(slides, "", extra)
}

/// [`deck`] with extra shapes in the layout's shape tree. Every slide relates
/// `rId3` to `ppt/charts/chart1.xml`.
fn deck_with_layout(slides: &[String], layout_extra: &str, extra: &[(&str, Vec<u8>)]) -> Package {
    let mut parts: Vec<(String, Vec<u8>)> = vec![
        ("[Content_Types].xml".into(), CT.into()),
        (
            "_rels/.rels".into(),
            rels(&[("rId1", "officeDocument", "ppt/presentation.xml")]).into(),
        ),
        ("ppt/theme/theme1.xml".into(), THEME.into()),
    ];
    let ids: String = (0..slides.len())
        .map(|i| format!(r#"<p:sldId id="{}" r:id="rIdS{i}"/>"#, 256 + i))
        .collect();
    parts.push((
        "ppt/presentation.xml".into(),
        format!(r#"<p:presentation {NS}><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rIdM"/></p:sldMasterIdLst><p:sldIdLst>{ids}</p:sldIdLst><p:sldSz cx="12192000" cy="6858000"/></p:presentation>"#).into(),
    ));
    let mut pres_rels = vec![(
        "rIdM".to_string(),
        "slideMaster".to_string(),
        "slideMasters/slideMaster1.xml".to_string(),
    )];
    for (i, body) in slides.iter().enumerate() {
        pres_rels.push((
            format!("rIdS{i}"),
            "slide".into(),
            format!("slides/slide{}.xml", i + 1),
        ));
        parts.push((
            format!("ppt/slides/slide{}.xml", i + 1),
            format!(r#"<p:sld {NS}>{}</p:sld>"#, tree(body)).into(),
        ));
        parts.push((
            format!("ppt/slides/_rels/slide{}.xml.rels", i + 1),
            rels(&[
                ("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml"),
                ("rId2", "image", "../media/image1.png"),
                ("rId3", "chart", "../charts/chart1.xml"),
            ])
            .into(),
        ));
    }
    let pres_rels: Vec<(&str, &str, &str)> = pres_rels
        .iter()
        .map(|(a, b, c)| (a.as_str(), b.as_str(), c.as_str()))
        .collect();
    parts.push((
        "ppt/_rels/presentation.xml.rels".into(),
        rels(&pres_rels).into(),
    ));
    let master_title = sp(
        2,
        "Title Placeholder 1",
        r#"<p:ph type="title"/>"#,
        &xfrm(838200, 365125, 10515600, 1325563),
        "",
    );
    let master_band = sp(
        9,
        "Brand band",
        "",
        &(xfrm(0, 6400800, 12192000, 457200)
            + r#"<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:solidFill><a:srgbClr val="1F4E79"/></a:solidFill>"#),
        "",
    );
    parts.push((
        "ppt/slideMasters/slideMaster1.xml".into(),
        format!(
            r#"<p:sldMaster {NS}><p:cSld><p:bg><p:bgPr><a:solidFill><a:schemeClr val="bg2"/></a:solidFill><a:effectLst/></p:bgPr></p:bg><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>{master_title}{master_band}</p:spTree></p:cSld><p:txStyles><p:titleStyle><a:lvl1pPr algn="ctr"><a:defRPr sz="4400"><a:solidFill><a:schemeClr val="tx1"/></a:solidFill><a:latin typeface="+mj-lt"/></a:defRPr></a:lvl1pPr></p:titleStyle><p:bodyStyle><a:lvl1pPr marL="228600" indent="-228600"><a:buFont typeface="Arial"/><a:buChar char="&#8226;"/><a:defRPr sz="2800"/></a:lvl1pPr></p:bodyStyle><p:otherStyle><a:lvl1pPr><a:defRPr sz="1800"/></a:lvl1pPr></p:otherStyle></p:txStyles></p:sldMaster>"#
        )
        .into(),
    ));
    parts.push((
        "ppt/slideMasters/_rels/slideMaster1.xml.rels".into(),
        rels(&[
            ("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml"),
            ("rId2", "theme", "../theme/theme1.xml"),
        ])
        .into(),
    ));
    let layout_title = sp(2, "Title 1", r#"<p:ph type="title"/>"#, "", "");
    parts.push((
        "ppt/slideLayouts/slideLayout1.xml".into(),
        format!(
            r#"<p:sldLayout {NS}>{}</p:sldLayout>"#,
            tree(&(layout_title + layout_extra))
        )
        .into(),
    ));
    parts.push((
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels".into(),
        rels(&[("rId1", "slideMaster", "../slideMasters/slideMaster1.xml")]).into(),
    ));
    for (name, data) in extra {
        parts.push((name.to_string(), data.clone()));
    }
    Package::from_parts(parts)
}

fn text_body(runs: &str) -> String {
    format!(r#"<p:txBody><a:bodyPr/><a:lstStyle/><a:p>{runs}</a:p></p:txBody>"#)
}

#[test]
fn title_placeholder_inherits_position_and_styles_from_layout_and_master() {
    let title = sp(
        4,
        "Title 3",
        r#"<p:ph type="title"/>"#,
        "",
        &text_body(r#"<a:r><a:rPr lang="en-US"/><a:t>Quarterly &amp; review</a:t></a:r>"#),
    );
    let html = pptx::render(&deck(&[title], &[]), "deck.pptx", None).unwrap();
    // Position comes from the master placeholder (the layout one has no xfrm).
    assert!(html.contains(r#"data-shape-id="4" data-shape-name="Title 3" data-qa-label="Title 3" data-source-layer="slide""#), "{html}");
    assert!(
        html.contains("left:6.875%;top:5.324%;width:86.250%;height:19.329%"),
        "{html}"
    );
    // titleStyle: centered, 44pt, major font, tx1.
    assert!(html.contains("text-align:center"));
    assert!(html.contains("font-size:4.5833cqw;font-family:&quot;Calibri Light&quot;,Arial,sans-serif;color:#000000"), "{html}");
    assert!(html.contains(r#"data-preview-label="Slide 1 — Quarterly &amp; review""#));
    // The master's non-placeholder band is composited; its title placeholder is not.
    assert!(html.contains(
        r#"data-shape-name="Brand band" data-qa-label="Brand band" data-source-layer="master""#
    ));
    assert!(!html.contains("Title Placeholder 1"));
    // Background from the master's scheme colour.
    assert!(html.contains("background:#EEECE1"), "{html}");
    assert!(html.contains("<title>deck.pptx</title>"));
}

#[test]
fn bullets_numbering_and_connectors() {
    let body = r#"<p:txBody><a:bodyPr anchor="ctr"/><a:lstStyle/><a:p><a:pPr marL="342900" indent="-342900"><a:buAutoNum type="alphaLcParenR"/></a:pPr><a:r><a:t>one</a:t></a:r></a:p><a:p><a:pPr marL="342900" indent="-342900"><a:buAutoNum type="alphaLcParenR"/></a:pPr><a:r><a:t>two</a:t></a:r></a:p></p:txBody>"#;
    let list = sp(
        5,
        "List",
        "",
        &(xfrm(0, 0, 6096000, 3429000) + r#"<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>"#),
        body,
    );
    let connector = r#"<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="6" name="Arrow"/><p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr><p:spPr><a:xfrm flipH="1"><a:off x="0" y="3429000"/><a:ext cx="6096000" cy="0"/></a:xfrm><a:prstGeom prst="line"><a:avLst/></a:prstGeom><a:ln w="19050"><a:solidFill><a:srgbClr val="C00000"/></a:solidFill><a:prstDash val="dash"/><a:tailEnd type="triangle"/></a:ln></p:spPr></p:cxnSp>"#;
    let html = pptx::render(&deck(&[list + connector], &[]), "d.pptx", None).unwrap();
    assert!(
        html.contains(">a)</span>") && html.contains(">b)</span>"),
        "{html}"
    );
    assert!(html.contains("justify-content:center"));
    assert!(
        html.contains(r#"<svg class="shape connector" data-shape-id="6""#),
        "{html}"
    );
    assert!(html.contains(r#"d="M1000 500L0 500""#), "{html}");
    assert!(html.contains(r#"stroke-dasharray="8.00 6.00""#), "{html}");
    // Marker ids hash the python-pptx partname and shape id (sha1, 12 hex).
    assert!(html.contains(r#"marker-end="url(#connector-tail-"#));
}

#[test]
fn a_broken_shape_is_skipped_not_the_deck() {
    let good = sp(
        7,
        "Good",
        "",
        &xfrm(0, 0, 100, 100),
        &text_body("<a:r><a:t>ok</a:t></a:r>"),
    );
    // A table frame without its table: v3 skipped it (AttributeError).
    let broken = r#"<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="8" name="Table 1"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr><p:xfrm><a:off x="0" y="0"/><a:ext cx="10" cy="10"/></p:xfrm><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"/></a:graphic></p:graphicFrame>"#;
    let html = pptx::render(&deck(&[good + broken], &[]), "d.pptx", None).unwrap();
    assert!(html.contains(r#"data-shape-name="Good""#));
    assert!(!html.contains("Table 1"));
}

#[test]
fn pictures_keep_crop_and_alt_text() {
    let pic = r#"<p:pic><p:nvPicPr><p:cNvPr id="3" name="Picture 2" descr="A &quot;red&quot; box"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="rId2"/><a:srcRect l="10000" r="20000"/><a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr><a:xfrm><a:off x="1219200" y="685800"/><a:ext cx="2438400" cy="1371600"/></a:xfrm><a:prstGeom prst="ellipse"><a:avLst/></a:prstGeom></p:spPr></p:pic>"#;
    let png = b"\x89PNG\r\n\x1a\nfake".to_vec();
    let html = pptx::render(
        &deck(&[pic.to_string()], &[("ppt/media/image1.png", png)]),
        "d.pptx",
        None,
    )
    .unwrap();
    assert!(
        html.contains(
            r#"data-crop-left="0.10000" data-crop-right="0.20000" data-crop-top="0.00000""#
        ),
        "{html}"
    );
    assert!(html.contains("clip-path:ellipse(50% 50% at 50% 50%)"));
    assert!(html.contains(r#"alt="A &quot;red&quot; box""#));
    assert!(
        html.contains("left:-14.2857%;top:-0.0000%;width:142.8571%;height:100.0000%"),
        "{html}"
    );
    assert!(html.contains("src=\"data:image/png;base64,"));
}

#[test]
fn live_decks_add_skeletons_for_missing_slides() {
    let slide = sp(
        4,
        "Title 3",
        r#"<p:ph type="title"/>"#,
        "",
        &text_body("<a:r><a:t>First</a:t></a:r>"),
    );
    let custom = r#"<?xml version="1.0"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" name="evo.deck"><vt:lpwstr>{"v":1,"total":3,"state":"building"}</vt:lpwstr></property></Properties>"#;
    let package = deck(
        &[slide],
        &[("docProps/custom.xml", custom.as_bytes().to_vec())],
    );
    let plan = DeckPlan {
        total: 3,
        done: false,
        session: None,
        added: None,
    };
    let html = pptx::render(&package, "d.pptx", Some(&plan)).unwrap();
    assert!(html.contains(r#"<main data-deck-live="true">"#));
    assert!(
        html.contains(r#"data-slide-status="done" data-slide-fresh>"#),
        "{html}"
    );
    assert!(html.contains(r#"data-preview-label="Slide 2" data-slide-status="building""#));
    assert!(html.contains("Building slide 2 of 3"));
    assert!(html.contains(r#"data-preview-label="Slide 3" data-slide-status="pending""#));
    assert!(html.contains(r#"<span class="done" style="width:33.33%"></span>"#));
    // Without a live request the same file renders plainly.
    let plain = pptx::render(&package, "d.pptx", None).unwrap();
    assert!(!plain.contains("data-deck-live"));
    assert!(!plain.contains("data-slide-status"));
}

#[test]
fn invalid_slide_size_fails() {
    let package = Package::from_parts([
        (
            "_rels/.rels".to_string(),
            rels(&[("rId1", "officeDocument", "ppt/presentation.xml")]).into_bytes(),
        ),
        (
            "ppt/presentation.xml".to_string(),
            format!(r#"<p:presentation {NS}><p:sldSz cx="0" cy="0"/></p:presentation>"#)
                .into_bytes(),
        ),
    ]);
    let error = pptx::render(&package, "d.pptx", None).unwrap_err();
    assert_eq!(
        error.to_string(),
        "Presentation has invalid slide dimensions"
    );
}

/// Dev aid for the v3 fidelity comparison: render every `.pptx` in
/// `EVO_PPTX_FIXTURES` into `EVO_PPTX_OUT` (`<stem>.html`, `<stem>.live.html`).
#[test]
#[ignore]
fn render_fixture_directory() {
    let (Ok(input), Ok(output)) = (
        std::env::var("EVO_PPTX_FIXTURES"),
        std::env::var("EVO_PPTX_OUT"),
    ) else {
        return;
    };
    std::fs::create_dir_all(&output).unwrap();
    for entry in std::fs::read_dir(&input).unwrap() {
        let path = entry.unwrap().path();
        if path.extension().and_then(|e| e.to_str()) != Some("pptx") {
            continue;
        }
        let stem = path.file_stem().unwrap().to_string_lossy().to_string();
        let name = path.file_name().unwrap().to_string_lossy().to_string();
        let bytes = std::fs::read(&path).unwrap();
        let package = match Package::open(&bytes) {
            Ok(package) => package,
            Err(error) => {
                eprintln!("{name}: {error}");
                continue;
            }
        };
        let started = std::time::Instant::now();
        let html = match pptx::render(&package, &name, None) {
            Ok(html) => html,
            Err(error) => {
                eprintln!("{name}: {error}");
                continue;
            }
        };
        eprintln!("{name}: {:?}", started.elapsed());
        std::fs::File::create(format!("{output}/{stem}.html"))
            .unwrap()
            .write_all(html.as_bytes())
            .unwrap();
        let plan = DeckPlan {
            total: 1,
            done: false,
            session: None,
            added: None,
        };
        if let Ok(live) = pptx::render(&package, &name, Some(&plan)) {
            std::fs::File::create(format!("{output}/{stem}.live.html"))
                .unwrap()
                .write_all(live.as_bytes())
                .unwrap();
        }
    }
}

// ---- Fixes over v3 (each test names the v3 behaviour it corrects) ----------

const C_NS: &str = "http://schemas.openxmlformats.org/drawingml/2006/chart";

/// A chart part whose plot area holds `plot` (and value axes, so scaling works).
fn chart_part(plot: &str) -> (&'static str, Vec<u8>) {
    let xml = format!(
        r#"<c:chartSpace xmlns:c="{C_NS}" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><c:chart><c:plotArea>{plot}<c:valAx><c:axId val="1"/><c:scaling><c:orientation val="minMax"/></c:scaling></c:valAx><c:valAx><c:axId val="2"/><c:scaling><c:orientation val="minMax"/></c:scaling></c:valAx></c:plotArea></c:chart></c:chartSpace>"#
    );
    ("ppt/charts/chart1.xml", xml.into_bytes())
}

fn series(branch: &str, values: &[&str]) -> String {
    let points: String = values
        .iter()
        .enumerate()
        .map(|(i, v)| format!(r#"<c:pt idx="{i}"><c:v>{v}</c:v></c:pt>"#))
        .collect();
    format!(
        r#"<c:{branch}><c:numRef><c:f>S!A1</c:f><c:numCache><c:ptCount val="{}"/>{points}</c:numCache></c:numRef></c:{branch}>"#,
        values.len()
    )
}

fn chart_frame() -> String {
    format!(
        r#"<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="30" name="Chart 29"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr><p:xfrm><a:off x="0" y="0"/><a:ext cx="6096000" cy="3048000"/></p:xfrm><a:graphic><a:graphicData uri="{C_NS}"><c:chart xmlns:c="{C_NS}" r:id="rId3"/></a:graphicData></a:graphic></p:graphicFrame>"#
    )
}

fn render_chart(plot: &str) -> String {
    let package = deck(&[chart_frame()], &[chart_part(plot)]);
    pptx::render(&package, "c.pptx", None).unwrap()
}

/// v3 never applied `a:lstStyle` (python-pptx has no `CT_TextBody.lstStyle`).
#[test]
fn fix_list_styles_apply_to_shapes_and_table_cells() {
    let body = r#"<p:txBody><a:bodyPr/><a:lstStyle><a:lvl1pPr algn="r"><a:defRPr sz="3200"><a:solidFill><a:srgbClr val="00AA00"/></a:solidFill></a:defRPr></a:lvl1pPr></a:lstStyle><a:p><a:r><a:t>styled by list</a:t></a:r></a:p></p:txBody>"#;
    let shape = sp(5, "Box", "", &xfrm(0, 0, 6096000, 1000000), body);
    let table = r#"<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="6" name="Table 5"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr><p:xfrm><a:off x="0" y="2000000"/><a:ext cx="6096000" cy="740000"/></p:xfrm><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl><a:tblPr/><a:tblGrid><a:gridCol w="6096000"/></a:tblGrid><a:tr h="370000"><a:tc><a:txBody><a:bodyPr/><a:lstStyle><a:lvl1pPr algn="ctr"/></a:lstStyle><a:p><a:r><a:t>cell</a:t></a:r></a:p></a:txBody><a:tcPr/></a:tc></a:tr></a:tbl></a:graphicData></a:graphic></p:graphicFrame>"#;
    let html = pptx::render(&deck(&[shape + table], &[]), "d.pptx", None).unwrap();
    assert!(html.contains("text-align:right"), "{html}");
    assert!(html.contains("font-size:3.3333cqw;"), "{html}");
    assert!(html.contains("color:#00AA00"), "{html}");
    assert!(
        html.contains(
            r#"<p style="margin:0;white-space:pre-wrap;line-height:1.12;text-align:center">"#
        ),
        "{html}"
    );
}

/// v3 sent subtitles to the master's title style (`"TITLE" in "SUBTITLE"`).
#[test]
fn fix_subtitles_inherit_the_body_style() {
    let subtitle = sp(
        4,
        "Subtitle 3",
        r#"<p:ph type="subTitle" idx="1"/>"#,
        &xfrm(0, 0, 6096000, 1000000),
        &text_body("<a:r><a:t>Subtitle</a:t></a:r>"),
    );
    let html = pptx::render(&deck(&[subtitle], &[]), "d.pptx", None).unwrap();
    // bodyStyle: 28 pt and its bullet; titleStyle would be 44 pt, centred.
    assert!(html.contains("font-size:2.9167cqw"), "{html}");
    assert!(!html.contains("font-size:4.5833cqw"), "{html}");
    assert!(html.contains(r#"<span class="bullet-marker""#), "{html}");
}

/// v3 showed every field's text twice (lxml `itertext` + `CT_TextField.text`).
#[test]
fn fix_field_text_appears_once() {
    let runs = r#"<a:r><a:t>Page </a:t></a:r><a:fld id="{B6F15528-21DE-4FAA-801E-634DDDAF4B2B}" type="slidenum"><a:rPr lang="en-US"/><a:t>7</a:t></a:fld>"#;
    let shape = sp(
        5,
        "Footer",
        "",
        &xfrm(0, 0, 100000, 100000),
        &text_body(runs),
    );
    let html = pptx::render(&deck(&[shape], &[]), "d.pptx", None).unwrap();
    assert!(html.contains(">7</span>"), "{html}");
    assert!(!html.contains(">77</span>"), "{html}");
}

fn scatter(symbol: &str, labels: bool) -> String {
    let labels = if labels {
        r#"<c:dLbls><c:showVal val="1"/></c:dLbls>"#
    } else {
        ""
    };
    format!(
        r#"<c:scatterChart><c:scatterStyle val="lineMarker"/><c:ser><c:idx val="0"/><c:order val="0"/><c:spPr><a:ln><a:noFill/></a:ln></c:spPr><c:marker><c:symbol val="{symbol}"/></c:marker>{}{}</c:ser>{labels}<c:axId val="1"/><c:axId val="2"/></c:scatterChart>"#,
        series("xVal", &["1", "2"]),
        series("yVal", &["3", "4"])
    )
}

/// v3 never labelled scatter points (python-pptx's scatter plot has no
/// `has_data_labels`).
#[test]
fn fix_scatter_data_labels_are_drawn() {
    let html = render_chart(&scatter("circle", true));
    assert!(
        html.contains(r#"<svg class="chart-svg chart-scatter""#),
        "{html}"
    );
    assert!(html.contains(r#"class="chart-data-label""#), "{html}");
    let unlabelled = render_chart(&scatter("circle", false));
    assert!(!unlabelled.contains(r#"class="chart-data-label""#));
}

/// v3 compared python-pptx's `AUTOMATIC` marker with `"AUTO"` and drew circles.
#[test]
fn fix_automatic_markers_are_diamonds() {
    let html = render_chart(&scatter("auto", false));
    assert!(
        html.contains(r##"class="chart-marker" fill="#4472c4" data-marker-style="diamond""##),
        "{html}"
    );
    assert!(!html.contains(r#"data-marker-style="circle""#), "{html}");
}

/// v3 lost a placeholder whose layout counterpart had no master mapping
/// (python-pptx raised `KeyError` for a header placeholder).
#[test]
fn fix_unmapped_layout_placeholder_keeps_the_shape() {
    let layout = sp(8, "Header 7", r#"<p:ph type="hdr" idx="5"/>"#, "", "");
    let slide = sp(
        4,
        "Header 3",
        r#"<p:ph type="hdr" idx="5"/>"#,
        "",
        &text_body("<a:r><a:t>Header text</a:t></a:r>"),
    );
    let html = pptx::render(&deck_with_layout(&[slide], &layout, &[]), "d.pptx", None).unwrap();
    assert!(html.contains(r#"data-shape-name="Header 3""#), "{html}");
    assert!(
        html.contains("left:0.000%;top:0.000%;width:0.000%;height:0.000%"),
        "{html}"
    );
}

/// v3 lost a text placeholder whose layout counterpart is a picture
/// placeholder (no text frame to read styles from).
#[test]
fn fix_text_over_picture_placeholder_is_kept() {
    let layout = r#"<p:pic><p:nvPicPr><p:cNvPr id="9" name="Picture Placeholder 8"/><p:cNvPicPr/><p:nvPr><p:ph type="pic" idx="7"/></p:nvPr></p:nvPicPr><p:blipFill/><p:spPr><a:xfrm><a:off x="1219200" y="685800"/><a:ext cx="6096000" cy="3429000"/></a:xfrm></p:spPr></p:pic>"#;
    let slide = sp(
        4,
        "Picture Placeholder 3",
        r#"<p:ph type="pic" idx="7"/>"#,
        "",
        &text_body("<a:r><a:t>Click to add</a:t></a:r>"),
    );
    let html = pptx::render(&deck_with_layout(&[slide], layout, &[]), "d.pptx", None).unwrap();
    assert!(
        html.contains(r#"data-shape-name="Picture Placeholder 3""#),
        "{html}"
    );
    assert!(
        html.contains("left:10.000%;top:10.000%;width:50.000%;height:50.000%"),
        "{html}"
    );
    assert!(html.contains(">Click to add</span>"), "{html}");
}

/// v3 lost a bar chart whose grouping is `standard` (python-pptx `KeyError`).
#[test]
fn fix_bar_chart_with_standard_grouping_renders() {
    let plot = format!(
        r#"<c:barChart><c:barDir val="col"/><c:grouping val="standard"/><c:ser><c:idx val="0"/><c:order val="0"/>{}</c:ser><c:axId val="1"/><c:axId val="2"/></c:barChart>"#,
        series("val", &["1", "2"])
    );
    let html = render_chart(&plot);
    assert!(
        html.contains(r#"<svg class="chart-svg chart-column chart-clustered""#),
        "{html}"
    );
}

/// v3 failed the whole deck for a chart without plots or a scatter chart
/// without `c:scatterStyle` (`IndexError`).
#[test]
fn fix_charts_missing_required_children_do_not_fail_the_deck() {
    let html = render_chart("");
    assert!(html.contains("Unsupported chart type: UNKNOWN"), "{html}");
    let scatter = scatter("circle", false).replace(r#"<c:scatterStyle val="lineMarker"/>"#, "");
    let html = render_chart(&scatter);
    assert!(
        html.contains(r#"<svg class="chart-svg chart-scatter""#),
        "{html}"
    );
}

/// v3 failed the whole deck on a non-finite cached value (`OverflowError`).
#[test]
fn fix_non_finite_chart_values_count_as_zero() {
    let plot = format!(
        r#"<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/><c:ser><c:idx val="0"/><c:order val="0"/>{}</c:ser><c:dLbls/><c:axId val="1"/><c:axId val="2"/></c:barChart>"#,
        series("val", &["INF", "2"])
    );
    let html = render_chart(&plot);
    assert!(html.contains(r#"class="chart-data-label""#), "{html}");
    assert!(
        html.contains(r##"font-size="11" fill="#404040">0</text>"##),
        "{html}"
    );
}

/// v3 failed the whole deck when a slide placeholder had an unknown type
/// (python-pptx's shape factory raised `ValueError`) or a run had no `a:t`.
#[test]
fn fix_malformed_slide_shapes_do_not_fail_the_deck() {
    let odd = sp(
        4,
        "Odd placeholder",
        r#"<p:ph type="bogus" idx="3"/>"#,
        &xfrm(0, 0, 100, 100),
        &text_body("<a:r><a:t>still here</a:t></a:r><a:r><a:rPr/></a:r>"),
    );
    let html = pptx::render(&deck(&[odd], &[]), "d.pptx", None).unwrap();
    assert!(
        html.contains(r#"data-shape-name="Odd placeholder""#),
        "{html}"
    );
    assert!(html.contains(">still here</span>"), "{html}");
}

/// v3 lost a chart frame whose chart part is missing (python-pptx `KeyError`).
#[test]
fn fix_chart_without_its_part_shows_unavailable() {
    let html = pptx::render(&deck(&[chart_frame()], &[]), "d.pptx", None).unwrap();
    assert!(html.contains(r#"data-shape-name="Chart 29""#), "{html}");
    assert!(html.contains("Chart data unavailable"), "{html}");
}

/// v3 lost a whole shape when one value did not parse (an `int()`/`float()`
/// failure in python-pptx or v3): a position, a colour transform, a list level,
/// a table size or span, a chart point. Each reads as absent instead.
#[test]
fn fix_unreadable_values_do_not_lose_the_shape() {
    let runs = r#"<a:r><a:rPr><a:solidFill><a:srgbClr val="FF0000"><a:lumMod val="abc"/></a:srgbClr></a:solidFill></a:rPr><a:t>red</a:t></a:r>"#;
    let body = format!(
        r#"<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:pPr lvl="x"/>{runs}</a:p></p:txBody>"#
    );
    let text = sp(
        5,
        "Odd values",
        "",
        r#"<a:xfrm><a:off x="abc" y="0"/><a:ext cx="100" cy="100"/></a:xfrm>"#,
        &body,
    );
    let table = r#"<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="6" name="Table 5"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr><p:xfrm><a:off x="0" y="0"/><a:ext cx="100" cy="100"/></p:xfrm><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl><a:tblGrid><a:gridCol w="x"/></a:tblGrid><a:tr h="370000"><a:tc gridSpan="y"><a:txBody><a:bodyPr/><a:p><a:r><a:t>cell</a:t></a:r></a:p></a:txBody></a:tc></a:tr></a:tbl></a:graphicData></a:graphic></p:graphicFrame>"#;
    let html = pptx::render(&deck(&[text + table], &[]), "d.pptx", None).unwrap();
    assert!(html.contains(r#"data-shape-name="Odd values""#), "{html}");
    assert!(html.contains("color:#FF0000"), "{html}");
    assert!(html.contains("left:0.000%"), "{html}");
    assert!(html.contains(r#"data-shape-name="Table 5""#), "{html}");
    let plot = format!(
        r#"<c:barChart><c:barDir val="col"/><c:ser><c:idx val="0"/><c:order val="0"/>{}</c:ser><c:axId val="1"/><c:axId val="2"/></c:barChart>"#,
        series("val", &["1", "two", "3"])
    );
    let chart = render_chart(&plot);
    assert!(
        chart.contains(r#"<svg class="chart-svg chart-column chart-clustered""#),
        "{chart}"
    );
}
