"""Why a language-server install is or is not offered.

The page used to hide its action whenever it could not be taken, which made
three different situations render identically: no managed installer exists,
one exists but its prerequisite is missing, and the server is already
installed. Each now states its own reason, so each is asserted here.
"""

from __future__ import annotations

import pytest

from app.agent.lsp_manager import SPECS
from app.services import language_server_service as service
from app.services.language_server_service import (
    INSTALL_RECIPES,
    MANUAL_HINTS,
    PREREQUISITE_HINTS,
    language_server_overview,
)


@pytest.fixture(autouse=True)
def _no_running_installs():
    service._install_jobs.clear()
    yield
    service._install_jobs.clear()


def _status(language_id: str):
    return next(
        item
        for item in language_server_overview().servers
        if item.language_id == language_id
    )


class TestCatalogueCoverage:
    def test_every_spec_can_be_installed_or_explains_itself(self):
        for spec in SPECS:
            assert (
                spec.language_id in INSTALL_RECIPES
                or spec.language_id in MANUAL_HINTS
            ), f"{spec.language_id} offers neither an installer nor a hint"

    def test_every_recipe_has_a_prerequisite_hint(self):
        # A recipe whose prerequisite is missing must be able to say which
        # tool to install; falling back to the bare binary name is a worse
        # sentence than the ones in PREREQUISITE_HINTS.
        for language_id, recipe in INSTALL_RECIPES.items():
            assert recipe.kind in PREREQUISITE_HINTS, language_id

    def test_toolchain_recipes_are_not_expected_in_the_managed_cache(self):
        for language_id, recipe in INSTALL_RECIPES.items():
            if recipe.scope == "toolchain":
                # Nothing is staged, so there is no pinned artifact to compare
                # a manifest against.
                assert recipe.kind in {"rustup", "gem"}, language_id


class TestBlockedReason:
    def test_missing_prerequisite_names_the_tool_to_install(self, monkeypatch):
        monkeypatch.setattr(service.shutil, "which", lambda _name: None)

        status = _status("typescript")

        assert status.installable is True
        assert status.installer == "npm"
        assert status.installer_available is False
        assert status.blocked_reason == PREREQUISITE_HINTS["npm"]

    def test_a_language_with_no_recipe_says_so(self, monkeypatch):
        monkeypatch.setattr(service.shutil, "which", lambda _name: None)

        status = _status("java")

        assert status.installable is False
        assert status.blocked_reason is not None
        assert "no managed installer" in status.blocked_reason.lower()

    def test_an_available_installer_is_not_blocked(self, monkeypatch):
        monkeypatch.setattr(service.shutil, "which", lambda _name: "/usr/bin/tool")
        monkeypatch.setattr(
            service, "managed_language_server_command", lambda *a, **k: None
        )
        monkeypatch.setattr(service, "_system_command", lambda _spec: None)

        assert _status("typescript").blocked_reason is None


class TestInstallPhaseReporting:
    def test_a_running_install_is_visible_on_the_row(self):
        service._install_jobs["go"] = service.InstallJob(
            language_id="go",
            phase="running",
            started_at="2026-01-01T00:00:00+00:00",
            finished_at=None,
            error=None,
        )

        status = _status("go")

        assert status.install_phase == "running"
        assert status.install_started_at == "2026-01-01T00:00:00+00:00"

    def test_a_failed_install_keeps_its_message_until_dismissed(self):
        service._install_jobs["go"] = service.InstallJob(
            language_id="go",
            phase="failed",
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:01:00+00:00",
            error="proxy.golang.org unreachable",
        )

        assert _status("go").install_error == "proxy.golang.org unreachable"

        service.dismiss_install_error("go")

        assert _status("go").install_error is None
        assert _status("go").install_phase == "idle"

    def test_dismiss_leaves_a_running_install_alone(self):
        service._install_jobs["go"] = service.InstallJob(
            language_id="go",
            phase="running",
            started_at="2026-01-01T00:00:00+00:00",
            finished_at=None,
            error=None,
        )

        service.dismiss_install_error("go")

        assert _status("go").install_phase == "running"


class TestScanTruncation:
    def test_a_truncated_walk_is_reported(self, tmp_path, monkeypatch):
        # A silently capped scan under-reports languages; the page has to be
        # able to say the list is a sample.
        monkeypatch.setattr(service, "_MAX_SCANNED_FILES", 2)
        for index in range(5):
            (tmp_path / f"file{index}.ts").write_text("//\n", encoding="utf-8")

        overview = language_server_overview((tmp_path,))

        assert overview.scan_truncated is True
        assert overview.scan_limit == 2

    def test_a_complete_walk_is_not_reported_as_truncated(self, tmp_path):
        (tmp_path / "one.ts").write_text("//\n", encoding="utf-8")

        overview = language_server_overview((tmp_path,))

        assert overview.scan_truncated is False
