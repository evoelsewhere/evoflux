from __future__ import annotations

from pathlib import Path

import pytest

from app.core.runtime_settings import (
    MemoryVectorSettings,
    RuntimeSettings,
    save_runtime_settings,
)
from app.services.memory_vector import (
    DisabledMemoryVectorBackend,
    MemoryVectorChunk,
    get_memory_vector_backend,
    semantic_memory_search,
)


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "config"
    monkeypatch.setattr("app.core.config.settings.EVOFLUX_CONFIG_DIR", str(target))
    return target


def test_memory_vector_backend_defaults_to_disabled(config_dir: Path) -> None:
    backend = get_memory_vector_backend()

    assert isinstance(backend, DisabledMemoryVectorBackend)
    assert backend.name == "disabled"
    assert backend.enabled is False


@pytest.mark.asyncio
async def test_disabled_memory_vector_backend_is_noop(config_dir: Path) -> None:
    backend = get_memory_vector_backend()

    await backend.upsert(
        [
            MemoryVectorChunk(
                id="1", source_ref="wiki:user", path="wiki/user.md", text="hello"
            )
        ]
    )
    assert await semantic_memory_search("hello", top_k=5) == []


def test_turbovec_setting_reports_unavailable_backend(config_dir: Path) -> None:
    save_runtime_settings(
        RuntimeSettings(
            memory_vector=MemoryVectorSettings(enabled=True, backend="turbovec")
        )
    )

    backend = get_memory_vector_backend()

    assert backend.name == "turbovec"
    assert backend.enabled is False
    assert "planned" in getattr(backend, "reason")
