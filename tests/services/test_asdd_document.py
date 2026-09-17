from __future__ import annotations

import pytest

from app.services.asdd_document import (
    AsddDocumentError,
    MarkdownDocument,
    optional_str,
    parse_document,
    render_document,
    require_str,
    string_list,
)

PAGE = """---
change: add-user-auth
title: Add user authentication
status: drafting
---

## Why

Because sessions own too much.
"""


def test_a_page_splits_into_front_matter_and_body() -> None:
    document = parse_document(PAGE)

    assert document.front_matter["change"] == "add-user-auth"
    assert document.body.startswith("## Why")


def test_render_round_trips_and_keeps_key_order() -> None:
    document = parse_document(PAGE)

    rendered = render_document(document.front_matter, document.body)

    assert rendered == PAGE
    assert parse_document(rendered) == document


def test_crlf_input_is_normalized_on_the_way_in() -> None:
    document = parse_document(PAGE.replace("\n", "\r\n"))

    assert "\r" not in document.body
    assert document.front_matter["status"] == "drafting"


def test_a_page_without_front_matter_is_all_body() -> None:
    document = parse_document("# Design\n\nSome prose.\n")

    assert document.front_matter == {}
    assert document.body == "# Design\n\nSome prose.\n"


def test_unreadable_front_matter_names_the_fault() -> None:
    with pytest.raises(AsddDocumentError, match="not valid YAML"):
        parse_document("---\nchange: [unclosed\n---\n\nbody\n")


def test_non_mapping_front_matter_is_refused() -> None:
    with pytest.raises(AsddDocumentError, match="must be a mapping"):
        parse_document("---\n- one\n- two\n---\n\nbody\n")


def test_required_fields_report_the_page_they_are_missing_from() -> None:
    document = MarkdownDocument(front_matter={}, body="")

    with pytest.raises(AsddDocumentError, match="proposal.md: front matter is missing"):
        require_str(document, "change", source="proposal.md")

    assert optional_str(document, "change") is None


def test_a_scalar_list_field_is_read_as_a_one_item_list() -> None:
    document = parse_document("---\ncapabilities: user-auth\n---\n\nbody\n")

    assert string_list(document, "capabilities") == ["user-auth"]


def test_an_empty_document_renders_to_nothing() -> None:
    assert render_document({}, "") == ""


def test_an_unquoted_timestamp_reads_back_as_iso_text() -> None:
    # YAML types what it recognizes, so a hand-written `recorded:` arrives as a
    # datetime. Every template in the skills writes it unquoted, so rejecting it
    # made correctness depend on whether the author happened to add quotes.
    document = parse_document("---\nrecorded: 2026-09-17T07:35:00Z\n---\n\nbody\n")

    assert optional_str(document, "recorded") == "2026-09-17T07:35:00Z"


def test_a_naive_timestamp_is_read_as_utc() -> None:
    document = parse_document("---\nrecorded: 2026-09-17 07:35:00\n---\n\nbody\n")

    assert optional_str(document, "recorded") == "2026-09-17T07:35:00Z"


def test_an_offset_timestamp_is_normalized_to_utc() -> None:
    document = parse_document("---\ncreated: 2026-09-17T14:35:00+07:00\n---\n\nbody\n")

    assert optional_str(document, "created") == "2026-09-17T07:35:00Z"


def test_a_date_only_field_keeps_its_day() -> None:
    document = parse_document("---\nrecorded: 2026-09-17\n---\n\nbody\n")

    assert optional_str(document, "recorded") == "2026-09-17"


def test_numeric_and_boolean_fields_read_as_their_text() -> None:
    document = parse_document("---\nid: 2\nresult: true\n---\n\nbody\n")

    assert optional_str(document, "id") == "2"
    assert optional_str(document, "result") == "true"


def test_a_required_field_accepts_a_typed_scalar() -> None:
    document = parse_document("---\nchange: 2026\n---\n\nbody\n")

    assert require_str(document, "change", source="proposal.md") == "2026"


def test_a_mapping_valued_field_is_not_a_string() -> None:
    document = parse_document("---\napprovals:\n  proposal: null\n---\n\nbody\n")

    assert optional_str(document, "approvals") is None
