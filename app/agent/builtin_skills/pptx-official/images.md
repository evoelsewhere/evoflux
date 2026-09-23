# Image sourcing (choose the right channel)

## Contents

- The four channels
- Downloading a URL for `add_picture`
- Decision (run per slide)
- Anti-patterns
- Scene defaults (rough mix per deck type)

"Every slide earns its visuals" does **not** mean "generate an image for
every slide." Choose the source based on what the image does.

## The four channels

Ordered by preference (lower cost and higher stability first):

**L1 · Draw in code.** Icons via react-icons / iconify. Charts via
matplotlib / plotly / echarts, or native python-pptx / PptxGenJS charts.
Flowcharts, comparisons, org charts via shapes and lines. Anything that is a
data or concept visualization — never fetch or generate an image for this.

**L2 · Search a stock library, then download the bytes.** When a slide
needs a **generic real photo** (city skyline, office desk, team
collaboration, nature), use `web_search` with a `site:unsplash.com` /
`site:pexels.com` / `site:pixabay.com` query to find a real URL, then
**download the image to a local file** and pass that path to `add_picture`
(see *Downloading* below). python-pptx's `add_picture` only accepts a local
path or a file-like object; it does not fetch a URL.

**L3 · Search a specific source.** For **specific real things** (a particular
company's logo, a product's official screenshot, a named person's photo), use
`web_search` with a targeted query (for example
`"Acme Inc" logo site:acme.com`, or `<product name> screenshot`), then
download the bytes the same way as L2. Never generate this kind of image — a
generated logo will not look like the real logo. `web_fetch` returns
text/markdown/html only and cannot deliver binary image bytes; download with
`shell` + `curl` or Python `urllib`.

**L4 · Generate an image.** Available only when an MCP server or plugin in
the session provides an image-generation tool, and only for **stylized
visuals** — cover art, hero backgrounds, illustration-style concept images.
Budget at most one or two generated images per deck, for the cover or section
dividers. When no such tool is attached, fall back to L1 or L2 and say so; do
not describe an image you could not produce.

## Downloading a URL for `add_picture`

Two working patterns. Both keep the bytes local so `add_picture` can read
them. Run the generator with `uv run --with python-pptx python build_deck.py`.

```python
# Pattern A: download to a file, then pass the path
from urllib.request import Request, urlopen
from pathlib import Path

def download_image(url: str, dest: Path) -> Path:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})  # some CDNs 403 an empty UA
    with urlopen(req, timeout=15) as r:
        dest.write_bytes(r.read())
    return dest

path = download_image(hit_url, Path("assets/hero.jpg"))
slide.shapes.add_picture(str(path), Inches(1), Inches(1.5), width=Inches(11))
```

```python
# Pattern B: in-memory via BytesIO — no temp file, same request headers
from io import BytesIO
from urllib.request import Request, urlopen

req = Request(hit_url, headers={"User-Agent": "Mozilla/5.0"})
with urlopen(req, timeout=15) as r:
    slide.shapes.add_picture(BytesIO(r.read()), Inches(1), Inches(1.5), width=Inches(11))
```

Or from a `shell` step:

```bash
curl -sSL -A "Mozilla/5.0" -o assets/hero.jpg "$URL"
```

Wrap any download in a try/except: on failure fall through to the next
channel or a shape-and-text fallback — never leave a slide blank. Every
outbound fetch is subject to the session's permission and sandbox rules, and
any image you embed must be one the user is licensed to use; when the licence
is unclear, say so instead of embedding it.

## Decision (run per slide)

1. Does this slide actually need a picture? Often the answer is no — a
   large stat callout, a comparison shape, a well-typeset quote, or a
   diagram *is* a visual. Skip pictures when layout and typography carry
   the message.
2. If yes, pick the cheapest channel that works:
   - Data / concept / flow / icon → **L1** (draw in code)
   - Generic real photo → **L2** (stock library search + download)
   - Specific brand / logo / product / person → **L3** (targeted web search + download)
   - Stylized cover / hero / illustration → **L4**, only when an
     image-generation tool is attached; otherwise fall back to L1 or L2
3. If a fetch fails: L2 → L3 → L4 → shape + text fallback. Never leave a
   slide blank because an image failed to load.

## Anti-patterns

- **Generating an image for every content slide.** Slow, expensive,
  style-inconsistent, visually noisy. A 20-slide deck with 20 generated
  images is a red flag, not a success.
- **Passing an HTTP URL to `add_picture`.** python-pptx raises
  `FileNotFoundError` — always download the bytes first.
- **Using `web_fetch` to grab image bytes.** `web_fetch` returns text only.
  Use `shell` + `curl` or Python `urllib` for binaries.
- **Making up a stock-library URL from memory.** Unsplash / Pexels CDN
  paths are opaque hashes — you cannot reliably recall a URL that both
  exists and matches the described content. Always search first, then
  download.
- **Generating a logo, celebrity, or product screenshot.** The output will
  not resemble the real thing. Use a targeted search instead (L3).
- **Executive / status / weekly decks in illustration style.** Work
  reporting is data + icons + hierarchy, not concept art. Reserve L4 for
  launch, brand, or hero visuals.
- **Leaving a slide blank because an image fetch failed.** Always have a
  shape + text fallback; a well-formatted stat callout is a better slide
  than an empty one anyway.

## Scene defaults (rough mix per deck type)

L2 and L3 each cost about one `web_search` plus one download per image —
cheap compared to L4, still not free. L1 remains the default.

| Deck type              | Dominant | Notes                                           |
|------------------------|----------|-------------------------------------------------|
| Status / OKR / weekly  | L1 (~90%) | Icons + data charts. Almost no L2 / L3 / L4.   |
| Strategy / proposal    | L1 + L2  | ~60% L1, ~30% L2 (searched stock), ~10% L4 cover. |
| Sales / pitch          | L2 + L3  | Customer logos and product shots (L3) matter. 1 L4 cover max. |
| Training / education   | L1 (~80%) | Diagrams and flowcharts win.                   |
| Launch / brand         | L4-heavy | Visuals are the point. Still limit style drift and reuse assets. |
| Competitive analysis   | L3-heavy | Logos and screenshots are irreplaceable.        |
