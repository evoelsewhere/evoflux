#!/usr/bin/env python3
"""Configure one Jira connection without placing the PAT in shell history."""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

from backend.evoflux_jira.client import normalize_base_url  # noqa: E402
from backend.evoflux_jira.config import ConnectionConfig, ConnectionStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", required=True, help="Installation PLUGIN_DATA path"
    )
    parser.add_argument("--name", default="default")
    parser.add_argument("--url", required=True)
    parser.add_argument("--no-verify-ssl", action="store_true")
    args = parser.parse_args()
    token = getpass.getpass("Jira PAT/API token: ")
    if not token:
        raise SystemExit("A non-empty token is required.")
    store = ConnectionStore(Path(args.data_dir) / "connections.json")
    store.save(
        ConnectionConfig(
            name=args.name,
            base_url=normalize_base_url(args.url),
            api_token=token,
            verify_ssl=not args.no_verify_ssl,
        )
    )
    print(f"Saved Jira connection {args.name!r} in {store.path}.")


if __name__ == "__main__":
    main()
