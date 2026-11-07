# Editing a .pptx: template fill and slide surgery

Three workflows, listed by increasing invasiveness. Pick the least invasive
one that solves the task. This file covers the first two; the raw XML
workflow is in `edit-xml.md`.

| Workflow | When to use |
|----------|-------------|
| **Template fill** — python-pptx, keep styling | You have a `.pptx` template and want to replace text / images while keeping the design |
| **Slide surgery** — reorder, add, delete slides | Structure changes but content per slide stays the same |
| **Raw XML** — explode → edit → assemble (`edit-xml.md`) | Anything the python-pptx API doesn't expose: custom XML parts, uncommon shapes, deep master edits, chart-bearing slide duplication |

Never overwrite the original file: write to a new path, run the QA checks,
then hand off. Python snippets go into a `.py` file in the workspace and run
with `uv run --with python-pptx python edit_deck.py`.

## Contents

- Template fill: discover the template, fill via python-pptx, double-mustache tokens, picture placeholders, delete unwanted content
- Slide surgery: list, duplicate, reorder, delete
- Common editing pitfalls
- After you edit

## Template fill

The most common editing task: someone hands you a `.pptx` with a designed
look and asks you to swap the content.

### Discover what's in the template

```bash
uv run --with python-pptx python scripts/contact_sheet.py template.pptx --cols 3
uv run --with python-pptx python scripts/dump_text.py template.pptx --notes --numbered > tpl.txt
```

Pair `template.contact-sheet.jpg` with `tpl.txt`: the visual layout of each
slide alongside its text is what you need to decide "the section 2 divider is
slide 4, the two-column team slide is slide 7," and so on. When LibreOffice
is unavailable, run the `document_preview` tool on the template instead; it
lists each slide's elements with their text and position.

### Fill via python-pptx

```python
from pptx import Presentation

prs = Presentation("template.pptx")

# Slides are ordered as they appear in the deck.
slide = prs.slides[0]
slide.shapes.title.text = "Q3 Product Review"                 # replace the title placeholder
slide.placeholders[1].text = "What shipped, what slipped"     # replace the subtitle

# Iterate the placeholders when you don't know the layout by heart:
for ph in slide.placeholders:
    print(ph.placeholder_format.idx, ph.name, "|", (ph.text or "")[:60])

prs.save("filled.pptx")
```

Rules of thumb:

- `shapes.title` is a shortcut for `placeholders[0]` on layouts that have
  one. On a blank layout (`slide_layouts[6]`) it returns `None`.
- Overwriting `.text` collapses all runs in the placeholder into one
  paragraph and one run. That destroys any bold, color, or font-size
  styling inside the placeholder. To preserve styling, replace at the run
  level:

  ```python
  for para in placeholder.text_frame.paragraphs:
      for run in para.runs:
          if "{{title}}" in run.text:
              run.text = run.text.replace("{{title}}", "Q3 Review")
  ```

- Placeholder text set via `.text` inherits the font from the layout —
  which is usually what you want. Set explicit `run.font.size` /
  `run.font.bold` only when you need to override the layout.

### Fill with double-mustache tokens

A robust convention: build the template with `{{title}}`, `{{stat}}`,
`{{point1}}` placeholders inside real placeholder shapes, then fill:

```python
from pptx import Presentation

FILLS = {
    "{{title}}": "Q3 Product Review",
    "{{subtitle}}": "Growth on flat headcount",
    "{{stat}}": "34%",
    "{{stat_label}}": "YoY revenue growth",
}

def replace_in_runs(paragraph, mapping):
    """Replace tokens while preserving each run's styling."""
    for run in paragraph.runs:
        for key, value in mapping.items():
            if key in run.text:
                run.text = run.text.replace(key, value)

prs = Presentation("template.pptx")
for slide in prs.slides:
    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        for para in shape.text_frame.paragraphs:
            replace_in_runs(para, FILLS)
prs.save("filled.pptx")
```

Tokens must live in a **single run** or the replacement misses them —
PowerPoint sometimes splits `{{title}}` across two runs when you edit the
template by hand. Fix this by re-typing the token from scratch inside
PowerPoint, or by joining runs before replacement:

```python
def joined_text(paragraph):
    return "".join(r.text for r in paragraph.runs)

def replace_and_rewrite(paragraph, mapping):
    text = joined_text(paragraph)
    for key, value in mapping.items():
        text = text.replace(key, value)
    if not paragraph.runs:
        return
    # keep the first run's styling; drop the rest
    for run in paragraph.runs[1:]:
        run._r.getparent().remove(run._r)
    paragraph.runs[0].text = text
```

### Fill images inside placeholders

Some templates have picture placeholders (`ph_type == PP_PLACEHOLDER.PICTURE`).
Replace them with:

```python
from pptx.util import Inches

for ph in slide.placeholders:
    if ph.placeholder_format.type != 18:      # PP_PLACEHOLDER.PICTURE
        continue
    ph.insert_picture("photo.png")            # keeps the placeholder's crop and position
```

If the template uses a plain image shape (not a picture placeholder),
delete the old shape and add a new one at the same position:

```python
old = None
for shape in slide.shapes:
    if shape.shape_type == 13 and shape.name == "hero_image":  # 13 = PICTURE
        old = shape
        break
if old is not None:
    left, top, width, height = old.left, old.top, old.width, old.height
    old._element.getparent().remove(old._element)
    slide.shapes.add_picture("photo.png", left, top, width, height)
```

### Delete unwanted content

Never leave a placeholder holding `{{project_name}}` or `Click to add
title` — a QA reviewer will spot it in five seconds. If a slide has more
slots than content, delete the slot entirely rather than clearing its
text:

```python
for shape in list(slide.shapes):
    if shape.has_text_frame and shape.text_frame.text.strip().startswith("{{unused"):
        shape._element.getparent().remove(shape._element)
```

## Slide surgery

### List / print slides

```python
from pptx import Presentation
prs = Presentation("input.pptx")
for i, s in enumerate(prs.slides):
    title = s.shapes.title.text if s.shapes.title else "(no title)"
    print(f"{i:2d}  layout={s.slide_layout.name!r:35s}  title={title!r}")
```

### Duplicate a slide

`python-pptx` doesn't ship a first-class `duplicate()`. For a slide with
charts, embedded objects, or custom XML, use `scripts/insert_slide.py --clone`
on an exploded tree (`edit-xml.md`). For a shallow duplicate, use this recipe
based on
[python-pptx issue #132](https://github.com/scanny/python-pptx/issues/132):

```python
import copy
from pptx import Presentation

def duplicate_slide(prs, index):
    """Duplicate the slide at `index` (0-based); returns the new Slide."""
    src = prs.slides[index]
    blank_layout = src.slide_layout
    new_slide = prs.slides.add_slide(blank_layout)

    # copy every shape from src to new_slide
    for shape in src.shapes:
        el = copy.deepcopy(shape.element)
        new_slide.shapes._spTree.insert_element_before(el, "p:extLst")

    # copy speaker notes
    if src.has_notes_slide:
        new_slide.notes_slide.notes_text_frame.text = (
            src.notes_slide.notes_text_frame.text
        )
    return new_slide

prs = Presentation("input.pptx")
duplicate_slide(prs, 3)      # duplicates slide index 3 to the end
prs.save("output.pptx")
```

The copy-shape trick doesn't re-wire the relationships (`_rels/`) that a
chart or embedded media needs: a duplicated chart renders empty.

### Reorder slides

```python
from pptx import Presentation

def move_slide(prs, old_index, new_index):
    """Move slide `old_index` to `new_index` (both 0-based)."""
    xml_slides = prs.slides._sldIdLst
    slides = list(xml_slides)
    xml_slides.remove(slides[old_index])
    xml_slides.insert(new_index, slides[old_index])

prs = Presentation("input.pptx")
move_slide(prs, 5, 1)         # move slide 6 to position 2
prs.save("output.pptx")
```

### Delete slides

```python
from pptx import Presentation

def delete_slide(prs, index):
    slides = list(prs.slides._sldIdLst)
    prs.slides._sldIdLst.remove(slides[index])

prs = Presentation("input.pptx")
delete_slide(prs, 0)          # drops the title slide
prs.save("output.pptx")
```

Deleted slides survive as unreferenced XML parts in the ZIP. That doesn't
break rendering, but it inflates the file. Drop them by exploding, pruning,
and reassembling:

```bash
uv run --with python-pptx python scripts/explode.py output.pptx unpacked/
uv run --with python-pptx python scripts/prune.py unpacked/
uv run --with python-pptx python scripts/assemble.py unpacked/ output-clean.pptx
```

## Common editing pitfalls

- **Placeholder text lost after `.text =`** — assigning to `.text`
  collapses all runs. If the placeholder had a mix of bold + italic +
  colored text, all of that is gone. Fix by iterating `paragraphs[i].runs[j]`
  and replacing per-run.
- **Ghost slides in the ZIP** — deleting a `<p:sldId>` leaves the slide
  part behind. `prune.py` is not optional; run it.
- **Duplicating a chart slide with the copy-shape trick** — the shape
  element gets copied but its relationship to `chart{n}.xml` doesn't.
  The duplicated chart renders empty. For chart-bearing slides, use the
  explode workflow + `insert_slide.py --clone`.
- **Editing shapes that inherit from the layout** — a shape can inherit its
  placeholder position from the layout. If you set `left` / `top` on the
  layout's placeholder, every slide that hasn't overridden it moves. Verify
  with the rendered-layout check.

## After you edit

Run the QA checks from `SKILL.md` once:

```bash
uv run --with python-pptx python scripts/diagnose.py output.pptx
uv run --with python-pptx python scripts/dump_text.py output.pptx --notes | grep -Ei "\{\{|TODO|TBD|lorem|click to add"
```

Then run the `document_preview` tool on the output and fix only what they
report. The most common failure is placeholder text that survived template
fill, which the grep catches.
