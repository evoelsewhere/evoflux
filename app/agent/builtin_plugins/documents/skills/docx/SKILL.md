---
name: docx
description: Create, edit, inspect, or verify editable Microsoft Word .docx files. Use when a DOCX or Word file is an input or required output, including template-preserving edits; do not trigger for prose, Markdown, PDF, spreadsheet, or slide work with no DOCX input or output.
---

# Work directly with DOCX files

Work with DOCX files using Python and `python-docx`. Keep authoring or
template-edit logic in a task-local script, never flatten an editable document
into screenshots, and never overwrite an uploaded source.

EvoFlux no longer provides a document-authoring tool, job store, or publish
step. Use the workspace's existing Python environment. Confirm `python-docx`
is importable before authoring. Do not silently install it or change the
project's environment; report the missing dependency.

## Choose the path

- **New document:** derive a restrained style system from the audience,
  content, language, and supplied brand assets. Read
  [document design and layout](references/document-design-and-layout.md).
- **Uploaded DOCX used as a template:** inspect styles, sections, package
  parts, relationships, headers, footers, tables, and content controls before
  applying targeted edits. Read
  [template fidelity](references/template-fidelity.md).
- **Uploaded DOCX used only as content:** extract its content and create a new
  document without claiming to preserve its design.
- **Read or review only:** inspect the relevant content and structure, answer
  the question, and do not modify or export the document unless asked.

## Required workflow for create or edit

1. Resolve source and output paths. Write a new `.docx`; keep uploads immutable.
2. Inspect the source package and document model before choosing edit targets.
3. Write and run a deterministic task-local Python authoring script.
4. Reopen the exact saved output with `python-docx` and test the OOXML ZIP.
5. Render every page with an available DOCX renderer and inspect the images.
6. Fix structural or visual defects, rerun the script, and verify the exact
   final bytes. Return the absolute workspace path and state any QA limitation.

## New documents

Use real Word styles and paragraphs for headings and prose, real list styles
for bullets and numbering, native tables, images with alt text, hyperlinks,
section headers and footers, and fields where the library supports them. Base
table widths on the actual section width and margins. Do not use fake bullets,
manual page numbers, repeated punctuation as rules, or tables to package normal
prose. Change layout or content before silently shrinking text.

## Uploaded templates

Prefer edits through stable document structure: paragraph and style identity,
table coordinates established during inspection, bookmarks, or verified plain
text content-control tags. Preserve run formatting when replacing substrings.
Snapshot package-part hashes before editing and review every changed part.

`python-docx` does not provide complete APIs for tracked changes, comments,
all content controls, fields, drawings, or embedded objects. For an unsupported
high-fidelity edit, use a narrowly scoped OOXML patch only after inspecting the
relevant part and relationships; otherwise stop and disclose the limitation.
Never claim preservation merely because the package reopens.

## Verification gate

Use an independent OOXML reopen plus a renderer. EvoFlux's in-app preview and
bundled renderer are semantic approximations, not Microsoft Word layout
engines. When exact pagination or font fidelity matters, also render with Word
or LibreOffice if one is available. If no renderer is available, complete only
structural checks and explicitly say that visual QA was not performed.
