from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest
from pptx.util import Inches

from app.services.document_preview import service as preview
from app.services.document_preview.live_deck import deck_is_live, read_deck_plan

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "app/agent/builtin_skills/pptx-official/scripts/deck_live.py"
)


@pytest.fixture
def deck_live():
    spec = importlib.util.spec_from_file_location("deck_live", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["deck_live"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("deck_live", None)


def _slide_statuses(rendered: str) -> list[str]:
    return re.findall(r'<article[^>]*data-slide-status="(\w+)"', rendered)


def _fresh_slides(rendered: str) -> int:
    return len(re.findall(r"<article[^>]*\bdata-slide-fresh\b", rendered))


def _add_slide(prs, text: str) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1)).text = text


def test_live_deck_previews_finished_slides_and_placeholders(
    deck_live, monkeypatch, tmp_path
):
    deck = tmp_path / "deck.pptx"
    deck_live.init(deck, ["Cover", "Why now", "Roadmap"])
    monkeypatch.setattr(preview.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))

    plan = read_deck_plan(deck)
    assert plan is not None and plan.total == 3 and not plan.done
    rendered = preview._render_source(deck)
    assert 'data-deck-live="true"' in rendered
    assert _slide_statuses(rendered) == ["building", "pending", "pending"]
    assert 'data-preview-label="Slide 2 — Why now"' in rendered
    assert "Building slide 1 of 3" in rendered
    assert '<h2 class="sk-title">Cover</h2>' in rendered
    assert _fresh_slides(rendered) == 0

    live = deck_live.LiveDeck(deck)
    prs = live.open()
    _add_slide(prs, "Cover text")
    live.save(prs)

    rendered = preview._render_source(deck)
    assert _slide_statuses(rendered) == ["done", "building", "pending"]
    assert "Cover text" in rendered
    assert "Building slide 2 of 3" in rendered
    # The slide that just landed is the only one marked fresh.
    assert _fresh_slides(rendered) == 1
    assert 'class="done" style="width:33.33%"' in rendered

    for text in ("Why now text", "Roadmap text"):
        _add_slide(prs, text)
    live.finish(prs)

    rendered = preview._render_source(deck)
    assert not deck_is_live(deck)
    assert "data-deck-live" not in rendered
    assert _slide_statuses(rendered) == []
    assert not deck_live._plan_path(deck).exists()


def test_mark_restores_the_plan_after_a_generator_rewrites_the_deck(
    deck_live, tmp_path
):
    from pptx import Presentation

    deck = tmp_path / "deck.pptx"
    deck_live.init(deck, ["One", "Two"])
    rewritten = Presentation()
    _add_slide(rewritten, "One")
    rewritten.save(deck)  # e.g. PptxGenJS writing slides 1..k from scratch
    assert read_deck_plan(deck) is None

    deck_live.mark(deck)

    plan = read_deck_plan(deck)
    assert plan is not None and plan.titles == ("One", "Two") and not plan.done
    deck_live.mark(deck, done=True)
    assert not deck_is_live(deck)


def test_live_deck_renders_natively_even_with_the_exact_renderer(
    deck_live, monkeypatch, tmp_path
):
    from app.services.office_runtime import installer

    deck = tmp_path / "deck.pptx"
    deck_live.init(deck, ["Cover"])
    monkeypatch.setattr(preview.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(
        preview,
        "installed_runtime_for_preview",
        lambda: installer.InstalledRuntime("26.8.0", tmp_path / "soffice", tmp_path),
    )

    def fail(*_args, **_kwargs):
        raise AssertionError("a deck under construction must not use LibreOffice")

    monkeypatch.setattr(preview, "_render_with_office_runtime", fail)

    assert preview._renderer_identity(deck) == "native"
    assert 'data-deck-live="true"' in preview._render_source(deck)
