"""A clarifying question must never offer the same answer twice.

Observed in a real EASD specify phase: three of four questions rendered
`options[2]` identical to `options[0]`, and the two-way question "in-memory
state only, or persistence?" offered "Yes, in-memory only" twice — leaving no
way to choose the second branch except free text. Selecting either duplicate
also lit both chips, because selection is compared by value.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent.tools.builtin.ask_user import (
    AskUserQuestionSpec,
    QuestionSpec,
    normalize_question_options,
)


class TestNormalization:
    def test_exact_duplicates_collapse_to_one(self):
        assert normalize_question_options(
            [
                "Rolling/sliding window",
                "Fixed (aligned) window",
                "Rolling/sliding window",
            ]
        ) == ["Rolling/sliding window", "Fixed (aligned) window"]

    def test_comparison_ignores_case_and_surrounding_space(self):
        assert normalize_question_options(
            ["In-memory only", "in-memory only ", "  IN-MEMORY ONLY"]
        ) == ["In-memory only"]

    def test_first_spelling_is_preserved(self):
        assert normalize_question_options(["Fixed Window", "fixed window"]) == [
            "Fixed Window"
        ]

    def test_blanks_are_dropped(self):
        assert normalize_question_options(["a", "", "   ", "b"]) == ["a", "b"]

    def test_order_is_stable(self):
        assert normalize_question_options(["c", "a", "b", "a"]) == ["c", "a", "b"]

    def test_empty_stays_empty(self):
        assert normalize_question_options([]) == []


class TestQuestionSpec:
    def test_duplicate_options_are_removed(self):
        spec = QuestionSpec(
            question="What window semantics should be enforced?",
            options=["Rolling", "Fixed", "Rolling"],
        )
        assert spec.options == ["Rolling", "Fixed"]

    def test_degenerate_two_way_question_collapses(self):
        """The exact observed failure: both branches read the same."""

        spec = QuestionSpec(
            question="In-memory state only, or persistence?",
            options=["Yes, in-memory only", "Yes, in-memory only"],
        )
        assert spec.options == ["Yes, in-memory only"]

    def test_strict_question_rejects_collapsed_choices(self):
        with pytest.raises(ValidationError) as excinfo:
            QuestionSpec(
                question="Route the branch",
                options=["Approve", "approve"],
                strict=True,
            )
        assert "two distinct options" in str(excinfo.value)

    def test_strict_question_accepts_distinct_choices(self):
        spec = QuestionSpec(
            question="Route the branch",
            options=["Approve", "Reject"],
            strict=True,
        )
        assert spec.options == ["Approve", "Reject"]

    def test_non_strict_question_may_have_no_options(self):
        assert QuestionSpec(question="Anything else?").options == []


class TestModelFacingSpec:
    def test_agent_supplied_duplicates_never_reach_the_user(self):
        spec = AskUserQuestionSpec(
            question="When exactly is a request counted?",
            options=[
                "Until oldest in window expires",
                "Until full window reset after next allowed",
                "Until oldest in window expires",
            ],
        )
        assert spec.options == [
            "Until oldest in window expires",
            "Until full window reset after next allowed",
        ]

    def test_option_description_warns_against_repeats(self):
        description = AskUserQuestionSpec.model_fields["options"].description or ""
        assert "distinct answer" in description
