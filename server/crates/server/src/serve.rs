//! `evoflux-server serve`: bind the gateway port, start Python behind it, and
//! print the desktop handshake only once Python has given its own (Review
//! Focus 5).
//!
//! Exit codes: 0 after a normal shutdown, 1 for a startup failure or a dead
//! parent, 2 for a usage error (as argparse), 3 when Python never became ready.
//!
//! Python is located from `--python-root` or `EVOFLUX_SIDECAR_ROOT` (the
//! bundled layout of `desktop/src-tauri/src/sidecar.rs`);
//! `EVOFLUX_GATEWAY_PYTHON_BIN`, `EVOFLUX_GATEWAY_SITE_PACKAGES` and
//! `EVOFLUX_GATEWAY_CLI_ENTRY` override each part (development and tests).
//! `EVOFLUX_GATEWAY_STATE_FILE`, when set, receives `{"pid":…,"port":…}` of
//! the current Python child each time it becomes ready (contract tests).

use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use evoflux_core::auth::DesktopAuth;
use evoflux_core::config::Settings;
use evoflux_core::paths::Paths;
use evoflux_core::{telemetry, watchdog};
use evoflux_gateway::proxy::GatewayOptions;
use evoflux_gateway::routing::{openapi_operations, Owner, RoutingTable};
use evoflux_gateway::supervisor::{PythonConfig, PythonSupervisor};
use tokio::io::AsyncWriteExt;
use tokio::sync::watch;
use tokio_util::sync::CancellationToken;

use crate::access_key;
use crate::app;
use crate::cli::{self, Command, ServeArgs};
use crate::handshake;
use crate::parent;
use crate::units::{self, UnitState};

const EXIT_STARTUP: u8 = 1;
const EXIT_USAGE: u8 = 2;
const EXIT_PYTHON_NOT_READY: u8 = 3;

/// Stays under the shell's 90 s first-attempt budget (`desktop/src-tauri/src/main.rs`).
const DEFAULT_PYTHON_WAIT: Duration = Duration::from_secs(85);
const STALL_THRESHOLD: Duration = Duration::from_millis(100);
/// How long open connections (SSE streams) may delay shutdown.
const SHUTDOWN_GRACE: Duration = Duration::from_secs(5);
const ROUTING_TOML: &str = include_str!("../../../routing.toml");
const PYTHON_OPENAPI: &str = include_str!("../../../../contract-tests/openapi/python-v3.1.1.json");

struct Prepared {
    args: ServeArgs,
    python: PythonPaths,
    python_wait: Duration,
    /// Passed to Python and printed in the handshake: generated or `EVOFLUX_DESKTOP_TOKEN`.
    handshake_token: Option<String>,
    /// What Rust-owned routes require (adds `EVOFLUX_ACCESS_KEY` and `settings.yaml`).
    auth_token: Option<String>,
    table: RoutingTable,
    state: UnitState,
    state_file: Option<PathBuf>,
}

struct PythonPaths {
    bin: PathBuf,
    site_packages: PathBuf,
    cli_entry: PathBuf,
}

/// Run the command line (arguments after the program name).
pub fn main(args: impl IntoIterator<Item = OsString>) -> ExitCode {
    let args = match cli::parse(args) {
        Ok(Command::Serve(args)) => args,
        Ok(Command::Help) => {
            println!("{}", cli::USAGE);
            return ExitCode::SUCCESS;
        }
        Err(error) => {
            eprintln!("evoflux-server: {error}");
            return ExitCode::from(EXIT_USAGE);
        }
    };
    let settings = match Settings::from_env() {
        Ok(settings) => settings,
        Err(error) => {
            eprintln!("evoflux-server: {error}");
            return ExitCode::from(EXIT_STARTUP);
        }
    };
    let _telemetry = telemetry::init(&settings);
    let prepared = match prepare(args, &settings) {
        Ok(prepared) => prepared,
        Err(error) => {
            tracing::error!(%error, "server_startup_failed");
            return ExitCode::from(EXIT_STARTUP);
        }
    };
    let runtime = match tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
    {
        Ok(runtime) => runtime,
        Err(error) => {
            tracing::error!(%error, "server_runtime_failed");
            return ExitCode::from(EXIT_STARTUP);
        }
    };
    ExitCode::from(runtime.block_on(run(prepared)))
}

fn env(name: &str) -> Option<String> {
    std::env::var(name).ok()
}

/// Everything that reads files or the environment, done before the runtime starts.
fn prepare(args: ServeArgs, settings: &Settings) -> Result<Prepared, String> {
    let (handshake_token, auth_token) = if args.generate_token {
        let token =
            handshake::generate_token().map_err(|e| format!("cannot generate token: {e}"))?;
        (Some(token.clone()), Some(token))
    } else {
        let desktop = env("EVOFLUX_DESKTOP_TOKEN").filter(|t| !t.is_empty());
        let auth =
            access_key::expected_token(env, &settings.config_dir).map_err(|e| e.to_string())?;
        (desktop, auth)
    };
    let python_wait = match env("EVOFLUX_GATEWAY_PYTHON_WAIT_S") {
        None => DEFAULT_PYTHON_WAIT,
        Some(raw) => raw
            .trim()
            .parse::<f64>()
            .ok()
            .and_then(|s| Duration::try_from_secs_f64(s).ok())
            .ok_or_else(|| format!("EVOFLUX_GATEWAY_PYTHON_WAIT_S must be seconds, got {raw:?}"))?,
    };
    let routing_text = match std::env::var_os("EVOFLUX_GATEWAY_ROUTING") {
        Some(path) => read_text(Path::new(&path))?,
        None => ROUTING_TOML.to_owned(),
    };
    let table = RoutingTable::from_toml(&routing_text, env("EVOFLUX_ROUTE_OVERRIDE").as_deref())
        .map_err(|e| format!("routing table: {e}"))?;
    let operations =
        openapi_operations(PYTHON_OPENAPI).map_err(|e| format!("routing table: {e}"))?;
    table
        .check_shadow_get_only(&operations)
        .map_err(|e| format!("routing table: {e}"))?;
    let python = python_paths(args.python_root.as_deref())?;
    Ok(Prepared {
        args,
        python,
        python_wait,
        handshake_token,
        auth_token,
        table,
        state: UnitState {
            settings: Arc::new(settings.clone()),
            paths: Arc::new(Paths::resolve(settings)),
            db: None,
        },
        state_file: std::env::var_os("EVOFLUX_GATEWAY_STATE_FILE").map(PathBuf::from),
    })
}

/// Startup-only synchronous read, before the async runtime starts.
#[allow(clippy::disallowed_methods)]
fn read_text(path: &Path) -> Result<String, String> {
    std::fs::read_to_string(path).map_err(|e| format!("cannot read {}: {e}", path.display()))
}

fn python_paths(python_root: Option<&Path>) -> Result<PythonPaths, String> {
    let root = python_root
        .map(Path::to_path_buf)
        .or_else(|| std::env::var_os("EVOFLUX_SIDECAR_ROOT").map(PathBuf::from));
    let overridden = |name: &str| std::env::var_os(name).map(PathBuf::from);
    let missing = || {
        "cannot locate Python: pass --python-root or set EVOFLUX_SIDECAR_ROOT \
         (or EVOFLUX_GATEWAY_PYTHON_BIN, EVOFLUX_GATEWAY_SITE_PACKAGES and EVOFLUX_GATEWAY_CLI_ENTRY)"
            .to_owned()
    };
    let site_packages = overridden("EVOFLUX_GATEWAY_SITE_PACKAGES")
        .or_else(|| root.as_ref().map(|r| r.join("site-packages")))
        .ok_or_else(missing)?;
    let cli_entry = overridden("EVOFLUX_GATEWAY_CLI_ENTRY")
        .or_else(|| {
            root.as_ref().map(|r| {
                r.join("site-packages")
                    .join("app")
                    .join("cli")
                    .join("__main__.py")
            })
        })
        .ok_or_else(missing)?;
    let bin = match overridden("EVOFLUX_GATEWAY_PYTHON_BIN") {
        Some(bin) => bin,
        None => bundled_python(root.as_deref().ok_or_else(missing)?)?,
    };
    if !cli_entry.is_file() {
        return Err(format!(
            "python CLI entry missing at {}",
            cli_entry.display()
        ));
    }
    Ok(PythonPaths {
        bin,
        site_packages,
        cli_entry,
    })
}

/// `resolve_python_bin` in `desktop/src-tauri/src/sidecar.rs`.
fn bundled_python(root: &Path) -> Result<PathBuf, String> {
    let python = root.join("python");
    let candidates = if cfg!(windows) {
        [
            python.join("python.exe"),
            python.join("install").join("python.exe"),
        ]
    } else {
        [
            python.join("bin").join("python3"),
            python.join("install").join("bin").join("python3"),
        ]
    };
    candidates
        .into_iter()
        .find(|c| c.is_file())
        .ok_or_else(|| format!("no bundled Python interpreter under {}", python.display()))
}

async fn run(prepared: Prepared) -> u8 {
    let _watchdog = watchdog::spawn(STALL_THRESHOLD);
    let (shutdown_tx, mut shutdown) = watch::channel(false);
    let parent_died = Arc::new(AtomicBool::new(false));
    if let Some(pid) = prepared.args.parent_pid {
        let died = Arc::clone(&parent_died);
        let tx = shutdown_tx.clone();
        let started = parent::spawn(pid, move || {
            died.store(true, Ordering::SeqCst);
            tx.send_replace(true);
        });
        if let Err(error) = started {
            tracing::error!(%error, "parent_watch_failed");
            return EXIT_STARTUP;
        }
    }
    // `shutdown_tx` lives until `run` returns, so a closed channel never reads as a stop.
    tokio::spawn(forward_signals(shutdown_tx.clone()));

    let listener = match tokio::net::TcpListener::bind((
        prepared.args.host.as_str(),
        prepared.args.port,
    ))
    .await
    {
        Ok(listener) => listener,
        Err(error) => {
            tracing::error!(host = %prepared.args.host, port = prepared.args.port, %error, "bind_failed");
            return EXIT_STARTUP;
        }
    };
    let port = match listener.local_addr() {
        Ok(addr) => addr.port(),
        Err(error) => {
            tracing::error!(%error, "bind_failed");
            return EXIT_STARTUP;
        }
    };
    let (gateway_secret, remote_proxy_secret) =
        match (handshake::generate_token(), handshake::generate_token()) {
            (Ok(a), Ok(b)) => (a, b),
            (Err(error), _) | (_, Err(error)) => {
                tracing::error!(%error, "secret_generation_failed");
                return EXIT_STARTUP;
            }
        };
    let cfg = PythonConfig {
        python_bin: prepared.python.bin,
        cli_entry: prepared.python.cli_entry,
        site_packages: prepared.python.site_packages,
        desktop_token: prepared.handshake_token.clone(),
        gateway_secret,
        remote_proxy_secret: remote_proxy_secret.clone(),
        gateway_port: port,
        disabled_services: prepared.table.disabled_python_services(),
        env_passthrough: vec![
            (
                "EVOFLUX_GATEWAY_URL".into(),
                format!("http://127.0.0.1:{port}"),
            ),
            (
                "EVOFLUX_RUST_UNITS".into(),
                prepared
                    .table
                    .units()
                    .iter()
                    .filter(|u| u.owner == Owner::Rust)
                    .map(|u| u.name.as_str())
                    .collect::<Vec<_>>()
                    .join(","),
            ),
        ],
        startup_timeout: prepared.python_wait,
    };
    let sup = tokio::select! {
        started = PythonSupervisor::start(cfg) => match started {
            Ok(sup) => Arc::new(sup),
            Err(error) => {
                // Python's own output already went to stderr as it arrived.
                tracing::error!(%error, "python_not_ready");
                return EXIT_PYTHON_NOT_READY;
            }
        },
        _ = shutdown.wait_for(|stop| *stop) => {
            return exit_code(&parent_died);
        }
    };

    if prepared.args.handshake {
        let line = handshake::line(
            port,
            std::process::id(),
            prepared.handshake_token.as_deref(),
        );
        if let Err(error) = print_line(&line).await {
            tracing::error!(%error, "handshake_write_failed");
        }
    }
    if let Some(path) = prepared.state_file {
        tokio::spawn(write_state(Arc::clone(&sup), path));
    }

    let auth = DesktopAuth::new(prepared.auth_token, remote_proxy_secret);
    let cancel = CancellationToken::new();
    let services = units::start_rust_services(&prepared.table, &prepared.state, cancel.clone());
    let router = router_with_units(
        Arc::new(prepared.table),
        Arc::clone(&sup),
        auth,
        units::router(&prepared.state),
        prepared.state.paths.state_dir.clone(),
    );
    let mut stop = shutdown.clone();
    let server = tokio::spawn(async move {
        axum::serve(listener, router)
            .with_graceful_shutdown(async move {
                let _ = stop.wait_for(|stop| *stop).await;
            })
            .await
    });
    let _ = shutdown.wait_for(|stop| *stop).await;
    match tokio::time::timeout(SHUTDOWN_GRACE, server).await {
        Ok(Ok(Ok(()))) => {}
        Ok(Ok(Err(error))) => tracing::error!(%error, "server_failed"),
        Ok(Err(error)) => tracing::error!(%error, "server_task_failed"),
        Err(_) => tracing::warn!("open connections still busy at shutdown"),
    }
    cancel.cancel();
    for service in services {
        let _ = service.await;
    }
    sup.shutdown().await;
    exit_code(&parent_died)
}

/// Build the same production router with the supplied area routes.
pub fn router_with_units(
    table: Arc<RoutingTable>,
    sup: Arc<PythonSupervisor>,
    auth: DesktopAuth,
    units: axum::Router,
    state_dir: PathBuf,
) -> axum::Router {
    app::router_with_options(table, sup, auth, units, GatewayOptions::from_env(state_dir))
}

fn exit_code(parent_died: &AtomicBool) -> u8 {
    if parent_died.load(Ordering::SeqCst) {
        EXIT_STARTUP
    } else {
        0
    }
}

async fn forward_signals(shutdown: watch::Sender<bool>) {
    #[cfg(unix)]
    {
        use tokio::signal::unix::{signal, SignalKind};
        match signal(SignalKind::terminate()) {
            Ok(mut term) => {
                tokio::select! {
                    _ = tokio::signal::ctrl_c() => {}
                    _ = term.recv() => {}
                }
            }
            Err(_) => {
                let _ = tokio::signal::ctrl_c().await;
            }
        }
    }
    #[cfg(not(unix))]
    {
        if tokio::signal::ctrl_c().await.is_err() {
            return;
        }
    }
    shutdown.send_replace(true);
}

async fn print_line(line: &str) -> std::io::Result<()> {
    let mut stdout = tokio::io::stdout();
    stdout.write_all(line.as_bytes()).await?;
    stdout.write_all(b"\n").await?;
    stdout.flush().await
}

async fn write_state(sup: Arc<PythonSupervisor>, path: PathBuf) {
    let mut updates = sup.subscribe();
    loop {
        let current = *updates.borrow_and_update();
        if let Some(up) = current {
            let json = format!("{{\"pid\":{},\"port\":{}}}", up.pid, up.addr.port());
            if let Err(error) = tokio::fs::write(&path, json).await {
                tracing::warn!(%error, "state_file_write_failed");
            }
        }
        if updates.changed().await.is_err() {
            return;
        }
    }
}
