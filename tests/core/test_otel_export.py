"""Tests for span export wiring in app/core/otel.py.

The local JSONL writer is what the in-app Telemetry page reads, so it must be
attached no matter which OTLP variables the machine happens to set.  An OTLP
forwarder is extra, opt-in, and never a replacement.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from loguru import logger
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.sampling import ALWAYS_ON

from app.core import otel
from app.core.jsonl_writer import JsonlBatchWriter


class _RecordingProvider(TracerProvider):
    """TracerProvider that remembers the processors added to it."""

    def __init__(self) -> None:
        super().__init__(sampler=ALWAYS_ON)
        self.processors: list[object] = []

    def add_span_processor(self, span_processor) -> None:  # noqa: ANN001
        self.processors.append(span_processor)
        super().add_span_processor(span_processor)


class _RecordingExporter:
    """Stands in for the optional OTLP exporter and records how it was built."""

    instances: list[_RecordingExporter] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.env_inside = dict(os.environ)
        _RecordingExporter.instances.append(self)

    def export(self, spans: object) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: float = 0) -> bool:
        return True


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every telemetry knob so a developer's shell cannot change a result."""
    for name in (
        "OTEL_SPAN_SAMPLE_RATIO",
        "OTEL_SLOW_SPAN_MS",
        "EVOFLUX_OTEL_OTLP_ENDPOINT",
        "EVOFLUX_OTEL_OTLP_PROTOCOL",
        "EVOFLUX_OTEL_OTLP_HEADERS",
        "EVOFLUX_OTEL_OTLP_TIMEOUT",
        "EVOFLUX_OTEL_RESOURCE_ATTRIBUTES",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_HEADERS",
        "OTEL_EXPORTER_OTLP_TRACES_HEADERS",
        "OTEL_RESOURCE_ATTRIBUTES",
    ):
        monkeypatch.delenv(name, raising=False)


def _record_one_span(
    provider: TracerProvider, writer: JsonlBatchWriter, spans_dir: Path
) -> list[dict]:
    """Emit one span, flush everything, and return the written records."""
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("probe"):
        pass
    provider.shutdown()
    writer.close()
    records: list[dict] = []
    for path in sorted(spans_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            records.append(json.loads(line))
    return records


# ── Local files ───────────────────────────────────────────────────────────────


def test_local_span_files_are_written_without_any_otlp_configuration(
    tmp_path: Path, clean_env: None
) -> None:
    provider = _RecordingProvider()
    writer = otel._configure_span_export(provider, tmp_path)

    assert len(provider.processors) == 1
    assert (tmp_path / "spans").is_dir()
    records = _record_one_span(provider, writer, tmp_path / "spans")
    assert [record["name"] for record in records] == ["probe"]


def test_generic_otel_endpoint_env_var_does_not_disable_file_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_env: None
) -> None:
    """Regression: a machine-wide OTEL_EXPORTER_OTLP_ENDPOINT blanked the page."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://collector.invalid/")

    assert otel._otlp_endpoint() == ""

    provider = _RecordingProvider()
    writer = otel._configure_span_export(provider, tmp_path)

    assert len(provider.processors) == 1
    records = _record_one_span(provider, writer, tmp_path / "spans")
    assert [record["name"] for record in records] == ["probe"]


def test_missing_otlp_exporter_warns_and_keeps_local_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_env: None
) -> None:
    monkeypatch.setenv("EVOFLUX_OTEL_OTLP_ENDPOINT", "https://collector.invalid/")
    monkeypatch.setattr(otel, "_load_otlp_exporter", lambda protocol: None)
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
    records = _record_one_span(provider, writer, tmp_path / "spans")
    assert [record["name"] for record in records] == ["probe"]


# ── Resource attributes ───────────────────────────────────────────────────────


def test_resource_ignores_machine_wide_otel_resource_attributes(
    monkeypatch: pytest.MonkeyPatch, clean_env: None
) -> None:
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "host.org=other-tool")
    monkeypatch.setenv("EVOFLUX_OTEL_RESOURCE_ATTRIBUTES", "env=dev,team=evo")

    resource = otel._resource("EvoFlux")

    assert resource.attributes["service.name"] == "EvoFlux"
    assert resource.attributes["env"] == "dev"
    assert resource.attributes["team"] == "evo"
    assert "host.org" not in resource.attributes


def test_recorded_spans_carry_only_evofluX_resource_attributes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_env: None
) -> None:
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "host.org=other-tool")
    monkeypatch.setenv("EVOFLUX_OTEL_RESOURCE_ATTRIBUTES", "env=dev")

    provider = _RecordingProvider()
    provider._resource = otel._resource("EvoFlux")
    writer = otel._configure_span_export(provider, tmp_path)

    records = _record_one_span(provider, writer, tmp_path / "spans")
    resource = records[0]["resource"]
    assert resource["service.name"] == "EvoFlux"
    assert resource["env"] == "dev"
    assert "host.org" not in resource


# ── OTLP forwarder ────────────────────────────────────────────────────────────


def test_evoflux_otlp_endpoint_adds_the_forwarder_alongside_the_file_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_env: None
) -> None:
    monkeypatch.setenv("EVOFLUX_OTEL_OTLP_ENDPOINT", "https://collector.invalid/")
    monkeypatch.setattr(
        otel, "_otlp_span_exporter", lambda endpoint: _RecordingExporter()
    )

    provider = _RecordingProvider()
    writer = otel._configure_span_export(provider, tmp_path)

    assert len(provider.processors) == 2
    provider.shutdown()
    writer.close()
    assert otel._otlp_endpoint() == "https://collector.invalid/"


def test_otlp_forwarder_is_built_with_evofluX_settings_only(
    monkeypatch: pytest.MonkeyPatch, clean_env: None
) -> None:
    monkeypatch.setenv("EVOFLUX_OTEL_OTLP_HEADERS", "apikey=evo,env=dev")
    monkeypatch.setenv("EVOFLUX_OTEL_OTLP_TIMEOUT", "7")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://copilot.invalid/")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "apikey=copilot")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_HEADERS", "apikey=copilot")
    monkeypatch.setattr(
        otel, "_load_otlp_exporter", lambda protocol: _RecordingExporter
    )
    _RecordingExporter.instances.clear()

    exporter = otel._otlp_span_exporter("https://evo.invalid/")

    assert exporter is _RecordingExporter.instances[-1]
    assert exporter.kwargs == {
        "endpoint": "https://evo.invalid/",
        "headers": {"apikey": "evo", "env": "dev"},
        "timeout": 7.0,
    }
    assert not [
        key for key in exporter.env_inside if key.startswith("OTEL_EXPORTER_OTLP")
    ]
    # The machine's own variables are restored after the exporter is built.
    assert os.environ["OTEL_EXPORTER_OTLP_TRACES_HEADERS"] == "apikey=copilot"


def test_otlp_protocol_defaults_to_grpc_and_accepts_http(
    monkeypatch: pytest.MonkeyPatch, clean_env: None
) -> None:
    assert otel._otlp_protocol() == "grpc"
    for raw in ("http", "http/protobuf", "HTTP/PROTOBUF"):
        monkeypatch.setenv("EVOFLUX_OTEL_OTLP_PROTOCOL", raw)
        assert otel._otlp_protocol() == "http/protobuf"
    monkeypatch.setenv("EVOFLUX_OTEL_OTLP_PROTOCOL", "grpc")
    assert otel._otlp_protocol() == "grpc"


def test_parse_pairs_skips_malformed_entries(clean_env: None) -> None:
    assert otel._parse_pairs("good=1, bad ,also=2,") == {"good": "1", "also": "2"}
    assert otel._parse_pairs("") == {}
