//! Port of python-dotenv 1.2.2 and the EvoFlux credential and MCP .env writers.
#![forbid(unsafe_code)]

mod parser;
mod writer;

pub use parser::{parse, read};
pub use writer::{merge_write, Quote, WriteOpts};

#[derive(Debug, thiserror::Error)]
pub enum DotenvError {
    #[error("invalid environment variable name")]
    InvalidName,
    #[error("invalid environment variable value for {key}")]
    InvalidValue { key: String },
    #[error("dotenv I/O failed")]
    Io(#[from] std::io::Error),
    #[error("dotenv write task failed")]
    Task(#[from] tokio::task::JoinError),
}

#[cfg(test)]
mod tests;
