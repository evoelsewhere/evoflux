//! The two ways a shell command can keep the tool waiting *after the command
//! itself is done* — the everyday "`npm run` is stuck" report.
//!
//! Neither is a property of the shell; both are properties of how the child is
//! wired, and both are invisible in a short command:
//!
//! 1. **A grandchild holding the inherited pipes.** A script that starts a
//!    watcher, a dev-server, or a background daemon leaves a process running that
//!    inherited stdout and stderr. Reading those to EOF then waits for a process
//!    the command no longer owns — and no timeout rescues it, because the timeout
//!    wraps the *child* wait and the child already exited successfully.
//! 2. **An inherited stdin that is never closed.** Anything that prompts — `npx`
//!    asking to install a package, `npm init`, `read` in a script, `git` asking
//!    for credentials — blocks on a pipe nothing will ever write to or close. It
//!    does not fail fast on EOF; it hangs until the timeout.
//!
//! These tests need a real shell, so they use `OsExecutionEnv` and are skipped
//! (not failed) where no bash exists.

use std::time::{Duration, Instant};

use evo_tools::{ExecutionErrorCode, OsExecutionEnv, Shell, ShellExecOptions};

fn scratch(tag: &str) -> std::path::PathBuf {
    let tmp = std::env::temp_dir().join(format!("evo-tools-{tag}-{}", std::process::id()));
    let _ = std::fs::create_dir_all(&tmp);
    tmp
}

/// A `sleep` that outlives the command is the minimal shape of `npm run dev &`:
/// the command finished and printed its output, but the inherited pipe stays
/// open, so a reader waiting for EOF waits for the wrong process.
#[tokio::test]
async fn a_grandchild_holding_stdout_does_not_hold_the_call_open() {
    let tmp = scratch("pipe-hold");
    let env = OsExecutionEnv::with_cwd(tmp.clone());
    let started = Instant::now();
    let result = tokio::time::timeout(
        Duration::from_secs(20),
        env.exec("sleep 5 & echo started", ShellExecOptions::default()),
    )
    .await;
    let elapsed = started.elapsed();
    let _ = std::fs::remove_dir_all(&tmp);

    let output = match result {
        Ok(Ok(output)) => output,
        Ok(Err(error)) if error.code == ExecutionErrorCode::ShellUnavailable => return,
        Ok(Err(error)) => panic!("exec failed: {error:?}"),
        Err(_) => panic!("exec never returned: a background child held the stdout pipe"),
    };
    assert!(
        output.stdout.contains("started"),
        "the command's own output must still be captured: {:?}",
        output.stdout
    );
    assert!(
        elapsed < Duration::from_secs(2),
        "waited {elapsed:?} on a process the command did not own (the grandchild's pipe held it open)"
    );
}

/// Already-read partial characters must be finalized even when a descendant
/// keeps both pipes open past the bounded drain grace period.
#[cfg(unix)]
#[tokio::test]
async fn bounded_pipe_drain_flushes_bytes_already_read() {
    let tmp = tempfile::tempdir().unwrap();
    let env = OsExecutionEnv::with_cwd(tmp.path().to_path_buf());
    let normal = match env
        .exec(
            "printf '\\344\\270'; sleep 0.05",
            ShellExecOptions::default(),
        )
        .await
    {
        Ok(output) => output,
        Err(error) if error.code == ExecutionErrorCode::ShellUnavailable => return,
        Err(error) => panic!("exec failed: {error:?}"),
    };
    assert!(!normal.stdout.is_empty());

    let mut stdout_callback = String::new();
    let mut stderr_callback = String::new();
    let started = Instant::now();
    let bounded = tokio::time::timeout(
        Duration::from_secs(1),
        env.exec(
            "printf '\\344\\270'; printf '\\344\\270' >&2; sleep 0.05; sleep 2 &",
            ShellExecOptions {
                on_stdout: Some(Box::new(|chunk| stdout_callback.push_str(chunk))),
                on_stderr: Some(Box::new(|chunk| stderr_callback.push_str(chunk))),
                ..Default::default()
            },
        ),
    )
    .await
    .expect("bounded drain waited for descendant EOF")
    .expect("exec failed");
    assert!(started.elapsed() < Duration::from_secs(1));
    assert_eq!(bounded.stdout, normal.stdout);
    assert_eq!(bounded.stderr, normal.stdout);
    assert_eq!(stdout_callback, bounded.stdout);
    assert_eq!(stderr_callback, bounded.stderr);
}

/// `cat` with no arguments reads stdin and exits at EOF. If stdin is left as an
/// open pipe nothing will ever close, it blocks instead.
#[tokio::test]
async fn a_command_reading_stdin_gets_eof_instead_of_waiting() {
    let tmp = scratch("stdin-eof");
    let env = OsExecutionEnv::with_cwd(tmp.clone());
    let started = Instant::now();
    let result = tokio::time::timeout(
        Duration::from_secs(20),
        env.exec(
            "cat; echo after-cat",
            ShellExecOptions {
                timeout: Some(10.0),
                ..Default::default()
            },
        ),
    )
    .await;
    let elapsed = started.elapsed();
    let _ = std::fs::remove_dir_all(&tmp);

    let output = match result {
        Ok(Ok(output)) => output,
        Ok(Err(error)) if error.code == ExecutionErrorCode::ShellUnavailable => return,
        // Blocking until the timeout is the failure this test exists for: the
        // command never saw EOF, so it never got past `cat`.
        Ok(Err(error)) => panic!("waited on an open stdin, then: {error:?}"),
        Err(_) => panic!("exec never returned: stdin was left open"),
    };
    assert!(
        output.stdout.contains("after-cat"),
        "stdin reached EOF, so the rest of the command ran: {:?}",
        output.stdout
    );
    assert!(
        elapsed < Duration::from_secs(3),
        "waited {elapsed:?} on a stdin that should have been closed"
    );
}

/// Guard for the path above: closing stdin early must not defeat the timeout, and
/// the timeout must still take the whole tree with it.
#[tokio::test]
async fn a_command_that_ignores_the_timeout_is_still_killed() {
    let tmp = scratch("timeout-kill");
    let env = OsExecutionEnv::with_cwd(tmp.clone());
    let started = Instant::now();
    let result = env
        .exec(
            "sleep 30",
            ShellExecOptions {
                timeout: Some(1.0),
                ..Default::default()
            },
        )
        .await;
    let elapsed = started.elapsed();
    let _ = std::fs::remove_dir_all(&tmp);

    match result {
        Err(error) if error.code == ExecutionErrorCode::ShellUnavailable => return,
        Err(error) => assert_eq!(error.code, ExecutionErrorCode::Timeout, "{error:?}"),
        Ok(output) => panic!("a hung command completed: {output:?}"),
    }
    assert!(
        elapsed < Duration::from_secs(5),
        "the timeout took {elapsed:?} to fire"
    );
}

/// Output larger than the pipe buffer (64 KiB on Linux) must be read while the
/// command runs. Waiting for the child before reading deadlocks: the command
/// blocks writing to a full pipe, and the reader waits for it to exit. A broad
/// `rg` over a docs folder is enough to hit it.
#[tokio::test]
async fn output_larger_than_the_pipe_buffer_is_read_while_the_command_runs() {
    let tmp = scratch("pipe-full");
    let env = OsExecutionEnv::with_cwd(tmp.clone());
    let started = Instant::now();
    let result = tokio::time::timeout(
        Duration::from_secs(20),
        env.exec(
            "head -c 300000 /dev/zero | tr '\\0' a; echo; head -c 300000 /dev/zero | tr '\\0' b >&2",
            ShellExecOptions::default(),
        ),
    )
    .await;
    let elapsed = started.elapsed();
    let _ = std::fs::remove_dir_all(&tmp);

    let output = match result {
        Ok(Ok(output)) => output,
        Ok(Err(error)) if error.code == ExecutionErrorCode::ShellUnavailable => return,
        Ok(Err(error)) => panic!("exec failed: {error:?}"),
        Err(_) => panic!("exec never returned: nothing drained the full stdout pipe"),
    };
    assert_eq!(output.stdout.trim_end().len(), 300_000);
    assert_eq!(output.stderr.len(), 300_000);
    assert!(elapsed < Duration::from_secs(5), "took {elapsed:?}");
}
