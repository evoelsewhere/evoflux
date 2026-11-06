//! One connection to an MCP server, on the official `rmcp` SDK.
//!
//! Results are handed on as JSON (`serde_json::Value`) in the protocol's own
//! shapes, so the desktop and the engine see exactly what the server sent.

use std::collections::BTreeMap;
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;

use rmcp::model::{
    CallToolRequestParams, ClientCapabilities, ClientConfig, GetPromptRequestParams,
    Implementation, ProtocolVersion,
};
use rmcp::service::{ClientLifecycleMode, ClientServiceExt, RunningService};
use rmcp::transport::streamable_http_client::StreamableHttpClientTransportConfig;
use rmcp::transport::{StreamableHttpClientTransport, TokioChildProcess};
use rmcp::RoleClient;
use serde_json::{Map, Value};
use tokio::io::AsyncBufReadExt;

use crate::config::Transport;

/// How long a server may take to start and answer the first request.
pub const CONNECT_TIMEOUT: Duration = Duration::from_secs(45);

#[derive(Debug, Clone, PartialEq)]
pub enum ConnectError {
    /// The server answered 401/403: it needs a sign-in or a token.
    NeedsAuth(String),
    Failed(String),
}

impl std::fmt::Display for ConnectError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ConnectError::NeedsAuth(e) | ConnectError::Failed(e) => f.write_str(e),
        }
    }
}

fn classify(error: String) -> ConnectError {
    let lower = error.to_ascii_lowercase();
    if lower.contains("401")
        || lower.contains("403")
        || lower.contains("unauthorized")
        || lower.contains("auth required")
    {
        ConnectError::NeedsAuth(error)
    } else {
        ConnectError::Failed(error)
    }
}

pub struct Connection {
    service: RunningService<RoleClient, ClientConfig>,
    /// `serverInfo` and instructions, as the server described itself.
    pub info: Value,
}

/// Who we are to servers, and the protocol versions we speak: the stateless
/// 2026-07-28 revision first, the `initialize` handshake for older servers.
fn client_config() -> ClientConfig {
    ClientConfig::new(
        ClientCapabilities::default(),
        Implementation::new("evo", env!("CARGO_PKG_VERSION")),
    )
}

fn lifecycle() -> ClientLifecycleMode {
    ClientLifecycleMode::Auto {
        preferred_versions: vec![ProtocolVersion::LATEST],
        legacy_version: Some(ProtocolVersion::LATEST_WITH_INITIALIZE),
    }
}

/// Connect to `transport`. `cwd` is where a command runs when its config
/// names no folder; `log` receives the server's stderr lines.
/// `auth`: a signed-in HTTP client for URL servers (see [`crate::auth`]).
pub async fn connect(
    transport: &Transport,
    cwd: Option<&Path>,
    log: Arc<dyn Fn(String) + Send + Sync>,
    auth: Option<rmcp::transport::auth::AuthClient<reqwest::Client>>,
) -> Result<Connection, ConnectError> {
    let start = async {
        match transport {
            Transport::Stdio {
                command,
                args,
                env,
                cwd: own_cwd,
            } => {
                let mut cmd = stdio_command(command, args, env);
                if let Some(dir) = own_cwd.as_deref().map(Path::new).or(cwd) {
                    cmd.current_dir(dir);
                }
                let (process, stderr) = TokioChildProcess::builder(cmd)
                    .stderr(std::process::Stdio::piped())
                    .spawn()
                    .map_err(|e| {
                        ConnectError::Failed(format!("could not start `{command}`: {e}"))
                    })?;
                if let Some(stderr) = stderr {
                    let log = log.clone();
                    tokio::spawn(async move {
                        let mut lines = tokio::io::BufReader::new(stderr).lines();
                        while let Ok(Some(line)) = lines.next_line().await {
                            log(line);
                        }
                    });
                }
                handshake(process).await
            }
            Transport::Http { url, headers } | Transport::Sse { url, headers } => {
                let mut config = StreamableHttpClientTransportConfig::with_uri(url.clone());
                for (name, value) in headers {
                    if name.eq_ignore_ascii_case("authorization") {
                        let token = value.strip_prefix("Bearer ").unwrap_or(value);
                        config = config.auth_header(token.to_string());
                    } else if let (Ok(name), Ok(value)) =
                        (name.parse::<http::HeaderName>(), value.parse())
                    {
                        config.custom_headers.insert(name, value);
                    }
                }
                match auth {
                    Some(client) => {
                        handshake(StreamableHttpClientTransport::with_client(client, config)).await
                    }
                    None => handshake(StreamableHttpClientTransport::from_config(config)).await,
                }
            }
        }
    };
    let service = tokio::time::timeout(CONNECT_TIMEOUT, start)
        .await
        .map_err(|_| {
            ConnectError::Failed(format!("no answer after {}s", CONNECT_TIMEOUT.as_secs()))
        })??;
    Ok(Connection::new(service))
}

/// The protocol handshake over any transport.
async fn handshake<T, E, A>(
    transport: T,
) -> Result<RunningService<RoleClient, ClientConfig>, ConnectError>
where
    T: rmcp::transport::IntoTransport<RoleClient, E, A>,
    E: std::error::Error + Send + Sync + 'static,
{
    client_config()
        .serve_with_lifecycle(transport, lifecycle())
        .await
        .map_err(|e| classify(e.to_string()))
}

/// Connect over an already open transport (tests, in-process servers).
pub async fn connect_transport<T, E, A>(transport: T) -> Result<Connection, ConnectError>
where
    T: rmcp::transport::IntoTransport<RoleClient, E, A>,
    E: std::error::Error + Send + Sync + 'static,
{
    Ok(Connection::new(handshake(transport).await?))
}

/// The command for a stdio server. On Windows a bare name like `npx` is
/// usually a `.cmd` script, which needs `cmd /c`; servers start without a
/// console window.
fn stdio_command(
    command: &str,
    args: &[String],
    env: &BTreeMap<String, String>,
) -> tokio::process::Command {
    #[cfg(windows)]
    let mut cmd = match resolve_windows(command) {
        Some(path)
            if path.extension().is_some_and(|e| {
                e.eq_ignore_ascii_case("cmd") || e.eq_ignore_ascii_case("bat")
            }) =>
        {
            let mut cmd = tokio::process::Command::new("cmd");
            cmd.arg("/d").arg("/s").arg("/c").arg(path).args(args);
            cmd
        }
        Some(path) => {
            let mut cmd = tokio::process::Command::new(path);
            cmd.args(args);
            cmd
        }
        None => {
            let mut cmd = tokio::process::Command::new(command);
            cmd.args(args);
            cmd
        }
    };
    #[cfg(not(windows))]
    let mut cmd = {
        let mut cmd = tokio::process::Command::new(command);
        cmd.args(args);
        cmd
    };
    cmd.envs(env);
    cmd.kill_on_drop(true);
    #[cfg(windows)]
    {
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    cmd
}

/// `command` on `PATH` with the extensions in `PATHEXT`, when it has none.
#[cfg(windows)]
fn resolve_windows(command: &str) -> Option<std::path::PathBuf> {
    let path = Path::new(command);
    if path.extension().is_some() || path.components().count() > 1 {
        return path.exists().then(|| path.to_path_buf());
    }
    let exts = std::env::var("PATHEXT").unwrap_or_else(|_| ".EXE;.CMD;.BAT".into());
    for dir in std::env::split_paths(&std::env::var_os("PATH")?) {
        for ext in exts.split(';').filter(|e| !e.is_empty()) {
            let candidate = dir.join(format!("{command}{}", ext.to_ascii_lowercase()));
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }
    None
}

fn to_json<T: serde::Serialize>(value: &T) -> Value {
    serde_json::to_value(value).unwrap_or(Value::Null)
}

/// A method the server does not have is an empty list, not an error.
fn missing_method(error: &rmcp::ServiceError) -> bool {
    let text = error.to_string().to_ascii_lowercase();
    text.contains("method not found") || text.contains("-32601")
}

impl Connection {
    fn new(service: RunningService<RoleClient, ClientConfig>) -> Self {
        let info = service
            .peer_info()
            .map(|info| serde_json::to_value(info).unwrap_or(Value::Null))
            .unwrap_or(Value::Null);
        Self { service, info }
    }

    /// `tools/list`, every page.
    pub async fn tools(&self) -> Result<Vec<Value>, String> {
        match self.service.list_all_tools().await {
            Ok(tools) => Ok(tools.iter().map(to_json).collect()),
            Err(e) if missing_method(&e) => Ok(Vec::new()),
            Err(e) => Err(e.to_string()),
        }
    }

    /// `prompts/list`, every page; empty when the server has no prompts.
    pub async fn prompts(&self) -> Result<Vec<Value>, String> {
        let has_prompts = self
            .service
            .peer_info()
            .map(|info| info.capabilities.prompts.is_some())
            .unwrap_or(true);
        if !has_prompts {
            return Ok(Vec::new());
        }
        match self.service.list_all_prompts().await {
            Ok(prompts) => Ok(prompts.iter().map(to_json).collect()),
            Err(e) if missing_method(&e) => Ok(Vec::new()),
            Err(e) => Err(e.to_string()),
        }
    }

    /// `resources/list`, every page; empty when the server has no resources.
    pub async fn resources(&self) -> Result<Vec<Value>, String> {
        let has = self
            .service
            .peer_info()
            .map(|info| info.capabilities.resources.is_some())
            .unwrap_or(true);
        if !has {
            return Ok(Vec::new());
        }
        match self.service.list_all_resources().await {
            Ok(resources) => Ok(resources.iter().map(to_json).collect()),
            Err(e) if missing_method(&e) => Ok(Vec::new()),
            Err(e) => Err(e.to_string()),
        }
    }

    /// `resources/read`: the resource's contents.
    pub async fn read_resource(&self, uri: &str) -> Result<Value, String> {
        let params = rmcp::model::ReadResourceRequestParams::new(uri.to_string());
        self.service
            .read_resource(params)
            .await
            .map(|result| to_json(&result))
            .map_err(|e| e.to_string())
    }

    /// `tools/call`: the result (`content`, `structuredContent`, `isError`).
    pub async fn call_tool(
        &self,
        name: &str,
        arguments: Option<Map<String, Value>>,
    ) -> Result<Value, String> {
        let mut params = CallToolRequestParams::new(name.to_string());
        params.arguments = arguments;
        self.service
            .call_tool(params)
            .await
            .map(|result| to_json(&result))
            .map_err(|e| e.to_string())
    }

    /// `prompts/get`: the prompt's messages.
    pub async fn get_prompt(
        &self,
        name: &str,
        arguments: Map<String, Value>,
    ) -> Result<Value, String> {
        let mut params = GetPromptRequestParams::new(name.to_string());
        if !arguments.is_empty() {
            params.arguments = Some(arguments);
        }
        self.service
            .get_prompt(params)
            .await
            .map(|result| to_json(&result))
            .map_err(|e| e.to_string())
    }

    /// Whether the connection is still up.
    pub fn is_closed(&self) -> bool {
        self.service.is_transport_closed()
    }

    pub async fn close(self) {
        let _ = self.service.cancel().await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rmcp::handler::server::ServerHandler;
    use rmcp::model::{
        CallToolResponse, CallToolResult, ContentBlock, GetPromptResponse, GetPromptResult,
        ListPromptsResult, ListToolsResult, PaginatedRequestParams, Prompt, PromptMessage, Role,
        ServerCapabilities, ServerConfig, Tool,
    };
    use rmcp::service::{RequestContext, ServiceExt};
    use rmcp::{ErrorData, RoleServer};

    /// A server with one tool (`echo`) and one prompt (`greet`).
    struct Echo;

    impl ServerHandler for Echo {
        fn get_info(&self) -> ServerConfig {
            ServerConfig::new(
                ServerCapabilities::builder()
                    .enable_tools()
                    .enable_prompts()
                    .build(),
            )
        }

        async fn list_tools(
            &self,
            _request: Option<PaginatedRequestParams>,
            _context: RequestContext<RoleServer>,
        ) -> Result<ListToolsResult, ErrorData> {
            let schema =
                serde_json::json!({"type": "object", "properties": {"text": {"type": "string"}}});
            let tool = Tool::new(
                "echo",
                "Repeat the text",
                schema.as_object().unwrap().clone(),
            );
            Ok(ListToolsResult::with_all_items(vec![tool]))
        }

        async fn call_tool(
            &self,
            request: CallToolRequestParams,
            _context: RequestContext<RoleServer>,
        ) -> Result<CallToolResponse, ErrorData> {
            let text = request
                .arguments
                .and_then(|a| a.get("text").cloned())
                .unwrap_or_default();
            let text = text.as_str().unwrap_or("").to_string();
            Ok(CallToolResponse::Complete(CallToolResult::success(vec![
                ContentBlock::text(format!("echo: {text}")),
            ])))
        }

        async fn list_prompts(
            &self,
            _request: Option<PaginatedRequestParams>,
            _context: RequestContext<RoleServer>,
        ) -> Result<ListPromptsResult, ErrorData> {
            Ok(ListPromptsResult::with_all_items(vec![Prompt::new(
                "greet",
                Some("Say hello"),
                None,
            )]))
        }

        async fn get_prompt(
            &self,
            request: GetPromptRequestParams,
            _context: RequestContext<RoleServer>,
        ) -> Result<GetPromptResponse, ErrorData> {
            let who = request
                .arguments
                .and_then(|a| a.get("who").cloned())
                .unwrap_or_default();
            let text = format!("Say hello to {}", who.as_str().unwrap_or("everyone"));
            Ok(GetPromptResponse::Complete(GetPromptResult::new(vec![
                PromptMessage::new_text(Role::User, text),
            ])))
        }
    }

    #[tokio::test]
    async fn lists_and_calls_tools_and_prompts() {
        let (client_end, server_end) = tokio::io::duplex(64 * 1024);
        tokio::spawn(async move {
            let server = Echo.serve(server_end).await.expect("server starts");
            let _ = server.waiting().await;
        });
        let conn = connect_transport(client_end).await.expect("handshake");
        let tools = conn.tools().await.unwrap();
        assert_eq!(tools.len(), 1);
        assert_eq!(tools[0]["name"], "echo");
        let mut args = Map::new();
        args.insert("text".into(), Value::String("hi".into()));
        let result = conn.call_tool("echo", Some(args)).await.unwrap();
        assert_eq!(result["content"][0]["text"], "echo: hi");
        let prompts = conn.prompts().await.unwrap();
        assert_eq!(prompts[0]["name"], "greet");
        let mut args = Map::new();
        args.insert("who".into(), Value::String("evo".into()));
        let prompt = conn.get_prompt("greet", args).await.unwrap();
        assert_eq!(prompt["messages"][0]["content"]["text"], "Say hello to evo");
        conn.close().await;
    }
}
