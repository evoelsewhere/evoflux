//! Test harness for the gateway; not shipped. `evoflux-server` (Task 11) is
//! the product binary.
//!
//! `evoflux-gateway-harness serve [--host H] [--port P] [--handshake]
//! [--generate-token] [--parent-pid N]` binds the gateway port, starts Python
//! through [`PythonSupervisor`] and prints the desktop handshake. Each time
//! Python becomes ready it also prints `EVOFLUX_GATEWAY_PYTHON {"pid":…,"port":…}`
//! (and writes that JSON to `EVOFLUX_GATEWAY_STATE_FILE` when set) so tests
//! can reach or kill the child. Python is located by
//! `EVOFLUX_GATEWAY_PYTHON_BIN`, `EVOFLUX_GATEWAY_SITE_PACKAGES` and
//! `EVOFLUX_GATEWAY_CLI_ENTRY`; the routing table by `EVOFLUX_GATEWAY_ROUTING`
//! (default: the repository's `server/routing.toml`).

use evoflux_gateway::proxy;
use evoflux_gateway::routing::RoutingTable;
use evoflux_gateway::supervisor::{PythonConfig, PythonSupervisor};
use std::collections::hash_map::RandomState;
use std::hash::{BuildHasher, Hasher};
use std::path::PathBuf;
use std::process::ExitCode;
use std::sync::Arc;
use std::time::Duration;
use tokio::io::AsyncWriteExt;

struct Args {
    host: String,
    port: u16,
    handshake: bool,
    generate_token: bool,
}

fn parse_args() -> Result<Args, String> {
    let mut args = std::env::args().skip(1);
    if args.next().as_deref() != Some("serve") {
        return Err("usage: evoflux-gateway-harness serve [options]".to_owned());
    }
    let mut parsed = Args {
        host: "127.0.0.1".to_owned(),
        port: 0,
        handshake: false,
        generate_token: false,
    };
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--host" => parsed.host = args.next().ok_or("--host needs a value")?,
            "--port" => {
                let raw = args.next().ok_or("--port needs a value")?;
                parsed.port = raw.parse().map_err(|_| format!("bad --port {raw:?}"))?;
            }
            "--handshake" => parsed.handshake = true,
            "--generate-token" => parsed.generate_token = true,
            // Python's own parent watch is not mirrored here; the harness is
            // stopped by its test, and the Job Object / reaper covers Python.
            "--parent-pid" => {
                args.next().ok_or("--parent-pid needs a value")?;
            }
            other => return Err(format!("unknown argument {other:?}")),
        }
    }
    Ok(parsed)
}

/// Test-grade randomness: std's per-process random hash keys. Not for production secrets.
fn random_hex() -> String {
    (0..4)
        .map(|i| {
            let mut hasher = RandomState::new().build_hasher();
            hasher.write_u64(i);
            hasher.write_u128(
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .map_or(0, |d| d.as_nanos()),
            );
            format!("{:016x}", hasher.finish())
        })
        .collect()
}

fn env_path(name: &str) -> Result<PathBuf, String> {
    std::env::var_os(name)
        .map(PathBuf::from)
        .ok_or_else(|| format!("{name} is not set"))
}

async fn print_stdout(line: String) {
    let mut stdout = tokio::io::stdout();
    let _ = stdout.write_all(line.as_bytes()).await;
    let _ = stdout.write_all(b"\n").await;
    let _ = stdout.flush().await;
}

async fn run() -> Result<(), String> {
    let args = parse_args()?;
    let routing = std::env::var_os("EVOFLUX_GATEWAY_ROUTING")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../routing.toml"));
    let override_env = std::env::var("EVOFLUX_ROUTE_OVERRIDE").ok();
    let table = RoutingTable::load(&routing, override_env.as_deref()).map_err(|e| e.to_string())?;
    // A shadow unit must not own a path with a non-GET operation.
    let openapi = std::env::var_os("EVOFLUX_GATEWAY_OPENAPI")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../../../contract-tests/openapi/python-v3.1.1.json")
        });
    let openapi = tokio::fs::read_to_string(&openapi)
        .await
        .map_err(|e| format!("cannot read {}: {e}", openapi.display()))?;
    let operations =
        evoflux_gateway::routing::openapi_operations(&openapi).map_err(|e| e.to_string())?;
    table
        .check_shadow_get_only(&operations)
        .map_err(|e| e.to_string())?;

    let token = if args.generate_token {
        Some(random_hex())
    } else {
        std::env::var("EVOFLUX_DESKTOP_TOKEN")
            .ok()
            .filter(|t| !t.is_empty())
    };
    let listener = tokio::net::TcpListener::bind((args.host.as_str(), args.port))
        .await
        .map_err(|e| format!("cannot bind {}:{}: {e}", args.host, args.port))?;
    let port = listener.local_addr().map_err(|e| e.to_string())?.port();

    let cfg = PythonConfig {
        python_bin: env_path("EVOFLUX_GATEWAY_PYTHON_BIN")?,
        cli_entry: env_path("EVOFLUX_GATEWAY_CLI_ENTRY")?,
        site_packages: env_path("EVOFLUX_GATEWAY_SITE_PACKAGES")?,
        desktop_token: token.clone(),
        gateway_secret: random_hex(),
        remote_proxy_secret: random_hex(),
        gateway_port: port,
        disabled_services: table.disabled_python_services(),
        env_passthrough: Vec::new(),
        startup_timeout: Duration::from_secs(85),
    };
    let sup = Arc::new(
        PythonSupervisor::start(cfg)
            .await
            .map_err(|e| e.to_string())?,
    );

    if args.handshake {
        let payload = serde_json::json!({
            "port": port,
            "pid": std::process::id(),
            "version": env!("CARGO_PKG_VERSION"),
            "token": token.unwrap_or_default(),
        });
        print_stdout(format!("EVOFLUX_HANDSHAKE {payload}")).await;
    }

    let mut updates = sup.subscribe();
    let state_file = std::env::var_os("EVOFLUX_GATEWAY_STATE_FILE").map(PathBuf::from);
    tokio::spawn(async move {
        loop {
            let current = *updates.borrow_and_update();
            if let Some(up) = current {
                let json = format!("{{\"pid\":{},\"port\":{}}}", up.pid, up.addr.port());
                if let Some(path) = &state_file {
                    let _ = tokio::fs::write(path, &json).await;
                }
                print_stdout(format!("EVOFLUX_GATEWAY_PYTHON {json}")).await;
            }
            if updates.changed().await.is_err() {
                return;
            }
        }
    });
    // `EVOFLUX_GATEWAY_STATE_DIR` enables shadow comparison for `shadow` units;
    // `EVOFLUX_GATEWAY_RECORD_DIR` records traffic.
    let options = match std::env::var_os("EVOFLUX_GATEWAY_STATE_DIR") {
        Some(dir) => proxy::GatewayOptions::from_env(PathBuf::from(dir)),
        None => proxy::GatewayOptions {
            shadow: None,
            recorder: evoflux_gateway::record::Recorder::from_env().map(Arc::new),
        },
    };
    let app = proxy::router_with(
        Arc::new(table),
        Arc::clone(&sup),
        axum::Router::new(),
        options,
    );
    let served = axum::serve(listener, app)
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await;
    sup.shutdown().await;
    served.map_err(|e| e.to_string())
}

#[tokio::main]
async fn main() -> ExitCode {
    tracing_subscriber::fmt()
        .with_writer(std::io::stderr)
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_env("EVOFLUX_GATEWAY_LOG")
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();
    match run().await {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            tracing::error!(%error, "gateway_harness_failed");
            ExitCode::from(3)
        }
    }
}
