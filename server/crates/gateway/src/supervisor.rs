//! Supervises the Python sidecar behind the gateway (design §3, Review Focus 1 and 4).
//!
//! Python is started with the bootstrap of `desktop/src-tauri/src/sidecar.rs`
//! (`python -c <bootstrap> <site-packages> <cli entry> serve --host 127.0.0.1
//! --port 0 --handshake`) plus the gateway-mode environment of
//! `app/core/gateway_mode.py`. Its process tree lives in a Job Object with
//! kill-on-close (Windows) or its own process group (POSIX), so it cannot
//! outlive the gateway. When Python exits on its own it is restarted, at most
//! three times in five minutes, after 1 s, 4 s and 10 s.

use process_wrap::tokio::{ChildWrapper, CommandWrap};
use serde::Deserialize;
use std::any::Any;
use std::collections::VecDeque;
use std::net::{Ipv4Addr, SocketAddr};
use std::path::PathBuf;
use std::process::{ExitStatus, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tokio::io::{AsyncBufReadExt, AsyncRead, AsyncWriteExt, BufReader};
use tokio::sync::watch;
use tokio::task::JoinHandle;

const HANDSHAKE_PREFIX: &str = "EVOFLUX_HANDSHAKE ";
const SHUTDOWN_GRACE: Duration = Duration::from_secs(5);
const RESTART_WINDOW: Duration = Duration::from_secs(5 * 60);
const RESTART_BACKOFF: [Duration; 3] = [
    Duration::from_secs(1),
    Duration::from_secs(4),
    Duration::from_secs(10),
];
const LOG_TAIL_LINES: usize = 200;

/// `sidecar.rs`: puts site-packages on `sys.path` from inside the child, so
/// `PYTHONPATH` never leaks into processes the agent spawns.
const BOOTSTRAP: &str = "import sys, runpy, site; \
     _site = sys.argv.pop(1); \
     _entry = sys.argv.pop(1); \
     site.addsitedir(_site); \
     sys.argv[0] = _entry; \
     runpy.run_path(_entry, run_name='__main__')";

/// How to start Python and what to tell it (T6's environment contract).
#[derive(Debug, Clone)]
pub struct PythonConfig {
    pub python_bin: PathBuf,
    pub cli_entry: PathBuf,
    pub site_packages: PathBuf,
    /// `EVOFLUX_DESKTOP_TOKEN`; Python stays the auth authority for its routes.
    pub desktop_token: Option<String>,
    /// `EVOFLUX_GATEWAY_SECRET`, sent back as `X-EvoFlux-Gateway` on every proxied request.
    pub gateway_secret: String,
    /// `EVOFLUX_REMOTE_PROXY_SECRET`.
    pub remote_proxy_secret: String,
    /// The gateway's own port (`EVOFLUX_TSNET_TARGET_PORT`).
    pub gateway_port: u16,
    /// `EVOFLUX_DISABLE_SERVICES`, from `RoutingTable::disabled_python_services`.
    pub disabled_services: Vec<String>,
    /// Extra variables set on the child on top of the inherited environment.
    pub env_passthrough: Vec<(String, String)>,
    /// How long to wait for Python's handshake (Task 11 uses 85 s on first start).
    pub startup_timeout: Duration,
}

#[derive(Debug, thiserror::Error)]
pub enum SupervisorError {
    #[error("cannot start {bin}: {source}")]
    Spawn { bin: String, source: std::io::Error },
    #[error("python exited before its handshake ({status})")]
    Exited { status: String },
    #[error("python gave no handshake within {0:?}")]
    HandshakeTimeout(Duration),
    #[error("invalid python handshake line: {0}")]
    BadHandshake(String),
}

/// The live Python sidecar: where to reach it and its interpreter pid.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Upstream {
    pub addr: SocketAddr,
    pub pid: u32,
}

#[derive(Debug, Deserialize)]
struct Handshake {
    port: u16,
    pid: u32,
}

/// Owns the Python child, its restarts and its shutdown.
pub struct PythonSupervisor {
    shared: Arc<Shared>,
    stop: watch::Sender<bool>,
    monitor: Mutex<Option<JoinHandle<()>>>,
}

struct Shared {
    cfg: PythonConfig,
    upstream: watch::Sender<Option<Upstream>>,
    log: Mutex<VecDeque<String>>,
}

impl PythonSupervisor {
    /// Start Python and wait for its handshake; the restart monitor then runs
    /// in the background until [`PythonSupervisor::shutdown`].
    pub async fn start(cfg: PythonConfig) -> Result<Self, SupervisorError> {
        let shared = Arc::new(Shared {
            cfg,
            upstream: watch::Sender::new(None),
            log: Mutex::new(VecDeque::with_capacity(LOG_TAIL_LINES)),
        });
        let instance = Instance::spawn(&shared).await?;
        shared.upstream.send_replace(Some(instance.upstream));
        let (stop, stop_rx) = watch::channel(false);
        let monitor = tokio::spawn(monitor(Arc::clone(&shared), instance, stop_rx));
        Ok(Self {
            shared,
            stop,
            monitor: Mutex::new(Some(monitor)),
        })
    }

    /// Python's address, or `None` while it is down or restarting.
    pub fn upstream(&self) -> Option<SocketAddr> {
        self.shared.upstream.borrow().map(|u| u.addr)
    }

    /// Python's address and pid as they change (`None` while down).
    pub fn subscribe(&self) -> watch::Receiver<Option<Upstream>> {
        self.shared.upstream.subscribe()
    }

    pub fn gateway_secret(&self) -> &str {
        &self.shared.cfg.gateway_secret
    }

    /// The last lines Python wrote to stdout and stderr.
    pub fn log_tail(&self) -> Vec<String> {
        self.shared.log_tail()
    }

    /// Stop Python: SIGTERM and a 5 s grace on POSIX, an immediate job
    /// termination on Windows (as `sidecar.rs` does), then kill the tree.
    pub async fn shutdown(&self) {
        self.stop.send_replace(true);
        let handle = self.monitor.lock().ok().and_then(|mut slot| slot.take());
        if let Some(handle) = handle {
            if let Err(error) = handle.await {
                tracing::warn!(%error, "python_monitor_failed");
            }
        }
    }
}

impl Shared {
    fn push_log(&self, line: String) {
        if let Ok(mut log) = self.log.lock() {
            if log.len() == LOG_TAIL_LINES {
                log.pop_front();
            }
            log.push_back(line);
        }
    }

    fn log_tail(&self) -> Vec<String> {
        self.log
            .lock()
            .map(|log| log.iter().cloned().collect())
            .unwrap_or_default()
    }
}

async fn monitor(shared: Arc<Shared>, first: Instance, mut stop: watch::Receiver<bool>) {
    let mut current = Some(first);
    let mut restarts: VecDeque<Instant> = VecDeque::new();
    loop {
        if let Some(mut instance) = current.take() {
            tokio::select! {
                status = instance.wait_python() => {
                    shared.upstream.send_replace(None);
                    let status = status.map_or_else(|e| e.to_string(), |s| s.to_string());
                    tracing::warn!(pid = instance.upstream.pid, %status, "python_exited");
                    instance.kill_tree().await;
                }
                () = stopped(&mut stop) => {
                    shared.upstream.send_replace(None);
                    instance.stop().await;
                    return;
                }
            }
        }
        let now = Instant::now();
        while restarts
            .front()
            .is_some_and(|at| now.duration_since(*at) > RESTART_WINDOW)
        {
            restarts.pop_front();
        }
        let Some(backoff) = RESTART_BACKOFF.get(restarts.len()).copied() else {
            tracing::error!(
                restarts = restarts.len(),
                "python_restart_limit_reached; backend stays unavailable"
            );
            return;
        };
        tokio::select! {
            () = tokio::time::sleep(backoff) => {}
            () = stopped(&mut stop) => return,
        }
        restarts.push_back(Instant::now());
        tracing::info!(attempt = restarts.len(), "python_restarting");
        tokio::select! {
            spawned = Instance::spawn(&shared) => match spawned {
                Ok(instance) => {
                    shared.upstream.send_replace(Some(instance.upstream));
                    current = Some(instance);
                }
                Err(error) => tracing::error!(%error, "python_restart_failed"),
            },
            () = stopped(&mut stop) => return,
        }
    }
}

/// One running Python process tree.
struct Instance {
    child: Box<dyn ChildWrapper>,
    upstream: Upstream,
    /// POSIX only: a `sh` that kills Python's process group when its stdin
    /// closes, which happens when the gateway dies, even by SIGKILL.
    #[cfg(unix)]
    reaper: Option<tokio::process::Child>,
}

impl Instance {
    async fn spawn(shared: &Arc<Shared>) -> Result<Self, SupervisorError> {
        let cfg = &shared.cfg;
        let mut command = CommandWrap::with_new(&cfg.python_bin, |cmd| {
            cmd.arg("-c")
                .arg(BOOTSTRAP)
                .arg(cfg.site_packages.as_os_str())
                .arg(cfg.cli_entry.as_os_str())
                .args(["serve", "--host", "127.0.0.1", "--port", "0", "--handshake"]);
            // v3's parent watch probes the parent with os.kill(pid, 0), which
            // on Windows sends CTRL_C_EVENT; the Job Object covers Windows.
            #[cfg(unix)]
            cmd.arg("--parent-pid").arg(std::process::id().to_string());
            cmd.env("PYTHONUNBUFFERED", "1")
                .env("EVOFLUX_GATEWAY_SECRET", &cfg.gateway_secret)
                .env("EVOFLUX_REMOTE_PROXY_SECRET", &cfg.remote_proxy_secret)
                .env("EVOFLUX_TSNET_TARGET_PORT", cfg.gateway_port.to_string())
                .env("EVOFLUX_DISABLE_SERVICES", cfg.disabled_services.join(","));
            match &cfg.desktop_token {
                Some(token) => cmd.env("EVOFLUX_DESKTOP_TOKEN", token),
                None => cmd.env_remove("EVOFLUX_DESKTOP_TOKEN"),
            };
            for (name, value) in &cfg.env_passthrough {
                cmd.env(name, value);
            }
            cmd.stdin(Stdio::null())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped());
        });
        #[cfg(windows)]
        {
            use process_wrap::tokio::{CreationFlags, JobObject, KillOnDrop};
            // As sidecar.rs: no console window for the child.
            command.wrap(CreationFlags(
                windows::Win32::System::Threading::CREATE_NO_WINDOW,
            ));
            command.wrap(JobObject);
            command.wrap(KillOnDrop);
        }
        #[cfg(unix)]
        {
            use process_wrap::tokio::{KillOnDrop, ProcessGroup};
            command.wrap(ProcessGroup::leader());
            command.wrap(KillOnDrop);
        }
        let mut child = command.spawn().map_err(|source| SupervisorError::Spawn {
            bin: cfg.python_bin.display().to_string(),
            source,
        })?;
        #[cfg(unix)]
        let reaper = spawn_reaper(child.id());

        if let Some(stderr) = child.stderr().take() {
            tokio::spawn(pump_lines(Arc::clone(shared), stderr));
        }
        let Some(stdout) = child.stdout().take() else {
            let _ = child.start_kill();
            return Err(SupervisorError::Exited {
                status: "no stdout".to_owned(),
            });
        };
        let mut instance = Self {
            child,
            upstream: Upstream {
                addr: SocketAddr::from((Ipv4Addr::LOCALHOST, 0)),
                pid: 0,
            },
            #[cfg(unix)]
            reaper,
        };
        let mut lines = BufReader::new(stdout).lines();
        let handshake = tokio::time::timeout(cfg.startup_timeout, async {
            loop {
                match lines.next_line().await {
                    Ok(Some(line)) => {
                        if let Some(json) = line.strip_prefix(HANDSHAKE_PREFIX) {
                            return serde_json::from_str::<Handshake>(json)
                                .map_err(|e| SupervisorError::BadHandshake(e.to_string()));
                        }
                        forward_line(shared, line).await;
                    }
                    Ok(None) | Err(_) => {
                        let status = instance.wait_python().await;
                        let status = status.map_or_else(|e| e.to_string(), |s| s.to_string());
                        return Err(SupervisorError::Exited { status });
                    }
                }
            }
        })
        .await;
        let handshake = match handshake {
            Ok(Ok(handshake)) => handshake,
            Ok(Err(error)) => {
                instance.kill_tree().await;
                return Err(error);
            }
            Err(_) => {
                instance.kill_tree().await;
                return Err(SupervisorError::HandshakeTimeout(cfg.startup_timeout));
            }
        };
        // Keep draining stdout so Python never blocks on a full pipe.
        tokio::spawn(pump_lines(Arc::clone(shared), lines.into_inner()));
        instance.upstream = Upstream {
            addr: SocketAddr::from((Ipv4Addr::LOCALHOST, handshake.port)),
            pid: handshake.pid,
        };
        tracing::info!(pid = handshake.pid, port = handshake.port, "python_ready");
        Ok(instance)
    }

    /// Wait for the process we started (not the whole job or group), so a
    /// crash is seen even while grandchildren are still alive.
    async fn wait_python(&mut self) -> std::io::Result<ExitStatus> {
        match native_child(self.child.as_mut()) {
            Some(native) => native.wait().await,
            None => self.child.wait().await,
        }
    }

    async fn kill_tree(&mut self) {
        if let Err(error) = self.child.start_kill() {
            tracing::debug!(%error, "python_kill_failed");
        }
        if tokio::time::timeout(SHUTDOWN_GRACE, self.child.wait())
            .await
            .is_err()
        {
            tracing::warn!("python_tree_still_running_after_kill");
        }
        self.stop_reaper().await;
    }

    async fn stop(&mut self) {
        #[cfg(unix)]
        {
            // SIGTERM lets uvicorn drain and run its shutdown hooks (sidecar.rs).
            const SIGTERM: i32 = 15;
            if let Some(native) = native_child(self.child.as_mut()) {
                let _ = ChildWrapper::signal(native, SIGTERM);
            }
            if tokio::time::timeout(SHUTDOWN_GRACE, self.wait_python())
                .await
                .is_err()
            {
                tracing::warn!("python_did_not_exit_in_grace; force-killing");
            }
        }
        self.kill_tree().await;
    }

    async fn stop_reaper(&mut self) {
        #[cfg(unix)]
        if let Some(mut reaper) = self.reaper.take() {
            let _ = reaper.start_kill();
            let _ = reaper.wait().await;
        }
    }
}

impl Drop for Instance {
    fn drop(&mut self) {
        let _ = self.child.start_kill();
    }
}

/// The innermost tokio child of a wrapper chain.
fn native_child(child: &mut dyn ChildWrapper) -> Option<&mut tokio::process::Child> {
    if (child as &dyn Any).is::<tokio::process::Child>() {
        return (child as &mut dyn Any).downcast_mut::<tokio::process::Child>();
    }
    let this: *const () = (child as *const dyn ChildWrapper).cast();
    let inner = child.inner_mut();
    if std::ptr::eq((inner as *const dyn ChildWrapper).cast::<()>(), this) {
        return None;
    }
    native_child(inner)
}

async fn stopped(stop: &mut watch::Receiver<bool>) {
    let _ = stop.wait_for(|stopped| *stopped).await;
}

#[cfg(unix)]
fn spawn_reaper(pgid: Option<u32>) -> Option<tokio::process::Child> {
    let pgid = pgid?;
    let spawned = tokio::process::Command::new("sh")
        .arg("-c")
        .arg("read _ignored; kill -KILL -- -\"$1\" 2>/dev/null")
        .arg("evoflux-reaper")
        .arg(pgid.to_string())
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn();
    match spawned {
        Ok(child) => Some(child),
        Err(error) => {
            tracing::warn!(%error, "python_reaper_unavailable");
            None
        }
    }
}

async fn pump_lines(shared: Arc<Shared>, stream: impl AsyncRead + Unpin) {
    let mut lines = BufReader::new(stream).lines();
    while let Ok(Some(line)) = lines.next_line().await {
        forward_line(&shared, line).await;
    }
}

/// Python's output goes to the gateway's stderr (the shell's `backend.log`)
/// and into the in-memory tail.
async fn forward_line(shared: &Shared, line: String) {
    let mut stderr = tokio::io::stderr();
    let _ = stderr.write_all(line.as_bytes()).await;
    let _ = stderr.write_all(b"\n").await;
    shared.push_log(line);
}
