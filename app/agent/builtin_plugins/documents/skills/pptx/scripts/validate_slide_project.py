#!/usr/bin/env python3
"""Validate an HTML-first PPTX project and its project-local Slide DNA."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.agent.builtin_plugins.documents.engines.pptx_html import (
    load_html_pptx_project,
    validate_html_pptx_project,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a schema-v6 HTML PPTX project without rendering it."
    )
    parser.add_argument("project", type=Path, help="Path to project.json")
    args = parser.parse_args()
    project_path = args.project.expanduser().resolve()

    try:
        project = load_html_pptx_project(project_path)
        details = validate_html_pptx_project(project, project_path)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "valid": False,
                    "project": str(project_path),
                    "error": str(exc),
                    "render_surfaces": "unverified",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "valid": True,
                "project": str(project_path),
                "details": details,
                "render_surfaces": "unverified",
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
