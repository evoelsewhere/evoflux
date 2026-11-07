//! Web tools for evo: read a public page as Markdown ([`fetch`]) and search
//! the web without a key ([`search`]: DuckDuckGo, then Exa, then Wikipedia).
//! Every connection is limited to public addresses ([`guard`]).

pub mod extract;
pub mod fetch;
pub mod guard;
pub mod search;

pub use fetch::{fetch, Page};
pub use search::{search, Found, Query, SearchResult};
