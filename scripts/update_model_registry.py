from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx

from app.agent.providers.model_registry import (
    MODELS_DEV_URL,
    _normalize_models_dev,
    apply_model_registry_aliases,
)


DEFAULT_OUTPUT = Path("app/agent/providers/model_registry.json")


def _read_existing(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return {
        str(key).lower(): value
        for key, value in parsed.items()
        if isinstance(value, dict)
    }


def _fetch_models_dev(url: str) -> Any:
    response = httpx.get(url, timeout=30.0)
    response.raise_for_status()
    return response.json()


def _supported_provider_ids() -> set[str]:
    from app.agent.providers.catalog import builtin_providers

    return {entry["id"].lower() for entry in builtin_providers()}


def _build_registry(fetched: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build a fresh snapshot; never carry stale rows from the old file."""
    supported = _supported_provider_ids()
    registry = {
        key: value
        for key, value in fetched.items()
        if key.partition(":")[0] in supported
    }
    return dict(
        sorted(
            apply_model_registry_aliases(
                registry, overwrite=True, include_plugins=False
            ).items()
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh the bundled minimized model registry from models.dev."
    )
    parser.add_argument("--url", default=MODELS_DEV_URL, help="models.dev API URL")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Bundled registry JSON path",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the generated registry differs from disk",
    )
    args = parser.parse_args()

    existing = _read_existing(args.output)
    fetched = _normalize_models_dev(_fetch_models_dev(args.url), include_plugins=False)
    registry = _build_registry(fetched)
    rendered = json.dumps(registry, separators=(",", ":"), sort_keys=True) + "\n"

    if args.check:
        current = (
            args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        )
        if current != rendered:
            print(
                f"{args.output} is stale: existing={len(existing)} fetched={len(fetched)} generated={len(registry)}"
            )
            return 1
        print(f"{args.output} is current: entries={len(registry)}")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(
        f"wrote {args.output}: existing={len(existing)} fetched={len(fetched)} generated={len(registry)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
