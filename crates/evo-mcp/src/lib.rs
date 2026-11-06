//! MCP for evo: the connectors a person adds in Customize.
//!
//! * [`config`]: the `mcpServers` file (`~/.evo/agent/mcp.json`): a server is
//!   a command to run (stdio) or a URL (streamable HTTP, or legacy SSE),
//!   plus evo's own keys: `disabled` and per-tool `toolPermissions`.
//! * [`client`]: one connection, on the official `rmcp` SDK. It speaks the
//!   current stateless protocol and falls back to the `initialize` handshake
//!   of older servers.
//! * [`pool`]: every configured server, connected once and shared by all
//!   chats: status, tools, prompts, a log tail, and calls by the name a chat
//!   sees (`mcp__<server>__<tool>`).
//!
//! The desktop shell hosts the pool (one connection per server, however many
//! chats are open) and hands each chat the tools through the engine's
//! external-tools path.

pub mod auth;
pub mod client;
pub mod config;
pub mod pool;

pub use config::{ConfigFile, Permission, ServerConfig};
pub use pool::{Pool, Status};
