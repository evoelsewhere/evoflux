# Editing a .pptx: raw XML workflow

For anything the python-pptx API doesn't expose — custom shapes, non-standard
XML parts, deep master edits, comments, duplicating chart-bearing slides, or
fixing files that don't open cleanly. Template fill and python-pptx slide
surgery are in `edit-template.md`.

Every script here runs as `uv run --with python-pptx python scripts/<name>.py`.
Never overwrite the original file: assemble to a new path, run the QA
checklist, then hand off.

## Contents

- Explode
- Slide order lives in `ppt/presentation.xml`
- `insert_slide.py`
- `prune.py`
- Editing slide XML
- Comments
- Reassemble
- Editing slide masters
- Common XML pitfalls
- After you edit

## Explode

```bash
uv run --with python-pptx python scripts/explode.py input.pptx unpacked/
```

You get a directory tree like:

```
unpacked/
├── [Content_Types].xml
├── _rels/.rels
├── docProps/{app,core}.xml
├── ppt/
│   ├── presentation.xml
│   ├── _rels/presentation.xml.rels
│   ├── slides/
│   │   ├── slide1.xml
│   │   ├── slide2.xml
│   │   └── _rels/
│   │       ├── slide1.xml.rels
│   │       └── slide2.xml.rels
│   ├── slideLayouts/…
│   ├── slideMasters/…
│   ├── notesSlides/…
│   ├── theme/…
│   └── media/            (images, video, audio)
```

XML parts are pretty-printed. Non-XML parts (images, embedded fonts) are
copied byte-for-byte.

## Slide order lives in `ppt/presentation.xml`

Slide order is a list of `<p:sldId>` elements inside `<p:sldIdLst>`:

```xml
<p:sldIdLst>
  <p:sldId id="256" r:id="rId2"/>
  <p:sldId id="257" r:id="rId3"/>
  <p:sldId id="258" r:id="rId4"/>
</p:sldIdLst>
```

Each `r:id` points at a `<Relationship>` in `ppt/_rels/presentation.xml.rels`,
which in turn names the slide part (`slides/slide1.xml`, etc.).

- **Reorder**: rearrange `<p:sldId>` elements. The `id=` values must stay
  unique but do not need to be sequential.
- **Delete**: remove the `<p:sldId>` element. Run `prune.py`
  afterwards to also delete the slide part and its rels; otherwise the
  file just gets bigger while the deleted slide stays hidden.
- **Add**: use `insert_slide.py` (below) — never manually copy
  `slide{n}.xml` files. Manual copying misses the `_rels` file, the
  `[Content_Types].xml` entry, and the notes back-reference.

## `insert_slide.py`

Two modes:

```bash
# Duplicate an existing slide (copies the slide XML and its rels; the
# notesSlide part is *shared* with the original, not copied)
uv run --with python-pptx python scripts/insert_slide.py unpacked/ --clone slide3.xml

# Build a new blank slide from a layout
uv run --with python-pptx python scripts/insert_slide.py unpacked/ --blank-from slideLayout5.xml
```

Both modes print the new slide's `<p:sldId>` element. Paste it into
`<p:sldIdLst>` at the position you want:

```
<p:sldId id="272" r:id="rId17"/>
```

The `id` and `rId` are guaranteed unique by the script.

## `prune.py`

```bash
uv run --with python-pptx python scripts/prune.py unpacked/
uv run --with python-pptx python scripts/prune.py unpacked/ --dry-run   # report only
```

Drops any slide not referenced by `<p:sldIdLst>`, its `_rels/*.xml.rels`,
any orphaned notes slides, and any media files (`ppt/media/*`) not
referenced by a remaining rels file. Prints a summary of what was
removed.

Run this before `assemble.py` whenever you've done a delete or you're
touching a hand-edited exploded tree.

## Editing slide XML

Every slide is a self-contained XML file whose top-level element is
`<p:sld>`. Text lives inside runs (`<a:r>`) inside paragraphs (`<a:p>`)
inside text bodies (`<p:txBody>`) inside shape (`<p:sp>`) elements:

```xml
<p:sp>
  <p:nvSpPr>...</p:nvSpPr>
  <p:spPr>...</p:spPr>
  <p:txBody>
    <a:bodyPr wrap="square"/>
    <a:lstStyle/>
    <a:p>
      <a:pPr algn="l"/>
      <a:r>
        <a:rPr lang="en-US" sz="2800" b="1"/>
        <a:t>Revenue grew 34%</a:t>
      </a:r>
    </a:p>
  </p:txBody>
</p:sp>
```

To change the text, edit the `<a:t>` element. To bold it, add `b="1"` on
`<a:rPr>`. To make it 24pt, set `sz="2400"` (units are hundredths of a
point).

Rules:

- **Preserve whitespace on `<a:t>`** — leading/trailing spaces are
  stripped unless the element carries `xml:space="preserve"`.
- **Never concatenate multi-item content into one `<a:t>`.** Give each
  bullet or step its own `<a:p>` element with its own `<a:pPr>`.
- **Use XML entities for smart quotes and non-ASCII inside `<a:t>`** if
  your editor mangles UTF-8. `&#x201C;` for `“`, `&#x201D;` for `”`,
  `&#x2018;` / `&#x2019;` for single quotes.
- **Do not use `xml.etree` to write PresentationML.** It corrupts
  namespaces on write. Use `lxml.etree` or `defusedxml.minidom`.
- **Bullet formatting is inherited from the layout by default.** If you
  add a `<a:buChar>` or `<a:buNone>`, it overrides the layout — do so
  only when you actually mean to.

## Comments

PowerPoint comments live in `ppt/comments/` (modern format) or
`ppt/commentAuthors.xml` + per-slide `commentsN.xml` (legacy format).
`python-pptx` does not expose comments; edit the XML directly:

```xml
<!-- ppt/commentAuthors.xml -->
<p:cmAuthorLst xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cmAuthor id="0" name="Reviewer" initials="RV" lastIdx="1" clrIdx="0"/>
</p:cmAuthorLst>
```

```xml
<!-- ppt/comments/comment1.xml -->
<p:cmLst xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cm authorId="0" dt="2026-07-04T09:00:00Z" idx="1">
    <p:pos x="1000" y="1000"/>
    <p:text>Please double-check this metric.</p:text>
  </p:cm>
</p:cmLst>
```

Add matching entries in `[Content_Types].xml` and in the slide's rels
file. Comments are rendered by PowerPoint's review pane; they do not
appear on the slide surface.

## Reassemble

```bash
uv run --with python-pptx python scripts/assemble.py unpacked/ output.pptx
uv run --with python-pptx python scripts/diagnose.py output.pptx
```

`assemble.py` writes `[Content_Types].xml` first (matching PowerPoint's
convention), then all other parts in POSIX-sorted order. Two consecutive
assemblies of the same unmodified tree produce byte-identical archives.

## Editing slide masters

The slide master defines the theme colors, the master fonts, and the
default text placeholders that every layout (and thus every slide)
inherits from. Editing the master is the fastest way to re-theme an
entire deck.

Master XML lives at `ppt/slideMasters/slideMaster1.xml`. To change all
titles to a deep navy:

```xml
<!-- inside <p:txStyles><p:titleStyle><a:lvl1pPr>...</a:lvl1pPr> -->
<a:defRPr sz="4000" b="1">
  <a:solidFill>
    <a:srgbClr val="1F3A5F"/>
  </a:solidFill>
</a:defRPr>
```

Colors from a scheme are safer than hex-coded overrides — they let you
retheme by swapping the theme XML:

```xml
<a:defRPr sz="4000" b="1">
  <a:solidFill>
    <a:schemeClr val="accent1"/>
  </a:solidFill>
</a:defRPr>
```

The scheme colors themselves are in `ppt/theme/theme1.xml` under
`<a:clrScheme>`.

## Common XML pitfalls

- **Ghost slides in the ZIP** — deleting a `<p:sldId>` leaves the slide
  part behind. `prune.py` is not optional; run it.
- **Wrong content type after adding a comment or chart** — a new part
  must have a matching `<Override PartName="..." ContentType="..."/>` in
  `[Content_Types].xml`, or PowerPoint refuses to render it.
- **Editing XML with `xml.etree`** — corrupts default namespaces on
  write (`<a:p>` becomes `<ns0:p>`). Use `lxml.etree` (`etree.tostring(..., pretty_print=True, xml_declaration=True, encoding="UTF-8")`)
  or `defusedxml.minidom.parseString` (run such a script with
  `uv run --with python-pptx --with defusedxml python fix_xml.py`).
- **Editing a layout placeholder moves every slide** — slides inherit
  placeholder position from the layout unless they override it. Verify
  with the rendered-layout check.

## After you edit

Always run the QA checklist from `SKILL.md`:

```bash
uv run --with python-pptx python scripts/diagnose.py output.pptx
uv run --with python-pptx python scripts/dump_text.py output.pptx --notes | grep -Ei "\{\{|TODO|TBD|lorem|click to add"
```

Then run the `document_preview` tool on the output. Assume something is
wrong; a grep with no match exits non-zero, which is the check passing.
