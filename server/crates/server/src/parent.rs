//! Port of `_start_parent_watch` (`app/cli/commands/serve.py`): a plain OS
//! thread polls the parent every 500 ms, so it fires even if the async
//! runtime is wedged. When the parent is gone it asks for a graceful shutdown
//! and, if that has not finished within 15 s, exits the process.
//!
//! Unlike v3's `os.kill(pid, 0)` this also works on Windows, and it compares
//! the parent's start time so a reused PID does not count as the parent.

use std::time::{Duration, Instant};

use sysinfo::{Pid, ProcessRefreshKind, ProcessStatus, ProcessesToUpdate, System};

const POLL: Duration = Duration::from_millis(500);
const SHUTDOWN_GRACE: Duration = Duration::from_secs(15);

/// Start watching `parent_pid`; `on_death` runs once when it is gone.
pub fn spawn(parent_pid: u32, on_death: impl FnOnce() + Send + 'static) -> std::io::Result<()> {
    std::thread::Builder::new()
        .name("parent-watch".to_owned())
        .spawn(move || watch(parent_pid, on_death))
        .map(|_| ())
}

fn watch(parent_pid: u32, on_death: impl FnOnce()) {
    let pid = Pid::from_u32(parent_pid);
    let mut system = System::new();
    let mut started_at = None;
    loop {
        match probe(&mut system, pid) {
            Some(start) if started_at.is_none_or(|first| first == start) => {
                started_at = Some(start);
            }
            _ => break,
        }
        std::thread::park_timeout(POLL);
    }
    // Logged first so backend.log keeps a trace if the watch ever fires by mistake.
    tracing::warn!(
        parent_pid,
        "parent-watch: parent no longer alive; shutting down"
    );
    on_death();
    let deadline = Instant::now() + SHUTDOWN_GRACE;
    while let Some(left) = deadline.checked_duration_since(Instant::now()) {
        std::thread::park_timeout(left);
    }
    tracing::error!("parent-watch: shutdown did not finish in time; exiting");
    std::process::exit(1);
}

/// The process's start time while it is alive (a zombie counts as gone).
fn probe(system: &mut System, pid: Pid) -> Option<u64> {
    system.refresh_processes_specifics(
        ProcessesToUpdate::Some(&[pid]),
        true,
        ProcessRefreshKind::nothing(),
    );
    system
        .process(pid)
        .filter(|process| process.status() != ProcessStatus::Zombie)
        .map(|process| process.start_time())
}
