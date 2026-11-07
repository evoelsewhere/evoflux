//! Lightweight file watching for live reload.
//!
//! Port of the upstream `packages/coding-agent/src/utils/fs-watch.ts`.
//! uses Node's `fs.watch` with a retry-on-error wrapper to (a) keep the git
//! footer's branch/status fresh and (b) hot-reload the active theme file.
//!
//! evo watches by polling modification times. That avoids a native watcher
//! dependency and behaves predictably on every platform (network drives, WSL
//! mounts, editors that replace files by rename). The retry delay matches
//! native [`FS_WATCH_RETRY_DELAY_MS`].

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, SystemTime};

/// Native `FS_WATCH_RETRY_DELAY_MS`: how long to wait after a watch error
/// before retrying.
pub const FS_WATCH_RETRY_DELAY_MS: u64 = 5_000;

/// Default poll interval. Short enough to feel immediate, long enough that a
/// few watched files cost nothing on the main thread.
pub const DEFAULT_POLL_INTERVAL_MS: u64 = 1_000;

fn mtime(path: &Path) -> Option<SystemTime> {
    std::fs::metadata(path).ok().and_then(|m| m.modified().ok())
}

fn snapshot(paths: &[PathBuf]) -> HashMap<PathBuf, Option<SystemTime>> {
    paths.iter().map(|p| (p.clone(), mtime(p))).collect()
}

/// A running watch. Dropping it does **not** stop the watch; call
/// [`WatchHandle::close`] to stop it deterministically (native `closeWatcher`).
pub struct WatchHandle {
    stop: Arc<AtomicBool>,
    join: Option<tokio::task::JoinHandle<()>>,
}

impl WatchHandle {
    /// Signal the watch to stop and wait for its task to finish.
    pub fn close(mut self) {
        self.stop.store(true, Ordering::SeqCst);
        if let Some(join) = self.join.take() {
            join.abort();
        }
    }

    /// Request stop without joining (useful from a drop path).
    pub fn request_stop(&self) {
        self.stop.store(true, Ordering::SeqCst);
    }
}

impl Drop for WatchHandle {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
    }
}

/// Watch `paths` for mtime changes, invoking `on_change` whenever any watched
/// path changes (content or existence). Missing paths are tracked too: creating
/// or deleting a watched path fires `on_change`.
///
/// Poll failures are tolerated: the watcher waits [`FS_WATCH_RETRY_DELAY_MS`] and
/// retries, never panicking (native `watchWithErrorHandler`).
pub fn watch_paths<F>(paths: Vec<PathBuf>, poll_interval: Duration, on_change: F) -> WatchHandle
where
    F: Fn() + Send + Sync + 'static,
{
    let stop = Arc::new(AtomicBool::new(false));
    let stop_task = stop.clone();
    let join = tokio::spawn(async move {
        let mut prev = snapshot(&paths);
        loop {
            tokio::time::sleep(poll_interval).await;
            if stop_task.load(Ordering::SeqCst) {
                break;
            }
            let current = match std::panic::catch_unwind(|| snapshot(&paths)) {
                Ok(snap) => snap,
                Err(_) => {
                    // A metadata read blew up; wait the retry delay and try
                    // again rather than tearing down the watch.
                    tokio::time::sleep(Duration::from_millis(FS_WATCH_RETRY_DELAY_MS)).await;
                    continue;
                }
            };
            if current != prev {
                prev = current;
                on_change();
            }
        }
    });
    WatchHandle {
        stop,
        join: Some(join),
    }
}

/// Convenience for a single path.
pub fn watch_path<F>(path: PathBuf, on_change: F) -> WatchHandle
where
    F: Fn() + Send + Sync + 'static,
{
    watch_paths(
        vec![path],
        Duration::from_millis(DEFAULT_POLL_INTERVAL_MS),
        on_change,
    )
}

// ── Folder trees ─────────────────────────────────────────────────────────────

/// How a file in a watched tree changed.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TreeChangeKind {
    Added,
    Modified,
    Deleted,
}

/// One changed file, relative to the watched root with `/` separators.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TreeChange {
    pub kind: TreeChangeKind,
    pub path: String,
}

/// The accepted files of a tree: relative path → (mtime, size).
#[derive(Debug, Clone, Default, PartialEq)]
pub struct TreeSnapshot {
    files: HashMap<String, (Option<SystemTime>, u64)>,
    /// The scan stopped at its entry budget; files it did not reach are not
    /// reported as deleted.
    truncated: bool,
}

impl TreeSnapshot {
    pub fn len(&self) -> usize {
        self.files.len()
    }

    pub fn is_empty(&self) -> bool {
        self.files.is_empty()
    }

    pub fn contains(&self, path: &str) -> bool {
        self.files.contains_key(path)
    }
}

/// Folders never descended into besides those starting with `.`: package
/// caches that hold thousands of files and no documents of the person's.
const SKIPPED_DIRS: &[&str] = &["node_modules"];

/// Whether a relative path has a segment starting with `.` (v3's watch filter).
pub fn has_hidden_segment(rel: &str) -> bool {
    rel.split(['/', '\\'])
        .any(|segment| segment.starts_with('.'))
}

/// Walk `root` (not following links, skipping hidden folders) and keep the
/// files whose relative path `accept` takes. At most `max_entries` directory
/// entries are looked at.
pub fn scan_tree(
    root: &Path,
    accept: &(dyn Fn(&str) -> bool + Send + Sync),
    max_entries: usize,
) -> TreeSnapshot {
    let mut snapshot = TreeSnapshot::default();
    let mut seen = 0usize;
    let mut stack = vec![(root.to_path_buf(), String::new())];
    while let Some((dir, prefix)) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&dir) else {
            continue;
        };
        for entry in entries.flatten() {
            seen += 1;
            if seen > max_entries {
                snapshot.truncated = true;
                return snapshot;
            }
            let name = entry.file_name().to_string_lossy().into_owned();
            if name.starts_with('.') {
                continue;
            }
            let rel = if prefix.is_empty() {
                name.clone()
            } else {
                format!("{prefix}/{name}")
            };
            let Ok(kind) = entry.file_type() else {
                continue;
            };
            if kind.is_dir() {
                if !SKIPPED_DIRS.contains(&name.as_str()) {
                    stack.push((entry.path(), rel));
                }
            } else if kind.is_file() && accept(&rel) {
                let meta = entry.metadata().ok();
                snapshot.files.insert(
                    rel,
                    (
                        meta.as_ref().and_then(|m| m.modified().ok()),
                        meta.map_or(0, |m| m.len()),
                    ),
                );
            }
        }
    }
    snapshot
}

/// The changes from `before` to `after`, sorted by path.
pub fn diff_trees(before: &TreeSnapshot, after: &TreeSnapshot) -> Vec<TreeChange> {
    let mut changes = Vec::new();
    for (path, stamp) in &after.files {
        match before.files.get(path) {
            None => changes.push(TreeChange {
                kind: TreeChangeKind::Added,
                path: path.clone(),
            }),
            Some(old) if old != stamp => changes.push(TreeChange {
                kind: TreeChangeKind::Modified,
                path: path.clone(),
            }),
            Some(_) => {}
        }
    }
    if !after.truncated {
        for path in before.files.keys() {
            if !after.files.contains_key(path) {
                changes.push(TreeChange {
                    kind: TreeChangeKind::Deleted,
                    path: path.clone(),
                });
            }
        }
    }
    changes.sort_by(|a, b| a.path.cmp(&b.path));
    changes
}

/// How [`watch_tree`] polls.
#[derive(Debug, Clone, Copy)]
pub struct TreeWatchOptions {
    /// Time between scans while nothing changes. Raised to four times the
    /// last scan's duration, so a large tree costs a bounded share of a core.
    pub poll: Duration,
    /// A change is reported once two scans this far apart agree (v3's
    /// watcher debounced by 300 ms).
    pub debounce: Duration,
    /// Longest wait for a file that keeps changing before it is reported.
    pub max_settle: Duration,
    /// Directory entries looked at per scan.
    pub max_entries: usize,
}

impl Default for TreeWatchOptions {
    fn default() -> Self {
        Self {
            poll: Duration::from_millis(500),
            debounce: Duration::from_millis(300),
            max_settle: Duration::from_secs(10),
            max_entries: 100_000,
        }
    }
}

/// Watch the files under `root` that `accept` takes and call `on_change` with
/// each settled batch of changes. The first scan is the baseline (no call).
pub fn watch_tree<A, F, Fut>(
    root: PathBuf,
    accept: A,
    options: TreeWatchOptions,
    on_change: F,
) -> WatchHandle
where
    A: Fn(&str) -> bool + Send + Sync + 'static,
    F: Fn(Vec<TreeChange>) -> Fut + Send + Sync + 'static,
    Fut: std::future::Future<Output = ()> + Send,
{
    let stop = Arc::new(AtomicBool::new(false));
    let stop_task = stop.clone();
    let accept: Arc<dyn Fn(&str) -> bool + Send + Sync> = Arc::new(accept);
    let join = tokio::spawn(async move {
        let scan = |accept: Arc<dyn Fn(&str) -> bool + Send + Sync>, root: PathBuf| async move {
            let started = std::time::Instant::now();
            let snapshot = tokio::task::spawn_blocking(move || {
                scan_tree(&root, &*accept, options.max_entries)
            })
            .await;
            (snapshot.ok(), started.elapsed())
        };
        let (mut prev, mut cost) = match scan(accept.clone(), root.clone()).await {
            (Some(snapshot), cost) => (snapshot, cost),
            (None, cost) => (TreeSnapshot::default(), cost),
        };
        loop {
            tokio::time::sleep(options.poll.max(cost * 4)).await;
            if stop_task.load(Ordering::SeqCst) {
                break;
            }
            let (Some(next), elapsed) = scan(accept.clone(), root.clone()).await else {
                tokio::time::sleep(Duration::from_millis(FS_WATCH_RETRY_DELAY_MS)).await;
                continue;
            };
            cost = elapsed;
            if diff_trees(&prev, &next).is_empty() {
                continue;
            }
            // Settle: wait until a file being written stops changing.
            let mut latest = next;
            let settle_started = std::time::Instant::now();
            loop {
                tokio::time::sleep(options.debounce).await;
                if stop_task.load(Ordering::SeqCst) {
                    return;
                }
                let (Some(again), _) = scan(accept.clone(), root.clone()).await else {
                    break;
                };
                let stable = again == latest;
                latest = again;
                if stable || settle_started.elapsed() >= options.max_settle {
                    break;
                }
            }
            let changes = diff_trees(&prev, &latest);
            prev = latest;
            if !changes.is_empty() {
                on_change(changes).await;
            }
        }
    });
    WatchHandle {
        stop,
        join: Some(join),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicUsize;

    fn office(rel: &str) -> bool {
        rel.ends_with(".pptx")
    }

    #[test]
    fn tree_scans_skip_hidden_folders_and_report_changes() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path();
        std::fs::create_dir_all(root.join("sub")).unwrap();
        std::fs::create_dir_all(root.join(".git")).unwrap();
        std::fs::create_dir_all(root.join("node_modules")).unwrap();
        std::fs::write(root.join("a.pptx"), "1").unwrap();
        std::fs::write(root.join("sub/b.pptx"), "1").unwrap();
        std::fs::write(root.join(".git/c.pptx"), "1").unwrap();
        std::fs::write(root.join("node_modules/d.pptx"), "1").unwrap();
        std::fs::write(root.join("notes.txt"), "1").unwrap();
        let before = scan_tree(root, &office, 1000);
        assert_eq!(before.len(), 2);
        assert!(before.contains("sub/b.pptx"));
        std::fs::write(root.join("a.pptx"), "22").unwrap();
        std::fs::remove_file(root.join("sub/b.pptx")).unwrap();
        std::fs::write(root.join("c.pptx"), "1").unwrap();
        let after = scan_tree(root, &office, 1000);
        let changes = diff_trees(&before, &after);
        assert_eq!(
            changes,
            vec![
                TreeChange {
                    kind: TreeChangeKind::Modified,
                    path: "a.pptx".into()
                },
                TreeChange {
                    kind: TreeChangeKind::Added,
                    path: "c.pptx".into()
                },
                TreeChange {
                    kind: TreeChangeKind::Deleted,
                    path: "sub/b.pptx".into()
                },
            ]
        );
        // A truncated scan never reports what it did not reach as deleted.
        let partial = scan_tree(root, &office, 1);
        assert!(partial.truncated);
        assert!(diff_trees(&after, &partial)
            .iter()
            .all(|c| c.kind != TreeChangeKind::Deleted));
        assert!(has_hidden_segment("a/.b/c.pptx") && !has_hidden_segment("a/b.c/d.pptx"));
    }

    #[test]
    fn tree_watch_reports_a_settled_change_once() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().to_path_buf();
        let rt = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .enable_time()
            .build()
            .unwrap();
        let batches = Arc::new(std::sync::Mutex::new(Vec::new()));
        rt.block_on(async {
            let sink = batches.clone();
            let options = TreeWatchOptions {
                poll: Duration::from_millis(30),
                debounce: Duration::from_millis(60),
                ..TreeWatchOptions::default()
            };
            let handle = watch_tree(root.clone(), office, options, move |changes| {
                let sink = sink.clone();
                async move { sink.lock().unwrap().push(changes) }
            });
            tokio::time::sleep(Duration::from_millis(100)).await;
            std::fs::write(root.join("deck.pptx"), "1").unwrap();
            std::fs::write(root.join("skip.txt"), "1").unwrap();
            tokio::time::sleep(Duration::from_millis(400)).await;
            handle.close();
        });
        let batches = batches.lock().unwrap();
        assert_eq!(
            *batches,
            vec![vec![TreeChange {
                kind: TreeChangeKind::Added,
                path: "deck.pptx".into()
            }]]
        );
    }

    #[test]
    fn detects_content_change() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("theme.json");
        std::fs::write(&file, "a").unwrap();

        let hits = Arc::new(AtomicUsize::new(0));
        let hits_task = hits.clone();
        let rt = tokio::runtime::Builder::new_current_thread()
            .enable_time()
            .build()
            .unwrap();
        rt.block_on(async {
            let handle = watch_paths(vec![file.clone()], Duration::from_millis(20), move || {
                hits_task.fetch_add(1, Ordering::SeqCst);
            });
            tokio::time::sleep(Duration::from_millis(60)).await;
            std::fs::write(&file, "bb").unwrap();
            // mtime resolution: ensure a visible change.
            tokio::time::sleep(Duration::from_millis(120)).await;
            handle.close();
        });
        assert!(
            hits.load(Ordering::SeqCst) >= 1,
            "expected at least one change"
        );
    }

    #[test]
    fn close_stops_watch() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("f");
        std::fs::write(&file, "x").unwrap();
        let rt = tokio::runtime::Builder::new_current_thread()
            .enable_time()
            .build()
            .unwrap();
        rt.block_on(async {
            let handle = watch_path(file, || {});
            handle.close();
        });
    }
}
