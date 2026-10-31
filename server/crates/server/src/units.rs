//! Area routers and services mounted by the production server.
use axum::Router;
use evoflux_core::{config::Settings, db::Db, paths::Paths};
use evoflux_gateway::routing::RoutingTable;
use std::sync::Arc;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;

#[derive(Clone)]
pub struct UnitState {
    pub settings: Arc<Settings>,
    pub paths: Arc<Paths>,
    pub db: Option<Arc<Db>>,
}
pub fn router(_state: &UnitState) -> Router {
    #[cfg(test)]
    if _state.settings.app_env == "serve-test-unit" {
        return Router::new().route(
            "/test-unit",
            axum::routing::get(|| async { "test unit response" }),
        );
    }
    Router::new()
}
pub fn start_rust_services(
    _table: &RoutingTable,
    _state: &UnitState,
    _cancel: CancellationToken,
) -> Vec<JoinHandle<()>> {
    #[cfg(test)]
    if _state.settings.app_env == "serve-test-unit"
        && _table.units().iter().any(|unit| {
            unit.name == "test-unit"
                && unit.owner == evoflux_gateway::routing::Owner::Rust
                && unit.services.iter().any(|name| name == "test-service")
        })
    {
        test_support::mark_started();
        return vec![tokio::spawn(async move {
            _cancel.cancelled().await;
            test_support::mark_stopped();
        })];
    }
    Vec::new()
}

#[cfg(test)]
pub(crate) mod test_support {
    use std::sync::atomic::{AtomicBool, Ordering};
    static STARTED: AtomicBool = AtomicBool::new(false);
    static STOPPED: AtomicBool = AtomicBool::new(false);
    pub fn reset() {
        STARTED.store(false, Ordering::SeqCst);
        STOPPED.store(false, Ordering::SeqCst);
    }
    pub fn mark_started() {
        STARTED.store(true, Ordering::SeqCst);
    }
    pub fn mark_stopped() {
        STOPPED.store(true, Ordering::SeqCst);
    }
    pub fn started() -> bool {
        STARTED.load(Ordering::SeqCst)
    }
    pub fn stopped() -> bool {
        STOPPED.load(Ordering::SeqCst)
    }
}
