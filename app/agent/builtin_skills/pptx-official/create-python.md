# Creating a .pptx with python-pptx

## Contents

- Which authoring surface?
- Running a generator
- Skeleton
- Text on a slide
- CJK / East-Asian text (Chinese, Japanese, Korean)
- Bulleted list
- Shapes and stat callouts
- Images
- Tables
- Charts
- Speaker notes
- Slide backgrounds
- Section dividers
- Common pitfalls (python-pptx)
- After you generate

## Which authoring surface?

Two surfaces write valid PresentationML that PowerPoint, Keynote, Google
Slides, and LibreOffice open cleanly:

- **python-pptx** (this file) — a Python object model over the spec. Best for
  repeatable, data-driven decks (weekly reports, dashboards, template fill).
- **PptxGenJS** (`create-pptxgenjs.md`) — a TypeScript/JavaScript API with
  more shape and chart primitives. Best for design-heavy custom layouts.

| Constraint | Choice |
|------------|--------|
| Python codebase already | python-pptx |
| Node / TypeScript codebase already | PptxGenJS |
| You want to fill a template made in PowerPoint | python-pptx |
| You want charts with custom colors + rounded backgrounds | PptxGenJS (more knobs) |
| You need speaker notes filled from a script | python-pptx (cleanest API) |
| You need SVG icons or React icon components on every slide | PptxGenJS + `react-icons` |
| You need to run in a container without Node or Bun installed | python-pptx |
| Bulk data → chart-heavy deck (100+ slides) | python-pptx (faster in practice) |

## Running a generator

Write the generator to a `.py` file in the workspace and run it with
`uv run --with python-pptx python build_deck.py`. `python-pptx` pulls in
`lxml` and `Pillow`, which the image recipes below also use.

## Skeleton

```python
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.enum.shapes import MSO_SHAPE
from pptx.dml.color import RGBColor

prs = Presentation()                      # default template opens at 4:3
prs.slide_width  = Inches(13.333)          # so set 16:9 (720p) explicitly
prs.slide_height = Inches(7.5)

# layout indices for the default template:
#   0 title, 1 title+content, 2 section header, 3 two-content,
#   4 comparison, 5 title only, 6 blank, 7 content+caption,
#   8 picture+caption
title_slide = prs.slides.add_slide(prs.slide_layouts[0])
title_slide.shapes.title.text = "Q3 Product Review"
title_slide.placeholders[1].text = "What shipped, what slipped, what's next"

prs.save("review.pptx")
```

## Live build

Build the deck one slide at a time so the user sees it take shape. Create
the file from the outline first — it opens in the preview straight away with
a placeholder per planned slide:

```bash
uv run --with python-pptx python <skill>/scripts/deck_live.py init review.pptx \
  --title "Q3 Product Review" --title "What shipped" --title "What's next"
```

Then write each slide as its own function and save after every one with
`LiveDeck` (atomic saves; the preview redraws each time):

```python
import sys
sys.path.insert(0, "<skill>/scripts")      # this skill's scripts directory
from deck_live import LiveDeck

live = LiveDeck("review.pptx")
prs = live.open()                           # 16:9, no slides yet
for build in (cover, shipped, next_steps):  # one function per outline slide
    build(prs)                              # add exactly one slide
    live.save(prs)
live.finish(prs)                            # marks the deck complete
```

Keep the order and count of `--title`s equal to the slides you add. Run the
QA steps after `finish`.

## Text on a slide

```python
from pptx.util import Pt
from pptx.enum.text import PP_ALIGN

slide = prs.slides.add_slide(prs.slide_layouts[5])   # title-only layout
slide.shapes.title.text = "Revenue grew 34% on 22% headcount"

# free-standing text box (not tied to a placeholder)
tb = slide.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(12.3), Inches(4.5))
tf = tb.text_frame
tf.word_wrap = True

p = tf.paragraphs[0]                   # first paragraph exists by default
p.text = "The efficiency story."
p.alignment = PP_ALIGN.LEFT
p.runs[0].font.size = Pt(28)
p.runs[0].font.bold = True

p2 = tf.add_paragraph()
p2.text = "Every product line beat plan; hiring stayed flat."
p2.runs[0].font.size = Pt(18)
```

Notes on text:

- `text_frame.paragraphs[0]` always exists. Do not call `add_paragraph()`
  for the first line; you'll get a blank line at the top.
- `run.font.size` must be a `Pt(...)` value. Passing a bare integer sets
  raw EMU and produces microscopic text.
- Set `text_frame.word_wrap = True` when you want the box to wrap; otherwise
  the text extends past the box's right edge without a visual clue.
- To match a placeholder's autofit behavior, don't touch it. To disable
  autofit and let text overflow, use `MSO_AUTO_SIZE.NONE`:

  ```python
  from pptx.enum.text import MSO_AUTO_SIZE
  tf.auto_size = MSO_AUTO_SIZE.NONE
  ```

## CJK / East-Asian text (Chinese, Japanese, Korean)

`run.font.name` only sets the **Latin** typeface (`a:latin`). CJK glyphs are
taken from the separate **East-Asian slot** (`a:ea`), which python-pptx does
not expose. If you leave it unset, PowerPoint falls back to a default and
Chinese / Japanese / Korean text often renders as tofu boxes (□□□) or an
inconsistent substitute — even when `run.font.name` looks correct. For any run
containing CJK text, set all three slots (`a:latin`, `a:ea`, `a:cs`) via XML:

```python
from pptx.oxml.ns import qn

def set_cjk_font(run, font_name):
    """Set Latin (a:latin), East-Asian (a:ea) and complex-script (a:cs) typefaces."""
    run.font.name = font_name                      # a:latin (python-pptx inserts it in order)
    rPr = run._r.get_or_add_rPr()
    # a:ea / a:cs aren't exposed by python-pptx, so build them by hand. But a:rPr
    # enforces child order (a:latin, a:ea, a:cs, a:sym, a:hlinkClick, ...); a bare
    # append() lands after any existing a:hlinkClick/a:sym/etc. and yields invalid
    # markup that PowerPoint "repairs" by dropping the font. Insert before the first
    # legal successor instead (a:ea must also precede a:cs).
    successors = {
        "a:ea": ("a:cs", "a:sym", "a:hlinkClick", "a:hlinkMouseOver", "a:rtl", "a:extLst"),
        "a:cs": ("a:sym", "a:hlinkClick", "a:hlinkMouseOver", "a:rtl", "a:extLst"),
    }
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.insert_element_before(el, *successors[tag])
        el.set("typeface", font_name)

set_cjk_font(p.runs[0], "Noto Sans CJK SC")        # a CJK-capable font present on the render machine
```

Choose a font that actually ships CJK glyphs and exists on the machine where
the deck will be viewed. In the common interactive case that's the machine
generating it — use the current OS's standard CJK face (check the platform
from your environment): `Microsoft YaHei` on Windows, `PingFang SC` on macOS,
`Noto Sans CJK SC` on Linux. If the deck targets viewers on a different or
unknown OS, prefer a portable name (`Microsoft YaHei` — every Windows ships
it; other platforms substitute). A wrong-but-CJK name only causes font
substitution; a Latin-only face such as Calibri causes tofu no matter which
slot you set.

## Bulleted list

```python
tf = tb.text_frame
tf.word_wrap = True

for i, item in enumerate(["First point", "Second point", "Third point"]):
    p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
    p.text = item
    p.level = 0
    p.runs[0].font.size = Pt(18)
```

`p.level = 1` for nested bullets. The theme controls the bullet character —
python-pptx does not expose direct control, so if the theme uses squares
and you want dots, either edit the master (`edit-xml.md` → *Editing slide
masters*) or use free text with a manual glyph.

## Shapes and stat callouts

```python
from pptx.enum.shapes import MSO_SHAPE
from pptx.dml.color import RGBColor

slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank

# background block
rect = slide.shapes.add_shape(
    MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), prs.slide_width, prs.slide_height
)
rect.fill.solid()
rect.fill.fore_color.rgb = RGBColor(0x1F, 0x3A, 0x5F)   # deep navy
rect.line.fill.background()                              # no border

# big number
n = slide.shapes.add_textbox(Inches(1), Inches(1.8), Inches(11), Inches(3))
n.text_frame.text = "34%"
r = n.text_frame.paragraphs[0].runs[0]
r.font.size = Pt(140); r.font.bold = True
r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

# label under the number
l = slide.shapes.add_textbox(Inches(1), Inches(5.1), Inches(11), Inches(1))
l.text_frame.text = "YoY revenue growth, Q3 vs Q3"
lr = l.text_frame.paragraphs[0].runs[0]
lr.font.size = Pt(22)
lr.font.color.rgb = RGBColor(0xC8, 0xD3, 0xE6)
```

Anti-pattern: setting the border by leaving `line` untouched. python-pptx's
default is a 1pt black line on rectangles; call `.line.fill.background()`
to make it invisible, or set a color explicitly.

## Images

```python
from pptx.util import Inches
slide.shapes.add_picture("chart.png", Inches(1), Inches(1.5), Inches(11), Inches(5.5))
```

If you omit `width` and `height`, python-pptx uses the image's native pixel
dimensions at 96 DPI. That is usually not what you want — **pass only one
dimension** and let the other be derived to preserve aspect ratio (passing
both `width` and `height` risks stretching the image):

```python
pic = slide.shapes.add_picture("chart.png", Inches(1), Inches(1.5), width=Inches(11))
# height is now (11 / native_w) * native_h, aspect preserved
```

Resample large images before adding them:

```python
from PIL import Image
img = Image.open("photo.jpg")
img.thumbnail((1600, 1600))              # cap the longest side
img.save("photo_small.jpg", quality=88, optimize=True)
slide.shapes.add_picture("photo_small.jpg", Inches(1), Inches(1.5), width=Inches(11))
```

A 4000×3000 photo in a 720p slide bloats the file for zero visual benefit.
`add_picture` needs a local path or file-like object; to use a web image,
download the bytes first (`images.md` → *Downloading*).

## Tables

```python
rows, cols = 4, 3
tbl = slide.shapes.add_table(rows, cols,
    Inches(1), Inches(1.5), Inches(11), Inches(4.5)).table

# header row
headers = ["Metric", "Q2", "Q3"]
for c, h in enumerate(headers):
    tbl.cell(0, c).text = h
    tbl.cell(0, c).text_frame.paragraphs[0].runs[0].font.bold = True

data = [
    ["Revenue", "$4.2M", "$5.6M"],
    ["Gross margin", "62%", "65%"],
    ["Headcount", "48", "51"],
]
for r, row in enumerate(data, start=1):
    for c, v in enumerate(row):
        tbl.cell(r, c).text = v
```

Column widths:

```python
tbl.columns[0].width = Inches(5)
tbl.columns[1].width = Inches(3)
tbl.columns[2].width = Inches(3)
```

## Charts

```python
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE

data = CategoryChartData()
data.categories = ["Q1", "Q2", "Q3", "Q4"]
data.add_series("Revenue ($M)", (3.1, 3.9, 4.6, 5.4))

chart = slide.shapes.add_chart(
    XL_CHART_TYPE.COLUMN_CLUSTERED,
    Inches(1), Inches(1.5), Inches(11), Inches(5.5),
    data
).chart

chart.has_title = True
chart.chart_title.text_frame.text = "Revenue by quarter"
chart.chart_title.text_frame.paragraphs[0].runs[0].font.size = Pt(20)
chart.has_legend = False
```

To style series colors (Office defaults look generic):

```python
from pptx.dml.color import RGBColor
series = chart.series[0]
fill = series.format.fill
fill.solid()
fill.fore_color.rgb = RGBColor(0x0D, 0x94, 0x88)
```

Supported chart types (subset that renders reliably across PowerPoint,
Keynote, LibreOffice):

| Enum member                    | Renders as              |
|--------------------------------|-------------------------|
| `COLUMN_CLUSTERED`             | vertical bars           |
| `BAR_CLUSTERED`                | horizontal bars         |
| `LINE`                         | line chart              |
| `LINE_MARKERS`                 | line + point markers    |
| `PIE`                          | pie                     |
| `DOUGHNUT`                     | donut                   |
| `XY_SCATTER`                   | scatter                 |
| `AREA` / `AREA_STACKED`        | area                    |

## Speaker notes

```python
notes_tf = slide.notes_slide.notes_text_frame
notes_tf.text = (
    "Open by acknowledging the miss on shipping notifications. "
    "Then pivot to the wins: three product launches, growth on flat headcount. "
    "Time to the last slide is roughly six minutes."
)
```

Notes support the same paragraph / run API as any text frame — bold, size,
color all work.

## Slide backgrounds

`python-pptx` does not expose slide background directly; use a full-slide
rectangle at the back z-order:

```python
bg = slide.shapes.add_shape(
    MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height
)
bg.fill.solid()
bg.fill.fore_color.rgb = RGBColor(0xF7, 0xF5, 0xF0)
bg.line.fill.background()

# push it to the back
spTree = bg._element.getparent()
spTree.remove(bg._element)
spTree.insert(2, bg._element)   # 2 skips the layout's nvGrpSpPr + grpSpPr
```

Or edit the master (`edit-xml.md` → *Editing slide masters*).

## Section dividers

Reuse layout 2 (`Section Header`), or clone a title slide and change the
title font to a section-appropriate style. Keeping section dividers on
their own layout means changing every divider is a single edit to the
master.

## Common pitfalls (python-pptx)

- **Reusing shape objects across slides** — `slide.shapes.add_shape(...)`
  returns a new shape. Do not stash the return and re-add to another slide
  — it copies the reference, not the object, and the second slide will
  render with a broken relationship.
- **`RGBColor` argument order** — hex nibbles as three integers. `RGBColor(0xFF, 0x00, 0x00)`
  is red; passing `"FF0000"` string raises `TypeError`.
- **Inches vs. EMU** — `Inches(1) == 914400 EMU`. Never pass raw integers
  to position/size fields unless you actually want EMU.
- **Charts without data** — `add_chart` requires at least one non-empty
  series, else PowerPoint errors on open. Placeholder chart? Give it a
  single `("", 0)` category.
- **Placeholder index depends on the layout.** `slide.placeholders[1]` is
  the subtitle on layout 0 but the *content* box on layout 1. Iterate:
  ```python
  for ph in slide.placeholders:
      print(ph.placeholder_format.idx, ph.name)
  ```

## After you generate

Always run the QA checklist from `SKILL.md` — even three-slide decks fail QA
more often than you'd think. Assume something is wrong; find it.
