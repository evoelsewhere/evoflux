#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]

use std::time::Duration;

use evoflux_core::watchdog;

#[tokio::test(flavor = "current_thread")]
#[allow(clippy::disallowed_methods)]
async fn watchdog_detects_block() {
    let handle = watchdog::spawn(Duration::from_millis(100));
    // Let the first ticks run, then block the only runtime thread.
    tokio::time::sleep(Duration::from_millis(120)).await;
    std::thread::sleep(Duration::from_millis(300));
    tokio::time::sleep(Duration::from_millis(120)).await;
    assert!(handle.stall_count() >= 1, "stall not detected");
}

#[tokio::test(flavor = "current_thread")]
async fn watchdog_quiet_when_runtime_is_responsive() {
    let handle = watchdog::spawn(Duration::from_millis(100));
    tokio::time::sleep(Duration::from_millis(300)).await;
    assert_eq!(handle.stall_count(), 0);
}

#[tokio::test(flavor = "current_thread")]
#[allow(clippy::disallowed_methods)]
async fn watchdog_stall_is_exported_as_prometheus_metrics() {
    evoflux_core::telemetry::install_metrics();
    let handle = watchdog::spawn(Duration::from_millis(100));
    tokio::time::sleep(Duration::from_millis(120)).await;
    std::thread::sleep(Duration::from_millis(300));
    tokio::time::sleep(Duration::from_millis(120)).await;
    assert!(handle.stall_count() >= 1);
    let text = evoflux_core::telemetry::render_prometheus();
    assert!(text.contains("EVOFLUX_runtime_stall_total"), "{text}");
    assert!(text.contains("EVOFLUX_runtime_stall_seconds"), "{text}");
}
