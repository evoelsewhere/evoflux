//! `evo-engine` — the headless evo application engine.
//!
//! Everything a front end needs to run an agent session without a terminal:
//! argument/option model ([`args`]), provider and model resolution
//! ([`provider`], [`config`], [`model_registry`]), credentials and OAuth
//! ([`auth`], [`credentials`]), settings ([`settings`]), project resources and
//! extension packages ([`resource_dirs`], [`resource_selection`],
//! [`resource_management`], [`packages`], [`install`]), harness construction and
//! session lifecycle ([`session`]), extension host actions
//! ([`extensions_actions`]), and the headless run modes including the
//! JSONL/RPC server ([`modes`], [`rpc`]).
//!
//! Front ends (the desktop app, and the transitional terminal UI in
//! `evo-cli`) talk to the engine over the wire contract in `evo-protocol`, and
//! supply their own built-in command list through [`builtin_commands`].
//!
//! Resources load from `.evo/` and `~/.evo/agent/`; extensions are Rust
//! `cdylib` plugins.

pub mod agent_session;
/// The on-device application database (see the `evo-store` crate).
pub use evo_store as app_db;
pub mod args;
pub mod auth;
pub mod auth_guidance;
pub mod builtin_commands;
pub mod agent_tool;
pub mod agents;
pub mod read_only;
pub mod child_agents;
pub mod worktrees;
pub mod config;
pub mod context_breakdown;
pub mod customize;
pub mod hooks;
pub mod instructions;
pub mod interaction;
pub mod lsp_tool;
pub mod memory;
pub mod web_tools;
pub mod plugins;
pub mod skill_runtime;
pub mod skill_tool;
pub mod credentials;
pub mod dev_extension;
pub mod docs_tool;
pub mod experimental;
pub mod export;
pub mod extension_api;
pub mod extensions_actions;
pub mod fs_watch;
pub mod host;
pub mod install;
pub mod model_registry;
pub mod modes;
pub mod native_store;
pub mod packages;
pub mod prebuilt_extensions;
pub mod provider;
pub mod provider_login;
pub mod provider_settings;
pub mod provider_usage;
pub mod mesh;
pub mod mesh_tools;
pub mod models_dev;
pub mod resource_commands;
pub mod resource_dirs;
pub mod resource_management;
pub mod resource_selection;
pub mod rpc;
pub mod saved_session_read;
pub mod session;
pub mod session_cwd;
pub mod settings;
pub mod side_questions;
pub mod source_info;
pub mod startup_diagnostics;
pub mod timings;
pub mod trust;

/// The wire contract, re-exported under the module name the engine has always
/// used for it.
pub mod remote {
    pub use evo_protocol::{cbor, client, codec, framing, mesh, message_accumulator, protocol};
}

/// Engine version. Aliases [`evo_plugin_sdk::HOST_VERSION`] so the version a
/// front end reports and the version handed to plugins can never disagree.
pub const VERSION: &str = evo_plugin_sdk::HOST_VERSION;

/// The application name. Aliases [`evo_plugin_sdk::HOST_NAME`] — the plugin
/// contract owns the identity, so extensions can label their output without
/// hardcoding a brand.
pub const APP_NAME: &str = evo_plugin_sdk::HOST_NAME;
