from app.services.aim.canonicalize import canonicalize_text
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


def test_mask_rule_replaces_pattern():
    profile = _profile(
        mask=[
            {"pattern": r'"timestamp":\s*"[^"]*"', "replace": '"timestamp":"<masked>"'}
        ]
    )
    text = '{"timestamp": "2026-07-16T10:00:00Z", "value": 1}'
    result = canonicalize_text(text, profile)
    assert '"timestamp":"<masked>"' in result
    assert "2026-07-16" not in result


def test_whitespace_normalize_collapses_spaces_and_trailing():
    profile = _profile(whitespace="normalize")
    text = "a   b\t\tc   \nline2  "
    result = canonicalize_text(text, profile)
    assert result == "a b c\nline2"


def test_whitespace_exact_leaves_text_untouched():
    profile = _profile(whitespace="exact")
    text = "a   b   "
    assert canonicalize_text(text, profile) == text


def test_from_yaml_dict_parses_full_schema():
    data = {
        "id": "default",
        "description": "test profile",
        "encoding": {"default": "utf-8"},
        "mask": [{"pattern": "x", "replace": "y"}],
        "whitespace": "normalize",
        "sort_before_diff": {"paths": ["**/*.json"]},
        "number_format": {"decimal_tolerance": 0.01, "trim_trailing_zeros": True},
        "fixed_width": {"fields": [{"field": "code", "width": 10, "pad": "right"}]},
    }
    profile = CanonicalProfile.from_yaml_dict(data)
    assert profile.id == "default"
    assert profile.encoding_default == "utf-8"
    assert profile.sort_before_diff_paths == ["**/*.json"]
    assert profile.decimal_tolerance == 0.01
    assert profile.fixed_width_fields[0].field == "code"
