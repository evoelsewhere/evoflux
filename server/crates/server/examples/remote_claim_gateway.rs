//! Contract-only gateway with one Rust-owned test unit and a real Python sidecar.
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::disallowed_methods)]
use axum::{routing::get, Router};
use evoflux_core::{
    auth::DesktopAuth,
    db::{Db, DbOptions},
};
use evoflux_gateway::{
    routing::RoutingTable,
    supervisor::{PythonConfig, PythonSupervisor},
};
use evoflux_server::{app, handshake};
use std::{path::PathBuf, sync::Arc, time::Duration};

#[tokio::main]
async fn main() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let token = "contract-token".to_owned();
    let secret = "contract-remote-secret".to_owned();
    let env_path = |name| PathBuf::from(std::env::var_os(name).unwrap());
    let sup = Arc::new(
        PythonSupervisor::start(PythonConfig {
            python_bin: env_path("EVOFLUX_GATEWAY_PYTHON_BIN"),
            site_packages: env_path("EVOFLUX_GATEWAY_SITE_PACKAGES"),
            cli_entry: env_path("EVOFLUX_GATEWAY_CLI_ENTRY"),
            desktop_token: Some(token.clone()),
            gateway_secret: "contract-gateway-secret".into(),
            remote_proxy_secret: secret.clone(),
            gateway_port: port,
            disabled_services: vec![],
            env_passthrough: vec![],
            startup_timeout: Duration::from_secs(85),
        })
        .await
        .unwrap(),
    );
    let db_path = env_path("EVOFLUX_DATA_DIR").join("evoflux.db");
    let db = Arc::new(
        tokio::task::spawn_blocking(move || Db::open(&db_path, DbOptions::default()))
            .await
            .unwrap()
            .unwrap(),
    );
    let table = Arc::new(RoutingTable::from_toml("[[unit]]\nname='test-unit'\nowner='rust'\nroutes=['/api/test-claim']\nservices=[]\n[[unit]]\nname='python'\nowner='python'\nroutes=['/**']\nservices=[]\n", None).unwrap());
    let units = Router::new().route(
        "/api/test-claim",
        get(|| async {
            axum::Json(serde_json::json!({"quote": "Contract quote", "author": "Contract author"}))
        }),
    );
    let router = app::router_with_options_and_db(
        table,
        sup,
        DesktopAuth::new(Some(token.clone()), secret),
        units,
        Default::default(),
        Some(db),
    );
    println!(
        "{}",
        handshake::line(port, std::process::id(), Some(&token))
    );
    axum::serve(listener, router).await.unwrap();
}
