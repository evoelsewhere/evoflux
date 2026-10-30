//! Logging and metrics setup.
//!
//! Logs go to stderr and, as JSON lines, to `{state}/logs/app/app.log`
//! (`app/core/logging_config.py`). Metrics keep Python's `EVOFLUX_` prefix and
//! are rendered in the Prometheus text format for `/metrics`.

use std::sync::OnceLock;

use metrics_exporter_prometheus::{Matcher, PrometheusBuilder, PrometheusHandle};
use tracing_appender::non_blocking::WorkerGuard;
use tracing_appender::rolling::{RollingFileAppender, Rotation};
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{fmt, EnvFilter};

use crate::config::Settings;
use crate::paths::Paths;

static PROMETHEUS: OnceLock<PrometheusHandle> = OnceLock::new();

const SECONDS_BUCKETS: &[f64] = &[
    0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
];

/// Keeps the background log writer alive; drop it at shutdown to flush.
pub struct TelemetryGuard {
    _file: Option<WorkerGuard>,
}

/// Install tracing and the metrics registry. Safe to call more than once: the
/// first call wins.
pub fn init(settings: &Settings) -> TelemetryGuard {
    install_metrics();
    let paths = Paths::resolve(settings);
    let (file_writer, guard) = match open_log_file(&paths) {
        Some(file) => {
            let (writer, guard) = tracing_appender::non_blocking(file);
            (Some(writer), Some(guard))
        }
        None => (None, None),
    };
    let filter = EnvFilter::try_new(settings.log_level.to_lowercase())
        .unwrap_or_else(|_| EnvFilter::new("info"));
    let file_layer =
        file_writer.map(|writer| fmt::layer().json().with_ansi(false).with_writer(writer));
    let _ = tracing_subscriber::registry()
        .with(filter)
        .with(fmt::layer().with_writer(std::io::stderr))
        .with(file_layer)
        .try_init();
    TelemetryGuard { _file: guard }
}

fn open_log_file(paths: &Paths) -> Option<RollingFileAppender> {
    std::fs::create_dir_all(&paths.log_dir).ok()?;
    RollingFileAppender::builder()
        .rotation(Rotation::NEVER)
        .filename_prefix("app.log")
        .build(&paths.log_dir)
        .ok()
}

/// Install the global metrics recorder if none is set. Idempotent.
pub fn install_metrics() {
    PROMETHEUS.get_or_init(|| {
        let recorder = PrometheusBuilder::new()
            .set_buckets_for_metric(Matcher::Suffix("_seconds".to_owned()), SECONDS_BUCKETS)
            .unwrap_or_else(|_| PrometheusBuilder::new())
            .build_recorder();
        let handle = recorder.handle();
        // Another recorder may already be installed by the host process.
        let _ = metrics::set_global_recorder(recorder);
        handle
    });
}

/// Prometheus text exposition of every recorded metric.
pub fn render_prometheus() -> String {
    PROMETHEUS
        .get()
        .map(PrometheusHandle::render)
        .unwrap_or_default()
}
