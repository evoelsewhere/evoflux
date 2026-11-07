"""Render the README banner to ``banner-light.png`` and ``banner-dark.png``.

The banner is ``docs/assets/readme/banner.html`` (``#dark`` selects the dark
theme); it shows ``app-light.png`` / ``app-dark.png`` from
``capture_app.py``. Output goes next to the HTML, 1600x800 at 2x.

Example::

    python scripts/readme-shots/render_banner.py
"""

from __future__ import annotations

import argparse
import pathlib

from playwright.sync_api import sync_playwright

REPO = pathlib.Path(__file__).resolve().parent.parent.parent


def render(source: pathlib.Path, scale: float) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for theme in ("light", "dark"):
                page = browser.new_page(viewport={"width": 1600, "height": 800}, device_scale_factor=scale)
                page.goto(source.as_uri() + ("#dark" if theme == "dark" else ""), wait_until="networkidle")
                page.evaluate("document.fonts.ready")
                page.wait_for_timeout(500)
                target = source.parent / f"banner-{theme}.png"
                page.locator("#banner").screenshot(path=str(target))
                print(f"wrote {target}")
                page.close()
        finally:
            browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", type=pathlib.Path, default=REPO / "docs" / "assets" / "readme" / "banner.html")
    parser.add_argument("--scale", type=float, default=2)
    args = parser.parse_args()
    render(args.source.resolve(), args.scale)


if __name__ == "__main__":
    main()
