//! Read-only agent tools: `read`, `ls`, `glob`, `grep` and `date`.
//!
//! Port of `app/agent/tools/builtin/filesystem/{read,ls,glob,grep}.py` and
//! `date.py`. The text a tool returns, its truncation limits and its error
//! messages are what the model sees, so they follow the Python tools exactly;
//! `server/KNOWN_DIFFERENCES.md` lists where they cannot.

use std::path::PathBuf;
use std::sync::Arc;

use async_trait::async_trait;
use serde_json::{json, Map, Value};

mod args;
mod date;
mod fnmatch;
mod fsutil;
mod glob;
mod grep;
mod ignore;
mod ls;
mod pyfmt;
mod read;
mod sandbox;
mod search_root;
#[cfg(test)]
mod testutil;

/// What a tool call runs against.
#[derive(Debug, Clone)]
pub struct ToolCtx {
    pub workspace_root: PathBuf,
    pub session_id: String,
}

/// What the model gets back. A failure carries the `Error: ...` text the agent
/// loop gives the model and sets `is_error`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ToolOutput {
    pub content: String,
    pub is_error: bool,
}

impl ToolOutput {
    fn ok(content: String) -> Self {
        Self {
            content,
            is_error: false,
        }
    }

    fn error(message: &str) -> Self {
        Self {
            content: format!("Error: {message}"),
            is_error: true,
        }
    }
}

#[async_trait]
pub trait Tool: Send + Sync {
    fn name(&self) -> &str;
    fn spec(&self) -> serde_json::Value;
    async fn call(&self, args: serde_json::Value, ctx: &ToolCtx) -> ToolOutput;
}

/// The read-only tools, in the order Python registers them.
///
/// Python's registry also records, for every one of these tools,
/// `read_only=True` and `concurrency_safe=True`, and the permission service
/// allows all five without a prompt (`_SAFE_TOOLS` in `app/agent/permission.py`;
/// config rules can still deny them). The rest of the registry metadata is
/// `capabilities` (`read`: `workspace_read`; `glob`, `grep`: `source_navigation`;
/// `ls`, `date`: none), `observation_kind` (`read`: `source`; `ls`, `glob`, `grep`:
/// `discovery`; `date`: none) and, for `read` only, the observation key and range
/// that let the agent loop reuse a slice it has already shown the model. The
/// `Tool` trait carries none of it; the caller applies it.
pub fn read_only_tools() -> Vec<Arc<dyn Tool>> {
    vec![
        Arc::new(read::ReadTool),
        Arc::new(ls::LsTool),
        Arc::new(glob::GlobTool),
        Arc::new(grep::GrepTool),
        Arc::new(date::DateTool),
    ]
}

/// Run a blocking tool body off the runtime and turn its result into output.
async fn run_blocking<F>(tool: &'static str, body: F) -> ToolOutput
where
    F: FnOnce() -> Result<String, String> + Send + 'static,
{
    match evoflux_core::blocking::run(body).await {
        Ok(Ok(content)) => ToolOutput::ok(content),
        Ok(Err(message)) => ToolOutput::error(&message),
        Err(_) => ToolOutput::error(&format!("Tool '{tool}' raised RuntimeError: worker failed")),
    }
}

/// The OpenAI-style definition Python's `Tool.definition` produces.
fn definition(name: &str, description: &str, properties: Value, required: &[&str]) -> Value {
    json!({
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    })
}

/// One property schema, keys in the order Pydantic emits them.
fn property(default: Option<Value>, description: &str, extra: &[(&str, Value)]) -> Value {
    let mut map = Map::new();
    if let Some(default) = default {
        map.insert("default".to_owned(), default);
    }
    map.insert("description".to_owned(), json!(description));
    for (key, value) in extra {
        map.insert((*key).to_owned(), value.clone());
    }
    Value::Object(map)
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::panic,
    clippy::disallowed_methods
)]
mod tests {
    use super::*;

    #[test]
    fn registry_order_and_names_match_python() {
        let names: Vec<String> = read_only_tools()
            .iter()
            .map(|t| t.name().to_owned())
            .collect();
        assert_eq!(names, vec!["read", "ls", "glob", "grep", "date"]);
    }

    #[test]
    fn spec_name_matches_tool_name() {
        for tool in read_only_tools() {
            assert_eq!(tool.spec()["function"]["name"], tool.name());
            assert_eq!(tool.spec()["type"], "function");
        }
    }

    #[test]
    fn errors_carry_the_agent_loop_prefix() {
        let out = ToolOutput::error("boom");
        assert_eq!(out.content, "Error: boom");
        assert!(out.is_error);
        let out = ToolOutput::ok("fine".into());
        assert_eq!(out.content, "fine");
        assert!(!out.is_error);
    }

    #[tokio::test]
    async fn run_blocking_maps_both_outcomes_and_panics() {
        assert_eq!(
            run_blocking("t", || Ok("x".into())).await,
            ToolOutput::ok("x".into())
        );
        assert_eq!(
            run_blocking("t", || Err("bad".into())).await,
            ToolOutput::error("bad")
        );
        let panicked = run_blocking("t", || -> Result<String, String> {
            std::panic::resume_unwind(Box::new("boom"))
        })
        .await;
        assert_eq!(
            panicked,
            ToolOutput::error("Tool 't' raised RuntimeError: worker failed")
        );
    }
}
