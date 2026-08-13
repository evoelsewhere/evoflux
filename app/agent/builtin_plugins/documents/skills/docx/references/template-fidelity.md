# DOCX template fidelity

Use when an uploaded DOCX controls the structure or appearance of a new or
edited document. The retained source is immutable and authoritative.

## Distill the source before editing

Record the source path and hash. Inspect every distinct page and section
pattern, not only the first page. Inventory page geometry, styles, numbering,
headers and footers, tables, drawings, relationships, fields, bookmarks,
content controls, comments, and opaque package parts.

Build an edit contract that identifies each intended slot by stable structure:
package part and structural path, style, bookmark, verified table coordinate,
content-control tag, relationship, or another inspected identifier. Record the
slot's purpose, allowed content, capacity, and whether it is editable,
preserve-only, or removable. Do not locate a target only by copied prose.

## Edit a copy conservatively

- Start from a working copy of the source, never a blank document or the
  uploaded file itself.
- Change only verified slots and preserve untouched styles, numbering,
  relationships, headers, footers, images, tables, and package parts.
- Prefer substring or run-level edits when surrounding rich text must remain.
- Reuse source components. If content does not fit, shorten it, use another
  documented source pattern, or stop; do not silently shrink type or overlay a
  second design system.
- Use a narrowly scoped OOXML patch only for an inspected feature that
  `python-docx` cannot preserve. Do not claim fidelity when the edit requires
  rebuilding an unsupported object.

## Fidelity gate

After saving, compare package parts and relationships with the baseline. Every
changed part must be explained by the edit contract. Reopen the exact output,
rerun relevant structural audits, render every page, and compare recurring
chrome, geometry, pagination, typography, tables, fields, and images with the
source pattern.

Pixel similarity alone is insufficient: relationships, bookmarks, numbering,
comments, controls, or drawing anchors can regress without an obvious visual
change. Any unexplained structural loss or movement outside intended slots is
a failure. Confirm the original source hash is unchanged before delivery.
