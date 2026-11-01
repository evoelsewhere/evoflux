//! Port of app/core/otel_retention.py: the sweeper that deletes old
//! `{state}/otel/spans/*.jsonl` and `{state}/otel/metrics/*.jsonl` partitions.

use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime};

use tokio::task::JoinHandle;
use tokio::time::sleep;
use tokio_util::sync::CancellationToken;

/// `OTEL_*` settings. Python reads them from the process environment; the
/// server builds this once from the environment it started with.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct OtelConfig {
    pub span_retention_days: i64,
    pub metric_retention_days: i64,
    pub sweep_interval_hours: i64,
    pub enabled: bool,
    pub sample_ratio: f64,
}

impl Default for OtelConfig {
    fn default() -> Self {
        Self {
            span_retention_days: 30,
            metric_retention_days: 90,
            sweep_interval_hours: 24,
            enabled: true,
            sample_ratio: 1.0,
        }
    }
}

/// `_int_env`: unset or unparsable gives the default, a low value is raised to the floor.
fn int_setting(raw: Option<String>, default: i64, min_value: i64) -> i64 {
    match raw {
        None => default,
        Some(text) => match text.trim().parse::<i64>() {
            Ok(value) => value.max(min_value),
            Err(_) => default,
        },
    }
}

impl OtelConfig {
    /// Read the settings through `lookup` (for example `|name| std::env::var(name).ok()`).
    pub fn from_lookup(lookup: impl Fn(&str) -> Option<String>) -> Self {
        let defaults = Self::default();
        Self {
            span_retention_days: int_setting(
                lookup("OTEL_SPAN_RETENTION_DAYS"),
                defaults.span_retention_days,
                1,
            ),
            metric_retention_days: int_setting(
                lookup("OTEL_METRIC_RETENTION_DAYS"),
                defaults.metric_retention_days,
                1,
            ),
            sweep_interval_hours: int_setting(
                lookup("OTEL_RETENTION_SWEEP_INTERVAL_HOURS"),
                defaults.sweep_interval_hours,
                1,
            ),
            enabled: match lookup("OTEL_RETENTION_ENABLED") {
                None => defaults.enabled,
                Some(text) => matches!(
                    text.trim().to_lowercase().as_str(),
                    "1" | "true" | "yes" | "on"
                ),
            },
            sample_ratio: crate::summary::sample_ratio(lookup("OTEL_SPAN_SAMPLE_RATIO").as_deref()),
        }
    }

    /// `_sweep_interval_seconds`.
    pub fn interval(&self) -> Duration {
        Duration::from_secs(
            u64::try_from(self.sweep_interval_hours.saturating_mul(3_600)).unwrap_or(86_400),
        )
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct SweepResult {
    pub scanned: u64,
    pub deleted: u64,
    pub errors: u64,
    pub bytes_freed: u64,
}

/// `sweep_old_partitions`: delete the direct-child `*.jsonl` regular files of
/// `root` whose mtime is before `now - max_age_days`. Per-file failures are
/// counted, never raised.
pub fn sweep_old_partitions(root: &Path, max_age_days: i64, now: SystemTime) -> SweepResult {
    sweep_with(&StdFs, root, max_age_days, now)
}

/// The file operations of the sweep; tests fail them on purpose.
trait SweepFs {
    /// `(mtime, size)` of a file.
    fn stat(&self, path: &Path) -> std::io::Result<(SystemTime, u64)>;
    fn remove(&self, path: &Path) -> std::io::Result<()>;
}

struct StdFs;

impl SweepFs for StdFs {
    fn stat(&self, path: &Path) -> std::io::Result<(SystemTime, u64)> {
        let meta = std::fs::metadata(path)?;
        Ok((meta.modified()?, meta.len()))
    }

    fn remove(&self, path: &Path) -> std::io::Result<()> {
        std::fs::remove_file(path)
    }
}

fn sweep_with(fs: &impl SweepFs, root: &Path, max_age_days: i64, now: SystemTime) -> SweepResult {
    let mut result = SweepResult::default();
    if max_age_days <= 0 || !root.exists() {
        return result;
    }
    let age = Duration::from_secs(
        u64::try_from(max_age_days)
            .unwrap_or(0)
            .saturating_mul(86_400),
    );
    let Some(cutoff) = now.checked_sub(age) else {
        return result;
    };
    let Ok(entries) = std::fs::read_dir(root) else {
        return result;
    };
    for entry in entries.filter_map(Result::ok) {
        let path = entry.path();
        let named_jsonl = path
            .file_name()
            .and_then(|name| name.to_str())
            .is_some_and(|name| name.ends_with(".jsonl"));
        if !named_jsonl || !path.is_file() {
            continue;
        }
        result.scanned += 1;
        let Ok((modified, size)) = fs.stat(&path) else {
            result.errors += 1;
            continue;
        };
        if modified >= cutoff {
            continue;
        }
        if let Err(error) = fs.remove(&path) {
            result.errors += 1;
            tracing::warn!(path = %path.display(), %error, "otel_retention_unlink_failed");
            continue;
        }
        result.deleted += 1;
        result.bytes_freed += size;
    }
    result
}

/// `run_otel_retention_once`: spans first, then metrics, each with its own age.
pub fn run_once(
    otel_dir: &Path,
    config: &OtelConfig,
    now: SystemTime,
) -> (SweepResult, SweepResult) {
    let spans = sweep_old_partitions(&otel_dir.join("spans"), config.span_retention_days, now);
    let metrics =
        sweep_old_partitions(&otel_dir.join("metrics"), config.metric_retention_days, now);
    if swept_something(&spans, &metrics) {
        tracing::info!(
            spans_deleted = spans.deleted,
            spans_bytes = spans.bytes_freed,
            metrics_deleted = metrics.deleted,
            metrics_bytes = metrics.bytes_freed,
            span_days = config.span_retention_days,
            metric_days = config.metric_retention_days,
            "otel_retention_swept"
        );
    } else {
        tracing::debug!(
            spans_scanned = spans.scanned,
            metrics_scanned = metrics.scanned,
            "otel_retention_swept nothing_to_delete"
        );
    }
    (spans, metrics)
}

/// Python logs at info when either pass deleted something, at debug otherwise.
fn swept_something(spans: &SweepResult, metrics: &SweepResult) -> bool {
    spans.deleted > 0 || metrics.deleted > 0
}

/// Start the retention loop: one sweep now, then one per interval until `cancel` fires.
/// Disabled by `OTEL_RETENTION_ENABLED`: logs and returns a finished task.
pub fn spawn_otel_retention(
    otel_dir: PathBuf,
    config: OtelConfig,
    cancel: CancellationToken,
) -> JoinHandle<()> {
    if !config.enabled {
        tracing::info!("otel_retention_disabled");
        return tokio::spawn(async {});
    }
    tracing::info!(
        span_days = config.span_retention_days,
        metric_days = config.metric_retention_days,
        interval_h = config.sweep_interval_hours,
        "otel_retention_started"
    );
    let interval = config.interval();
    tokio::spawn(async move {
        loop {
            let dir = otel_dir.clone();
            let sweep =
                evoflux_core::blocking::run(move || run_once(&dir, &config, SystemTime::now()));
            tokio::select! {
                () = cancel.cancelled() => return,
                outcome = sweep => {
                    if let Err(error) = outcome {
                        tracing::warn!(%error, "otel_retention_sweep_failed");
                    }
                }
            }
            tokio::select! {
                () = cancel.cancelled() => return,
                () = sleep(interval) => {}
            }
        }
    })
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::disallowed_methods
)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use std::fs::File;
    use std::time::Instant;

    const DAY: Duration = Duration::from_secs(86_400);

    fn config_from(pairs: &[(&str, &str)]) -> OtelConfig {
        let map: HashMap<String, String> = pairs
            .iter()
            .map(|(k, v)| ((*k).to_owned(), (*v).to_owned()))
            .collect();
        OtelConfig::from_lookup(|name| map.get(name).cloned())
    }

    fn aged(dir: &Path, name: &str, bytes: usize, age: Duration, now: SystemTime) -> PathBuf {
        let path = dir.join(name);
        std::fs::write(&path, vec![b'x'; bytes]).unwrap();
        File::options()
            .write(true)
            .open(&path)
            .unwrap()
            .set_modified(now - age)
            .unwrap();
        path
    }

    #[test]
    fn defaults_match_python() {
        let config = config_from(&[]);
        assert_eq!(config, OtelConfig::default());
        assert_eq!(config.span_retention_days, 30);
        assert_eq!(config.metric_retention_days, 90);
        assert_eq!(config.interval(), Duration::from_secs(24 * 3_600));
        assert!(config.enabled);
        assert_eq!(config.sample_ratio, 1.0);
    }

    #[test]
    fn env_overrides_floors_and_bad_values() {
        let config = config_from(&[
            ("OTEL_SPAN_RETENTION_DAYS", "7"),
            ("OTEL_METRIC_RETENTION_DAYS", " 14 "),
            ("OTEL_RETENTION_SWEEP_INTERVAL_HOURS", "6"),
            ("OTEL_SPAN_SAMPLE_RATIO", "0.25"),
        ]);
        assert_eq!(config.span_retention_days, 7);
        assert_eq!(config.metric_retention_days, 14);
        assert_eq!(config.interval(), Duration::from_secs(6 * 3_600));
        assert_eq!(config.sample_ratio, 0.25);

        let floored = config_from(&[
            ("OTEL_SPAN_RETENTION_DAYS", "0"),
            ("OTEL_METRIC_RETENTION_DAYS", "-5"),
            ("OTEL_RETENTION_SWEEP_INTERVAL_HOURS", "0"),
        ]);
        assert_eq!(floored.span_retention_days, 1);
        assert_eq!(floored.metric_retention_days, 1);
        assert_eq!(floored.interval(), Duration::from_secs(3_600));

        let unparsable = config_from(&[
            ("OTEL_SPAN_RETENTION_DAYS", "soon"),
            ("OTEL_METRIC_RETENTION_DAYS", "1.5"),
            ("OTEL_RETENTION_SWEEP_INTERVAL_HOURS", ""),
        ]);
        assert_eq!(unparsable.span_retention_days, 30);
        assert_eq!(unparsable.metric_retention_days, 90);
        assert_eq!(unparsable.sweep_interval_hours, 24);
    }

    #[test]
    fn enabled_flag_accepts_only_the_truthy_spellings() {
        for value in ["1", "true", "TRUE", " yes ", "On"] {
            assert!(
                config_from(&[("OTEL_RETENTION_ENABLED", value)]).enabled,
                "{value}"
            );
        }
        for value in ["0", "false", "no", "off", "", "enabled", "2"] {
            assert!(
                !config_from(&[("OTEL_RETENTION_ENABLED", value)]).enabled,
                "{value}"
            );
        }
    }

    #[test]
    fn sweep_deletes_old_files_and_counts_bytes() {
        let dir = tempfile::tempdir().unwrap();
        let now = SystemTime::now();
        let old = aged(dir.path(), "2026-09-01-10.jsonl", 100, 45 * DAY, now);
        let fresh = aged(dir.path(), "2026-10-26-10.jsonl", 50, 5 * DAY, now);
        let result = sweep_old_partitions(dir.path(), 30, now);
        assert_eq!(
            result,
            SweepResult {
                scanned: 2,
                deleted: 1,
                errors: 0,
                bytes_freed: 100
            }
        );
        assert!(!old.exists());
        assert!(fresh.exists());
    }

    #[test]
    fn sweep_keeps_a_file_exactly_at_the_cutoff_and_deletes_one_second_older() {
        let dir = tempfile::tempdir().unwrap();
        let now = SystemTime::now();
        let exact = aged(dir.path(), "a.jsonl", 1, 30 * DAY, now);
        let older = aged(
            dir.path(),
            "b.jsonl",
            1,
            30 * DAY + Duration::from_secs(1),
            now,
        );
        let result = sweep_old_partitions(dir.path(), 30, now);
        assert_eq!((result.scanned, result.deleted), (2, 1));
        assert!(exact.exists());
        assert!(!older.exists());
    }

    #[test]
    fn sweep_uses_mtime_not_the_name() {
        let dir = tempfile::tempdir().unwrap();
        let now = SystemTime::now();
        let ancient_name_fresh_file = aged(dir.path(), "1999-01-01-00.jsonl", 1, DAY, now);
        sweep_old_partitions(dir.path(), 30, now);
        assert!(ancient_name_fresh_file.exists());
    }

    #[test]
    fn sweep_selects_only_direct_jsonl_regular_files() {
        let dir = tempfile::tempdir().unwrap();
        let now = SystemTime::now();
        let old_txt = aged(dir.path(), "old.txt", 1, 99 * DAY, now);
        let old_nested = {
            std::fs::create_dir(dir.path().join("sub")).unwrap();
            aged(&dir.path().join("sub"), "deep.jsonl", 1, 99 * DAY, now)
        };
        std::fs::create_dir(dir.path().join("folder.jsonl")).unwrap();
        let old_hidden = aged(dir.path(), ".hidden.jsonl", 1, 99 * DAY, now);
        let result = sweep_old_partitions(dir.path(), 30, now);
        assert_eq!((result.scanned, result.deleted), (1, 1));
        assert!(old_txt.exists());
        assert!(old_nested.exists());
        assert!(dir.path().join("folder.jsonl").is_dir());
        assert!(!old_hidden.exists());
    }

    #[test]
    fn sweep_without_a_root_or_with_a_zero_age_scans_nothing() {
        let dir = tempfile::tempdir().unwrap();
        let now = SystemTime::now();
        assert_eq!(
            sweep_old_partitions(&dir.path().join("missing"), 30, now),
            SweepResult::default()
        );
        let old = aged(dir.path(), "a.jsonl", 1, 99 * DAY, now);
        assert_eq!(
            sweep_old_partitions(dir.path(), 0, now),
            SweepResult::default()
        );
        assert_eq!(
            sweep_old_partitions(dir.path(), -3, now),
            SweepResult::default()
        );
        assert!(old.exists());
    }

    #[test]
    fn run_once_gives_spans_30_days_and_metrics_90() {
        let dir = tempfile::tempdir().unwrap();
        let spans = dir.path().join("spans");
        let metrics = dir.path().join("metrics");
        std::fs::create_dir(&spans).unwrap();
        std::fs::create_dir(&metrics).unwrap();
        let now = SystemTime::now();
        let old_span = aged(&spans, "s-old.jsonl", 10, 45 * DAY, now);
        let old_metric = aged(&metrics, "m-mid.jsonl", 20, 45 * DAY, now);
        let ancient_metric = aged(&metrics, "m-old.jsonl", 30, 100 * DAY, now);
        let (span_result, metric_result) = run_once(dir.path(), &OtelConfig::default(), now);
        assert_eq!((span_result.deleted, span_result.bytes_freed), (1, 10));
        assert_eq!((metric_result.deleted, metric_result.bytes_freed), (1, 30));
        assert!(!old_span.exists());
        assert!(old_metric.exists());
        assert!(!ancient_metric.exists());

        let tight = config_from(&[("OTEL_METRIC_RETENTION_DAYS", "10")]);
        let (_, metric_result) = run_once(dir.path(), &tight, now);
        assert_eq!(metric_result.deleted, 1);
        assert!(!old_metric.exists());
    }

    struct FailingFs {
        bad_stat: &'static str,
        bad_remove: &'static str,
    }

    impl SweepFs for FailingFs {
        fn stat(&self, path: &Path) -> std::io::Result<(SystemTime, u64)> {
            if path.to_string_lossy().contains(self.bad_stat) {
                return Err(std::io::Error::other("stat failed"));
            }
            StdFs.stat(path)
        }

        fn remove(&self, path: &Path) -> std::io::Result<()> {
            if path.to_string_lossy().contains(self.bad_remove) {
                return Err(std::io::Error::other("unlink failed"));
            }
            StdFs.remove(path)
        }
    }

    #[test]
    fn stat_and_unlink_failures_are_counted_and_the_sweep_goes_on() {
        let dir = tempfile::tempdir().unwrap();
        let now = SystemTime::now();
        let stat_fails = aged(dir.path(), "stat-fails.jsonl", 3, 99 * DAY, now);
        let unlink_fails = aged(dir.path(), "unlink-fails.jsonl", 5, 99 * DAY, now);
        let removed = aged(dir.path(), "removed.jsonl", 7, 99 * DAY, now);
        let fs = FailingFs {
            bad_stat: "stat-fails",
            bad_remove: "unlink-fails",
        };
        let result = sweep_with(&fs, dir.path(), 30, now);
        assert_eq!(
            result,
            SweepResult {
                scanned: 3,
                deleted: 1,
                errors: 2,
                bytes_freed: 7
            }
        );
        assert!(stat_fails.exists());
        assert!(unlink_fails.exists());
        assert!(!removed.exists());
    }

    #[test]
    fn the_sweep_is_logged_at_info_only_when_something_was_deleted() {
        let none = SweepResult::default();
        let some = SweepResult {
            deleted: 1,
            ..SweepResult::default()
        };
        assert!(!swept_something(&none, &none));
        assert!(swept_something(&some, &none));
        assert!(swept_something(&none, &some));
        assert!(swept_something(&some, &some));
        let scanned_only = SweepResult {
            scanned: 4,
            errors: 2,
            ..SweepResult::default()
        };
        assert!(!swept_something(&scanned_only, &scanned_only));
    }

    #[test]
    fn run_once_tolerates_missing_directories() {
        let dir = tempfile::tempdir().unwrap();
        let (spans, metrics) = run_once(dir.path(), &OtelConfig::default(), SystemTime::now());
        assert_eq!(
            (spans, metrics),
            (SweepResult::default(), SweepResult::default())
        );
    }

    /// Let the loop task finish its sweep and register its sleep (real time; the clock is paused).
    async fn settle() {
        std::thread::sleep(Duration::from_millis(200));
        for _ in 0..20 {
            tokio::task::yield_now().await;
        }
    }

    async fn until(mut done: impl FnMut() -> bool) {
        let deadline = Instant::now() + Duration::from_secs(5);
        while !done() {
            assert!(Instant::now() < deadline, "timed out waiting");
            tokio::task::yield_now().await;
        }
    }

    #[tokio::test]
    async fn disabled_starts_nothing() {
        let dir = tempfile::tempdir().unwrap();
        let now = SystemTime::now();
        let spans = dir.path().join("spans");
        std::fs::create_dir(&spans).unwrap();
        let old = aged(&spans, "a.jsonl", 1, 99 * DAY, now);
        let config = OtelConfig {
            enabled: false,
            ..OtelConfig::default()
        };
        let handle =
            spawn_otel_retention(dir.path().to_path_buf(), config, CancellationToken::new());
        tokio::time::timeout(Duration::from_secs(2), handle)
            .await
            .expect("a disabled sweeper ends at once")
            .unwrap();
        assert!(old.exists());
    }

    #[tokio::test(start_paused = true)]
    async fn sweeps_at_start_then_every_interval_and_stops_on_cancel() {
        let dir = tempfile::tempdir().unwrap();
        let spans = dir.path().join("spans");
        std::fs::create_dir(&spans).unwrap();
        let now = SystemTime::now();
        let first = aged(&spans, "first.jsonl", 1, 45 * DAY, now);
        let cancel = CancellationToken::new();
        let handle = spawn_otel_retention(
            dir.path().to_path_buf(),
            OtelConfig::default(),
            cancel.clone(),
        );
        until(|| !first.exists()).await;
        settle().await;

        let second = aged(&spans, "second.jsonl", 1, 45 * DAY, SystemTime::now());
        tokio::time::advance(Duration::from_secs(24 * 3_600 - 60)).await;
        for _ in 0..50 {
            tokio::task::yield_now().await;
        }
        assert!(second.exists(), "no sweep before the interval has passed");
        tokio::time::advance(Duration::from_secs(120)).await;
        until(|| !second.exists()).await;

        cancel.cancel();
        handle.await.unwrap();
        let third = aged(&spans, "third.jsonl", 1, 45 * DAY, SystemTime::now());
        tokio::time::advance(Duration::from_secs(48 * 3_600)).await;
        for _ in 0..50 {
            tokio::task::yield_now().await;
        }
        assert!(third.exists(), "a cancelled loop sweeps no more");
    }
}
