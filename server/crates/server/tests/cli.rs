//! The `evoflux-server` binary: handshake, Python wait, parent watch and the
//! settings it must honour before it starts.
#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing,
    clippy::disallowed_methods
)]

mod common;

use common::*;
use std::process::Stdio;
use std::time::{Duration, Instant};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, BufReader};

#[tokio::test(flavor = "multi_thread")]
async fn handshake_line_exact() {
    let home = tempfile::tempdir().unwrap();
    let mut server = spawn_server(&home, &fake_upstream(), &["--generate-token"], &[]);
    let line = first_stdout_line(&mut server, Duration::from_secs(60)).await;
    let pattern = regex::Regex::new(
        r#"^EVOFLUX_HANDSHAKE \{"port":\d+,"pid":\d+,"version":"[^"]+","token":"[^"]+"\}$"#,
    )
    .unwrap();
    assert!(pattern.is_match(&line), "unexpected handshake: {line:?}");
    let json: serde_json::Value =
        serde_json::from_str(line.strip_prefix("EVOFLUX_HANDSHAKE ").unwrap()).unwrap();
    assert_eq!(json["version"], app_version());
    assert_eq!(json["pid"], server.id().unwrap());
    // Python's `secrets.token_urlsafe(32)`: 43 URL-safe characters.
    let token = json["token"].as_str().unwrap();
    assert_eq!(token.len(), 43);
    assert!(token
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_'));
    stop(server).await;
}

#[tokio::test(flavor = "multi_thread")]
async fn handshake_waits_for_python() {
    let home = tempfile::tempdir().unwrap();
    let start = Instant::now();
    let mut server = spawn_server(
        &home,
        &tests_dir().join("slow_python.py"),
        &[],
        &[("EVOFLUX_TEST_HANDSHAKE_DELAY_S", "3")],
    );
    let line = first_stdout_line(&mut server, Duration::from_secs(60)).await;
    assert!(line.starts_with("EVOFLUX_HANDSHAKE "), "{line:?}");
    assert!(
        start.elapsed() >= Duration::from_secs(3),
        "handshake after {:?}, before Python's",
        start.elapsed()
    );
    stop(server).await;
}

#[tokio::test(flavor = "multi_thread")]
async fn python_never_ready_exits_with_log_tail() {
    let home = tempfile::tempdir().unwrap();
    let start = Instant::now();
    let mut server = spawn_server(
        &home,
        &tests_dir().join("never_ready.py"),
        &[],
        &[("EVOFLUX_GATEWAY_PYTHON_WAIT_S", "2")],
    );
    let (status, stdout, stderr) = wait_output(&mut server, Duration::from_secs(30)).await;
    assert_eq!(status.code(), Some(3), "stderr: {stderr}");
    assert!(!stdout.contains("EVOFLUX_HANDSHAKE"), "stdout: {stdout}");
    assert!(
        stderr.contains("never_ready last log line"),
        "stderr: {stderr}"
    );
    assert!(start.elapsed() < Duration::from_secs(20));
}

#[tokio::test(flavor = "multi_thread")]
async fn parent_death_exits() {
    let home = tempfile::tempdir().unwrap();
    let mut parent = tokio::process::Command::new(python())
        .args(["-c", "import time; time.sleep(120)"])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .kill_on_drop(true)
        .spawn()
        .unwrap();
    let parent_pid = parent.id().unwrap().to_string();
    let mut server = spawn_server(
        &home,
        &fake_upstream(),
        &["--generate-token", "--parent-pid", &parent_pid],
        &[],
    );
    first_stdout_line(&mut server, Duration::from_secs(60)).await;
    parent.kill().await.unwrap();
    let killed = Instant::now();
    let status = tokio::time::timeout(Duration::from_secs(20), server.wait())
        .await
        .expect("server outlived its parent")
        .unwrap();
    assert!(!status.success(), "{status}");
    assert!(killed.elapsed() < Duration::from_secs(20));
}

#[tokio::test(flavor = "multi_thread")]
async fn unreadable_settings_yaml_refuses_to_start() {
    let home = tempfile::tempdir().unwrap();
    let config = home.path().join("config");
    std::fs::create_dir_all(&config).unwrap();
    std::fs::write(config.join("settings.yaml"), "server: [access_key\n").unwrap();
    let mut server = spawn_server(&home, &fake_upstream(), &[], &[]);
    let (status, stdout, stderr) = wait_output(&mut server, Duration::from_secs(30)).await;
    assert_eq!(status.code(), Some(1), "stderr: {stderr}");
    assert!(!stdout.contains("EVOFLUX_HANDSHAKE"), "stdout: {stdout}");
    assert!(stderr.contains("settings.yaml"), "stderr: {stderr}");
}

#[tokio::test(flavor = "multi_thread")]
async fn settings_access_key_protects_rust_routes() {
    let home = tempfile::tempdir().unwrap();
    let config = home.path().join("config");
    std::fs::create_dir_all(&config).unwrap();
    std::fs::write(config.join("settings.yaml"), "server:\n  access_key: k\n").unwrap();
    let mut server = spawn_server(&home, &fake_upstream(), &[], &[]);
    let handshake = handshake_json(&mut server).await;
    // Python's handshake carries only a generated or EVOFLUX_DESKTOP_TOKEN token.
    assert_eq!(handshake["token"], "");
    let port = handshake["port"].as_u64().unwrap();
    // `/metrics/gateway` is exempt from desktop auth (non-API path, as Python's
    // `/metrics`), so the token wiring is proven on an `/api` route.
    let (status, _) = http_get(port, "/api/gateway/ping", &[]).await;
    assert_eq!(status, 401);
    let (status, _) = http_get(
        port,
        "/api/gateway/ping",
        &[("Authorization", "Bearer wrong")],
    )
    .await;
    assert_eq!(status, 401);
    let (status, body) =
        http_get(port, "/api/gateway/ping", &[("Authorization", "Bearer k")]).await;
    assert_eq!(status, 200, "{body}");
    stop(server).await;
}

#[tokio::test(flavor = "multi_thread")]
async fn gateway_metrics_are_served_by_rust() {
    let home = tempfile::tempdir().unwrap();
    let mut server = spawn_server(&home, &fake_upstream(), &[], &[]);
    let handshake = handshake_json(&mut server).await;
    let port = handshake["port"].as_u64().unwrap();
    let (status, body) = http_get(port, "/metrics/gateway", &[]).await;
    // The fake upstream answers 404 for every path it does not know.
    assert_eq!(status, 200, "{body}");
    stop(server).await;
}

#[tokio::test(flavor = "multi_thread")]
async fn unknown_argument_is_a_usage_error() {
    let home = tempfile::tempdir().unwrap();
    let mut server = spawn_server(&home, &fake_upstream(), &["--bogus"], &[]);
    let (status, _, stderr) = wait_output(&mut server, Duration::from_secs(30)).await;
    assert_eq!(status.code(), Some(2), "stderr: {stderr}");
    assert!(stderr.contains("--bogus"), "stderr: {stderr}");
}

async fn handshake_json(server: &mut tokio::process::Child) -> serde_json::Value {
    let line = first_stdout_line(server, Duration::from_secs(60)).await;
    serde_json::from_str(line.strip_prefix("EVOFLUX_HANDSHAKE ").unwrap()).unwrap()
}

async fn wait_output(
    server: &mut tokio::process::Child,
    limit: Duration,
) -> (std::process::ExitStatus, String, String) {
    let mut stdout = server.stdout.take().unwrap();
    let mut stderr = server.stderr.take().unwrap();
    let (mut out, mut err) = (String::new(), String::new());
    let collected = tokio::time::timeout(limit, async {
        let (a, b) = tokio::join!(
            stdout.read_to_string(&mut out),
            stderr.read_to_string(&mut err)
        );
        a.unwrap();
        b.unwrap();
        server.wait().await.unwrap()
    })
    .await;
    match collected {
        Ok(status) => (status, out, err),
        Err(_) => {
            let _ = server.kill().await;
            panic!("server still running after {limit:?}");
        }
    }
}

async fn first_stdout_line(server: &mut tokio::process::Child, limit: Duration) -> String {
    let stdout = server.stdout.take().unwrap();
    let mut lines = BufReader::new(stdout).lines();
    let line = tokio::time::timeout(limit, lines.next_line())
        .await
        .expect("no stdout line in time")
        .unwrap()
        .expect("stdout closed before the handshake");
    // Keep draining so the server never blocks on a full pipe.
    tokio::spawn(async move { while let Ok(Some(_)) = lines.next_line().await {} });
    if let Some(stderr) = server.stderr.take() {
        tokio::spawn(async move {
            let mut lines = BufReader::new(stderr).lines();
            while let Ok(Some(_)) = lines.next_line().await {}
        });
    }
    line
}
