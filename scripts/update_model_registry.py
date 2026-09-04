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
    provider_envelopes,
)


DEFAULT_OUTPUT = Path("app/agent/providers/model_registry.json")
DEFAULT_PROVIDER_OUTPUT = Path("app/agent/providers/provider_catalog.json")


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


def _build_provider_catalog(payload: Any) -> dict[str, dict[str, Any]]:
    """Provider envelopes for every provider models.dev lists.

    Bundling these is what lets a cold, offline install resolve an endpoint
    and a credential name without the registry restating every base URL in
    code — precisely the duplication that goes stale when a provider moves
    its API.

    The whole catalog is bundled, not just the curated subset: an envelope
    is six small fields, the entire set costs well under a tenth of what the
    model metadata does, and carrying all of it is what makes the long tail
    of providers reachable offline instead of only after a first fetch.
    """
    return dict(sorted(provider_envelopes(payload).items()))


def _fetch_models_dev(url: str) -> Any:
    response = httpx.get(url, timeout=30.0)
    response.raise_for_status()
    return response.json()


def _supported_provider_ids() -> set[str]:
    """Providers whose models belong in the offline snapshot.

    The curated set, plus the catalog rows those providers borrow from: a
    vendor's regional and plan endpoints list models the base row does not,
    and a user pointed at one of those endpoints should see real metadata
    offline rather than a bare model ID.
    """
    from app.agent.providers.catalog import builtin_providers
    from app.agent.providers.model_registry import _sibling_providers

    ids = {entry["id"].lower() for entry in builtin_providers()}
    for sources in _sibling_providers().values():
        ids.update(source.lower() for source in sources)
    return ids


def _build_registry(
    fetched: dict[str, dict[str, Any]], *, curated_only: bool = False
) -> dict[str, dict[str, Any]]:
    """Build a fresh snapshot; never carry stale rows from the old file.

    The whole catalog is bundled by default. EvoFlux can configure and use
    every provider models.dev lists, so restricting the offline snapshot to
    the curated ones would leave the long tail with real credentials, a real
    endpoint, and no idea what any of its models can do until the catalog
    downloads — a worse failure than a larger package, because it is silent:
    context windows, prices and reasoning controls would all read "unknown".

    *curated_only* keeps the old, smaller shape for anyone who wants it.
    """
    if curated_only:
        supported = _supported_provider_ids()
        fetched = {
            key: value
            for key, value in fetched.items()
            if key.partition(":")[0] in supported
        }
    return dict(
        sorted(
            apply_model_registry_aliases(
                fetched, overwrite=True, include_plugins=False
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
        "--provider-output",
        type=Path,
        default=DEFAULT_PROVIDER_OUTPUT,
        help="Bundled provider-envelope JSON path",
    )
    parser.add_argument(
        "--curated-only",
        action="store_true",
        help=(
            "Bundle only curated providers' models. Smaller, but leaves the "
            "models.dev long tail without metadata until the catalog is fetched."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the generated registry differs from disk",
    )
    args = parser.parse_args()

    existing = _read_existing(args.output)
    payload = _fetch_models_dev(args.url)
    fetched = _normalize_models_dev(payload, include_plugins=False)
    registry = _build_registry(fetched, curated_only=args.curated_only)
    rendered = json.dumps(registry, separators=(",", ":"), sort_keys=True) + "\n"
    providers = _build_provider_catalog(payload)
    providers_rendered = (
        json.dumps(providers, separators=(",", ":"), sort_keys=True) + "\n"
    )

    if args.check:
        current = (
            args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        )
        current_providers = (
            args.provider_output.read_text(encoding="utf-8")
            if args.provider_output.exists()
            else ""
        )
        if current != rendered:
            print(
                f"{args.output} is stale: existing={len(existing)} fetched={len(fetched)} generated={len(registry)}"
            )
            return 1
        if current_providers != providers_rendered:
            print(f"{args.provider_output} is stale: generated={len(providers)}")
            return 1
        print(
            f"{args.output} is current: entries={len(registry)} "
            f"providers={len(providers)}"
        )
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    args.provider_output.parent.mkdir(parents=True, exist_ok=True)
    args.provider_output.write_text(providers_rendered, encoding="utf-8")
    print(
        f"wrote {args.output}: existing={len(existing)} fetched={len(fetched)} generated={len(registry)}"
    )
    print(f"wrote {args.provider_output}: providers={len(providers)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
