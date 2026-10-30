from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "migration" / "check_board.py"
SPEC = importlib.util.spec_from_file_location("check_board", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
check_board = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = check_board
SPEC.loader.exec_module(check_board)

HEADER = "| " + " | ".join(check_board.COLUMNS) + " |"
SEPARATOR = "|" + "---|" * len(check_board.COLUMNS)


def board_text(*rows: str) -> str:
    return "\n".join(["# Board", "", HEADER, SEPARATOR, *rows, ""])


def row(
    lane: str = "quote",
    unit: str = "edge-stateless",
    routes: str = "`/api/quote/**`",
    owned: str = "`server/crates/area-quote/**`, `contract-tests/quote/**`",
    status: str = "open",
    claimed_by: str = "-",
    updated: str = "2026-10-30",
) -> str:
    return (
        f"| {lane} | {unit} | `app/x.py` | {routes} | {owned} | {status} "
        f"| {claimed_by} | {updated} | - |"
    )


def unit(name: str, routes: list[str], services: list[str] | None = None):
    return check_board.Unit(name, "python", tuple(routes), tuple(services or ()))


def test_split_unit_requires_valid_pin_breaker() -> None:
    missing = unit("settings", ["/api/settings/**"])
    assert check_board.check_pin_breakers([missing])
    assert check_board.check_pin_breakers([unit("agent-runtime", [])]) == []
    bad = check_board.Unit("settings", "python", (), (), ("adapter:other",))
    assert check_board.check_pin_breakers([bad])
    good = check_board.Unit("settings", "python", (), (), ("adapter:settings",))
    assert check_board.check_pin_breakers([good]) == []


def test_duplicate_route_in_distinct_units_is_rejected() -> None:
    units = [unit("one", ["/api/a/**"]), unit("two", ["/api/a/**"])]
    assert any(
        "more than one unit" in error
        for error in check_board.check_routes_assigned(units, ["/api/a"])
    )


def test_webbridge_agent_ingress_stays_with_python_loop() -> None:
    units = check_board.load_routing(check_board.ROUTING)
    assert (
        check_board.owner_for(
            units, "/api/team/webbridge/sessions/{session_id}/messages"
        )
        == "agent-runtime"
    )
    assert (
        check_board.owner_for(units, "/api/team/webbridge/status")
        == "webbridge-browser"
    )
    assert (
        check_board.owner_for(units, "/api/team/workspace/git/ai/generate")
        == "agent-runtime"
    )
    assert (
        check_board.owner_for(units, "/api/team/workspace/git/status") == "git-coding"
    )


@pytest.fixture
def app_paths(tmp_path, monkeypatch) -> list[str]:
    """Route paths of an app that always has the web UI mounted."""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("EVOFLUX_WEB_DIST", str(tmp_path))
    from app.api.app import create_app

    paths = check_board.registered_route_paths(create_app())
    assert "/" in paths  # the SPA mount reports an empty path; it is normalised
    return paths


# --- the real repository files ------------------------------------------------


def test_registered_routes_each_resolve_to_one_unit(app_paths: list[str]) -> None:
    units = check_board.load_routing(check_board.ROUTING)
    paths = app_paths

    assert len(paths) > 250
    assert check_board.check_routes_assigned(units, paths) == []


def test_every_gateway_service_is_in_exactly_one_unit() -> None:
    units = check_board.load_routing(check_board.ROUTING)

    assert check_board.check_services(units) == []
    assigned = [s for u in units for s in u.services]
    assert sorted(assigned) == sorted(check_board.GATEWAY_SERVICES)


def test_routing_toml_is_all_python() -> None:
    units = check_board.load_routing(check_board.ROUTING)

    assert units
    assert {u.owner for u in units} == {"python"}


def test_cutover_units_document_matches_routing_toml() -> None:
    units = check_board.load_routing(check_board.ROUTING)
    text = check_board.CUTOVER_UNITS.read_text(encoding="utf-8")

    assert check_board.check_cutover_document(units, text) == []


def test_board_rows_parse_and_validate() -> None:
    units = check_board.load_routing(check_board.ROUTING)
    rows = check_board.parse_board(check_board.BOARD.read_text(encoding="utf-8"))

    assert rows
    assert check_board.check_rows(rows, units) == []


def test_board_lane_owned_paths_do_not_overlap() -> None:
    rows = check_board.parse_board(check_board.BOARD.read_text(encoding="utf-8"))

    assert check_board.check_overlaps(rows) == []


def test_every_registered_route_is_owned_by_a_lane_of_its_unit(
    app_paths: list[str],
) -> None:
    units = check_board.load_routing(check_board.ROUTING)
    rows = check_board.parse_board(check_board.BOARD.read_text(encoding="utf-8"))
    paths = app_paths

    assert check_board.check_lane_coverage(rows, units, paths) == []


def test_known_differences_file_is_empty() -> None:
    assert (ROOT / "server" / "KNOWN_DIFFERENCES.md").read_text(encoding="utf-8") == ""


def test_agents_md_is_the_authoritative_copy_of_the_workflow() -> None:
    workflow = (ROOT / "documents/plans/rust-migration-workflow.md").read_text(
        encoding="utf-8"
    )
    agents = (ROOT / "server" / "AGENTS.md").read_text(encoding="utf-8")

    assert "authoritative" in agents.split("\n\n", 1)[0].lower()
    assert "server/AGENTS.md" in workflow.split("\n\n", 2)[1]
    # The authoritative copy evolves through owner-reviewed shared PRs (for
    # example ADR 0001), so only its structure is pinned: every section of the
    # planning record still exists.
    headings = [line for line in workflow.splitlines() if line.startswith("#")]
    assert headings
    for heading in headings:
        assert heading in agents.splitlines()


def _assert_workflow_rules(agents: str) -> None:
    import re

    phrases = (
        "Never weaken an existing test",
        "No AI co-author trailers",
        "Flaky = failing",
        "Prove the tests can fail",
        "No DDL",
        "#![forbid(unsafe_code)]",
        "Never edit a gate",
        "Rust never calls Python",
    )
    for phrase in phrases:
        assert phrase in agents, phrase
    sections = re.split(r"(?m)^## (?:[1-9]|10)\. [^\n]+\n", agents)
    assert len(sections) == 11
    for section in sections[1:]:
        assert len(section.strip()) >= 100


def test_authoritative_rules_survive_mutations() -> None:
    import pytest

    agents = (ROOT / "server" / "AGENTS.md").read_text(encoding="utf-8")
    _assert_workflow_rules(agents)
    for phrase in (
        "Never weaken an existing test",
        "No AI co-author trailers",
        "Flaky = failing",
        "Prove the tests can fail",
        "No DDL",
        "#![forbid(unsafe_code)]",
        "Never edit a gate",
        "Rust never calls Python",
    ):
        with pytest.raises(AssertionError):
            _assert_workflow_rules(agents.replace(phrase, "REMOVED"))
    with pytest.raises(AssertionError):
        _assert_workflow_rules(
            agents.replace(
                "## 4. Generated and shared code",
                "## 4. Generated and shared code\n",
                1,
            ).replace(
                agents.split("## 4. Generated and shared code", 1)[1].split("## 5.", 1)[
                    0
                ],
                "\nshort\n",
            )
        )


# --- the checker itself can fail ----------------------------------------------


def test_parse_board_reads_columns_and_strips_backticks() -> None:
    rows = check_board.parse_board(board_text(row()))

    assert rows == [
        {
            "lane": "quote",
            "unit": "edge-stateless",
            "python_sources": "app/x.py",
            "routes": "/api/quote/**",
            "owned_paths": "server/crates/area-quote/**, contract-tests/quote/**",
            "status": "open",
            "claimed_by": "-",
            "updated": "2026-10-30",
            "gate_report": "-",
        }
    ]


def test_parse_board_rejects_wrong_columns() -> None:
    text = board_text(row()).replace("claimed_by", "owner")

    with pytest.raises(check_board.BoardError, match="columns"):
        check_board.parse_board(text)


def test_check_rows_flags_bad_status_unit_and_claim() -> None:
    units = [unit("edge-stateless", ["/api/quote/**"])]
    rows = check_board.parse_board(
        board_text(
            row(lane="a", status="done", routes="-"),
            row(lane="b", unit="nowhere", routes="-"),
            row(lane="c", status="claimed", routes="-"),
            row(lane="d", status="blocked:phase-0", routes="-"),
            row(lane="e", unit="none", routes="-"),
        )
    )

    errors = check_board.check_rows(rows, units)

    assert any("a" in e and "status" in e for e in errors)
    assert any("b" in e and "unit" in e for e in errors)
    assert any("c" in e and "claimed_by" in e for e in errors)
    assert not any(e.startswith("d") or e.startswith("e") for e in errors)


def test_check_rows_flags_duplicate_lane_and_route_in_wrong_unit() -> None:
    units = [
        unit("edge-stateless", ["/api/quote/**"]),
        unit("agent-runtime", ["/api/team/**"]),
    ]
    rows = check_board.parse_board(
        board_text(
            row(lane="quote"),
            row(lane="quote"),
            row(lane="team", routes="`/api/quote/**`", unit="agent-runtime"),
        )
    )

    errors = check_board.check_rows(rows, units)

    assert any("duplicate" in e for e in errors)
    assert any("team" in e and "/api/quote" in e for e in errors)


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("server/crates/area-a/**", "server/crates/area-b/**", False),
        ("server/crates/area-a/**", "server/crates/area-a/src/lib.rs", True),
        ("server/crates/core/src/db/**", "server/crates/core/src/*.rs", False),
        ("server/crates/core/src/*.rs", "server/crates/core/src/db.rs", True),
        ("contract-tests/**", "contract-tests/quote/**", True),
        ("server/Cargo.toml", "server/Cargo.toml", True),
        ("server/Cargo.toml", "server/clippy.toml", False),
    ],
)
def test_globs_overlap(a: str, b: str, expected: bool) -> None:
    assert check_board.globs_overlap(a, b) is expected


def test_check_overlaps_flags_two_lanes_on_one_path() -> None:
    rows = check_board.parse_board(
        board_text(
            row(lane="a", owned="`contract-tests/**`"),
            row(lane="b", owned="`contract-tests/quote/**`"),
        )
    )

    errors = check_board.check_overlaps(rows)

    assert len(errors) == 1
    assert "a" in errors[0] and "b" in errors[0]


def test_owner_for_uses_longest_prefix_and_exact_paths() -> None:
    units = [
        unit("health", ["/api/health/live/**"]),
        unit("runtime", ["/api/health/**", "/api/team/**"]),
        unit("meta", ["/metrics"]),
    ]

    assert check_board.owner_for(units, "/api/health/live") == "health"
    assert check_board.owner_for(units, "/api/health/ready") == "runtime"
    assert check_board.owner_for(units, "/api/health") == "runtime"
    assert check_board.owner_for(units, "/metrics") == "meta"
    assert check_board.owner_for(units, "/metrics/x") is None
    assert check_board.owner_for(units, "/api/healthy") is None


def test_check_routes_assigned_flags_unowned_and_duplicate_patterns() -> None:
    units = [
        unit("a", ["/api/x/**"]),
        unit("b", ["/api/x/**", "/api/y/**"]),
    ]

    errors = check_board.check_routes_assigned(units, ["/api/x/1", "/api/z"])

    assert any("/api/z" in e and "no unit" in e for e in errors)
    assert any("/api/x/**" in e and "a" in e and "b" in e for e in errors)


def test_check_services_flags_missing_duplicate_and_unknown() -> None:
    names = list(check_board.GATEWAY_SERVICES)
    units = [
        unit("a", [], names[1:]),
        unit("b", [], [names[2], "bogus"]),
    ]

    errors = check_board.check_services(units)

    assert any(names[0] in e and "no unit" in e for e in errors)
    assert any(names[2] in e and "more than one" in e for e in errors)
    assert any("bogus" in e and "unknown" in e for e in errors)


def test_check_cutover_document_flags_drift() -> None:
    units = [check_board.Unit("a", "python", ("/api/x/**",), ("scheduler",), ("none",))]
    good = (
        "## Route prefixes\n\n| route | unit | pinned by |\n|---|---|---|\n"
        "| `/api/x/**` | a | state |\n\n"
        "## Lifespan services\n\n| service | unit | pinned by |\n|---|---|---|\n"
        "| `scheduler` | a | state |\n\n"
        "## Units\n\n"
        "| unit | phase | pin_breaker | reverse_deps | adapter_call_sites | rationale |\n"
        "|---|---|---|---|---|---|\n"
        "| `a` | 1 | none | - | - | state |\n"
    )
    drifted = good.replace("| a | state |\n\n##", "| b | state |\n\n##")

    assert check_board.check_cutover_document(units, good) == []
    assert check_board.check_cutover_document(units, drifted)


def test_status_counts() -> None:
    rows = check_board.parse_board(
        board_text(
            row(lane="a"),
            row(lane="b"),
            row(lane="c", status="claimed", claimed_by="claude"),
            row(lane="d", status="blocked:phase-0"),
        )
    )

    assert check_board.status_counts(rows) == {
        "open": 2,
        "claimed": 1,
        "blocked": 1,
    }


def test_check_rows_flags_a_route_claimed_by_two_lanes() -> None:
    units = [unit("edge-stateless", ["/api/quote/**", "/api/commands/**"])]
    rows = check_board.parse_board(
        board_text(
            row(lane="quote"),
            row(lane="commands", routes="`/api/commands/**`, `/api/quote/**`"),
        )
    )

    errors = check_board.check_rows(rows, units)

    assert any("/api/quote/**" in e and "also claimed" in e for e in errors)


def test_web_ui_catch_all_never_covers_an_api_route() -> None:
    units = [
        unit("meta", ["/**"]),
        unit("runtime", ["/api/team/**"]),
    ]
    rows = check_board.parse_board(
        board_text(
            row(lane="web-ui", unit="meta", routes="`/**`", owned="`a/**`"),
            row(lane="team", unit="runtime", routes="`/api/team/**`", owned="`b/**`"),
        )
    )

    assert check_board.check_routes_assigned(units, ["/", "/app", "/api/team/x"]) == []
    assert check_board.check_lane_coverage(rows, units, ["/", "/api/team/x"]) == []
    assert check_board.check_routes_assigned(units, ["/api/new"])
    assert check_board.check_lane_coverage(rows, units, ["/api/new"])


def test_adapter_breaker_must_name_its_own_unit() -> None:
    wrong = check_board.Unit("git", "python", (), (), ("adapter:wiki",))
    errors = check_board.check_pin_breakers([wrong])
    assert any("must be adapter:git" in e for e in errors)


def test_none_breaker_is_allowed_for_stateless_units_only_alone() -> None:
    stateless = check_board.Unit("quote", "python", (), (), ("none",))
    mixed = check_board.Unit("quote", "python", (), (), ("none", "file-lock:x"))
    assert check_board.check_pin_breakers([stateless]) == []
    assert check_board.check_pin_breakers([mixed])


def test_unit_can_combine_adapter_and_file_lock_breakers() -> None:
    both = check_board.Unit(
        "git", "python", (), (), ("adapter:git", "file-lock:git-repo")
    )
    assert check_board.check_pin_breakers([both]) == []
    bad_lock = check_board.Unit("git", "python", (), (), ("file-lock:Git Repo",))
    assert check_board.check_pin_breakers([bad_lock])


UNITS_HEADER = (
    "## Units\n\n"
    "| unit | phase | pin_breaker | reverse_deps | adapter_call_sites | rationale |\n"
    "|---|---|---|---|---|---|\n"
)


def test_adapter_call_sites_require_reverse_deps() -> None:
    units = [check_board.Unit("git", "python", (), (), ("adapter:git",))]
    ok = UNITS_HEADER + "| `git` | 2 | `adapter:git` | locks | `app/x.py` | why |\n"
    bad = UNITS_HEADER + "| `git` | 2 | `adapter:git` | - | `app/x.py` | why |\n"

    assert check_board._check_breaker_table(units, ok) == []
    errors = check_board._check_breaker_table(units, bad)
    assert any("no reverse_deps" in e for e in errors)


def test_adapter_call_sites_need_an_adapter_breaker_and_table_must_match() -> None:
    units = [check_board.Unit("git", "python", (), (), ("none",))]
    sites = UNITS_HEADER + "| `git` | 2 | none | locks | `app/x.py` | why |\n"
    drift = UNITS_HEADER + "| `git` | 2 | `adapter:git` | - | - | why |\n"

    errors = check_board._check_breaker_table(units, sites)
    assert any("no adapter breaker" in e for e in errors)
    errors = check_board._check_breaker_table(units, drift)
    assert any("pin_breaker of git" in e for e in errors)


@pytest.mark.parametrize(
    ("path", "unit_name"),
    [
        ("/api/team/abc/terminal/x", "terminal"),
        ("/api/team/abc/files/watch", "agent"),
        ("/api/team/abc/files/a.txt", "files"),
        ("/api/team/workspace/files/read", "files-ws"),
        ("/api/team/abc/stream", "agent"),
        ("/api/team/abc", "agent"),
    ],
)
def test_param_segments_match_one_segment_and_literals_win(
    path: str, unit_name: str
) -> None:
    units = [
        unit("agent", ["/api/team/**", "/api/team/{session_id}/files/watch/**"]),
        unit("terminal", ["/api/team/{session_id}/terminal/**"]),
        unit("files", ["/api/team/{session_id}/files/**"]),
        unit("files-ws", ["/api/team/workspace/files/**"]),
    ]

    assert check_board.owner_for(units, path) == unit_name


def test_param_pattern_does_not_match_a_missing_segment() -> None:
    units = [unit("t", ["/api/team/{session_id}/terminal/**"]), unit("a", ["/api/**"])]

    assert check_board.owner_for(units, "/api/team/terminal") == "a"
    assert check_board.owner_for(units, "/api/team//terminal") == "a"


def test_concrete_path_instantiates_templates() -> None:
    assert check_board.concrete_path("/api/team/{session_id}/x") == "/api/team/abc/x"
    assert check_board.concrete_path("/f/{file_path:path}") == "/f/a/b"


def test_check_concrete_routes_flags_a_template_that_only_matches_literally() -> None:
    template = ["/api/team/{session_id}/terminal"]
    good = [unit("a", ["/api/team/**", "/api/team/{session_id}/terminal/**"])]
    broken = [unit("a", ["/api/team/**"]), unit("t", ["/api/team/abc/terminal/**"])]

    assert check_board.check_concrete_routes(good, template) == []
    assert check_board.check_concrete_routes(broken, template)


EXPECTED_UNIT_FOR_SEGMENT = {
    "terminal": "terminal-processes",
    "terminals": "terminal-processes",
    "files": "workspace-files",
    "workspace": "workspace-files",
    "uploads": "workspace-files",
    "browser": "webbridge-browser",
    "computer": "webbridge-browser",
    "document-preview": "documents-preview",
    "office-preview": "documents-preview",
    "document-versions": "documents-preview",
    "motion-review": "documents-preview",
    "media": "documents-preview",
}


def test_templated_session_routes_land_in_their_units_not_agent_runtime(
    app_paths: list[str],
) -> None:
    units = check_board.load_routing(check_board.ROUTING)
    checked = 0
    for path in app_paths:
        parts = path.split("/")
        if parts[:3] != ["", "api", "team"] or len(parts) < 5:
            continue
        if parts[3] != "{session_id}" or parts[4] not in EXPECTED_UNIT_FOR_SEGMENT:
            continue
        if parts[4:6] == ["files", "watch"]:
            expected = "terminal-processes"
        else:
            expected = EXPECTED_UNIT_FOR_SEGMENT[parts[4]]
        concrete = check_board.concrete_path(path)
        assert check_board.owner_for(units, concrete) == expected, concrete
        checked += 1

    assert checked >= 20
    assert check_board.check_concrete_routes(units, app_paths) == []
