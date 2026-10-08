"""Tests for span export wiring in app/core/otel.py.

The local JSONL writer is what the in-app Telemetry page reads, so it must be
attached no matter which OTLP variables the machine happens to set.  An OTLP
forwarder is extra, opt-in, and never a replacement.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from loguru import logger
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.sampling import ALWAYS_ON

from app.core import otel
from app.core.jsonl_writer import JsonlBatchWriter

_GRPC_EXPORTER_MODULE = "opentelemetry.exporter.otlp.proto.grpc.trace_exporter"


class _RecordingProvider(TracerProvider):
    """TracerProvider that remembers the processors added to it."""

    def __init__(self) -> None:
        super().__init__(sampler=ALWAYS_ON)
        self.processors: list[object] = []

    def add_span_processor(self, span_processor) -> None:  # noqa: ANN001
        self.processors.append(span_processor)
        super().add_span_processor(span_processor)


@pytest.fixture
def clean_sampling_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove sampling knobs so a developer's shell cannot change the outcome."""
    monkeypatch.delenv("OTEL_SPAN_SAMPLE_RATIO", raising=False)
    monkeypatch.delenv("OTEL_SLOW_SPAN_MS", raising=False)
    monkeypatch.delenv("EVOFLUX_OTEL_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)


def _record_one_span(
    provider: TracerProvider, writer: JsonlBatchWriter, spans_dir: Path
) -> list[str]:
    """Emit one span, flush everything, and return the written span names."""
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("probe"):
        pass
    provider.shutdown()
    writer.close()
    names: list[str] = []
    for path in sorted(spans_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            names.append(json.loads(line)["name"])
    return names


def test_local_span_files_are_written_without_any_otlp_configuration(
    tmp_path: Path, clean_sampling_env: None
) -> None:
    provider = _RecordingProvider()
    writer = otel._configure_span_export(provider, tmp_path)

    assert len(provider.processors) == 1
    assert (tmp_path / "spans").is_dir()
    assert _record_one_span(provider, writer, tmp_path / "spans") == ["probe"]


def test_generic_otel_endpoint_env_var_does_not_disable_file_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_sampling_env: None
) -> None:
    """Regression: a machine-wide OTEL_EXPORTER_OTLP_ENDPOINT blanked the page."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://collector.invalid/")

    assert otel._otlp_endpoint() == ""

    provider = _RecordingProvider()
    writer = otel._configure_span_export(provider, tmp_path)

    assert len(provider.processors) == 1
    assert _record_one_span(provider, writer, tmp_path / "spans") == ["probe"]


def test_missing_otlp_exporter_warns_and_keeps_local_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_sampling_env: None
) -> None:
    monkeypatch.setenv("EVOFLUX_OTEL_OTLP_ENDPOINT", "https://collector.invalid/")
    # ``None`` in sys.modules makes the optional import fail deterministically.
    monkeypatch.setitem(sys.modules, _GRPC_EXPORTER_MODULE, None)
    messages: list[str] = []
    sink_id = logger.add(
        lambda message: messages.append(message.record["message"]), level="WARNING"
    )
    try:
        provider = _RecordingProvider()
        writer = otel._configure_span_export(provider, tmp_path)
    finally:
        logger.remove(sink_id)

    assert len(provider.processors) == 1
    assert any("otel_otlp_exporter_unavailable" in text for text in messages)
    assert _record_one_span(provider, writer, tmp_path / "spans") == ["probe"]


def test_evoflux_otlp_endpoint_adds_the_forwarder_alongside_the_file_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_sampling_env: None
) -> None:
    monkeypatch.setenv("EVOFLUX_OTEL_OTLP_ENDPOINT", "https://collector.invalid/")
    monkeypatch.setattr(otel, "_otlp_span_exporter", lambda endpoint: MagicMock())

    provider = _RecordingProvider()
    writer = otel._configure_span_export(provider, tmp_path)

    assert len(provider.processors) == 2
    provider.shutdown()
    writer.close()
    assert otel._otlp_endpoint() == "https://collector.invalid/"
