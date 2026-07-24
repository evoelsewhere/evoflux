from pathlib import Path
from uuid import uuid4

from app.services.aim.business_rules import (
    business_rule_review_ready,
    confirm_business_rules,
    confirm_no_business_rules,
)


def _write_rule(root: Path, rule_id: str, unit: str, status: str = "candidate") -> None:
    path = root / "business-rules" / f"{rule_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nstatus: {status}\nunit: {unit}\nsource_ref: src/a.c:1\n---\n\n"
        f"# {rule_id}: Exact behavior\n\nA cited behavior.\n"
    )


def test_confirm_business_rules_records_hash_bound_review(tmp_path: Path):
    _write_rule(tmp_path, "BR-CORE-0001", "core/A")

    confirm_business_rules(tmp_path, "core/A", str(uuid4()))

    ready, blocker = business_rule_review_ready(tmp_path, "core/A")
    assert ready, blocker
    assert "status: confirmed" in (
        tmp_path / "business-rules/BR-CORE-0001.md"
    ).read_text()


def test_review_invalidates_when_rule_changes(tmp_path: Path):
    _write_rule(tmp_path, "BR-CORE-0001", "core/A")
    confirm_business_rules(tmp_path, "core/A", str(uuid4()))
    path = tmp_path / "business-rules/BR-CORE-0001.md"
    path.write_text(path.read_text() + "Changed after approval.\n")

    ready, blocker = business_rule_review_ready(tmp_path, "core/A")
    assert not ready
    assert "changed after review" in blocker


def test_no_rules_requires_explicit_empty_catalog(tmp_path: Path):
    confirm_no_business_rules(tmp_path, "core/A", str(uuid4()))
    ready, blocker = business_rule_review_ready(tmp_path, "core/A")
    assert ready, blocker