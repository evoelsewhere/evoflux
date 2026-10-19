"""Offline Intelligent UI eval and opt-in smoke against a loopback EvoFlux API.

The default invocation validates and summarizes prompt cases only. ``--live``
creates synthetic local chat sessions and records outcome metadata only; it
never prints prompts, tool arguments/results, provider credentials, or model
reasoning. A caller must explicitly provide a loopback ``--base-url``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from time import monotonic
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


LIVE_SMOKE_FIELDS = {
    "case_id",
    "model_id",
    "expected_choice",
    "observed_choice",
    "selection_match",
    "tool",
    "kind",
    "prompt_bytes",
    "payload_bytes",
    "has_provenance",
    "status",
    "error_category",
}
EXPECTED_CHOICES = {"prose", "ui_block", "dashboard", "motion", "scene3d"}
ARTIFACT_CHOICES = {"ui_block", "dashboard", "motion", "scene3d"}
DEFAULT_CASES = (
    Path(__file__).parents[1]
    / "tests"
    / "fixtures"
    / "intelligent_ui"
    / "rich_artifact_cases.json"
)


def load_cases(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("evaluation fixture must be a JSON array")
    cases: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, value in enumerate(raw):
        if not isinstance(value, dict):
            raise ValueError(f"case {index} must be an object")
        case_id = value.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in ids:
            raise ValueError(f"case {index} must have a unique non-empty id")
        if not isinstance(value.get("prompt"), str) or not value["prompt"].strip():
            raise ValueError(f"case {case_id} must have a prompt")
        if value.get("expected_choice") not in EXPECTED_CHOICES:
            raise ValueError(f"case {case_id} has an unknown expected_choice")
        if not isinstance(value.get("required_evidence"), list) or not isinstance(
            value.get("forbidden_choices"), list
        ):
            raise ValueError(
                f"case {case_id} must define evidence and forbidden_choices lists"
            )
        ids.add(case_id)
        cases.append(value)
    return cases


def select_cases(
    cases: list[dict[str, Any]], case_ids: list[str]
) -> list[dict[str, Any]]:
    """Select requested fixture IDs while preserving their requested order."""
    selected_ids = list(dict.fromkeys(case_ids))
    if not selected_ids:
        return cases
    by_id = {case["id"]: case for case in cases}
    unknown = [case_id for case_id in selected_ids if case_id not in by_id]
    if unknown:
        raise ValueError(f"unknown evaluation case id(s): {', '.join(unknown)}")
    return [by_id[case_id] for case_id in selected_ids]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="Run one case by ID; may be repeated",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=300,
        help="Stop a live case if its stream has no terminal event before this deadline",
    )
    parser.add_argument(
        "--models", default="", help="Comma-separated registered model IDs"
    )
    parser.add_argument(
        "--compare-with-configured",
        action="store_true",
        help="Also use EVOFLUX_INTELLIGENT_UI_COMPARE_MODEL",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Send synthetic prompts to the explicitly supplied loopback API",
    )
    parser.add_argument(
        "--base-url",
        help="Loopback EvoFlux team API root, e.g. http://127.0.0.1:8000/api/team",
    )
    return parser.parse_args(argv)


def _loopback_api_root(raw: str) -> str:
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ValueError(
            "live smoke is restricted to an explicitly supplied loopback URL"
        )
    if not parsed.path.rstrip("/").endswith("/api/team"):
        raise ValueError("--base-url must end with /api/team")
    return raw.rstrip("/")


def _request(
    url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None
) -> Any:
    request = Request(url, data=data, headers=headers or {})
    return urlopen(request, timeout=300)


def _run_case(
    api_root: str,
    model_id: str,
    case: dict[str, Any],
    *,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    form = urlencode(
        {"message": case["prompt"], "mode": "work", "model": model_id}
    ).encode()
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    token = os.environ.get("EVOFLUX_DESKTOP_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    outcome: dict[str, Any] = {
        "case_id": case["id"],
        "model_id": model_id,
        "expected_choice": case.get("expected_choice"),
        "observed_choice": None,
        "selection_match": None,
        "tool": None,
        "kind": None,
        "prompt_bytes": len(case["prompt"].encode("utf-8")),
        "payload_bytes": 0,
        "has_provenance": False,
        "status": "incomplete",
        "error_category": None,
    }
    with _request(f"{api_root}/chat", data=form, headers=headers) as response:
        session = json.loads(response.read().decode("utf-8"))
    session_id = session.get("session_id") if isinstance(session, dict) else None
    if not isinstance(session_id, str) or not session_id:
        outcome["status"] = "missing_session"
        return outcome
    deadline = monotonic() + timeout_seconds
    event_name = ""
    with _request(f"{api_root}/{session_id}/stream", headers=headers) as response:
        for raw_line in response:
            if monotonic() >= deadline:
                outcome["status"] = "timeout"
                outcome["error_category"] = "timeout"
                break
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if line.startswith("event:"):
                event_name = line[6:].strip()
                continue
            if not line.startswith("data:"):
                continue
            try:
                payload = json.loads(line[5:].strip())
            except (ValueError, TypeError):
                continue
            if not isinstance(payload, dict):
                continue
            event_type = str(payload.get("type") or event_name)
            if event_type == "tool_start" and isinstance(payload.get("name"), str):
                outcome["tool"] = payload["name"]
            elif event_type in {"ui_block", "visual_artifact"}:
                outcome["tool"] = event_type
                outcome["observed_choice"] = (
                    event_type if event_type == "ui_block" else payload.get("kind")
                )
            if event_type == "visual_artifact":
                outcome["kind"] = payload.get("kind")
                source_html = payload.get("source_html")
                scene = payload.get("scene")
                material = (
                    source_html
                    if isinstance(source_html, str)
                    else json.dumps(scene, ensure_ascii=False)
                    if scene is not None
                    else ""
                )
                outcome["payload_bytes"] = len(material.encode("utf-8"))
                sources = payload.get("sources")
                outcome["has_provenance"] = isinstance(sources, list) and bool(sources)
            if event_type == "done":
                outcome["status"] = "complete"
                if outcome["expected_choice"] in ARTIFACT_CHOICES:
                    outcome["selection_match"] = (
                        outcome["observed_choice"] == outcome["expected_choice"]
                    )
                break
            elif event_type == "error":
                outcome["status"] = "error"
                metadata = payload.get("metadata")
                exception = (
                    metadata.get("exception") if isinstance(metadata, dict) else None
                )
                outcome["error_category"] = (
                    exception
                    if isinstance(exception, str)
                    and exception.isascii()
                    and exception.isidentifier()
                    else "agent_error"
                )
                break
    return outcome


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        cases = select_cases(load_cases(args.cases), args.case_id)
        if not args.live:
            print(
                json.dumps(
                    {
                        "live": False,
                        "case_count": len(cases),
                        "case_ids": [case["id"] for case in cases],
                        "status": "not_run",
                    }
                )
            )
            return 0
        if not args.base_url:
            raise ValueError(
                "--live requires --base-url; live requests are never sent by default"
            )
        api_root = _loopback_api_root(args.base_url)
        if args.timeout_seconds < 1:
            raise ValueError("--timeout-seconds must be at least 1")
        models = [model.strip() for model in args.models.split(",") if model.strip()]
        if args.compare_with_configured:
            comparison = os.environ.get(
                "EVOFLUX_INTELLIGENT_UI_COMPARE_MODEL", ""
            ).strip()
            if not comparison:
                raise ValueError(
                    "--compare-with-configured requires EVOFLUX_INTELLIGENT_UI_COMPARE_MODEL"
                )
            if comparison not in models:
                models.append(comparison)
        if not models:
            raise ValueError("--live requires at least one --models entry")
        results = [
            _run_case(
                api_root,
                model,
                case,
                timeout_seconds=args.timeout_seconds,
            )
            for model in models
            for case in cases
        ]
        print(json.dumps(results, ensure_ascii=False))
        return 0 if all(result["status"] == "complete" for result in results) else 1
    except (OSError, ValueError, HTTPError, URLError) as exc:
        print(f"smoke_intelligent_ui: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
