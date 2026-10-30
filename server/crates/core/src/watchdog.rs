//! Async-runtime stall detection.
//!
//! A task ticks every 50 ms and measures how late each tick ran; lateness above
//! the threshold counts as a stall. A plain OS thread watches the task's
//! heartbeat, so a runtime that is blocked outright is still reported.

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

const TICK: Duration = Duration::from_millis(50);
const WATCHER_POLL: Duration = Duration::from_millis(250);
const WATCHER_LIMIT: Duration = Duration::from_secs(1);

pub struct WatchdogHandle {
    stalls: Arc<AtomicU64>,
    shutdown: Arc<AtomicBool>,
    task: tokio::task::JoinHandle<()>,
    watcher: Option<JoinHandle<()>>,
}

impl WatchdogHandle {
    /// Stalls above the threshold seen so far.
    pub fn stall_count(&self) -> u64 {
        self.stalls.load(Ordering::Relaxed)
    }
}

impl Drop for WatchdogHandle {
    fn drop(&mut self) {
        self.shutdown.store(true, Ordering::Relaxed);
        self.task.abort();
        if let Some(watcher) = &self.watcher {
            watcher.thread().unpark();
        }
    }
}

/// Start the watchdog on the current tokio runtime.
pub fn spawn(threshold: Duration) -> WatchdogHandle {
    let stalls = Arc::new(AtomicU64::new(0));
    let shutdown = Arc::new(AtomicBool::new(false));
    let epoch = Instant::now();
    let heartbeat = Arc::new(AtomicU64::new(0));

    let task = tokio::spawn({
        let stalls = Arc::clone(&stalls);
        let heartbeat = Arc::clone(&heartbeat);
        async move {
            let mut interval = tokio::time::interval(TICK);
            interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
            interval.tick().await;
            let mut last = Instant::now();
            loop {
                interval.tick().await;
                let now = Instant::now();
                let late = now.duration_since(last).saturating_sub(TICK);
                last = now;
                heartbeat.store(millis(now.duration_since(epoch)), Ordering::Relaxed);
                if late > threshold {
                    stalls.fetch_add(1, Ordering::Relaxed);
                    metrics::counter!("EVOFLUX_runtime_stall_total").increment(1);
                    metrics::histogram!("EVOFLUX_runtime_stall_seconds").record(late.as_secs_f64());
                }
            }
        }
    });

    let watcher = std::thread::Builder::new()
        .name("evoflux-watchdog".to_owned())
        .spawn({
            let shutdown = Arc::clone(&shutdown);
            move || watch(epoch, &heartbeat, &shutdown)
        })
        .ok();

    WatchdogHandle {
        stalls,
        shutdown,
        task,
        watcher,
    }
}

fn watch(epoch: Instant, heartbeat: &AtomicU64, shutdown: &AtomicBool) {
    let mut reported = false;
    while !shutdown.load(Ordering::Relaxed) {
        std::thread::park_timeout(WATCHER_POLL);
        let age = millis(epoch.elapsed()).saturating_sub(heartbeat.load(Ordering::Relaxed));
        if age > millis(WATCHER_LIMIT) {
            if !reported {
                tracing::error!(late_ms = age, "runtime_stalled");
                reported = true;
            }
        } else {
            reported = false;
        }
    }
}

fn millis(d: Duration) -> u64 {
    u64::try_from(d.as_millis()).unwrap_or(u64::MAX)
}
