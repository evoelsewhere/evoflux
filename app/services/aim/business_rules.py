"""Business-rule discovery, confirmation, and review evidence."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid7

import yaml

_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)", re.DOTALL)


class BusinessRuleError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BusinessRule:
    id: str
    unit: str
    status: Literal["candidate", "confirmed"]
    source_ref: str | None
    path: Path
    title: str
    sha256: str


def _parse_rule(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise BusinessRuleError(f"business rule {path.name} has no frontmatter")
    data = yaml.safe_load(match.group(1)) or {}
    if not isinstance(data, dict):
        raise BusinessRuleError(f"business rule {path.name} frontmatter is invalid")
    return data, match.group(2).strip()


def _rule_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def list_business_rules(kb_root: Path, unit: str) -> list[BusinessRule]:
    rules_root = kb_root / "business-rules"
    if not rules_root.is_dir():
        return []
    rules: list[BusinessRule] = []
    for path in sorted(rules_root.glob("*.md")):
        data, body = _parse_rule(path)
        if data.get("unit") != unit:
            continue
        status = data.get("status")
        if status not in {"candidate", "confirmed"}:
            raise BusinessRuleError(
                f"business rule {path.name} has invalid status {status!r}"
            )
        title = next(
            (line.removeprefix("# ").strip() for line in body.splitlines() if line.startswith("# ")),
            path.stem,
        )
        rules.append(
            BusinessRule(
                id=path.stem,
                unit=unit,
                status=status,
                source_ref=(
                    str(data["source_ref"]) if data.get("source_ref") is not None else None
                ),
                path=path,
                title=title,
                sha256=_rule_digest(path),
            )
        )
    return rules


def business_rule_review_path(kb_root: Path, unit: str) -> Path:
    module, name = unit.split("/", 1)
    return kb_root / "state" / "business-rules" / module / f"{name}.yaml"


def _write_review(
    kb_root: Path,
    unit: str,
    *,
    outcome: Literal["confirmed", "no_rules"],
    execution_id: str,
) -> Path:
    try:
        UUID(execution_id)
    except ValueError as exc:
        raise BusinessRuleError("workflow execution id is not a UUID") from exc
    rules = list_business_rules(kb_root, unit)
    path = business_rule_review_path(kb_root, unit)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "id": str(uuid7()),
                "unit": unit,
                "outcome": outcome,
                "workflow_execution_id": execution_id,
                "rules": [
                    {"id": rule.id, "status": rule.status, "sha256": rule.sha256}
                    for rule in rules
                ],
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def confirm_business_rules(kb_root: Path, unit: str, execution_id: str) -> Path:
    rules = list_business_rules(kb_root, unit)
    if not rules:
        raise BusinessRuleError(
            f"unit {unit} has no business rules; record an explicit no-rules review"
        )
    for rule in rules:
        data, body = _parse_rule(rule.path)
        data["status"] = "confirmed"
        content = (
            f"---\n{yaml.safe_dump(data, sort_keys=False).strip()}\n---\n\n"
            f"{body}\n"
        )
        rule.path.write_text(content, encoding="utf-8")
    return _write_review(
        kb_root, unit, outcome="confirmed", execution_id=execution_id
    )


def confirm_no_business_rules(kb_root: Path, unit: str, execution_id: str) -> Path:
    rules = list_business_rules(kb_root, unit)
    if rules:
        raise BusinessRuleError(
            f"unit {unit} has {len(rules)} business rule(s); they must be reviewed"
        )
    return _write_review(kb_root, unit, outcome="no_rules", execution_id=execution_id)


def business_rule_review_ready(kb_root: Path, unit: str) -> tuple[bool, str]:
    path = business_rule_review_path(kb_root, unit)
    if not path.is_file():
        return False, f"business rules for {unit} have not been reviewed"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        rules = list_business_rules(kb_root, unit)
    except (OSError, UnicodeDecodeError, yaml.YAMLError, BusinessRuleError) as exc:
        return False, str(exc)
    if data.get("unit") != unit:
        return False, f"business-rule review names {data.get('unit')!r}, expected {unit}"
    outcome = data.get("outcome")
    recorded = {
        str(item.get("id")): (item.get("status"), item.get("sha256"))
        for item in data.get("rules", [])
        if isinstance(item, dict)
    }
    current = {rule.id: (rule.status, rule.sha256) for rule in rules}
    if outcome == "no_rules":
        return (not current, "" if not current else f"unit {unit} now has unreviewed rules")
    if outcome != "confirmed":
        return False, f"business-rule review for {unit} has invalid outcome {outcome!r}"
    if not current:
        return False, f"business-rule review for {unit} records no confirmed rules"
    if any(rule.status != "confirmed" for rule in rules):
        return False, f"business rules for {unit} still contain candidates"
    if current != recorded:
        return False, f"business rules for {unit} changed after review"
    return True, ""