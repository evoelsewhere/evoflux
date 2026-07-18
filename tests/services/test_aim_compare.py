from pathlib import Path

from app.services.aim.compare import compare_dirs, write_report
from app.services.aim.models import CanonicalProfile


def _profile(**overrides) -> CanonicalProfile:
    base = {
        "id": "test",
        "mask": [],
        "whitespace": "normalize",
        "sort_before_diff_paths": [],
        "decimal_tolerance": 0.0,
    }
    base.update(overrides)
    return CanonicalProfile(**base)


def test_identical_files_pass(tmp_path: Path):
    expected = tmp_path / "expected"
    actual = tmp_path / "actual"
    expected.mkdir()
    actual.mkdir()
    (expected / "out.txt").write_text("hello world\n")
    (actual / "out.txt").write_text("hello world\n")

    report = compare_dirs(expected, actual, _profile())
    assert report.verdict == "pass"
    assert report.diff_count == 0


def test_text_diff_fails_with_unified_diff_detail(tmp_path: Path):
    expected = tmp_path / "expected"
    actual = tmp_path / "actual"
    expected.mkdir()
    actual.mkdir()
    (expected / "out.txt").write_text("line1\nline2\n")
    (actual / "out.txt").write_text("line1\nCHANGED\n")

    report = compare_dirs(expected, actual, _profile())
    assert report.verdict == "fail"
    assert report.diff_count == 1
    assert report.files[0].status == "diff"
    assert "CHANGED" in report.files[0].detail


def test_missing_and_extra_files_detected(tmp_path: Path):
    expected = tmp_path / "expected"
    actual = tmp_path / "actual"
    expected.mkdir()
    actual.mkdir()
    (expected / "only_expected.txt").write_text("x")
    (actual / "only_actual.txt").write_text("y")

    report = compare_dirs(expected, actual, _profile())
    statuses = {f.path: f.status for f in report.files}
    assert statuses["only_expected.txt"] == "missing"
    assert statuses["only_actual.txt"] == "extra"
    assert report.verdict == "fail"


def test_json_numeric_tolerance_accepts_small_delta(tmp_path: Path):
    expected = tmp_path / "expected"
    actual = tmp_path / "actual"
    expected.mkdir()
    actual.mkdir()
    (expected / "out.json").write_text('{"amount": 10.001}')
    (actual / "out.json").write_text('{"amount": 10.002}')

    report = compare_dirs(expected, actual, _profile(decimal_tolerance=0.01))
    assert report.verdict == "pass"

    report_strict = compare_dirs(expected, actual, _profile(decimal_tolerance=0.0))
    assert report_strict.verdict == "fail"


def test_sort_before_diff_ignores_json_array_order(tmp_path: Path):
    expected = tmp_path / "expected"
    actual = tmp_path / "actual"
    expected.mkdir()
    actual.mkdir()
    (expected / "out.json").write_text('[3, 1, 2]')
    (actual / "out.json").write_text('[1, 2, 3]')

    report = compare_dirs(expected, actual, _profile())
    assert report.verdict == "fail"

    report_sorted = compare_dirs(
        expected, actual, _profile(sort_before_diff_paths=["*.json"])
    )
    assert report_sorted.verdict == "pass"


def test_mask_normalizes_volatile_fields_before_diff(tmp_path: Path):
    expected = tmp_path / "expected"
    actual = tmp_path / "actual"
    expected.mkdir()
    actual.mkdir()
    (expected / "out.txt").write_text("run-id: abc123\nvalue: 1")
    (actual / "out.txt").write_text("run-id: xyz789\nvalue: 1")

    report = compare_dirs(expected, actual, _profile())
    assert report.verdict == "fail"

    masked_profile = _profile(
        mask=[{"pattern": r"run-id: \w+", "replace": "run-id: <masked>"}]
    )
    report_masked = compare_dirs(expected, actual, masked_profile)
    assert report_masked.verdict == "pass"


def test_ignore_globs_drop_volatile_files(tmp_path: Path):
    expected = tmp_path / "expected"
    actual = tmp_path / "actual"
    expected.mkdir()
    actual.mkdir()
    (expected / "out.txt").write_text("same\n")
    (actual / "out.txt").write_text("same\n")
    # A volatile log present only on one side, and differing — must not count.
    (expected / "run.log").write_text("started 10:00\n")
    (actual / "run.log").write_text("started 11:11\n")
    (actual / "spool.log").write_text("extra\n")

    report = compare_dirs(expected, actual, _profile(ignore=["*.log"]))
    assert report.verdict == "pass"
    assert report.diff_count == 0

    report_no_ignore = compare_dirs(expected, actual, _profile())
    assert report_no_ignore.verdict == "fail"


def test_fixed_width_field_level_compare(tmp_path: Path):
    expected = tmp_path / "expected"
    actual = tmp_path / "actual"
    expected.mkdir()
    actual.mkdir()
    # 3-char id, 8-char amount. Second row's amount rounds within tolerance.
    (expected / "rec.txt").write_text("001    10.00\n002    20.00\n")
    (actual / "rec.txt").write_text("001    10.00\n002    20.01\n")

    fields = [
        {"field": "id", "width": 7, "pad": "right"},
        {"field": "amount", "width": 8, "pad": "left"},
    ]
    strict = _profile(fixed_width_fields=fields, decimal_tolerance=0.0)
    report = compare_dirs(expected, actual, strict)
    assert report.verdict == "fail"
    assert "field amount" in report.files[0].detail

    tolerant = _profile(fixed_width_fields=fields, decimal_tolerance=0.05)
    assert compare_dirs(expected, actual, tolerant).verdict == "pass"


def test_plaintext_decimal_tolerance(tmp_path: Path):
    expected = tmp_path / "expected"
    actual = tmp_path / "actual"
    expected.mkdir()
    actual.mkdir()
    (expected / "out.txt").write_text("total 100.00 count 3\n")
    (actual / "out.txt").write_text("total 100.01 count 3\n")

    assert compare_dirs(expected, actual, _profile()).verdict == "fail"
    assert (
        compare_dirs(expected, actual, _profile(decimal_tolerance=0.05)).verdict
        == "pass"
    )


def test_trim_trailing_zeros_makes_decimals_equal(tmp_path: Path):
    expected = tmp_path / "expected"
    actual = tmp_path / "actual"
    expected.mkdir()
    actual.mkdir()
    (expected / "out.txt").write_text("amount 1.50 rate 2.000\n")
    (actual / "out.txt").write_text("amount 1.5 rate 2\n")

    assert compare_dirs(expected, actual, _profile(trim_trailing_zeros=True)).verdict == "pass"
    assert compare_dirs(expected, actual, _profile(trim_trailing_zeros=False)).verdict == "fail"


def test_legacy_encoding_fallback_decodes_ebcdic(tmp_path: Path):
    expected = tmp_path / "expected"
    actual = tmp_path / "actual"
    expected.mkdir()
    actual.mkdir()
    # Golden written in EBCDIC (cp037); actual in utf-8. With the fallback
    # they canonicalize to the same text and match.
    (expected / "out.txt").write_bytes("HELLO\n".encode("cp037"))
    (actual / "out.txt").write_text("HELLO\n", encoding="utf-8")

    report = compare_dirs(
        expected, actual, _profile(encoding_legacy_fallback="cp037")
    )
    assert report.verdict == "pass"


def test_write_report_creates_json_and_markdown(tmp_path: Path):
    expected = tmp_path / "expected"
    actual = tmp_path / "actual"
    expected.mkdir()
    actual.mkdir()
    (expected / "out.txt").write_text("a")
    (actual / "out.txt").write_text("a")

    report = compare_dirs(expected, actual, _profile())
    report_dir = tmp_path / "report"
    json_path, md_path = write_report(report, report_dir)

    assert json_path.exists()
    assert md_path.exists()
    assert '"verdict": "pass"' in json_path.read_text()
