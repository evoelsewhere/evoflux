---
name: docx
description: "Create, inspect, or edit Word documents (.docx), including reports, proposals, forms, templates, tracked changes, and comments, with a design-first OpenXML workflow. Triggers on DOCX, Word document, or Word template."
---

# DOCX

For a new Word document, call `docx_engine(action="catalog")`, then
`docx_engine(action="compose", ...)`. The model owns the document archetype,
content, semantic blocks, and content-completeness contract; the engine owns
styles, native numbering, table geometry, headers/footers, render, and QA. Do
not write a free-form `python-docx` script for routine creation. Low-level
OpenXML remains an escape hatch for unsupported features and template edits.

## Template-first contract

If a DOCX is supplied, copy and patch it; do not rebuild an approximation.
Inspect stable paragraph IDs, content-control tags, tables, headers, and
footers, then create an explicit mutation plan:

```bash
python "{SKILL_DIR}/scripts/template.py" inspect template.docx \
  --out /tmp/template-manifest.json
python "{SKILL_DIR}/scripts/template.py" apply template.docx output.docx \
  --plan /tmp/template-edit-plan.json
python "{SKILL_DIR}/scripts/template.py" verify template.docx output.docx \
  --plan /tmp/template-edit-plan.json
```

Supported plan actions are `replace_paragraph` (prefer `para_id`, otherwise
use inspected `paragraph` index), `replace_content_control` (`tag`), and
`replace_table_cell` (`table`, `row`, `column`). Set `part` when targeting a
header, footer, note, or comments part. The editor preserves run formatting
and changes only listed XML parts; styles, numbering, settings, theme, and
fonts are protected.

## Workflow

1. Classify every input as `source to edit`, `fillable template`, `visual
   reference`, or `content source`.
2. For an existing DOCX, copy it to the output path and make local edits. Read
   `word/document.xml`, styles, numbering, headers, footers, relationships, and
   comments before changing layout. A template is a contract, not inspiration.
   Prefer tagged content controls and paragraph IDs over text search.
3. For a new DOCX, call the engine catalog, then select a document profile:
   `standard-business`, `compact-reference`, `narrative-proposal`, or
   `operational-sop`. Resolve it into page size/margins, fonts, type scale,
   paragraph rhythm, heading colors, table geometry, header/footer, and accent
   tokens. Express the document as semantic paragraphs, headings, real lists,
   callouts, quotes, fixed-geometry tables, images, and page breaks.
4. Build a content-completeness contract before pagination. Persist required
   sections or fields with `declare_content_contract`; QA must fail if a
   decision, requirement, owner, procedure step, acceptance check, source, or
   appendix is silently removed merely to shorten the document.
5. Compose through `docx_engine`; its schema rejects unknown blocks, malformed
   table geometry, and unsafe asset paths before writing.
6. Run `docx_engine(action="validate", render=true)`, inspect every page, then
   fix and repeat. Deliver only the final DOCX unless the user asks for sources
   or previews.

## Design rules

- Match the user's language in the document and filename.
- Match density to the archetype. A short memo may use generous spacing;
  a compact reference or SOP should preserve operational detail through a
  tighter type scale, shorter paragraph rhythm, explicit steps, checklists,
  metadata blocks, and well-structured tables. Do not inflate headings or
  create decorative whitespace that pushes useful content into unnecessary
  pages.
- Profile defaults:
  - `standard-business`: 11 pt body and formal memo/report hierarchy;
  - `compact-reference`: 10.5 pt body with compact labels, lists, and tables;
  - `narrative-proposal`: 11 pt body with more generous prose rhythm;
  - `operational-sop`: 10 pt body, compact steps/checks, and high information
    density without fixed-height rows.
- Prefer a strong title block, restrained low-saturation palette, clear
  hierarchy, and generous whitespace over decorative clutter.
- Use a cover only when the archetype benefits from one. Reports and proposals
  usually do; short memos and forms usually do not.
- Add a TOC for long documents with three or more substantive sections. Use a
  real field and add a subtle instruction to update it on first open.
- Headers and page-number footers are the default for multi-page documents.
- Use real Word headings, bullets, and numbering. Never simulate bullets or
  numbered lists with text characters.
- Tables are for repeated row/column data, not for laying out prose. Set
  `tblGrid`, cell widths, margins, alignment, repeating header rows, and allow
  rows to grow.
- Dense content is not itself a defect. QA should reject clipping, missing
  sections, fake lists, weak navigation, fixed row heights, broken table
  geometry, and unstructured walls of text—not a legitimate number of steps,
  rows, or paragraphs.
- Keep headings with the following paragraph; enable widow/orphan control; do
  not use fixed row heights that can clip content.
- Native, editable document content wins over screenshots. Use raster charts
  only when the requested chart cannot reasonably be represented as an
  editable Word table or native chart package.

## Creation stack

Use:

```python
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
```

Start from a clean `Document()` for new files. Configure styles and sections
before adding body content. For existing files, load the copy with
`Document(output_path)` and preserve untouched package parts.

Use `scripts/stylekit.py` for deterministic page geometry, typography, tables,
fields, and header/footer helpers. For advanced edits, the existing
`scripts/office/` utilities can unpack, validate, and repack OOXML.

To accept common tracked revisions without an Office application, run:

```bash
python "{SKILL_DIR}/scripts/accept_changes.py" tracked.docx accepted.docx
```

This unwraps insertions, removes deletions/moved-from content and revision
property snapshots, and disables revision tracking with direct OOXML edits.

For template edits, run the `verify` subcommand in `scripts/template.py`
before `scripts/qa.py`. Any unplanned package-part change is a regression even
if Word opens the file.

## Required QA

Run:

```bash
python "{SKILL_DIR}/scripts/qa.py" output.docx --render-dir /tmp/docx-render
```

For a template edit, include the unmodified source:

```bash
python "{SKILL_DIR}/scripts/qa.py" output.docx \
  --render-dir /tmp/docx-render --compare-to template.docx
```

The structural gate must pass. The bundled Chromium OpenXML renderer produces
approximately paginated PNGs without LibreOffice, carries page geometry,
headers, footers, inline images, paragraph spacing, and tables, and checks DOM
overflow. Its report deliberately says `confidence: approximate` because CSS
pagination is not the Microsoft Word layout engine. Inspect every image at full
size. If Chromium is unavailable, say so in the handoff and do not claim visual
QA passed.

Before delivery also confirm:

- all requested content is present;
- there are no leftover placeholders or fake bullets;
- headings, tables, images, links, comments, and revisions are structurally
  intact;
- no clipping, overlap, broken page breaks, missing glyphs, or large accidental
  gaps appear in the latest render.
