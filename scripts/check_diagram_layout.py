"""Run the diagram geometry preflight on a saved HTML or SVG file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.agent.tools.builtin.visualize.geometry import check_svg_layout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="HTML or SVG file to preflight")
    args = parser.parse_args()
    result = check_svg_layout(args.file.read_text(encoding="utf-8"))
    print(json.dumps(result, indent=2))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
