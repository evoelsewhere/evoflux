#!/usr/bin/env python3
"""Render an xlsx as PDF (and optionally PNG pages) via headless LibreOffice.

Usage:
    python pdf_out.py workbook.xlsx                # writes workbook.pdf beside input
    python pdf_out.py workbook.xlsx --dest reports/  # writes reports/workbook.pdf
    python pdf_out.py workbook.xlsx --png          # also writes workbook-<page>.png
    python pdf_out.py workbook.xlsx --png --dpi 110 --first 1 --last 3

Pages are rasterised with Poppler's `pdftoppm` when it is on PATH, otherwise
with pypdfium2, which `uv` fetches on first use. View the PNGs with the
agent's `read` tool.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from runtime.libreoffice import LibreOfficeNotFound, invoke, locate_libreoffice  # noqa: E402


class RenderFailed(RuntimeError):
    """LibreOffice could not produce a PDF."""


def render_pdf(source: Path, out_dir: Path, timeout_seconds: float) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="xlsx-pdf-") as scratch:
        result = invoke(
            [
                "--headless",
                "--calc",
                "--convert-to", "pdf",
                "--outdir", scratch,
                str(source.resolve()),
            ],
            timeout=timeout_seconds,
        )
        if not result.ok:
            raise RenderFailed(
                f"soffice returned {result.returncode}: "
                f"{result.stderr.strip() or '(no stderr)'}"
            )
        produced = next(Path(scratch).glob("*.pdf"), None)
        if produced is None:
            raise RenderFailed("no PDF produced by LibreOffice")
        final = out_dir / (source.stem + ".pdf")
        shutil.move(str(produced), str(final))
        return final


def _pypdfium2_command() -> list[str] | None:
    uv = shutil.which("uv")
    if uv is None:
        return None
    return [uv, "run", "--no-project", "--quiet", "--with", "pypdfium2",
            "--with", "pillow", "python", "-m", "pypdfium2_cli"]


def rasterise(pdf: Path, out_dir: Path, dpi: int,
              first: int | None, last: int | None) -> list[Path]:
    """PDF -> `<stem>-<page>.png` files in `out_dir`; returns them in page order."""
    if shutil.which("pdftoppm"):
        cmd = ["pdftoppm", "-png", "-r", str(dpi)]
        if first:
            cmd += ["-f", str(first)]
        if last:
            cmd += ["-l", str(last)]
        proc = subprocess.run([*cmd, str(pdf), str(out_dir / pdf.stem)],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            raise RenderFailed(f"pdftoppm returned {proc.returncode}: {proc.stderr.strip()}")
        pages = sorted(out_dir.glob(f"{pdf.stem}-*.png"))
    else:
        command = _pypdfium2_command()
        if command is None:
            raise RenderFailed(
                "cannot rasterise: pdftoppm (Poppler) is not on PATH and `uv` is "
                "missing for the pypdfium2 fallback. Use the PDF instead."
            )
        pages = []
        with tempfile.TemporaryDirectory(prefix="xlsx-png-") as scratch_str:
            scratch = Path(scratch_str)
            cmd = [*command, "render", str(pdf), "--output", str(scratch),
                   "--format", "png", "--scale", str(dpi / 72.0)]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                raise RenderFailed(f"pypdfium2 returned {proc.returncode}: {proc.stderr.strip()}")
            for page in sorted(scratch.glob(f"{pdf.stem}_*.png")):
                digits = page.stem.rsplit("_", 1)[1]
                if not digits.isdigit():
                    continue
                number = int(digits)
                if (first and number < first) or (last and number > last):
                    continue
                target = out_dir / f"{pdf.stem}-{digits}.png"
                shutil.move(str(page), target)
                pages.append(target)
    if not pages:
        raise RenderFailed("no PNG pages produced")
    return pages


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Render an xlsx as PDF.")
    p.add_argument("workbook", type=Path)
    p.add_argument("--dest", type=Path, default=None,
                   help="output directory (default: same as input)")
    p.add_argument("--png", action="store_true",
                   help="also rasterise the PDF to one PNG per page")
    p.add_argument("--dpi", type=int, default=110,
                   help="PNG resolution (default 110)")
    p.add_argument("--first", type=int, default=None, help="first page to rasterise (1-based)")
    p.add_argument("--last", type=int, default=None, help="last page to rasterise (1-based)")
    p.add_argument("--timeout", type=float, default=60.0,
                   help="LibreOffice timeout in seconds")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.workbook.exists():
        print(f"no such workbook: {args.workbook}", file=sys.stderr)
        return 1

    try:
        locate_libreoffice()
    except LibreOfficeNotFound as exc:
        print(str(exc), file=sys.stderr)
        return 3

    out_dir = (args.dest or args.workbook.parent).resolve()

    try:
        final = render_pdf(args.workbook, out_dir, args.timeout)
    except subprocess.TimeoutExpired:
        print(f"LibreOffice exceeded {args.timeout}s timeout", file=sys.stderr)
        return 4
    except RenderFailed as exc:
        print(str(exc), file=sys.stderr)
        return 4

    print(str(final))
    if args.png:
        try:
            for page in rasterise(final, out_dir, args.dpi, args.first, args.last):
                print(str(page))
        except RenderFailed as exc:
            print(str(exc), file=sys.stderr)
            return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
