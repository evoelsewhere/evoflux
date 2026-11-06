//! Web tools for evo: read a public page as Markdown ([`fetch`]) and search
//! the web ([`search`], through DuckDuckGo's HTML page). Every connection is
//! limited to public addresses ([`guard`]).

pub mod extract;
pub mod fetch;
pub mod guard;
pub mod search;

pub use fetch::{fetch, Page};
pub use search::{search, Query, SearchResult};
