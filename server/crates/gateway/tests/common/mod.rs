//! Shared helpers: a Python interpreter, the fake upstream and a served gateway.
#![allow(
    dead_code,
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing
)]

use axum::body::Body;
use evoflux_gateway::proxy;
use evoflux_gateway::routing::RoutingTable;
use evoflux_gateway::supervisor::{PythonConfig, PythonSupervisor};
use http_body_util::BodyExt;
use hyper_util::client::legacy::Client;
use hyper_util::rt::TokioExecutor;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, Instant};

pub const SECRET: &str = "test-gateway-secret";

pub fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

pub fn fake_upstream() -> PathBuf {
    repo_root().join("contract-tests/gateway/fake_upstream.py")
}

/// `EVOFLUX_TEST_PYTHON`, else the repository venv, else `python3`/`python` on PATH.
pub fn python() -> PathBuf {
    if let Some(path) = std::env::var_os("EVOFLUX_TEST_PYTHON") {
        return PathBuf::from(path);
    }
    let venv = if cfg!(windows) {
        repo_root().join(".venv/Scripts/python.exe")
    } else {
        repo_root().join(".venv/bin/python")
    };
    if venv.is_file() {
        return venv;
    }
    PathBuf::from(if cfg!(windows) { "python" } else { "python3" })
}

pub fn fake_config(gateway_port: u16, disabled: Vec<String>) -> PythonConfig {
    let entry = fake_upstream();
    PythonConfig {
        python_bin: python(),
        site_packages: entry.parent().unwrap().to_path_buf(),
        cli_entry: entry,
        desktop_token: Some("test-desktop-token".to_owned()),
        gateway_secret: SECRET.to_owned(),
        remote_proxy_secret: "test-remote-secret".to_owned(),
        gateway_port,
        disabled_services: disabled,
        env_passthrough: vec![("EVOFLUX_TEST_PASSTHROUGH".to_owned(), "yes".to_owned())],
        startup_timeout: Duration::from_secs(30),
    }
}

pub struct Gateway {
    pub addr: SocketAddr,
    pub sup: Arc<PythonSupervisor>,
}

/// Serve the gateway router in front of the fake upstream.
pub async fn serve(table: RoutingTable, rust_routes: axum::Router) -> Gateway {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let cfg = fake_config(addr.port(), table.disabled_python_services());
    let sup = Arc::new(PythonSupervisor::start(cfg).await.unwrap());
    let app = proxy::router(Arc::new(table), Arc::clone(&sup), rust_routes);
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    Gateway { addr, sup }
}

pub fn python_only() -> RoutingTable {
    RoutingTable::from_toml(
        r#"
[[unit]]
name = "web"
owner = "python"
routes = ["/**"]
services = []
"#,
        None,
    )
    .unwrap()
}

pub type HttpClient = Client<hyper_util::client::legacy::connect::HttpConnector, Body>;

pub fn client() -> HttpClient {
    Client::builder(TokioExecutor::new()).build_http()
}

pub async fn get(client: &HttpClient, url: String) -> (u16, Vec<u8>) {
    let response = client.get(url.parse().unwrap()).await.unwrap();
    let status = response.status().as_u16();
    let body = response
        .into_body()
        .collect()
        .await
        .unwrap()
        .to_bytes()
        .to_vec();
    (status, body)
}

pub async fn get_json(client: &HttpClient, url: String) -> serde_json::Value {
    let (status, body) = get(client, url).await;
    assert_eq!(status, 200, "{}", String::from_utf8_lossy(&body));
    serde_json::from_slice(&body).unwrap()
}

/// Kill one process hard (`taskkill /F` or `kill -9`), not its tree.
pub async fn kill_pid(pid: u32) {
    let status = if cfg!(windows) {
        tokio::process::Command::new("taskkill")
            .args(["/F", "/PID", &pid.to_string()])
            .output()
            .await
    } else {
        tokio::process::Command::new("kill")
            .args(["-9", &pid.to_string()])
            .output()
            .await
    };
    assert!(status.unwrap().status.success(), "could not kill {pid}");
}

pub async fn pid_alive(pid: u32) -> bool {
    if cfg!(windows) {
        let out = tokio::process::Command::new("tasklist")
            .args(["/FI", &format!("PID eq {pid}"), "/FO", "CSV", "/NH"])
            .output()
            .await
            .unwrap();
        String::from_utf8_lossy(&out.stdout).contains(&format!("\"{pid}\""))
    } else {
        tokio::process::Command::new("kill")
            .args(["-0", &pid.to_string()])
            .output()
            .await
            .unwrap()
            .status
            .success()
    }
}

/// Wait until `check` holds, polling every 100 ms, or panic after `limit`.
pub async fn eventually<F, Fut>(limit: Duration, what: &str, mut check: F) -> Duration
where
    F: FnMut() -> Fut,
    Fut: std::future::Future<Output = bool>,
{
    let start = Instant::now();
    loop {
        if check().await {
            return start.elapsed();
        }
        assert!(start.elapsed() < limit, "{what} not within {limit:?}");
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
}
