//! The optional LibreOffice runtime evo uses to render Office documents.
//!
//! A leaf crate: it knows the pinned manifest ([`manifest`]), how to install the
//! archive safely ([`Runtime::start_install`]) and how to run `soffice` headless
//! ([`Runtime::convert_to_pdf`]). It knows nothing about chats, RPC or the
//! desktop app. Design: `docs/features/office/sdd.md`, ADR 0008.

mod convert;
mod install;
pub mod manifest;
pub mod preview;
pub mod versions;

pub use convert::{export_filter, supports, CONVERSION_TIMEOUT};
pub use install::{InstallJob, Installed, Phase, Runtime, Status};

/// Everything that can go wrong with the runtime.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("{0}")]
    Install(String),
    #[error("The Office runtime is not installed.")]
    NotInstalled,
    #[error("{0}")]
    Convert(String),
    #[error("LibreOffice did not finish within {0} seconds.")]
    Timeout(u64),
    #[error("{0}")]
    Io(#[from] std::io::Error),
}
