from pathlib import Path

import pytest

from app.services.aim.kb_store import list_units, read_manifest, read_unit, write_unit
from app.services.aim.models import AimManifest


def test_write_then_read_unit_round_trips(tmp_path: Path):
    write_unit(
        tmp_path,
        "core-batch",
        "PAYROLL01",
        kind="program",
        phase="inventory",
        source_paths=["src/PAYROLL01.cbl"],
        body="Initial notes.",
    )
    result = read_unit(tmp_path, "core-batch", "PAYROLL01")
    assert result is not None
    frontmatter, body = result
    assert frontmatter.kind == "program"
    assert frontmatter.phase == "inventory"
    assert frontmatter.source_paths == ["src/PAYROLL01.cbl"]
    assert body == "Initial notes."


def test_partial_update_preserves_body_and_other_fields(tmp_path: Path):
    write_unit(
        tmp_path,
        "core-batch",
        "PAYROLL01",
        kind="program",
        phase="inventory",
        source_paths=["src/PAYROLL01.cbl"],
        body="Detailed module doc written by aim-archaeologist.",
    )
    write_unit(tmp_path, "core-batch", "PAYROLL01", phase="understood")

    frontmatter, body = read_unit(tmp_path, "core-batch", "PAYROLL01")
    assert frontmatter.phase == "understood"
    assert frontmatter.kind == "program"  # preserved
    assert frontmatter.source_paths == ["src/PAYROLL01.cbl"]  # preserved
    assert body == "Detailed module doc written by aim-archaeologist."  # preserved


def test_read_unit_returns_none_when_missing(tmp_path: Path):
    assert read_unit(tmp_path, "core-batch", "NOPE") is None


def test_list_units_walks_modules_tree(tmp_path: Path):
    write_unit(tmp_path, "core-batch", "PAYROLL01", kind="program", phase="inventory")
    write_unit(tmp_path, "core-batch", "TAXCALC", kind="program", phase="understood")
    write_unit(tmp_path, "screens", "LOGIN", kind="screen", phase="designed")

    units = list_units(tmp_path)
    keys = {(m, n) for m, n, _, _ in units}
    assert keys == {
        ("core-batch", "PAYROLL01"),
        ("core-batch", "TAXCALC"),
        ("screens", "LOGIN"),
    }
    by_key = {(m, n): fm for m, n, fm, _ in units}
    assert by_key[("core-batch", "TAXCALC")].phase == "understood"


def test_list_units_skips_files_without_frontmatter(tmp_path: Path):
    (tmp_path / "modules" / "core-batch").mkdir(parents=True)
    (tmp_path / "modules" / "core-batch" / "NOTES.md").write_text("no frontmatter here")
    write_unit(tmp_path, "core-batch", "PAYROLL01", kind="program")

    units = list_units(tmp_path)
    assert len(units) == 1
    assert units[0][1] == "PAYROLL01"


def test_list_units_empty_when_no_modules_dir(tmp_path: Path):
    assert list_units(tmp_path) == []


def test_read_manifest_parses_aim_yaml(tmp_path: Path):
    (tmp_path / "aim.yaml").write_text(
        """
rulebook:
  id: java8-java21
  version: "0.1"
roles:
  source: [core-batch-repo]
  target: [core-batch-java21]
golden_dir: golden
compare_default_profile: default
phase: understand
"""
    )
    manifest = read_manifest(tmp_path)
    assert isinstance(manifest, AimManifest)
    assert manifest.rulebook.id == "java8-java21"
    assert manifest.roles.source == ["core-batch-repo"]
    assert manifest.phase == "understand"


def test_read_manifest_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        read_manifest(tmp_path)
