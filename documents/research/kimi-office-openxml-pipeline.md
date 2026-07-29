# Kimi-inspired Office artifact pipeline for EvoFlux

Date: 2026-07-29

## Research question

How should EvoFlux replace its external Office authoring binary with a
self-contained workflow that produces better DOCX, PPTX, and XLSX artifacts?

## Sources reviewed

- Kimi Agent product page: https://www.kimi.com/agent
- Kimi Code CLI Agent Skills documentation:
  https://moonshotai.github.io/kimi-cli/en/customization/skills.html
- Kimi Code CLI source: https://github.com/MoonshotAI/kimi-cli
- Community archive describing extracted Kimi document skills:
  https://github.com/thvroyal/kimi-skills
- `python-docx` documentation: https://python-docx.readthedocs.io/
- `python-pptx` documentation: https://python-pptx.readthedocs.io/
- `openpyxl` documentation: https://openpyxl.readthedocs.io/

## What is verifiable

Kimi publicly presents documents, slides, and spreadsheets as agent
deliverables. Kimi Code CLI uses progressive skill discovery: the model sees
skill metadata first and loads the full workflow only when relevant. This is
compatible with EvoFlux's existing `SKILL.md` loader.

The community archive is useful for understanding workflow ideas, but it is not
an official Moonshot repository and does not provide a redistributable
open-source license. Its code and prompts must therefore not be copied into
EvoFlux.

The reusable ideas are architectural:

1. Separate new-file creation from template-preserving edits.
2. Treat design as a token system rather than scattered formatting.
3. Prefer native OpenXML objects so charts, tables, formulas, and text remain
   editable.
4. Validate structure and content after each meaningful build block.
5. Render the final artifact and visually inspect every page, slide, or sheet.
6. Keep sources and calculations auditable inside the artifact.

No official, licensed Kimi PPTX implementation was found. Community PPTX
examples commonly use `python-pptx`, but EvoFlux's presentation workflow and
helpers are an independent implementation.

## EvoFlux decision

Use a Python-only OpenXML stack that can be bundled consistently on macOS,
Linux, and Windows:

| Format | Authoring/editing | Deep control | Structural QA | Visual QA |
| --- | --- | --- | --- | --- |
| DOCX | `python-docx` | `lxml` + targeted OOXML | package/content/style checks | Chromium OpenXML pagination (`approximate`) |
| PPTX | `python-pptx` | targeted OOXML | bounds, placeholders, charts, overflow heuristics | Chromium OpenXML slide PNGs (`medium`) |
| XLSX | `openpyxl` | direct worksheet/workbook XML when required | formulas, cached errors, charts, package checks | Chromium OpenXML sheet PNGs (`medium`) |

The sidecar now bundles these libraries, Playwright, and its matching Chromium
runtime directly. Artifact authoring and visual QA no longer depend on a
platform-specific Office executable or a warm resident process. Preview HTML is
generated in-process from OpenXML, then Chromium provides deterministic PNG
capture and DOM overflow checks.

The current browser renderer resolves PowerPoint theme colors and inherited
backgrounds, composites non-placeholder master/layout artwork, and keeps native
slide charts, tables, pictures, and shapes in their source geometry. Workbook
charts and images are placed from their worksheet drawing anchors rather than
shown in a detached gallery. DOCX uses explicit page geometry plus repeated
headers/footers and table splitting. These are visual-QA approximations; the
template editor still protects the original OpenXML parts as the fidelity
source of truth.

PPTX creation now uses a layout-first gate. New slides select one of five flat
silhouettes before copy is written, reserve named regions with a collision
guard, and reject text that cannot fit at the minimum readable font size.
Structural and Chromium QA detect title wrapping, text capacity, shape
collisions, excessive rounded-card styling, and overly dense slides. When a
template is supplied, unchanged layout debt is baselined so preservation does
not create false failures, while new or worsened issues remain blocking.

## Quality gates

Each built-in skill follows the same lifecycle:

```text
classify input
  -> inspect source/template
  -> declare a mutation map
  -> patch a working copy
  -> replay the mutation map and diff package parts
  -> structural QA
  -> render
  -> inspect every visual
  -> repair and repeat
  -> deliver only the final artifact
```

Format-specific gates:

- DOCX: target paragraphs by stable paragraph ID or tagged content control;
  preserve styles, numbering, settings, headers, fields, and relationships.
- PPTX: map output slides to inspected source frames and target stable shape
  IDs; protect masters, layouts, themes, geometry, typography, and brand marks.
- XLSX: target explicit sheet/cell addresses; retain cell style IDs and protect
  styles, formulas outside the map, charts, tables, pivots, drawings, and VBA.

The template editors work directly on ZIP package parts. Every unselected part
is copied byte-for-byte. Verification replays the declared plan into a clean
copy and requires the delivered package to match it exactly, so an unplanned
change inside an otherwise allowed slide, worksheet, or document part is also
detected.

## Known limits

- Python libraries do not cover every OpenXML feature. Existing unsupported
  features should be preserved by editing a copied package and patching only
  the smallest XML part.
- The first template-editing contract intentionally optimizes substitutions:
  PPTX text/table cells/images, DOCX paragraphs/content controls/table cells,
  and XLSX cell values/formulas. Structural operations such as adding slides,
  changing Word sections, or expanding spreadsheet tables need a larger,
  explicitly reviewed mutation map.
- Production bundles Chromium. Development can use
  `EVOFLUX_CHROMIUM_PATH` or a locally installed Chrome/Chromium. If neither is
  available, structural QA still runs and the report identifies the fallback
  as `structural-only`.
- Browser output is visual lint, not a claim of Microsoft Office pixel parity.
  PPTX and XLSX use `medium` confidence. DOCX uses `approximate` confidence
  because Word-compatible pagination is a separate layout engine.
- Spreadsheet formula evaluation is delegated to Excel/LibreOffice. Workbooks
  request full automatic recalculation on open, while QA also checks any cached
  results already present.
