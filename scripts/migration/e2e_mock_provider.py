"""Serve the contract-tests mock model provider for the Playwright smoke suite.

Prints ``MOCK_PROVIDER <base_url>`` once listening, then runs until killed.
Usage: ``uv run python scripts/migration/e2e_mock_provider.py [recording]``.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "contract-tests"))

from mock_provider.server import MockProvider  # noqa: E402


def main() -> None:
    provider = MockProvider()
    provider.load(sys.argv[1] if len(sys.argv) > 1 else "openai_text_hello")
    print(f"MOCK_PROVIDER {provider.base_url}", flush=True)
    threading.Event().wait()


if __name__ == "__main__":
    main()
