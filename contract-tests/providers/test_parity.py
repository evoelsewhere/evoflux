"""Provider parity: the provider under ``TARGET`` matches the recorded Python run.

The recorded files come from ``record_parity.py`` (Python provider against the
mock). ``TARGET=python`` proves they still describe Python; ``TARGET=rust``
runs the Rust provider on the same cases.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from cases import CASES  # noqa: E402
from parity import PARITY_DIR, build_rust_example, parse_recording, run  # noqa: E402


@pytest.fixture(scope="session")
def provider_target(target: str) -> str:
    if target == "rust":
        build_rust_example()
    elif target != "python":
        pytest.skip("provider parity has no gateway target: providers serve no HTTP route")
    return target


def test_every_case_is_recorded() -> None:
    recorded = {path.stem for path in PARITY_DIR.glob("*.json")}
    assert recorded == {case["name"] for case in CASES}


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_provider_matches_recording(provider_target: str, case: dict) -> None:
    record = json.loads((PARITY_DIR / f"{case['name']}.json").read_text(encoding="utf-8"))
    assert record["case"] == case, "case changed; re-run record_parity.py"
    assert record["responses"] == parse_recording(case["recording"]), (
        "recording changed; re-run record_parity.py"
    )
    actual = run(provider_target, case)
    assert actual["events"] == record["expected"]["events"]
    assert actual["requests"] == record["expected"]["requests"]
