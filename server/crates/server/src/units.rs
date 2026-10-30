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
    Router::new()
}
pub fn start_rust_services(
    _table: &RoutingTable,
    _state: &UnitState,
    _cancel: CancellationToken,
) -> Vec<JoinHandle<()>> {
    Vec::new()
}
