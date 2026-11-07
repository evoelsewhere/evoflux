//! A tiny stdio MCP server for trying connectors locally: one read-only tool
//! (`echo`), one tool that changes something (`add_note`) and one prompt
//! (`review`). It logs to stderr, which the app shows as the server log.
//!
//! cargo build -p evo-mcp --example echo_server
//! then add a connector with the built binary as its command.

use std::sync::Mutex;

use rmcp::handler::server::ServerHandler;
use rmcp::model::{
    CallToolRequestParams, CallToolResponse, CallToolResult, ContentBlock, GetPromptRequestParams,
    GetPromptResponse, GetPromptResult, ListPromptsResult, ListToolsResult, PaginatedRequestParams,
    Prompt, PromptArgument, PromptMessage, Role, ServerCapabilities, ServerConfig, Tool,
    ToolAnnotations,
};
use rmcp::service::{RequestContext, ServiceExt};
use rmcp::{ErrorData, RoleServer};

#[derive(Default)]
struct Echo {
    notes: Mutex<Vec<String>>,
}

fn schema(
    props: serde_json::Value,
    required: &[&str],
) -> serde_json::Map<String, serde_json::Value> {
    serde_json::json!({"type": "object", "properties": props, "required": required})
        .as_object()
        .unwrap()
        .clone()
}

impl ServerHandler for Echo {
    fn get_info(&self) -> ServerConfig {
        let mut info = ServerConfig::new(
            ServerCapabilities::builder()
                .enable_tools()
                .enable_prompts()
                .build(),
        );
        info.server_info.name = "echo-server".into();
        info.instructions =
            Some("A test server: echo repeats text; add_note stores a note.".into());
        info
    }

    async fn list_tools(
        &self,
        _request: Option<PaginatedRequestParams>,
        _context: RequestContext<RoleServer>,
    ) -> Result<ListToolsResult, ErrorData> {
        let echo = Tool::new(
            "echo",
            "Repeat a message back",
            schema(
                serde_json::json!({"message": {"type": "string"}}),
                &["message"],
            ),
        )
        .annotate(ToolAnnotations::new().read_only(true));
        let note = Tool::new(
            "add_note",
            "Store a note (changes the server's state)",
            schema(serde_json::json!({"text": {"type": "string"}}), &["text"]),
        );
        Ok(ListToolsResult::with_all_items(vec![echo, note]))
    }

    async fn call_tool(
        &self,
        request: CallToolRequestParams,
        _context: RequestContext<RoleServer>,
    ) -> Result<CallToolResponse, ErrorData> {
        let arg = |key: &str| {
            request
                .arguments
                .as_ref()
                .and_then(|a| a.get(key))
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string()
        };
        eprintln!("call {}", request.name);
        let text = match request.name.as_ref() {
            "echo" => format!("echo: {}", arg("message")),
            "add_note" => {
                let mut notes = self.notes.lock().unwrap();
                notes.push(arg("text"));
                format!("{} notes stored", notes.len())
            }
            other => {
                return Ok(CallToolResponse::Complete(CallToolResult::error(vec![
                    ContentBlock::text(format!("no tool {other}")),
                ])))
            }
        };
        Ok(CallToolResponse::Complete(CallToolResult::success(vec![
            ContentBlock::text(text),
        ])))
    }

    async fn list_prompts(
        &self,
        _request: Option<PaginatedRequestParams>,
        _context: RequestContext<RoleServer>,
    ) -> Result<ListPromptsResult, ErrorData> {
        let arg = PromptArgument::new("topic")
            .with_description("What to review")
            .with_required(true);
        Ok(ListPromptsResult::with_all_items(vec![Prompt::new(
            "review",
            Some("Ask for a short review of a topic"),
            Some(vec![arg]),
        )]))
    }

    async fn get_prompt(
        &self,
        request: GetPromptRequestParams,
        _context: RequestContext<RoleServer>,
    ) -> Result<GetPromptResponse, ErrorData> {
        let topic = request
            .arguments
            .and_then(|a| a.get("topic").cloned())
            .unwrap_or_default();
        let text = format!(
            "Give a three-point review of {}.",
            topic.as_str().unwrap_or("this project")
        );
        Ok(GetPromptResponse::Complete(GetPromptResult::new(vec![
            PromptMessage::new_text(Role::User, text),
        ])))
    }
}

#[tokio::main]
async fn main() {
    eprintln!("echo-server starting");
    let server = Echo::default()
        .serve(rmcp::transport::stdio())
        .await
        .expect("stdio");
    let _ = server.waiting().await;
}
