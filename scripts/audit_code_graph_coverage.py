#!/usr/bin/env python3
"""Measure code-graph extraction coverage on real repositories.

This deliberately reports structural and search-only coverage separately. A
file being searchable is not evidence that its symbols or relations were
parsed, and repository readiness is not a parser-quality percentage.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from app.services.code_index.file_matcher import MAX_SOURCE_BYTES, walk_source_records
from app.services.code_index.languages import SEARCH_ONLY_LANGUAGES, fallback_language
from app.services.code_index.parsers.registry import default_registry
from app.services.code_index.settings import load_project_settings


def _percent(numerator: int, denominator: int) -> float:
    return round((numerator / denominator * 100.0) if denominator else 0.0, 2)


def audit_repository(root: Path) -> dict[str, Any]:
    started = time.monotonic()
    canonical = root.expanduser().resolve(strict=True)
    settings = load_project_settings(canonical)
    registry = default_registry()
    extensions = set(registry.supported_extensions()) | set(SEARCH_ONLY_LANGUAGES)
    max_bytes = settings.max_file_size or MAX_SOURCE_BYTES
    metrics: dict[str, Any] = {
        "repository": str(canonical),
        "indexable_files": 0,
        "structural_files": 0,
        "search_only_files": 0,
        "parsed_files": 0,
        "parse_failures": 0,
        "lines": 0,
        "source_bytes": 0,
    }
    languages: Counter[str] = Counter()
    node_kinds: Counter[str] = Counter()
    relation_kinds: Counter[str] = Counter()
    parse_errors: list[dict[str, str]] = []
    symbol_count = 0
    signature_count = 0
    docstring_count = 0

    for record in walk_source_records(
        canonical,
        extensions=extensions,
        max_bytes=max_bytes,
        include=settings.includes,
        processor_for=lambda path: ("", settings.language_for(path)),
        force_read=True,
    ):
        metrics["indexable_files"] += 1
        metrics["source_bytes"] += len(record.content)
        metrics["lines"] += record.content.count(b"\n") + 1
        parser = (
            registry.for_language(record.language_override)
            if record.language_override
            else registry.for_path(record.key)
        )
        if parser is None:
            metrics["search_only_files"] += 1
            language = record.language_override or fallback_language(record.key)
            languages[language or "unknown"] += 1
            continue

        metrics["structural_files"] += 1
        languages[parser.name] += 1
        try:
            result = parser.parse(file_path=record.key, source=record.content)
        except Exception as exc:  # noqa: BLE001 - audit must report every parser failure
            metrics["parse_failures"] += 1
            if len(parse_errors) < 20:
                parse_errors.append(
                    {
                        "path": record.key,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
            continue

        metrics["parsed_files"] += 1
        symbols = [node for node in result.nodes if node.kind != "file"]
        symbol_count += len(symbols)
        signature_count += sum(bool(node.signature) for node in symbols)
        docstring_count += sum(bool(node.docstring) for node in symbols)
        node_kinds.update(node.kind for node in symbols)
        relation_kinds.update(edge.kind for edge in result.edges)

    lines = int(metrics["lines"])
    structural_files = int(metrics["structural_files"])
    indexable_files = int(metrics["indexable_files"])
    metrics.update(
        {
            "symbols": symbol_count,
            "relations": sum(relation_kinds.values()),
            "symbols_per_kloc": round(symbol_count / max(1.0, lines / 1000.0), 2),
            "structural_file_success_pct": _percent(
                int(metrics["parsed_files"]), structural_files
            ),
            "structural_file_share_pct": _percent(structural_files, indexable_files),
            "signature_completeness_pct": _percent(signature_count, symbol_count),
            "docstring_completeness_pct": _percent(docstring_count, symbol_count),
            "languages": dict(languages.most_common()),
            "node_kinds": dict(node_kinds.most_common()),
            "relation_kinds": dict(relation_kinds.most_common()),
            "parse_errors": parse_errors,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    )
    return metrics


def _print_human(report: dict[str, Any]) -> None:
    print(f"\n{report['repository']}")
    print(
        "  files: "
        f"{report['indexable_files']} indexable · "
        f"{report['structural_files']} structural · "
        f"{report['search_only_files']} search-only · "
        f"{report['parse_failures']} failures"
    )
    print(
        "  coverage: "
        f"{report['structural_file_success_pct']}% structural parse success · "
        f"{report['structural_file_share_pct']}% structural share"
    )
    print(
        "  graph: "
        f"{report['symbols']} symbols · {report['relations']} relations · "
        f"{report['symbols_per_kloc']} symbols/KLOC"
    )
    print(
        "  detail: "
        f"{report['signature_completeness_pct']}% signatures · "
        f"{report['docstring_completeness_pct']}% docs"
    )
    print(f"  languages: {report['languages']}")
    print(f"  node kinds: {report['node_kinds']}")
    print(f"  relation kinds: {report['relation_kinds']}")
    if report["parse_errors"]:
        print(f"  parse errors: {report['parse_errors']}")
    print(f"  elapsed: {report['elapsed_seconds']}s")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repositories", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    reports = [audit_repository(root) for root in args.repositories]
    if args.as_json:
        print(json.dumps(reports, indent=2, sort_keys=True))
    else:
        for report in reports:
            _print_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
