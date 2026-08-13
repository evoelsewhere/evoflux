# PDF form workflow

Use this workflow only for filling or inspecting PDF forms. Keep the source
immutable and store sensitive field values only as long as the task requires.
Use the confirmed Python interpreter for commands below; command examples omit
the interpreter name for portability.

## Route by form type

1. Run `scripts/check_fillable_fields.py <input.pdf>`.
2. If AcroForm fields exist, use the fillable-field path.
3. Otherwise use the annotation fallback only when the user accepts that the
   result will contain annotations rather than native fields.

## Fillable AcroForm path

1. Run
   `scripts/extract_form_field_info.py <input.pdf> <field-info.json>`.
2. Review every field ID, type, page, rectangle, and allowed value. Render the
   relevant pages with `scripts/convert_pdf_to_images.py` to understand labels.
3. Create a JSON list containing only intended values:

```json
[
  {
    "field_id": "legal_name",
    "description": "Applicant legal name",
    "page": 1,
    "value": "Example Name"
  }
]
```

For checkboxes, radio groups, and choices, use an exact value reported by the
inspection script. Do not guess export values.

4. Run
   `scripts/fill_fillable_fields.py <input.pdf> <values.json> <output.pdf>`.
5. Re-extract fields from the output, compare intended values, and render every
   changed page. Confirm appearances are visible and not clipped.

Do not flatten fields unless requested. Preserve field names, annotations,
page boxes, and unrelated values; do not introduce document JavaScript.

## Non-fillable annotation fallback

1. Run `scripts/extract_form_structure.py <input.pdf> <structure.json>`.
2. Prefer extracted text labels, lines, and boxes over visual estimation. If
   the page is scanned, render it and determine coordinates from the image.
3. Remember the coordinate boundary:
   PDF points usually use bottom-left origin; rendered images use top-left.
4. Create a fields document with page metadata and bounding boxes:

```json
{
  "pages": [
    {"page_number": 1, "pdf_width": 612, "pdf_height": 792}
  ],
  "form_fields": [
    {
      "description": "Applicant legal name",
      "page_number": 1,
      "label_bounding_box": [72, 96, 180, 112],
      "entry_bounding_box": [190, 92, 500, 116],
      "entry_text": {"text": "Example Name", "font_size": 11}
    }
  ]
}
```

5. Run `scripts/check_bounding_boxes.py <fields.json>`. Fix every overlap or
   undersized entry box.
6. Optionally overlay boxes on a rendered page with
   `scripts/create_validation_image.py` and inspect the result.
7. Run
   `scripts/fill_pdf_form_with_annotations.py <input.pdf> <fields.json> <output.pdf>`.
8. Render every changed page and confirm text alignment, clipping, contrast,
   page rotation, and checkbox placement.

Annotations are not native form fields and may print or flatten differently.
State this limitation in the deliverable.

## Stop conditions

Stop when field identities or coordinates are ambiguous, a required value was
not supplied, or output appearances cannot be verified. Never infer sensitive
answers from unrelated conversation context.
