"""OpenTelemetry SDK bootstrap — file-based export, no external service required.

Output layout (always written; forwarding is additive):

    {STATE_DIR}/otel/spans/YYYY-MM-DD-HH.jsonl      (hourly partitions)
    {STATE_DIR}/otel/metrics/YYYY-MM-DD.jsonl       (daily partitions)

Design
------
- **Always-sample at head** so the filter below can make tail-like decisions on
  error status + duration.  Cardinality is controlled by a deterministic
  per-trace ratio in the export filter, not by dropping at span-start.
- **Tier at export time** — every span that ended is inspected:
    1. Error spans are always exported.
    2. Spans longer than ``OTEL_SLOW_SPAN_MS`` are always exported.
    3. Others are exported only when the deterministic trace hash falls under
       ``OTEL_SPAN_SAMPLE_RATIO`` (default 1.0 — keep everything; lower the
       ratio only if span volume becomes unmanageable).
- **JsonlBatchWriter** is used for both spans and metrics — bounded queue,
  drop-on-backpressure with a Prometheus counter, hourly span partitioning.
- **Local files are unconditional.**  Forwarding to an OTLP collector is an
  extra span processor, so exporting elsewhere can never blank the in-app
  Telemetry page, which reads these files.

Env vars
--------
EvoFlux reads only its own variables.  The generic ``OTEL_*`` ones belong to
whatever else runs on the machine (Copilot, CI agents, vendor SDKs), so they
never change what EvoFlux records, where it sends it, or which credentials and
identity attributes travel with it.

- ``EVOFLUX_OTEL_OTLP_ENDPOINT`` — collector to forward spans to.  When set,
  spans go to the local files *and* to that collector.
- ``EVOFLUX_OTEL_OTLP_PROTOCOL`` — ``grpc`` (default) or ``http/protobuf``.
- ``EVOFLUX_OTEL_OTLP_HEADERS`` — ``key=value,key2=value2`` sent with each
  export.
- ``EVOFLUX_OTEL_OTLP_TIMEOUT`` — export timeout in seconds.
- ``EVOFLUX_OTEL_RESOURCE_ATTRIBUTES`` — extra resource attributes,
  ``key=value,key2=value2``, on top of ``service.name``.
- ``OTEL_SPAN_SAMPLE_RATIO`` — float in [0.0, 1.0]; default 1.0. Keep the
  default so every tool invocation shows up in the waterfall; only lower it
  if span volume becomes unmanageable.
- ``OTEL_SLOW_SPAN_MS`` — int; spans slower than this are always kept, even
  if the ratio drops them. Default 1000.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from loguru import logger
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    MetricExporter,
    MetricExportResult,
    MetricsData,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.trace.status import StatusCode

from app.core.jsonl_writer import (
    JsonlBatchWriter,
    daily_partition,
    hourly_partition,
)
from app.core.metrics import SPANS_DROPPED, SPANS_WRITTEN

_INSTRUMENTATION_SCOPE = "EvoFlux"

_tracer_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None
_span_writer: JsonlBatchWriter | None = None
_metric_writer: JsonlBatchWriter | None = None


# ── Sampling config ───────────────────────────────────────────────────────────


def _sample_ratio() -> float:
    raw = os.getenv("OTEL_SPAN_SAMPLE_RATIO", "1.0")
    try:
        v = float(raw)
    except ValueError:
        return 1.0
    return max(0.0, min(1.0, v))


def _slow_span_threshold_ns() -> int:
    raw = os.getenv("OTEL_SLOW_SPAN_MS", "1000")
    try:
        return int(float(raw) * 1_000_000)
    except ValueError:
        return 1_000_000_000


def _trace_passes_ratio(trace_id: int, ratio: float) -> bool:
    """Deterministic per-trace sampling: use the low 64 bits as a pseudo-random
    value.  Equivalent to ``TraceIdRatioBased`` so collectors stay consistent.
    """
    if ratio >= 1.0:
        return True
    if ratio <= 0.0:
        return False
    # Same normalisation used by OTel's TraceIdRatioBased.
    threshold = int(ratio * (1 << 64))
    return (trace_id & ((1 << 64) - 1)) < threshold


# ── File exporters ────────────────────────────────────────────────────────────


class _FilteringJsonlSpanExporter(SpanExporter):
    """Feeds spans to ``JsonlBatchWriter`` after applying the error/slow/ratio tier."""

    def __init__(self, writer: JsonlBatchWriter) -> None:
        self._writer = writer
        self._ratio = _sample_ratio()
        self._slow_ns = _slow_span_threshold_ns()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        for span in spans:
            if not self._should_export(span):
                continue
            self._writer.write(_span_to_dict(span), ts=_span_end_datetime(span))
        return SpanExportResult.SUCCESS

    def _should_export(self, span: ReadableSpan) -> bool:
        # Tier 1: errors always exported.
        if span.status.status_code == StatusCode.ERROR:
            return True
        # Tier 2: slow spans always exported.
        if span.start_time is not None and span.end_time is not None:
            duration = span.end_time - span.start_time
            if duration >= self._slow_ns:
                return True
        # Tier 3: deterministic ratio.
        ctx = span.get_span_context()
        if ctx is None:
            return False
        return _trace_passes_ratio(ctx.trace_id, self._ratio)

    def shutdown(self) -> None:
        pass


# ── Span export wiring ────────────────────────────────────────────────────────


def _otlp_endpoint() -> str:
    """Return EvoFlux's own OTLP endpoint, or ``""``.

    Deliberately not the generic ``OTEL_EXPORTER_OTLP_ENDPOINT``: that variable
    is process-global and other tools on the machine set it (Copilot, CI
    agents, vendor SDKs).  Honouring it here used to replace the file exporter,
    which silently blanked the in-app Telemetry page on those machines.
    """
    return os.getenv("EVOFLUX_OTEL_OTLP_ENDPOINT", "").strip()


#: Every generic variable the OTLP exporters consult for a value that was not
#: passed explicitly.  EvoFlux hides them while it builds its own exporter so a
#: collector configured for another tool cannot receive EvoFlux spans, and its
#: credentials cannot travel with them.
_OTLP_ENV_VARS: tuple[str, ...] = (
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_HEADERS",
    "OTEL_EXPORTER_OTLP_TIMEOUT",
    "OTEL_EXPORTER_OTLP_COMPRESSION",
    "OTEL_EXPORTER_OTLP_CERTIFICATE",
    "OTEL_EXPORTER_OTLP_CLIENT_KEY",
    "OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE",
    "OTEL_EXPORTER_OTLP_INSECURE",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_HEADERS",
    "OTEL_EXPORTER_OTLP_TRACES_TIMEOUT",
    "OTEL_EXPORTER_OTLP_TRACES_COMPRESSION",
    "OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE",
    "OTEL_EXPORTER_OTLP_TRACES_CLIENT_KEY",
    "OTEL_EXPORTER_OTLP_TRACES_CLIENT_CERTIFICATE",
    "OTEL_EXPORTER_OTLP_TRACES_INSECURE",
    "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL",
)


@contextmanager
def _isolated_otlp_env() -> Iterator[None]:
    """Hide the generic OTLP variables for the duration of the block."""
    saved = {
        name: os.environ.pop(name) for name in _OTLP_ENV_VARS if name in os.environ
    }
    try:
        yield
    finally:
        os.environ.update(saved)


def _parse_pairs(raw: str) -> dict[str, str]:
    """Parse ``key=value,key2=value2`` into a mapping, skipping malformed pairs."""
    pairs: dict[str, str] = {}
    for chunk in raw.split(","):
        key, separator, value = chunk.partition("=")
        key = key.strip()
        if not separator or not key:
            if chunk.strip():
                logger.warning("otel_env_pair_ignored value={}", chunk.strip())
            continue
        pairs[key] = value.strip()
    return pairs


def _resource(service_name: str) -> Resource:
    """Build the resource EvoFlux stamps on its own telemetry.

    ``Resource.create`` would merge the machine-wide ``OTEL_RESOURCE_ATTRIBUTES``
    that other tools set (host, user, org), stamping their identity onto EvoFlux
    files.  Only EvoFlux's own variable is read here.
    """
    attributes = {"service.name": service_name}
    attributes.update(_parse_pairs(os.getenv("EVOFLUX_OTEL_RESOURCE_ATTRIBUTES", "")))
    return Resource(attributes=attributes)


def _otlp_protocol() -> str:
    """``grpc`` (default) or ``http/protobuf``, from EvoFlux's own variable."""
    raw = os.getenv("EVOFLUX_OTEL_OTLP_PROTOCOL", "grpc").strip().lower()
    return (
        "http/protobuf" if raw in {"http", "http/protobuf", "http-protobuf"} else "grpc"
    )


def _otlp_headers() -> dict[str, str]:
    return _parse_pairs(os.getenv("EVOFLUX_OTEL_OTLP_HEADERS", ""))


def _otlp_timeout_seconds() -> float | None:
    raw = os.getenv("EVOFLUX_OTEL_OTLP_TIMEOUT", "").strip()
    if not raw:
        return None
    try:
        return max(1.0, float(raw))
    except ValueError:
        logger.warning("otel_otlp_timeout_ignored value={}", raw)
        return None


def _load_otlp_exporter(protocol: str) -> Callable[..., SpanExporter] | None:
    """Return the OTLP exporter class for ``protocol``, or ``None`` when absent.

    Both exporters are optional dependencies: the local pipeline works without
    them.  Typed as a factory because the classes are duck-typed here and the
    packages are not installed for static analysis.
    """
    try:
        if protocol == "http/protobuf":
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # ty: ignore[unresolved-import]
                OTLPSpanExporter,
            )
        else:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # ty: ignore[unresolved-import]
                OTLPSpanExporter,
            )
    except ImportError:
        return None
    return OTLPSpanExporter


def _otlp_span_exporter(endpoint: str) -> SpanExporter | None:
    """Build the optional OTLP forwarder, or ``None`` when the dep is absent.

    Everything the exporter needs is passed explicitly, and the generic OTLP
    variables are hidden while it is built: the gRPC exporter falls back to
    ``OTEL_EXPORTER_OTLP_TRACES_HEADERS`` for a falsy ``headers`` argument and
    the HTTP one merges those headers unconditionally.
    """
    protocol = _otlp_protocol()
    exporter_cls = _load_otlp_exporter(protocol)
    if exporter_cls is None:
        logger.warning(
            "otel_otlp_exporter_unavailable endpoint={} protocol={} package={}",
            endpoint,
            protocol,
            "opentelemetry-exporter-otlp-proto-http"
            if protocol == "http/protobuf"
            else "opentelemetry-exporter-otlp-proto-grpc",
        )
        return None
    with _isolated_otlp_env():
        return exporter_cls(
            endpoint=endpoint,
            headers=_otlp_headers(),
            timeout=_otlp_timeout_seconds(),
        )


def _configure_span_export(
    tracer_provider: TracerProvider, otel_dir: Path
) -> JsonlBatchWriter:
    """Attach span processors: local JSONL always, OTLP only when opted in.

    The local writer is unconditional because the Telemetry page reads those
    files (:mod:`app.services.observability_service`), and because a machine
    wide OTLP variable must not turn EvoFlux into a sender for someone else's
    collector.  Returns the writer so :func:`shutdown_otel` can close it.
    """
    spans_dir = otel_dir / "spans"
    writer = JsonlBatchWriter(
        root=spans_dir,
        partition_fn=hourly_partition,
        on_write=lambda n: SPANS_WRITTEN.inc(n),
        on_drop=lambda: SPANS_DROPPED.inc(),
        name="spans",
    )
    tracer_provider.add_span_processor(
        BatchSpanProcessor(_FilteringJsonlSpanExporter(writer))
    )
    logger.info(
        "otel_trace_exporter=file dir={} sample_ratio={:.3f} slow_ms={}",
        spans_dir,
        _sample_ratio(),
        _slow_span_threshold_ns() // 1_000_000,
    )

    endpoint = _otlp_endpoint()
    if endpoint:
        exporter = _otlp_span_exporter(endpoint)
        if exporter is not None:
            tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("otel_trace_exporter=otlp endpoint={}", endpoint)
    return writer


class _JsonlMetricExporter(MetricExporter):
    """Feeds metric batches to ``JsonlBatchWriter`` (daily partitions)."""

    def __init__(self, writer: JsonlBatchWriter) -> None:
        super().__init__()
        self._writer = writer

    def export(
        self, metrics_data: MetricsData, timeout_millis: float = 10_000, **_: object
    ) -> MetricExportResult:
        self._writer.write(
            _metrics_to_dict(metrics_data),
            ts=datetime.now(timezone.utc),
        )
        return MetricExportResult.SUCCESS

    def force_flush(self, timeout_millis: float = 30_000) -> bool:
        return True

    def shutdown(self, timeout_millis: float = 30_000, **_: object) -> None:
        pass


# ── Serialisation helpers ─────────────────────────────────────────────────────


def _span_end_datetime(span: ReadableSpan) -> datetime:
    if span.end_time:
        return datetime.fromtimestamp(span.end_time / 1_000_000_000, tz=timezone.utc)
    return datetime.now(timezone.utc)


def _span_to_dict(span: ReadableSpan) -> dict:
    ctx = span.context
    parent_id = (
        f"0x{span.parent.span_id:016x}" if span.parent and span.parent.span_id else None
    )
    return {
        "name": span.name,
        "trace_id": f"0x{ctx.trace_id:032x}" if ctx else None,
        "span_id": f"0x{ctx.span_id:016x}" if ctx else None,
        "parent_id": parent_id,
        "kind": str(span.kind.name),
        "start_time": span.start_time,
        "end_time": span.end_time,
        "duration_ms": round((span.end_time - span.start_time) / 1_000_000, 3)
        if span.start_time and span.end_time
        else None,
        "status": span.status.status_code.name,
        "attributes": dict(span.attributes or {}),
        "events": [
            {
                "name": e.name,
                "timestamp": e.timestamp,
                "attributes": dict(e.attributes or {}),
            }
            for e in (span.events or [])
        ],
        "resource": dict((span.resource or Resource.create()).attributes),
    }


def _metrics_to_dict(data: MetricsData) -> dict:
    """Minimal flat dict for metrics JSONL — readable without OTel SDK."""
    out: list[dict] = []
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                out.append(
                    {
                        "name": m.name,
                        "description": m.description,
                        "unit": m.unit,
                        "data": str(m.data),
                    }
                )
    return {"metrics": out}


# ── Setup / teardown ──────────────────────────────────────────────────────────


def setup_otel(
    service_name: str = "EvoFlux",
    otel_dir: Path | None = None,
) -> None:
    """Bootstrap OTel SDK.  Safe to call multiple times — idempotent.

    Args:
        service_name: Emitted as ``service.name`` resource attribute.
        otel_dir: Directory for span/metric files.  Defaults to
            ``{EVOFLUX_STATE_DIR}/otel/`` resolved from settings.
    """
    global _tracer_provider, _meter_provider, _span_writer, _metric_writer

    if _tracer_provider is not None:
        return  # Me already set up

    if otel_dir is None:
        from app.core.config import settings

        otel_dir = Path(settings.EVOFLUX_STATE_DIR) / "otel"

    resource = _resource(service_name)

    # ── Tracer provider ───────────────────────────────────────────────────────
    # Head sampler is ALWAYS_ON; tiering happens at export via the filter.
    _tracer_provider = TracerProvider(resource=resource, sampler=ALWAYS_ON)

    _span_writer = _configure_span_export(_tracer_provider, otel_dir)

    trace.set_tracer_provider(_tracer_provider)

    # ── Meter provider ────────────────────────────────────────────────────────
    metrics_dir = otel_dir / "metrics"
    _metric_writer = JsonlBatchWriter(
        root=metrics_dir,
        partition_fn=daily_partition,
        name="metrics",
    )
    metric_reader = PeriodicExportingMetricReader(
        _JsonlMetricExporter(_metric_writer),
        export_interval_millis=60_000,  # Me flush metrics every 60 s
    )
    _meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(_meter_provider)

    logger.info(
        "otel_setup_complete service={} spans_dir={} metrics_dir={}",
        service_name,
        otel_dir / "spans",
        metrics_dir,
    )


def shutdown_otel() -> None:
    """Flush and shut down providers gracefully on app shutdown."""
    global _span_writer, _metric_writer
    if _tracer_provider is not None:
        _tracer_provider.shutdown()
    if _meter_provider is not None:
        _meter_provider.shutdown()
    if _span_writer is not None:
        _span_writer.close()
        _span_writer = None
    if _metric_writer is not None:
        _metric_writer.close()
        _metric_writer = None


def get_tracer() -> trace.Tracer:
    """Return the EvoFlux tracer. setup_otel() must have been called first."""
    return trace.get_tracer(_INSTRUMENTATION_SCOPE)


def get_meter() -> metrics.Meter:
    """Return the EvoFlux meter. setup_otel() must have been called first."""
    return metrics.get_meter(_INSTRUMENTATION_SCOPE)
