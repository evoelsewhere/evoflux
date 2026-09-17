from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.services.asdd_document import parse_document
from app.services.asdd_spec_format import parse_delta, parse_spec
from app.services.asdd_store import (
    AsddCatalogue,
    AsddChangeExists,
    AsddChangeNotFound,
    AsddStoreError,
    normalize_data_directory,
    normalize_slug,
    parse_open_questions,
    parse_tasks,
    slugify,
)

DELTA = """## ADDED Requirements

### Requirement: Slug identity

A change SHALL be identified by its directory name.

#### Scenario: Two chats open the same change

- **WHEN** two Coding chats point at `add-user-auth`
- **THEN** both read and write the same change folder
"""


@pytest.fixture
def catalogue(tmp_path: Path) -> AsddCatalogue:
    return AsddCatalogue.create(tmp_path, "documents/asdd")


def seeded(catalogue: AsddCatalogue) -> AsddCatalogue:
    catalogue.create_change(
        change_id="add-user-auth",
        title="Add user authentication",
        risk="standard",
        capabilities=["user-auth"],
    )
    return catalogue


def test_a_new_change_starts_at_drafting_with_no_approvals(
    catalogue: AsddCatalogue,
) -> None:
    record = catalogue.create_change(
        change_id="add-user-auth", title="Add user authentication"
    )

    assert record.artifacts.status == "drafting"
    assert record.artifacts.approvals == {
        "proposal": None,
        "specs": None,
        "design": None,
        "tasks": None,
    }
    assert catalogue.list_change_ids() == ["add-user-auth"]


def test_the_change_folder_is_the_only_identity(catalogue: AsddCatalogue) -> None:
    record = seeded(catalogue).read_change("add-user-auth")
    text = (record.path / "proposal.md").read_text(encoding="utf-8")

    assert "add-user-auth" in text
    for absent in ("content_hash", "session_id", "run_id", "revision_id"):
        assert absent not in text


def test_a_proposal_that_names_another_change_is_refused(
    catalogue: AsddCatalogue,
) -> None:
    record = seeded(catalogue).read_change("add-user-auth")
    path = record.path / "proposal.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "change: add-user-auth", "change: something-else"
        ),
        encoding="utf-8",
    )

    with pytest.raises(AsddStoreError, match="lives in 'add-user-auth/'"):
        catalogue.read_change("add-user-auth")


def test_creating_a_change_twice_is_refused(catalogue: AsddCatalogue) -> None:
    seeded(catalogue)

    with pytest.raises(AsddChangeExists):
        catalogue.create_change(change_id="add-user-auth", title="Again")


def test_reading_an_unknown_change_says_so(catalogue: AsddCatalogue) -> None:
    with pytest.raises(AsddChangeNotFound):
        catalogue.read_change("never-existed")


def test_approving_advances_the_status_and_stamps_the_gate(
    catalogue: AsddCatalogue,
) -> None:
    seeded(catalogue)

    record = catalogue.approve("add-user-auth", "proposal")

    assert record.artifacts.status == "specifying"
    assert record.artifacts.approvals["proposal"]
    assert record.artifacts.approvals["specs"] is None


def test_a_second_approval_of_the_same_artifact_is_harmless(
    catalogue: AsddCatalogue,
) -> None:
    seeded(catalogue)
    catalogue.approve("add-user-auth", "proposal")

    record = catalogue.approve("add-user-auth", "proposal")

    assert record.artifacts.status == "specifying"


def test_writing_a_delta_registers_its_capability(catalogue: AsddCatalogue) -> None:
    seeded(catalogue)

    record = catalogue.write_delta("add-user-auth", "user-auth", parse_delta(DELTA))

    assert record.artifacts.delta_capabilities == ["user-auth"]
    assert record.artifacts.spec_problems == []


def test_a_malformed_delta_is_reported_rather_than_raised(
    catalogue: AsddCatalogue,
) -> None:
    record = seeded(catalogue).read_change("add-user-auth")
    path = record.path / "specs" / "user-auth" / "spec.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "## ADDED Requirements\n\n### Requirement: Naked\n\nNo scenario here.\n",
        encoding="utf-8",
    )

    problems = catalogue.read_change("add-user-auth").artifacts.spec_problems

    assert any("has no scenario" in problem for problem in problems)


def test_tasks_progress_is_read_from_the_checklist(catalogue: AsddCatalogue) -> None:
    seeded(catalogue)

    record = catalogue.write_artifact(
        "add-user-auth",
        "tasks",
        "## 1. Implementation\n\n- [x] Write the store\n- [ ] Write the route\n",
    )

    assert (record.artifacts.tasks_total, record.artifacts.tasks_done) == (2, 1)


def test_evidence_is_a_page_in_the_change_folder(catalogue: AsddCatalogue) -> None:
    seeded(catalogue)

    record = catalogue.record_evidence(
        "add-user-auth",
        evidence_id="pytest-services",
        kind="machine",
        result="passed",
        summary="pytest tests/services",
        requirement="Slug identity",
    )

    assert record.artifacts.evidence_ids == ["pytest-services"]
    assert (record.path / "evidence" / "pytest-services.md").is_file()
    assert record.artifacts.review_recorded is False


def test_a_passing_review_page_satisfies_the_independent_review_gate(
    catalogue: AsddCatalogue,
) -> None:
    seeded(catalogue)

    record = catalogue.record_evidence(
        "add-user-auth",
        evidence_id="review-1",
        kind="review",
        result="passed",
        summary="Reviewed the integrated revision.",
    )

    assert record.artifacts.review_recorded is True


def test_archiving_folds_the_delta_into_a_new_capability_spec(
    catalogue: AsddCatalogue,
) -> None:
    """A capability with no spec yet must be created, not skipped."""

    seeded(catalogue)
    catalogue.write_delta("add-user-auth", "user-auth", parse_delta(DELTA))

    updated = catalogue.archive_change("add-user-auth", today=date(2026, 9, 16))

    assert updated == ["user-auth"]
    assert catalogue.list_capabilities() == ["user-auth"]
    spec = catalogue.read_spec("user-auth")
    assert spec is not None
    assert [item.name for item in spec[1].requirements] == ["Slug identity"]


def test_archiving_retires_the_change_folder_under_a_dated_name(
    catalogue: AsddCatalogue,
) -> None:
    seeded(catalogue)
    catalogue.write_delta("add-user-auth", "user-auth", parse_delta(DELTA))

    catalogue.archive_change("add-user-auth", today=date(2026, 9, 16))

    assert catalogue.list_change_ids() == []
    assert catalogue.list_archived() == ["2026-09-16-add-user-auth"]
    archived = (
        catalogue.archive_path / "2026-09-16-add-user-auth" / "proposal.md"
    ).read_text(encoding="utf-8")
    assert "status: archived" in archived


def test_archiving_merges_into_an_existing_capability_spec(
    catalogue: AsddCatalogue,
) -> None:
    seeded(catalogue)
    catalogue.write_delta("add-user-auth", "user-auth", parse_delta(DELTA))
    catalogue.archive_change("add-user-auth", today=date(2026, 9, 16))

    catalogue.create_change(
        change_id="extend-user-auth", title="Extend", capabilities=["user-auth"]
    )
    catalogue.write_delta(
        "extend-user-auth",
        "user-auth",
        parse_delta(
            """## ADDED Requirements

### Requirement: Soft chat pointer

A chat SHALL point at a change without owning it.

#### Scenario: Switch change

- **WHEN** a chat opens another change
- **THEN** the previous change keeps its state
"""
        ),
    )

    catalogue.archive_change("extend-user-auth", today=date(2026, 9, 17))

    spec = catalogue.read_spec("user-auth")
    assert spec is not None
    assert [item.name for item in spec[1].requirements] == [
        "Slug identity",
        "Soft chat pointer",
    ]


def test_a_change_with_no_delta_cannot_be_archived(catalogue: AsddCatalogue) -> None:
    seeded(catalogue)

    with pytest.raises(AsddStoreError, match="no capability delta"):
        catalogue.archive_change("add-user-auth")


def test_a_change_with_a_malformed_delta_cannot_be_archived(
    catalogue: AsddCatalogue,
) -> None:
    record = seeded(catalogue).read_change("add-user-auth")
    path = record.path / "specs" / "user-auth" / "spec.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "## ADDED Requirements\n\n### Requirement: Naked\n", encoding="utf-8"
    )

    with pytest.raises(AsddStoreError, match="cannot be archived"):
        catalogue.archive_change("add-user-auth")


def test_a_refused_archive_leaves_every_capability_spec_untouched(
    catalogue: AsddCatalogue,
) -> None:
    """A fold that cannot finish must not half-finish.

    Merging one capability and then failing would leave the change open with
    its requirements already in the catalogue, and the retry would be refused
    for requirements the catalogue now contains.
    """

    seeded(catalogue)
    catalogue.write_delta("add-user-auth", "user-auth", parse_delta(DELTA))
    broken = catalogue.change_path("add-user-auth") / "specs" / "audit-log" / "spec.md"
    broken.parent.mkdir(parents=True)
    broken.write_text(
        "## ADDED Requirements\n\n### Requirement: Naked\n", encoding="utf-8"
    )

    with pytest.raises(AsddStoreError, match="cannot be archived"):
        catalogue.archive_change("add-user-auth")

    assert catalogue.list_capabilities() == []
    assert catalogue.list_change_ids() == ["add-user-auth"]


def test_a_delta_with_unreadable_front_matter_reports_itself(
    catalogue: AsddCatalogue,
) -> None:
    record = seeded(catalogue).read_change("add-user-auth")
    path = record.path / "specs" / "user-auth" / "spec.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\ncapability: [\n---\n\n## ADDED Requirements\n", encoding="utf-8"
    )

    artifacts = catalogue.read_change("add-user-auth").artifacts

    assert artifacts.delta_capabilities == ["user-auth"]
    assert any("not valid YAML" in problem for problem in artifacts.spec_problems)


def test_an_unreadable_evidence_page_does_not_hide_the_others(
    catalogue: AsddCatalogue,
) -> None:
    seeded(catalogue)
    record = catalogue.record_evidence(
        "add-user-auth",
        evidence_id="pytest",
        kind="machine",
        result="passed",
        summary="pytest tests/services",
    )
    (record.path / "evidence" / "broken.md").write_text(
        "---\nid: [\n---\n", encoding="utf-8"
    )

    assert catalogue.read_change("add-user-auth").artifacts.evidence_ids == ["pytest"]


def test_an_archived_slug_cannot_be_reused(catalogue: AsddCatalogue) -> None:
    seeded(catalogue)
    catalogue.write_delta("add-user-auth", "user-auth", parse_delta(DELTA))
    catalogue.archive_change("add-user-auth", today=date(2026, 9, 16))

    with pytest.raises(AsddChangeExists, match="already archived"):
        catalogue.create_change(change_id="add-user-auth", title="Again")


def test_a_name_an_archived_slug_merely_ends_with_is_still_free(
    catalogue: AsddCatalogue,
) -> None:
    """`add-user-auth` being archived must not reserve `auth`."""

    seeded(catalogue)
    catalogue.write_delta("add-user-auth", "user-auth", parse_delta(DELTA))
    catalogue.archive_change("add-user-auth", today=date(2026, 9, 16))

    record = catalogue.create_change(change_id="auth", title="Auth")

    assert record.change_id == "auth"
    assert catalogue.archived_change_ids() == {"add-user-auth"}


def test_the_archive_name_is_the_one_the_fold_will_create(
    catalogue: AsddCatalogue,
) -> None:
    """Callers report this name, so it cannot be computed off a second clock."""

    seeded(catalogue)
    catalogue.write_delta("add-user-auth", "user-auth", parse_delta(DELTA))
    predicted = catalogue.archive_entry_name("add-user-auth", today=date(2026, 9, 16))

    catalogue.archive_change("add-user-auth", today=date(2026, 9, 16))

    assert predicted == "2026-09-16-add-user-auth"
    assert (catalogue.archive_path / predicted).is_dir()


def test_rewriting_the_same_state_produces_no_diff(catalogue: AsddCatalogue) -> None:
    seeded(catalogue)
    path = catalogue.change_path("add-user-auth") / "proposal.md"
    before = path.read_text(encoding="utf-8")

    catalogue.write_proposal("add-user-auth")

    assert path.read_text(encoding="utf-8") == before


def test_proposal_front_matter_keeps_its_declared_order(
    catalogue: AsddCatalogue,
) -> None:
    seeded(catalogue)
    catalogue.approve("add-user-auth", "proposal")
    document = parse_document(
        (catalogue.change_path("add-user-auth") / "proposal.md").read_text(
            encoding="utf-8"
        )
    )

    assert list(document.front_matter) == [
        "change",
        "title",
        "status",
        "risk",
        "capabilities",
        "created",
        "approvals",
    ]


def test_a_published_spec_reads_back_as_the_delta_that_created_it(
    catalogue: AsddCatalogue,
) -> None:
    seeded(catalogue)
    catalogue.write_delta("add-user-auth", "user-auth", parse_delta(DELTA))
    catalogue.archive_change("add-user-auth", today=date(2026, 9, 16))
    text = catalogue.spec_path("user-auth").read_text(encoding="utf-8")

    reparsed = parse_spec(parse_document(text).body)

    assert reparsed.requirements[0].scenarios[0].steps == [
        "- **WHEN** two Coding chats point at `add-user-auth`",
        "- **THEN** both read and write the same change folder",
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Add User Auth", "add-user-auth"),
        ("add_user_auth", "add-user-auth"),
        ("  add--user--auth  ", "add-user-auth"),
    ],
)
def test_slugs_are_normalized_predictably(value: str, expected: str) -> None:
    assert normalize_slug(value, label="change id") == expected


@pytest.mark.parametrize("value", ["", "---", "Ăn sáng", "a" * 81])
def test_unusable_slugs_are_refused(value: str) -> None:
    with pytest.raises(AsddStoreError):
        normalize_slug(value, label="change id")


@pytest.mark.parametrize(
    "value", ["/absolute", "../escape", ".git/hooks", ".evoflux/asdd", "", "."]
)
def test_the_data_directory_cannot_escape_the_repository(value: str) -> None:
    with pytest.raises(AsddStoreError):
        normalize_data_directory(value)


def test_parse_tasks_counts_both_bullet_styles() -> None:
    assert parse_tasks("- [x] a\n* [ ] b\n- not a task\n") == (2, 1)


@pytest.mark.parametrize(
    ("title", "slug"),
    [
        ("Add PDF export!!", "add-pdf-export"),
        ("  Add   PDF export  ", "add-pdf-export"),
        ("Fix #123 (urgent!)", "fix-123-urgent"),
        ("café & crème", "cafe-creme"),
        # The user of this repository writes in Vietnamese. `normalize_slug`
        # rejected every one of these, so no change could be opened at all.
        ("Thêm tìm kiếm ghi chú", "them-tim-kiem-ghi-chu"),
        # `đ` is a letter, not an accented `d`, so NFKD alone drops it.
        ("Đổi tên trường slug", "doi-ten-truong-slug"),
    ],
)
def test_a_title_in_any_language_derives_a_slug(title: str, slug: str) -> None:
    assert slugify(title, label="title") == slug


def test_a_title_with_nothing_to_transliterate_asks_for_an_id() -> None:
    with pytest.raises(AsddStoreError, match="give the change an id of its own"):
        slugify("日本語のタイトル", label="title")


def test_a_derived_slug_never_ends_in_a_hyphen() -> None:
    # Truncating at 80 characters can land mid-word, and a trailing hyphen is
    # not a slug `normalize_slug` would accept back.
    derived = slugify("word " * 40, label="title")

    assert len(derived) <= 80
    assert not derived.endswith("-")
    assert normalize_slug(derived, label="change id") == derived


def test_an_explicit_change_id_is_still_validated_not_derived() -> None:
    # The two helpers stay different on purpose: an id the author typed has to
    # be the id they get, so a wrong one is refused rather than corrected.
    with pytest.raises(AsddStoreError, match="must be a lowercase slug"):
        normalize_slug("Add PDF export!!", label="change id")


def test_an_untouched_open_questions_section_asks_nothing() -> None:
    # The template ships italic prompts. Reading those back as four unanswered
    # questions would block a design nobody had written yet.
    body = (
        "## Approach\n\nA shape.\n\n## Open questions\n\n"
        "- _Anything the implementation will have to decide, named here rather\n"
        "  than discovered later._\n"
    )

    assert parse_open_questions(body) == []


def test_real_open_questions_are_read_back() -> None:
    body = (
        "## Migration and rollback\n\n- Reversible.\n\n"
        "## Open questions\n\n"
        "- **Page size**: A4 or US Letter?\n"
        "- **PDF metadata**: should it carry an author?\n\n"
        "## Decisions\n\n- Something already settled.\n"
    )

    assert parse_open_questions(body) == [
        "**Page size**: A4 or US Letter?",
        "**PDF metadata**: should it carry an author?",
    ]


def test_open_questions_stop_at_the_next_section() -> None:
    body = "## Open questions\n\n- One question.\n\n## Decisions\n\n- Not a question.\n"

    assert parse_open_questions(body) == ["One question."]


def test_a_design_without_the_section_has_no_open_questions() -> None:
    assert parse_open_questions("## Approach\n\nA shape.\n") == []


def test_a_wrapped_question_is_read_as_one_question() -> None:
    body = (
        "## Open questions\n\n"
        "- **Character encoding**: does the bundled font cover Vietnamese\n"
        "  diacritics, or do we fall back to a system font?\n"
    )

    assert parse_open_questions(body) == [
        "**Character encoding**: does the bundled font cover Vietnamese "
        "diacritics, or do we fall back to a system font?"
    ]


def test_evidence_coverage_is_read_per_requirement(catalogue: AsddCatalogue) -> None:
    seeded(catalogue)
    catalogue.write_delta("add-user-auth", "user-auth", parse_delta(DELTA))
    catalogue.record_evidence(
        "add-user-auth",
        evidence_id="pytest",
        kind="machine",
        result="passed",
        summary="ok",
        requirement="Slug identity",
    )
    # A page with no requirement covers the change as a whole and cannot say
    # whether any one requirement was exercised.
    catalogue.record_evidence(
        "add-user-auth",
        evidence_id="smoke",
        kind="manual",
        result="passed",
        summary="looked at it",
    )

    artifacts = catalogue.read_change("add-user-auth").artifacts

    assert artifacts.delta_requirements == ["Slug identity"]
    assert artifacts.evidence_results == {"Slug identity": ["passed"]}
