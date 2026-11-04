//! The shared provider catalog: which AI providers EvoFlux knows, how to
//! connect to each, which models.dev data ships offline, and whether the
//! user's environment holds credentials for one.
//!
//! Ports `app/agent/providers/catalog.py`, the curated table and the
//! models.dev lookups of `registry.py` and `model_registry.py`, and
//! `_provider_is_configured` of `app/api/routes/settings.py`. Python is the
//! spec; `tests/dump_catalog.py` dumps its catalog to the checked-in fixture
//! the differential tests compare against.
//!
//! Start from [`catalog()`] (bundled data only) or build a [`Catalog`] with a
//! fetched models.dev payload and installed plugins.

#![forbid(unsafe_code)]

mod catalog;
mod configured;
mod data;
mod overrides_table;
mod registry;
mod registry_table;

pub use catalog::{catalog, Catalog, CredentialField, Kind, PluginProvider, ProviderEntry, Source};
pub use configured::{CredentialLookup, EnvMap};
pub use data::{
    bundled_model_registry, bundled_model_registry_json, bundled_provider_catalog_json,
    provider_envelopes, Envelope, Envelopes,
};
pub use registry::{
    config_from_models_dev, custom_provider, derived_base_url_env_var, get_provider_config,
    is_recommended, provider_ids, provider_rank, provider_registry, transport_for_npm, AuthKind,
    ProviderConfig, Transport, DEFAULT_TRANSPORT, NPM_TRANSPORTS, RECOMMENDED_PROVIDERS,
};
