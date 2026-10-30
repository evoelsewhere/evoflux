//! Database metrics with Python's names and labels (`app/core/metrics.py`).

use std::collections::BTreeMap;
use std::fmt::Write as _;
use std::sync::Mutex;
use std::time::Duration;

pub(crate) const POOL_WAIT: &str = "EVOFLUX_db_pool_wait_seconds";
pub(crate) const POOL_TIMEOUTS: &str = "EVOFLUX_db_pool_timeouts_total";
pub(crate) const CONFLICTS: &str = "EVOFLUX_db_concurrent_conflicts_total";
pub(crate) const RETRIES: &str = "EVOFLUX_db_concurrent_retries_total";
pub(crate) const CHECKPOINTS: &str = "EVOFLUX_db_wal_checkpoints_total";

/// `DB_POOL_WAIT` buckets in `app/core/metrics.py`.
const WAIT_BUCKETS: [f64; 13] = [
    0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0,
];

type Labels = Vec<(&'static str, String)>;

#[derive(Default)]
pub(crate) struct Metrics {
    series: Mutex<BTreeMap<(String, Labels), f64>>,
}

impl Metrics {
    pub(crate) fn inc(&self, name: &str, labels: &[(&'static str, &str)]) {
        self.add(name.to_owned(), owned(labels), 1.0);
    }

    pub(crate) fn observe_wait(&self, lane: &str, route: &str, waited: Duration) {
        let labels = [("lane", lane), ("route", route)];
        let secs = waited.as_secs_f64();
        for le in WAIT_BUCKETS {
            if secs <= le {
                let mut bucket = owned(&labels);
                bucket.push(("le", le.to_string()));
                self.add(format!("{POOL_WAIT}_bucket"), bucket, 1.0);
            }
        }
        let mut inf = owned(&labels);
        inf.push(("le", "+Inf".to_owned()));
        self.add(format!("{POOL_WAIT}_bucket"), inf, 1.0);
        self.add(format!("{POOL_WAIT}_sum"), owned(&labels), secs);
        self.add(format!("{POOL_WAIT}_count"), owned(&labels), 1.0);
    }

    /// Sum of every series named `name` whose labels include all of `labels`.
    pub(crate) fn value(&self, name: &str, labels: &[(&str, &str)]) -> f64 {
        let Ok(series) = self.series.lock() else {
            return 0.0;
        };
        series
            .iter()
            .filter(|((n, l), _)| {
                n == name
                    && labels
                        .iter()
                        .all(|(k, v)| l.iter().any(|(lk, lv)| lk == k && lv == v))
            })
            .map(|(_, v)| v)
            .sum()
    }

    /// Prometheus text exposition of every series.
    pub(crate) fn render(&self) -> String {
        let mut out = String::new();
        let Ok(series) = self.series.lock() else {
            return out;
        };
        for ((name, labels), value) in series.iter() {
            let labels: Vec<String> = labels.iter().map(|(k, v)| format!("{k}=\"{v}\"")).collect();
            let _ = writeln!(out, "{name}{{{}}} {value}", labels.join(","));
        }
        out
    }

    fn add(&self, name: String, labels: Labels, by: f64) {
        if let Ok(mut series) = self.series.lock() {
            *series.entry((name, labels)).or_insert(0.0) += by;
        }
    }
}

fn owned(labels: &[(&'static str, &str)]) -> Labels {
    labels.iter().map(|(k, v)| (*k, (*v).to_owned())).collect()
}
