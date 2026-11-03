//! Parity driver: reads `{"workspace": str, "cases": [{"tool", "args"}]}` on
//! stdin and prints `[{"content", "is_error"}]`, like
//! `contract-tests/tools/py_driver.py` does for the Python tools.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing,
    clippy::disallowed_methods
)]

use std::io::Read;

use evoflux_area_tools::{read_only_tools, ToolCtx};
use serde_json::{json, Value};

#[tokio::main(flavor = "multi_thread")]
async fn main() {
    let mut input = String::new();
    std::io::stdin().read_to_string(&mut input).unwrap();
    let request: Value = serde_json::from_str(&input).unwrap();
    let ctx = ToolCtx {
        workspace_root: request["workspace"].as_str().unwrap().into(),
        session_id: "parity".into(),
        denied_patterns: match request["config_dir"].as_str() {
            Some(dir) => evoflux_area_tools::load_denied_patterns(dir.into()).await,
            None => Vec::new(),
        },
    };
    let tools = read_only_tools();
    let mut outputs = Vec::new();
    for case in request["cases"].as_array().unwrap() {
        let name = case["tool"].as_str().unwrap();
        let tool = tools.iter().find(|t| t.name() == name).unwrap();
        let out = tool.call(case["args"].clone(), &ctx).await;
        outputs.push(json!({"content": out.content, "is_error": out.is_error}));
    }
    println!("{}", Value::Array(outputs));
}
