# Advanced PDF operations

Use this reference only after the PDF skill's basic lane selection is
insufficient. Probe the workspace before choosing an optional executable.

## Select the smallest available engine

| Need | Preferred engine | Important boundary |
|---|---|---|
| Page count, merge, split, crop, metadata, forms | `pypdf` | Does not render pages or perform OCR |
| Text, word boxes, simple tables | `pdfplumber` | Coordinates use a top-origin model in many APIs |
| Raster verification | `pypdfium2` | A render proves appearance, not semantic preservation |
| New authored pages | ReportLab | Test font coverage and page overflow |
| Repair, linearize, advanced encryption | `qpdf` when installed | It is optional and not bundled by the plugin |
| OCR | An available OCR engine | Preserve the source raster; verify the text layer |

Do not introduce a second language/runtime such as `pdf-lib` unless it is
already part of the user's project and materially safer for the requested job.

## Inspect before mutation

Record file hash, page count, page boxes, rotation, encryption, metadata,
bookmarks, annotations, form presence, attachments, and whether each page has
a usable text layer. Reject ambiguous page ranges and never overwrite the
source.

PDF coordinates are measured in points. Confirm whether the selected library
uses bottom-left or top-left origin before placing annotations, crops, or form
values. Account for CropBox, MediaBox, and page rotation.

## Transform safely

- Preserve page order, dimensions, boxes, bookmarks, links, annotations,
  metadata, and forms unless the request explicitly changes them.
- Merge or split with explicit zero-based/one-based conversions at the API
  boundary; verify the resulting page sequence independently.
- Crop by changing the intended page box only after checking rotation and
  content bounds. Cropping is not redaction.
- When encrypting, confirm the requested user/owner password behavior and
  permissions by reopening with the intended credentials.
- When decrypting, never log or return the password.

## Create with ReportLab

Use Platypus for flowing documents and canvas primitives for fixed-position
content. Register fonts deliberately, test every required language glyph, use
`<sub>`/`<super>` inside ReportLab paragraphs, and split long tables across
pages with repeated headers. Render every created page.

## OCR and redaction

Treat OCR as unavailable until an engine is discovered. Keep the original
image layer, use the correct language packs, and sample low-confidence text.
Verify that the final PDF is searchable without shifting the visible page.

For redaction, remove or rewrite underlying text, images, annotations, and
metadata before drawing any replacement fill. Confirm with text extraction,
object inspection, and raster review. A black rectangle alone is not redaction.

## Resource and failure handling

Process large documents page-by-page, close readers/bitmaps promptly, and bound
render resolution. Do not weaken encryption or discard damaged objects merely
to make a file reopen. If repair changes structure, compare page count,
rendered appearance, text, forms, and navigation with the source and disclose
the repair.
