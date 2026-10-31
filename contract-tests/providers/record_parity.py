"""Record ``parity/<case>.json`` from the Python provider.

    uv run --group contract python contract-tests/providers/record_parity.py [case ...]

Each file holds the case (model, messages, tools, options, recording), the
recording as the mock parses it, and what Python did with it: the request
bodies the mock received and the event list. The files live in the Rust
crate, whose unit tests replay the embedded recording and compare.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

from cases import CASES  # noqa: E402
from parity import PARITY_DIR, parse_recording, run  # noqa: E402


def main(names: list[str]) -> None:
    PARITY_DIR.mkdir(exist_ok=True)
    for case in CASES:
        if names and case["name"] not in names:
            continue
        result = run("python", case)
        record = {
            "case": case,
            "responses": parse_recording(case["recording"]),
            "expected": result,
        }
        path = PARITY_DIR / f"{case['name']}.json"
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"recorded {path.name}: {len(result['events'])} events")


if __name__ == "__main__":
    main(sys.argv[1:])
