//! Runs `tests/parity/cases.json` through the Rust tools and compares each
//! answer with what the Python tools gave (`tests/parity/golden.json`, recorded
//! by `contract-tests/tools` against `TARGET=python`).
//!
//! Cases that need workspace links are skipped, loudly, where the platform
//! cannot create one.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing,
    clippy::disallowed_methods
)]

mod common;

use std::collections::BTreeMap;
use std::path::Path;

use common::Workspace;
use evoflux_area_tools::{read_only_tools, ToolCtx};
use serde_json::Value;

fn parity_dir() -> std::path::PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/parity")
}

fn load(path: &Path) -> Value {
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

#[tokio::test(flavor = "multi_thread")]
async fn rust_tools_answer_like_python() {
    let data = load(&parity_dir().join("cases.json"));
    let golden = load(&parity_dir().join("golden.json"));
    let platform = if cfg!(windows) { "windows" } else { "posix" };
    let tools = read_only_tools();
    let tmp = tempfile::tempdir().unwrap();

    let mut checked = 0usize;
    let mut skipped = Vec::new();
    let mut failures: BTreeMap<String, String> = BTreeMap::new();
    for (name, fixture) in data["fixtures"].as_object().unwrap() {
        let workspace = Workspace::build(&tmp.path().join(name), fixture, &data["outside"]);
        let has_links = !fixture["links"].as_array().unwrap().is_empty();
        let ctx = ToolCtx {
            workspace_root: workspace.ws.clone(),
            session_id: "golden".into(),
        };
        for case in data["cases"].as_array().unwrap() {
            let fixture_name = case
                .get("fixture")
                .and_then(Value::as_str)
                .unwrap_or("main");
            if fixture_name != name {
                continue;
            }
            if let Some(only) = case.get("only_os").and_then(Value::as_str) {
                if only != platform {
                    continue;
                }
            }
            let id = case["id"].as_str().unwrap();
            if has_links && !workspace.links_ok {
                skipped.push(id.to_owned());
                continue;
            }
            let tool = tools
                .iter()
                .find(|t| t.name() == case["tool"].as_str().unwrap())
                .unwrap();
            let args: Value =
                serde_json::from_str(&workspace.substitute_json(&case["args"])).unwrap();
            let out = tool.call(args, &ctx).await;
            let mut content = workspace.normalise(
                &out.content,
                case.get("normalize").is_some(),
                case.get("normalize_drive").is_some(),
            );
            if let Some(prefix) = case.get("prefix_only").and_then(Value::as_str) {
                assert!(content.starts_with(prefix), "{id}: {content}");
                content = prefix.to_owned();
            }
            let want = &golden[id];
            checked += 1;
            if want["content"] != content || want["is_error"] != out.is_error {
                failures.insert(
                    id.to_owned(),
                    format!(
                        "python: {:?} (error={})\n     rust: {:?} (error={})",
                        want["content"].as_str().unwrap_or("<missing>"),
                        want["is_error"],
                        content,
                        out.is_error
                    ),
                );
            }
        }
    }
    if !skipped.is_empty() {
        eprintln!(
            "SKIPPED {} link cases: this platform cannot create workspace links",
            skipped.len()
        );
    }
    assert!(checked > 200, "only {checked} cases ran");
    assert!(
        failures.is_empty(),
        "{} of {checked} cases differ from Python:\n{}",
        failures.len(),
        failures
            .iter()
            .map(|(id, text)| format!("{id}\n  {text}"))
            .collect::<Vec<_>>()
            .join("\n")
    );
}
