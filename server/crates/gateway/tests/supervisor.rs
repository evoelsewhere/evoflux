#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing
)]

mod common;

use common::*;
use evoflux_gateway::supervisor::{PythonSupervisor, SupervisorError};
use std::process::Stdio;
use std::time::{Duration, Instant};
use tokio::io::{AsyncBufReadExt, BufReader};

#[tokio::test(flavor = "multi_thread")]
async fn passes_the_gateway_mode_environment() {
    let cfg = fake_config(4321, vec!["scheduler".into(), "dream_scheduler".into()]);
    let sup = PythonSupervisor::start(cfg).await.unwrap();
    let addr = sup.upstream().unwrap();
    let request = hyper::Request::get(format!("http://{addr}/fake/env"))
        .header("x-evoflux-gateway", SECRET)
        .body(axum::body::Body::empty())
        .unwrap();
    let response = client().request(request).await.unwrap();
    let body = http_body_util::BodyExt::collect(response.into_body())
        .await
        .unwrap()
        .to_bytes();
    let env: serde_json::Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(env["EVOFLUX_GATEWAY_SECRET"], SECRET);
    assert_eq!(env["EVOFLUX_REMOTE_PROXY_SECRET"], "test-remote-secret");
    assert_eq!(env["EVOFLUX_TSNET_TARGET_PORT"], "4321");
    assert_eq!(env["EVOFLUX_DISABLE_SERVICES"], "scheduler,dream_scheduler");
    assert_eq!(env["EVOFLUX_DESKTOP_TOKEN"], "test-desktop-token");
    assert_eq!(env["EVOFLUX_TEST_PASSTHROUGH"], "yes");
    assert!(sup.log_tail().iter().any(|l| l == "fake_upstream starting"));
    sup.shutdown().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn direct_python_access_rejected() {
    let sup = PythonSupervisor::start(fake_config(1, vec![]))
        .await
        .unwrap();
    let addr = sup.upstream().unwrap();
    let (status, _) = get(&client(), format!("http://{addr}/fake/headers")).await;
    assert_eq!(status, 403);
    sup.shutdown().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn missing_handshake_times_out_with_log_tail() {
    let mut cfg = fake_config(1, vec![]);
    // The interpreter itself prints a line and never a handshake.
    cfg.cli_entry = repo_root().join("server/crates/gateway/tests/no_handshake.py");
    cfg.startup_timeout = Duration::from_secs(2);
    let start = Instant::now();
    match PythonSupervisor::start(cfg).await {
        Err(SupervisorError::HandshakeTimeout(limit)) => assert_eq!(limit, Duration::from_secs(2)),
        Err(other) => panic!("expected a timeout, got {other}"),
        Ok(_) => panic!("expected a timeout"),
    }
    assert!(start.elapsed() < Duration::from_secs(10));
}

#[tokio::test(flavor = "multi_thread")]
async fn restart_limit_is_three_per_five_minutes() {
    let sup = PythonSupervisor::start(fake_config(1, vec![]))
        .await
        .unwrap();
    let mut updates = sup.subscribe();
    let backoffs = [1, 4, 10];
    for expected in backoffs {
        let pid = updates.borrow_and_update().unwrap().pid;
        kill_pid(pid).await;
        let down_at = Instant::now();
        let next = loop {
            updates.changed().await.unwrap();
            if let Some(up) = *updates.borrow_and_update() {
                break up;
            }
        };
        assert_ne!(next.pid, pid);
        let waited = down_at.elapsed();
        assert!(
            waited >= Duration::from_secs(expected) && waited < Duration::from_secs(expected + 10),
            "restart after {waited:?}, backoff {expected}s"
        );
    }
    let pid = updates.borrow_and_update().unwrap().pid;
    kill_pid(pid).await;
    tokio::time::sleep(Duration::from_secs(12)).await;
    assert!(sup.upstream().is_none(), "a fourth restart happened");
    sup.shutdown().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn test_kill_gateway_kills_python_tree() {
    let mut gateway = tokio::process::Command::new(env!("CARGO_BIN_EXE_evoflux-gateway-harness"))
        .args(["serve", "--port", "0", "--handshake", "--generate-token"])
        .env("EVOFLUX_GATEWAY_PYTHON_BIN", python())
        .env("EVOFLUX_GATEWAY_CLI_ENTRY", fake_upstream())
        .env(
            "EVOFLUX_GATEWAY_SITE_PACKAGES",
            fake_upstream().parent().unwrap(),
        )
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .kill_on_drop(true)
        .spawn()
        .unwrap();
    let mut lines = BufReader::new(gateway.stdout.take().unwrap()).lines();
    let (mut python_pid, mut gateway_port) = (None, None);
    while python_pid.is_none() || gateway_port.is_none() {
        let line = tokio::time::timeout(Duration::from_secs(30), lines.next_line())
            .await
            .unwrap()
            .unwrap()
            .expect("harness exited");
        if let Some(json) = line.strip_prefix("EVOFLUX_GATEWAY_PYTHON ") {
            let v: serde_json::Value = serde_json::from_str(json).unwrap();
            python_pid = v["pid"].as_u64().map(|p| p as u32);
        } else if let Some(json) = line.strip_prefix("EVOFLUX_HANDSHAKE ") {
            let v: serde_json::Value = serde_json::from_str(json).unwrap();
            gateway_port = v["port"].as_u64();
        }
    }
    let (python_pid, port) = (python_pid.unwrap(), gateway_port.unwrap());
    let child = get_json(&client(), format!("http://127.0.0.1:{port}/fake/child")).await;
    let child_pid = child["pid"].as_u64().unwrap() as u32;
    assert!(pid_alive(python_pid).await && pid_alive(child_pid).await);

    gateway.start_kill().unwrap(); // TerminateProcess / SIGKILL: no cleanup code runs
    gateway.wait().await.unwrap();
    let gone = eventually(Duration::from_secs(5), "python tree gone", || async move {
        !pid_alive(python_pid).await && !pid_alive(child_pid).await
    })
    .await;
    assert!(gone < Duration::from_secs(5));
}
