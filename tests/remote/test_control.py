from __future__ import annotations

from uuid import UUID

import pytest
import pytest_asyncio

import app.core.db as db_module
from app.models.chat import ChatSession
from app.remote import control


@pytest_asyncio.fixture
async def chat_session() -> ChatSession:
    async with db_module.async_session_factory() as db:
        session = ChatSession(title="Control test", mode="work", session_type="main")
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session


@pytest.mark.asyncio
async def test_set_permission_mode_persists_a_valid_mode(chat_session: ChatSession) -> None:
    async with db_module.async_session_factory() as db:
        result = await control.set_permission_mode(db, str(chat_session.id), "ask")

    assert result.status == "ok"
    async with db_module.async_session_factory() as db:
        refreshed = await db.get(ChatSession, chat_session.id)
        assert refreshed is not None
        assert refreshed.permission_mode == "ask"


@pytest.mark.asyncio
async def test_set_permission_mode_rejects_bypass(chat_session: ChatSession) -> None:
    async with db_module.async_session_factory() as db:
        result = await control.set_permission_mode(db, str(chat_session.id), "bypass")

    assert result.status == "invalid"
    async with db_module.async_session_factory() as db:
        refreshed = await db.get(ChatSession, chat_session.id)
        assert refreshed is not None
        assert refreshed.permission_mode != "bypass"


@pytest.mark.asyncio
async def test_set_permission_mode_rejects_unknown_mode(chat_session: ChatSession) -> None:
    async with db_module.async_session_factory() as db:
        result = await control.set_permission_mode(db, str(chat_session.id), "nonsense")

    assert result.status == "invalid"


@pytest.mark.asyncio
async def test_set_permission_mode_not_found_for_unknown_session() -> None:
    async with db_module.async_session_factory() as db:
        result = await control.set_permission_mode(db, str(UUID(int=0)), "ask")

    assert result.status == "not_found"


class _FakeLead:
    """Stand-in for the roster's real lead-agent config object — only
    ``.name`` is read by list_lead_names/resolve_configured_lead."""

    def __init__(self, name: str) -> None:
        self.name = name


def _mock_one_lead_roster(monkeypatch: pytest.MonkeyPatch, name: str = "evoflux") -> None:
    """The test sandbox's isolated config dirs (pytest.ini's EVOFLUX_CONFIG_DIR
    etc.) have no real agent configs seeded, so configured_lead_rosters
    returns empty there — mock it with one controlled, fake roster instead
    of depending on whatever happens to exist on disk in this environment.
    Patched at the module level so both list_lead_names' direct call and
    resolve_configured_lead's own internal call see the same fake roster."""
    monkeypatch.setattr(
        "app.services.team_manager.configured_lead_rosters",
        lambda mode: (name, [(_FakeLead(name), None, [])]),
    )


@pytest.mark.asyncio
async def test_list_lead_names_returns_configured_leads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_one_lead_roster(monkeypatch, "evoflux")

    names = await control.list_lead_names("work")

    assert names == ["evoflux"]


@pytest.mark.asyncio
async def test_list_lead_names_is_bounded_to_five(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rosters = [(_FakeLead(f"lead-{i}"), None, []) for i in range(8)]
    monkeypatch.setattr(
        "app.services.team_manager.configured_lead_rosters",
        lambda mode: ("lead-0", fake_rosters),
    )

    names = await control.list_lead_names("work")

    assert len(names) == 5


@pytest.mark.asyncio
async def test_set_lead_agent_persists_a_valid_lead(
    chat_session: ChatSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_one_lead_roster(monkeypatch, "evoflux")

    async with db_module.async_session_factory() as db:
        result = await control.set_lead_agent(db, str(chat_session.id), "evoflux")

    assert result.status == "ok"
    async with db_module.async_session_factory() as db:
        refreshed = await db.get(ChatSession, chat_session.id)
        assert refreshed is not None
        assert refreshed.agent_name == "evoflux"


@pytest.mark.asyncio
async def test_set_lead_agent_rejects_unknown_name(
    chat_session: ChatSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_one_lead_roster(monkeypatch, "evoflux")

    async with db_module.async_session_factory() as db:
        result = await control.set_lead_agent(
            db, str(chat_session.id), "not-a-real-configured-lead-name"
        )

    assert result.status == "invalid"


@pytest.mark.asyncio
async def test_set_lead_agent_conflicts_while_session_is_running(
    chat_session: ChatSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_one_lead_roster(monkeypatch, "evoflux")
    monkeypatch.setattr(
        "app.services.memory_stream_store.running_session_ids",
        lambda: {str(chat_session.id)},
    )

    async with db_module.async_session_factory() as db:
        result = await control.set_lead_agent(db, str(chat_session.id), "evoflux")

    assert result.status == "conflict"


class _FakeModelEntry:
    """Stand-in for the real registry's ModelCatalogEntry — only ``.id``
    is read by list_model_ids/set_model."""

    def __init__(self, id: str) -> None:
        self.id = id


class _FakeRegistry:
    def __init__(self, model_ids: list[str]) -> None:
        self.models = [_FakeModelEntry(mid) for mid in model_ids]


def _mock_registry(monkeypatch: pytest.MonkeyPatch, model_ids: list[str]) -> None:
    """Mocked rather than using this environment's real, ambiently-configured
    provider registry (present here via a "xiaomi" provider, but not
    guaranteed on every machine this suite runs on) — same lesson as
    _mock_one_lead_roster above."""

    async def _fake_get_registry(*args: object, **kwargs: object) -> _FakeRegistry:
        return _FakeRegistry(model_ids)

    monkeypatch.setattr("app.api.routes.agents.get_registry", _fake_get_registry)


@pytest.mark.asyncio
async def test_list_model_ids_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_registry(monkeypatch, [f"provider:model-{i}" for i in range(8)])

    model_ids = await control.list_model_ids(limit=5)

    assert len(model_ids) == 5


@pytest.mark.asyncio
async def test_set_model_persists_a_valid_model(
    chat_session: ChatSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_registry(monkeypatch, ["provider:model-a", "provider:model-b"])

    async with db_module.async_session_factory() as db:
        result = await control.set_model(db, str(chat_session.id), "provider:model-a")

    assert result.status == "ok"
    async with db_module.async_session_factory() as db:
        refreshed = await db.get(ChatSession, chat_session.id)
        assert refreshed is not None
        assert refreshed.model == "provider:model-a"


@pytest.mark.asyncio
async def test_set_model_rejects_unknown_model_id(
    chat_session: ChatSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_registry(monkeypatch, ["provider:model-a"])

    async with db_module.async_session_factory() as db:
        result = await control.set_model(
            db, str(chat_session.id), "not-a-real-provider:not-a-real-model"
        )

    assert result.status == "invalid"
