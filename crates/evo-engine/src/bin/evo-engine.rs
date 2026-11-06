//! The `evo-engine` binary: the headless engine a front end runs as a child
//! process. The desktop app starts it with `--mode rpc` and speaks the JSONL
//! protocol from `evo-protocol` over its stdin/stdout.
//!
//! The harness drives provider streams with `block_in_place`, which requires
//! the multi-thread runtime.

use std::process::ExitCode;

#[tokio::main(flavor = "multi_thread")]
async fn main() -> ExitCode {
    let code = evo_engine::host::run().await;
    ExitCode::from(code as u8)
}
