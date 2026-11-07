"""Capture the desktop UI with sample data for the README banner.

Loads the desktop app's Vite dev server in Playwright's Chromium with a fake
Tauri IPC (``mock-tauri.js``: a canned chat replayed by a fake engine) and a
small fake repository for the Files tool (``mock-fs.js``). Nothing here is
app code, and the app itself always runs against the real engine.

Writes ``app-light.png`` and ``app-dark.png`` (1680x1000 at 2x) to
``docs/assets/readme/`` unless another folder is given.

Example::

    cd apps/desktop && bun run dev        # Vite on http://localhost:1420
    python scripts/readme-shots/capture_app.py
"""

from __future__ import annotations

import argparse
import pathlib
import re

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
WIDTH, HEIGHT = 1680, 1000

# Saved UI state the app reads at startup: theme and panel widths.
STORAGE = """
try {{
  localStorage.setItem('evo.theme', '{theme}');
  localStorage.setItem('evo.ui', JSON.stringify({{ state: {{ sidePanelWidth: 760, sidebarWidth: 256 }}, version: 0 }}));
}} catch {{}}
"""

# Put the turn's "Completed in" line near the top of the thread.
SCROLL_CHAT = """(offset) => {
  const anchor = [...document.querySelectorAll('button')].find((b) => b.innerText.trim().startsWith('Completed in'));
  let el = anchor;
  while (el && !(el.scrollHeight > el.clientHeight + 4 && getComputedStyle(el).overflowY !== 'visible')) el = el.parentElement;
  if (el) el.scrollTop += anchor.getBoundingClientRect().top - el.getBoundingClientRect().top - offset;
}"""

# Show the editor from `line`, scrolled fully left (opening a file can leave
# it scrolled under the sticky gutter).
SCROLL_EDITOR = """(line) => {
  const scroller = document.querySelector('.cm-scroller');
  if (!scroller) return;
  const height = document.querySelector('.cm-line')?.getBoundingClientRect().height || 18;
  scroller.scrollTop = (line - 1) * height;
  scroller.scrollLeft = 0;
}"""


def capture(url: str, out: pathlib.Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for theme in ("light", "dark"):
                context = browser.new_context(
                    viewport={"width": WIDTH, "height": HEIGHT},
                    device_scale_factor=2,
                    color_scheme=theme,
                )
                context.add_init_script(path=str(HERE / "mock-tauri.js"))
                context.add_init_script(path=str(HERE / "mock-fs.js"))
                context.add_init_script(STORAGE.format(theme=theme))
                page = context.new_page()
                errors: list[str] = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(2500)
                page.evaluate("document.fonts.ready")

                # Unfold the turn and its edit steps, then open fetch.rs in Files.
                page.get_by_text(re.compile(r"^Completed in")).first.click()
                page.wait_for_timeout(600)
                page.get_by_text(re.compile(r"^Edited files and ran commands")).first.click()
                page.wait_for_timeout(600)
                page.get_by_text(re.compile(r"^Edited crates/evo-web/src/fetch\.rs")).first.click()
                page.wait_for_timeout(1500)

                page.evaluate(SCROLL_EDITOR, 27)
                page.evaluate(SCROLL_CHAT, 24)
                page.wait_for_timeout(500)
                page.evaluate(SCROLL_EDITOR, 27)
                page.mouse.move(WIDTH // 2, HEIGHT - 2)
                page.wait_for_timeout(600)

                target = out / f"app-{theme}.png"
                page.screenshot(path=str(target))
                print(f"wrote {target}")
                unknown = page.evaluate("[...window.__mockUnknown].sort()")
                if unknown:
                    print(f"  commands answered with null: {', '.join(unknown)}")
                for error in errors:
                    print(f"  page error: {error}")
                context.close()
        finally:
            browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", default="http://localhost:1420/", help="the desktop app's Vite dev server")
    parser.add_argument("--out", type=pathlib.Path, default=REPO / "docs" / "assets" / "readme")
    args = parser.parse_args()
    capture(args.url, args.out)


if __name__ == "__main__":
    main()
