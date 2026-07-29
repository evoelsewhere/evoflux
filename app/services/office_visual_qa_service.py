"""LibreOffice-free visual QA for OpenXML documents.

The service renders EvoFlux's sandboxed Office HTML through a bundled Chromium
runtime, captures one PNG per slide/page/sheet, and runs DOM-based overflow
checks.  It is a visual-lint renderer rather than a claim of pixel parity with
Microsoft Office; the returned confidence field makes that distinction
machine-readable.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from app.core.config import settings
from app.services.office_preview_service import render_office_preview

_SELECTORS = {
    ".pptx": (".slide", "slide", "medium"),
    ".docx": (".document-page", "page", "approximate"),
    ".xlsx": (".sheet", "sheet", "medium"),
}
_BROWSER_NAMES = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "chrome",
    "msedge",
)


def _is_browser_executable(path: Path) -> bool:
    if not path.is_file():
        return False
    name = path.name.lower()
    excluded = (
        "crashpad",
        "helper",
        "setup",
        "proxy",
        "driver",
        ".dll",
        ".dylib",
        ".so",
    )
    return not any(token in name for token in excluded)


def _bundled_browser_candidates() -> list[Path]:
    roots: list[Path] = []
    for origin in (Path(__file__).resolve(), Path(sys.executable).resolve()):
        for parent in origin.parents:
            browser = parent / "browser"
            if browser.is_dir() and browser not in roots:
                roots.append(browser)
    patterns = (
        "**/chrome-headless-shell",
        "**/chrome-headless-shell.exe",
        "**/chrome",
        "**/chrome.exe",
        "**/Chromium.app/Contents/MacOS/Chromium",
    )
    candidates: list[Path] = []
    for root in roots:
        for pattern in patterns:
            candidates.extend(root.glob(pattern))
    return candidates


def find_chromium() -> Path | None:
    """Return a configured, bundled, Playwright, or system Chromium binary."""
    if settings.EVOFLUX_CHROMIUM_PATH:
        configured = Path(settings.EVOFLUX_CHROMIUM_PATH).expanduser()
        if _is_browser_executable(configured):
            return configured.resolve()
        logger.warning("office_visual_qa_invalid_chromium path={}", configured)

    for candidate in _bundled_browser_candidates():
        if _is_browser_executable(candidate):
            return candidate.resolve()

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            managed = Path(playwright.chromium.executable_path)
        if _is_browser_executable(managed):
            return managed.resolve()
    except Exception:
        pass

    if sys.platform == "darwin":
        applications = (
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        )
        for candidate in applications:
            if _is_browser_executable(candidate):
                return candidate
    elif sys.platform == "win32":
        roots = (
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        )
        relative_paths = (
            "Google/Chrome/Application/chrome.exe",
            "Microsoft/Edge/Application/msedge.exe",
            "Chromium/Application/chrome.exe",
        )
        for root in roots:
            if not root:
                continue
            for relative in relative_paths:
                candidate = Path(root) / relative
                if _is_browser_executable(candidate):
                    return candidate

    for name in _BROWSER_NAMES:
        executable = shutil.which(name)
        if executable and _is_browser_executable(Path(executable)):
            return Path(executable).resolve()
    return None


def _paginate_docx(page: Any) -> None:
    page.evaluate(
        """
        () => {
          const documentRoot = document.querySelector('.document');
          const flow = document.querySelector('.document-flow');
          if (!documentRoot || !flow || document.querySelector('.document-page')) return;
          const blocks = Array.from(flow.children);
          const headerTemplate = document.querySelector('.document-header-template');
          const footerTemplate = document.querySelector('.document-footer-template');
          const pages = document.createElement('div');
          pages.className = 'document-pages';
          flow.replaceWith(pages);

          function makePage() {
            const shell = document.createElement('section');
            shell.className = 'document-page';
            shell.innerHTML =
              '<header class="document-page-header"></header>' +
              '<main class="document-page-body"></main>' +
              '<footer class="document-page-footer"></footer>';
            shell.querySelector('.document-page-header').innerHTML =
              headerTemplate ? headerTemplate.innerHTML : '';
            shell.querySelector('.document-page-footer').innerHTML =
              footerTemplate ? footerTemplate.innerHTML : '';
            pages.appendChild(shell);
            return shell.querySelector('.document-page-body');
          }

          let body = makePage();
          function appendSplitTable(sourceTable) {
            const rows = Array.from(sourceTable.rows);
            const hasHeader = rows.length > 0 &&
              Array.from(rows[0].cells).every((cell) => cell.tagName === 'TH');
            const header = hasHeader ? rows[0].cloneNode(true) : null;
            let table = sourceTable.cloneNode(false);
            let tableBody = document.createElement('tbody');
            table.appendChild(tableBody);
            body.appendChild(table);
            rows.forEach((row, index) => {
              tableBody.appendChild(row);
              if (body.scrollHeight > body.clientHeight + 2 &&
                  tableBody.rows.length > 1) {
                tableBody.removeChild(row);
                body = makePage();
                table = sourceTable.cloneNode(false);
                tableBody = document.createElement('tbody');
                table.appendChild(tableBody);
                body.appendChild(table);
                if (header && index > 0) tableBody.appendChild(header.cloneNode(true));
                tableBody.appendChild(row);
              }
            });
          }
          for (const block of blocks) {
            if (block.dataset.pageBreakBefore === 'true' && body.children.length) {
              body = makePage();
            }
            body.appendChild(block);
            if (body.scrollHeight > body.clientHeight + 2 &&
                block.tagName === 'TABLE') {
              body.removeChild(block);
              if (body.children.length) body = makePage();
              appendSplitTable(block);
            } else if (body.scrollHeight > body.clientHeight + 2 &&
                       body.children.length > 1) {
              body.removeChild(block);
              body = makePage();
              body.appendChild(block);
            }
          }
          documentRoot.dataset.paginated = 'true';
        }
        """
    )


def _dom_lint(page: Any, suffix: str) -> dict[str, list[str]]:
    result = page.evaluate(
        """
        ({suffix}) => {
          const errors = [];
          const warnings = [];
          const containers = suffix === '.pptx'
            ? document.querySelectorAll('.slide')
            : suffix === '.docx'
              ? document.querySelectorAll('.document-page-body')
              : document.querySelectorAll('.sheet');
          containers.forEach((container, containerIndex) => {
            const bounds = container.getBoundingClientRect();
            const targets = suffix === '.pptx'
              ? container.querySelectorAll('.shape')
              : suffix === '.docx'
                ? container.querySelectorAll('p, table, img')
                : container.querySelectorAll('td');
            targets.forEach((target) => {
              const box = target.getBoundingClientRect();
              const label = target.dataset.qaLabel || target.dataset.shapeName ||
                target.dataset.cell || target.tagName.toLowerCase();
              if (box.right > bounds.right + 2 || box.left < bounds.left - 2 ||
                  box.bottom > bounds.bottom + 2 || box.top < bounds.top - 2) {
                errors.push(`item ${containerIndex + 1}: ${label} is outside its canvas`);
              }
              if (target.scrollWidth > target.clientWidth + 2 ||
                  target.scrollHeight > target.clientHeight + 2) {
                const message = `item ${containerIndex + 1}: ${label} may clip or overflow`;
                if (suffix === '.xlsx') warnings.push(message);
                else errors.push(message);
              }
            });
            if (suffix === '.pptx') {
              const shapes = Array.from(container.querySelectorAll('.shape'))
                .filter((shape) => {
                  const box = shape.getBoundingClientRect();
                  return box.width > 3 && box.height > 3 &&
                    shape.dataset.sourceLayer === 'slide' &&
                    !String(shape.dataset.shapeName || '').includes('[allow-overlap]');
                });
              for (let leftIndex = 0; leftIndex < shapes.length; leftIndex += 1) {
                for (let rightIndex = leftIndex + 1;
                     rightIndex < shapes.length; rightIndex += 1) {
                  const left = shapes[leftIndex];
                  const right = shapes[rightIndex];
                  const a = left.getBoundingClientRect();
                  const b = right.getBoundingClientRect();
                  const width = Math.max(0, Math.min(a.right, b.right) -
                    Math.max(a.left, b.left));
                  const height = Math.max(0, Math.min(a.bottom, b.bottom) -
                    Math.max(a.top, b.top));
                  const ratio = width * height /
                    Math.max(Math.min(a.width * a.height, b.width * b.height), 1);
                  if (ratio < 0.12) continue;
                  const containerArea = bounds.width * bounds.height;
                  const leftBackground = a.width * a.height > containerArea * 0.72 &&
                    !left.classList.contains('text-shape');
                  const rightBackground = b.width * b.height > containerArea * 0.72 &&
                    !right.classList.contains('text-shape');
                  if (leftBackground || rightBackground) continue;
                  const leftText = left.classList.contains('text-shape');
                  const rightText = right.classList.contains('text-shape');
                  const flatContainer = ratio > 0.94 && leftText !== rightText &&
                    ((left.classList.contains('vector-shape') && !leftText) ||
                     (right.classList.contains('vector-shape') && !rightText));
                  if (flatContainer) continue;
                  const leftLabel = left.dataset.shapeName ||
                    left.dataset.shapeId || 'shape';
                  const rightLabel = right.dataset.shapeName ||
                    right.dataset.shapeId || 'shape';
                  const message = `item ${containerIndex + 1}: ${leftLabel} and ` +
                    `${rightLabel} visually overlap by ${Math.round(ratio * 100)}%`;
                  if (leftText || rightText) errors.push(message);
                  else warnings.push(message);
                }
              }
            }
          });
          return {errors: [...new Set(errors)], warnings: [...new Set(warnings)]};
        }
        """,
        {"suffix": suffix},
    )
    return {
        "errors": list(result.get("errors", [])),
        "warnings": list(result.get("warnings", [])),
    }


def render_office_images(source: Path, render_dir: Path) -> dict[str, Any]:
    """Render one PNG per logical Office item using Chromium and OpenXML HTML."""
    suffix = source.suffix.lower()
    if suffix not in _SELECTORS:
        return {
            "status": "unsupported",
            "engine": "structural-only",
            "confidence": "none",
            "reason": f"{suffix or 'file'} is not supported",
            "images": [],
            "errors": [],
            "warnings": [],
        }
    browser_path = find_chromium()
    if browser_path is None:
        return {
            "status": "unavailable",
            "engine": "structural-only",
            "confidence": "none",
            "reason": "Bundled Chromium and system Chrome/Chromium were not found",
            "images": [],
            "errors": [],
            "warnings": [],
        }

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return {
            "status": "unavailable",
            "engine": "structural-only",
            "confidence": "none",
            "reason": f"Playwright is unavailable: {exc}",
            "images": [],
            "errors": [],
            "warnings": [],
        }

    selector, prefix, confidence = _SELECTORS[suffix]
    render_dir.mkdir(parents=True, exist_ok=True)
    try:
        html_path = render_office_preview(source)
    except Exception as exc:
        return {
            "status": "failed",
            "engine": "chromium-openxml",
            "confidence": confidence,
            "browser": str(browser_path),
            "reason": f"OpenXML preview failed: {exc}",
            "images": [],
            "errors": [],
            "warnings": [],
        }
    images: list[str] = []
    try:
        with sync_playwright() as playwright:
            browser_args = [
                "--disable-dev-shm-usage",
                "--font-render-hinting=none",
            ]
            if (
                sys.platform.startswith("linux")
                and hasattr(os, "geteuid")
                and os.geteuid() == 0
            ):
                browser_args.append("--no-sandbox")
            browser = playwright.chromium.launch(
                executable_path=str(browser_path),
                headless=True,
                args=browser_args,
            )
            page = browser.new_page(
                viewport={"width": 1440, "height": 1100},
                device_scale_factor=1.5,
            )
            page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
            page.emulate_media(media="screen")
            if suffix == ".docx":
                _paginate_docx(page)
            page.locator(selector).first.wait_for(state="visible", timeout=15_000)
            lint = _dom_lint(page, suffix)
            items = page.locator(selector)
            for index in range(items.count()):
                output = render_dir / f"{prefix}-{index + 1}.png"
                items.nth(index).screenshot(path=str(output), animations="disabled")
                images.append(str(output))
            browser.close()
    except Exception as exc:
        logger.warning(
            "office_visual_qa_failed file={} browser={} error={}",
            source.name,
            browser_path,
            str(exc)[:500],
        )
        return {
            "status": "failed",
            "engine": "chromium-openxml",
            "confidence": confidence,
            "browser": str(browser_path),
            "reason": str(exc),
            "images": images,
            "errors": [],
            "warnings": [],
        }
    return {
        "status": "rendered",
        "engine": "chromium-openxml",
        "confidence": confidence,
        "browser": str(browser_path),
        "images": images,
        "errors": lint["errors"],
        "warnings": lint["warnings"],
    }


def compare_rendered_images(
    before: list[str],
    after: list[str],
) -> dict[str, Any]:
    """Return deterministic pixel-diff ratios for two render sets."""
    from PIL import Image, ImageChops

    if len(before) != len(after):
        return {
            "errors": [
                f"Rendered item count changed from {len(before)} to {len(after)}"
            ],
            "items": [],
        }
    items = []
    errors: list[str] = []
    for index, (before_path, after_path) in enumerate(zip(before, after, strict=True)):
        with Image.open(before_path).convert("RGBA") as left:
            with Image.open(after_path).convert("RGBA") as right:
                if left.size != right.size:
                    errors.append(
                        f"Item {index + 1}: image size changed from "
                        f"{left.size} to {right.size}"
                    )
                    items.append({"item": index + 1, "size_changed": True})
                    continue
                difference = ImageChops.difference(left, right)
                rgb_difference = difference.convert("RGB")
                histogram = rgb_difference.histogram()
                changed = sum(
                    count for value, count in enumerate(histogram) if value % 256 != 0
                )
                denominator = max(left.width * left.height * 3, 1)
                items.append(
                    {
                        "item": index + 1,
                        "pixel_channel_change_ratio": round(changed / denominator, 8),
                        "changed_bounds": rgb_difference.getbbox(),
                    }
                )
    return {"errors": errors, "items": items}
