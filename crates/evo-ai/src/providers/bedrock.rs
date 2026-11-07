//! Amazon Bedrock `ConverseStream` provider (`bedrock-converse-stream`).
//!
//! Ported from EvoFlux's `bedrock/bedrock.py`, which drives the same API
//! through boto3. Converse is Bedrock's model-neutral surface: one request
//! shape for Claude, Nova, Llama, Mistral and the rest.
//!
//! - **Endpoint.** `POST {base}/model/{modelId}/converse-stream`, where `base`
//!   is `https://bedrock-runtime.{region}.amazonaws.com`.
//! - **Auth.** The request credential (`SimpleStreamOptions::api_key`) is
//!   a Bedrock API key, sent as `Authorization: Bearer`; IAM access keys
//!   encoded by [`encode_iam_credential`], which sign the request with AWS
//!   Signature Version 4; or `aws-profile:<name>`, resolved per request from
//!   the environment and `~/.aws` (see [`super::aws_credentials`]).
//! - **Response.** An `application/vnd.amazon.eventstream` body: binary frames
//!   of typed headers and a JSON payload, decoded by [`EventStreamDecoder`].

use std::collections::BTreeMap;
use std::sync::Arc;

use async_trait::async_trait;
use base64::Engine as _;
use futures::StreamExt;
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};

use crate::event_stream::{
    create_assistant_message_event_stream_with_cancellation, AssistantMessageEventStream,
    AssistantMessageEventStreamProducer,
};
use crate::model::Model;
use crate::provider::{Provider, SimpleStreamOptions};
use crate::providers::anthropic::cost::calculate_cost;
use crate::providers::anthropic::json_parse::parse_streaming_json;
use crate::providers::anthropic::retry::retry_provider_request;
use crate::types::{
    Api, AssistantMessage, AssistantMessageEvent, Content, Context, DoneReason, ErrorReason,
    InputModality, Message, StopReason, ThinkingContent, ThinkingContentType, ThinkingLevel,
    ToolCall, ToolCallType, UserContent,
};
use crate::AiError;

/// Prefix marking a request credential as encoded IAM access keys.
pub const IAM_CREDENTIAL_PREFIX: &str = "aws-iam:";

/// IAM access keys for SigV4 signing.
#[derive(Clone, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct IamCredential {
    pub access_key_id: String,
    pub secret_access_key: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub session_token: Option<String>,
}

/// Encode IAM keys as one opaque request credential.
pub fn encode_iam_credential(credential: &IamCredential) -> String {
    let json = serde_json::to_vec(credential).expect("credential serializes");
    format!(
        "{IAM_CREDENTIAL_PREFIX}{}",
        base64::engine::general_purpose::STANDARD.encode(json)
    )
}

/// Decode a credential produced by [`encode_iam_credential`].
pub fn decode_iam_credential(value: &str) -> Option<IamCredential> {
    let encoded = value.strip_prefix(IAM_CREDENTIAL_PREFIX)?;
    let json = base64::engine::general_purpose::STANDARD
        .decode(encoded)
        .ok()?;
    serde_json::from_slice(&json).ok()
}

/// The region in a `bedrock-runtime.{region}.amazonaws.com` endpoint.
pub fn region_of(base_url: &str) -> Option<String> {
    let host = reqwest::Url::parse(base_url).ok()?.host_str()?.to_string();
    let rest = host
        .strip_prefix("bedrock-runtime.")
        .or_else(|| host.strip_prefix("bedrock-runtime-fips."))
        .or_else(|| host.strip_prefix("bedrock."))?;
    rest.split('.').next().map(str::to_string)
}

pub struct BedrockProvider {
    id: String,
    http: reqwest::Client,
    models: Vec<Model>,
}

impl BedrockProvider {
    pub fn with_models(id: impl Into<String>, http: reqwest::Client, models: Vec<Model>) -> Self {
        Self {
            id: id.into(),
            http,
            models,
        }
    }
}

#[async_trait]
impl Provider for BedrockProvider {
    fn id(&self) -> &str {
        &self.id
    }

    fn models(&self) -> &[Model] {
        &self.models
    }

    async fn stream_simple(
        &self,
        model: &Model,
        ctx: &Context,
        opts: &SimpleStreamOptions,
    ) -> AssistantMessageEventStream {
        let (mut producer, stream) =
            create_assistant_message_event_stream_with_cancellation(&opts.signal);
        let http = self.http.clone();
        let body = build_request(model, ctx, opts);
        let model = model.clone();
        let mut opts = opts.clone();
        opts.signal = producer.cancellation_token();
        tokio::spawn(async move {
            run_stream(&mut producer, http, &model, body, &opts).await;
        });
        stream
    }
}

// ---------------------------------------------------------------------------
// Request
// ---------------------------------------------------------------------------

fn image_format(mime: &str) -> &'static str {
    match mime {
        "image/png" => "png",
        "image/gif" => "gif",
        "image/webp" => "webp",
        _ => "jpeg",
    }
}

fn image_block(data: &str, mime: &str) -> Value {
    json!({"image": {"format": image_format(mime), "source": {"bytes": data}}})
}

fn is_claude(model: &Model) -> bool {
    model.id.contains("anthropic.claude") || model.id.contains("anthropic/claude")
}

fn supports_cache_points(model: &Model) -> bool {
    let id = model.id.to_ascii_lowercase();
    id.contains("anthropic.claude") || id.contains("amazon.nova")
}

fn thinking_budget(level: ThinkingLevel) -> Option<u64> {
    match level {
        ThinkingLevel::Off => None,
        ThinkingLevel::Minimal => Some(1024),
        ThinkingLevel::Low => Some(2048),
        ThinkingLevel::Medium => Some(8192),
        ThinkingLevel::High => Some(16_384),
        ThinkingLevel::Xhigh | ThinkingLevel::Max => Some(32_000),
    }
}

/// Append `block` to the last message when it has `role`, else start one:
/// Converse requires roles to alternate.
fn push_block(messages: &mut Vec<Value>, role: &str, blocks: Vec<Value>) {
    if blocks.is_empty() {
        return;
    }
    if let Some(last) = messages.last_mut() {
        if last["role"] == role {
            if let Some(content) = last["content"].as_array_mut() {
                content.extend(blocks);
                return;
            }
        }
    }
    messages.push(json!({"role": role, "content": blocks}));
}

pub(crate) fn build_request(model: &Model, ctx: &Context, opts: &SimpleStreamOptions) -> Value {
    let images = model.input.contains(&InputModality::Image);
    let thinking = model.reasoning && is_claude(model);
    let mut messages: Vec<Value> = Vec::new();
    for message in &ctx.messages {
        match message {
            Message::User(user) => {
                let blocks = match &user.content {
                    UserContent::Text(text) => vec![json!({"text": text})],
                    UserContent::Blocks(blocks) => blocks
                        .iter()
                        .filter_map(|block| match block {
                            Content::Text(text) if !text.text.is_empty() => {
                                Some(json!({"text": text.text}))
                            }
                            Content::Image(image) if images => {
                                Some(image_block(&image.data, &image.mime_type))
                            }
                            _ => None,
                        })
                        .collect(),
                };
                push_block(&mut messages, "user", blocks);
            }
            Message::Assistant(assistant) => {
                let blocks: Vec<Value> = assistant
                    .content
                    .iter()
                    .filter_map(|block| match block {
                        Content::Text(text) if !text.text.trim().is_empty() => {
                            Some(json!({"text": text.text}))
                        }
                        // Only signed reasoning can be replayed; unsigned text
                        // from another provider is dropped.
                        Content::Thinking(t) if thinking && !t.redacted => t
                            .thinking_signature
                            .as_ref()
                            .map(|signature| {
                                json!({"reasoningContent": {"reasoningText": {
                                    "text": t.thinking, "signature": signature}}})
                            }),
                        Content::Thinking(t) if thinking && t.redacted => t
                            .thinking_signature
                            .as_ref()
                            .map(|data| json!({"reasoningContent": {"redactedContent": data}})),
                        Content::ToolCall(call) => Some(json!({"toolUse": {
                            "toolUseId": call.id,
                            "name": call.name,
                            "input": if call.arguments.is_object() { call.arguments.clone() } else { json!({}) },
                        }})),
                        _ => None,
                    })
                    .collect();
                push_block(&mut messages, "assistant", blocks);
            }
            Message::ToolResult(result) => {
                let mut content: Vec<Value> = result
                    .content
                    .iter()
                    .filter_map(|block| match block {
                        Content::Text(text) if !text.text.is_empty() => {
                            Some(json!({"text": text.text}))
                        }
                        Content::Image(image) if images => {
                            Some(image_block(&image.data, &image.mime_type))
                        }
                        _ => None,
                    })
                    .collect();
                if content.is_empty() {
                    content.push(json!({"text": "(no tool output)"}));
                }
                let mut block = json!({"toolResult": {
                    "toolUseId": result.tool_call_id,
                    "content": content,
                }});
                if result.is_error {
                    block["toolResult"]["status"] = json!("error");
                }
                push_block(&mut messages, "user", vec![block]);
            }
        }
    }
    // Converse requires the conversation to open with a user turn.
    if messages
        .first()
        .is_some_and(|first| first["role"] != "user")
    {
        messages.insert(
            0,
            json!({"role": "user", "content": [{"text": "(continue)"}]}),
        );
    }

    let mut body = Map::new();
    body.insert("messages".into(), Value::Array(messages));
    if let Some(system) = ctx.system_prompt.as_deref().filter(|s| !s.is_empty()) {
        let mut system_blocks = vec![json!({"text": system})];
        if supports_cache_points(model) {
            system_blocks.push(json!({"cachePoint": {"type": "default"}}));
        }
        body.insert("system".into(), Value::Array(system_blocks));
    }

    let budget = thinking
        .then(|| thinking_budget(opts.reasoning_level()))
        .flatten();
    let mut max_tokens = opts.max_tokens.unwrap_or(model.max_tokens);
    if max_tokens == 0 {
        max_tokens = 8192;
    }
    if let Some(budget) = budget {
        // The budget counts toward maxTokens; leave room for the answer.
        max_tokens = max_tokens.max(budget + 4096);
        body.insert(
            "additionalModelRequestFields".into(),
            json!({"thinking": {"type": "enabled", "budget_tokens": budget}}),
        );
    }
    body.insert("inferenceConfig".into(), json!({"maxTokens": max_tokens}));

    if !ctx.tools.is_empty() {
        let tools: Vec<Value> = ctx
            .tools
            .iter()
            .map(|tool| {
                json!({"toolSpec": {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": {"json": tool.parameters.as_value()},
                }})
            })
            .collect();
        body.insert("toolConfig".into(), json!({"tools": tools}));
    }
    if let Some(params) = &model.sampling_params {
        for (name, value) in params {
            body.insert(name.clone(), value.clone());
        }
    }
    Value::Object(body)
}

// ---------------------------------------------------------------------------
// SigV4
// ---------------------------------------------------------------------------

fn sha256_hex(bytes: &[u8]) -> String {
    hex(&Sha256::digest(bytes))
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn hmac_sha256(key: &[u8], message: &[u8]) -> Vec<u8> {
    const BLOCK: usize = 64;
    let mut key_block = [0u8; BLOCK];
    if key.len() > BLOCK {
        key_block[..32].copy_from_slice(&Sha256::digest(key));
    } else {
        key_block[..key.len()].copy_from_slice(key);
    }
    let mut inner = Sha256::new();
    inner.update(key_block.map(|byte| byte ^ 0x36));
    inner.update(message);
    let mut outer = Sha256::new();
    outer.update(key_block.map(|byte| byte ^ 0x5c));
    outer.update(inner.finalize());
    outer.finalize().to_vec()
}

/// `(YYYYMMDD'T'HHMMSS'Z', YYYYMMDD)` for Unix seconds.
fn amz_dates(unix: i64) -> (String, String) {
    let days = unix.div_euclid(86_400);
    let secs = unix.rem_euclid(86_400);
    // Civil-from-days (Howard Hinnant).
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    let date = format!("{y:04}{m:02}{d:02}");
    let time = format!(
        "{date}T{:02}{:02}{:02}Z",
        secs / 3600,
        (secs % 3600) / 60,
        secs % 60
    );
    (time, date)
}

/// RFC 3986 encoding of one path segment, as SigV4 requires.
fn uri_encode(segment: &str) -> String {
    let mut out = String::new();
    for byte in segment.bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(byte as char)
            }
            other => out.push_str(&format!("%{other:02X}")),
        }
    }
    out
}

/// Headers that sign `POST {url}` with `body` for `service` in `region`.
pub(crate) fn sigv4_headers(
    credential: &IamCredential,
    region: &str,
    service: &str,
    method: &str,
    url: &reqwest::Url,
    body: &[u8],
    unix: i64,
) -> BTreeMap<String, String> {
    let (amz_date, date) = amz_dates(unix);
    let host = match url.port() {
        Some(port) => format!("{}:{port}", url.host_str().unwrap_or_default()),
        None => url.host_str().unwrap_or_default().to_string(),
    };
    let payload_hash = sha256_hex(body);
    // Non-S3 services sign the path with each segment encoded twice: the
    // URL already carries it encoded once.
    let canonical_uri = url
        .path()
        .split('/')
        .map(uri_encode)
        .collect::<Vec<_>>()
        .join("/");
    let mut query: Vec<(String, String)> = url
        .query_pairs()
        .map(|(k, v)| (uri_encode(&k), uri_encode(&v)))
        .collect();
    query.sort();
    let canonical_query = query
        .iter()
        .map(|(k, v)| format!("{k}={v}"))
        .collect::<Vec<_>>()
        .join("&");
    let mut signed: BTreeMap<String, String> = BTreeMap::new();
    signed.insert("host".into(), host);
    signed.insert("x-amz-date".into(), amz_date.clone());
    signed.insert("x-amz-content-sha256".into(), payload_hash.clone());
    if let Some(token) = &credential.session_token {
        signed.insert("x-amz-security-token".into(), token.clone());
    }
    let canonical_headers: String = signed
        .iter()
        .map(|(k, v)| format!("{k}:{}\n", v.trim()))
        .collect();
    let signed_headers = signed.keys().cloned().collect::<Vec<_>>().join(";");
    let canonical_request = format!(
        "{method}\n{canonical_uri}\n{canonical_query}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
    );
    let scope = format!("{date}/{region}/{service}/aws4_request");
    let string_to_sign = format!(
        "AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n{}",
        sha256_hex(canonical_request.as_bytes())
    );
    let k_date = hmac_sha256(
        format!("AWS4{}", credential.secret_access_key).as_bytes(),
        date.as_bytes(),
    );
    let k_region = hmac_sha256(&k_date, region.as_bytes());
    let k_service = hmac_sha256(&k_region, service.as_bytes());
    let k_signing = hmac_sha256(&k_service, b"aws4_request");
    let signature = hex(&hmac_sha256(&k_signing, string_to_sign.as_bytes()));
    let mut headers = signed;
    headers.remove("host");
    headers.insert(
        "authorization".into(),
        format!(
            "AWS4-HMAC-SHA256 Credential={}/{scope}, SignedHeaders={signed_headers}, Signature={signature}",
            credential.access_key_id
        ),
    );
    headers
}

/// Auth headers for a Bedrock request: SigV4 for IAM keys, else Bearer.
pub fn auth_headers(
    credential: &str,
    region: &str,
    service: &str,
    method: &str,
    url: &reqwest::Url,
    body: &[u8],
) -> BTreeMap<String, String> {
    match decode_iam_credential(credential) {
        Some(iam) => {
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs() as i64)
                .unwrap_or(0);
            sigv4_headers(&iam, region, service, method, url, body, now)
        }
        None => BTreeMap::from([("authorization".into(), format!("Bearer {credential}"))]),
    }
}

// ---------------------------------------------------------------------------
// Event stream
// ---------------------------------------------------------------------------

/// One decoded `application/vnd.amazon.eventstream` message.
#[derive(Debug, PartialEq)]
pub(crate) struct EventMessage {
    pub headers: BTreeMap<String, String>,
    pub payload: Vec<u8>,
}

/// Incremental decoder for AWS event-stream framing:
/// `total_len u32 | headers_len u32 | prelude_crc u32 | headers | payload | crc u32`.
#[derive(Default)]
pub(crate) struct EventStreamDecoder {
    buffer: Vec<u8>,
}

impl EventStreamDecoder {
    pub fn push(&mut self, bytes: &[u8]) {
        self.buffer.extend_from_slice(bytes);
    }

    pub fn next(&mut self) -> Result<Option<EventMessage>, String> {
        if self.buffer.len() < 12 {
            return Ok(None);
        }
        let total = u32::from_be_bytes(self.buffer[0..4].try_into().unwrap()) as usize;
        let headers_len = u32::from_be_bytes(self.buffer[4..8].try_into().unwrap()) as usize;
        if total < 16 || headers_len + 16 > total || total > 16 * 1024 * 1024 {
            return Err("malformed event-stream frame".into());
        }
        if self.buffer.len() < total {
            return Ok(None);
        }
        let frame: Vec<u8> = self.buffer.drain(..total).collect();
        let mut headers = BTreeMap::new();
        let raw = &frame[12..12 + headers_len];
        let mut at = 0;
        while at < raw.len() {
            let name_len = raw[at] as usize;
            at += 1;
            let name = String::from_utf8_lossy(raw.get(at..at + name_len).ok_or("bad header")?)
                .into_owned();
            at += name_len;
            let kind = *raw.get(at).ok_or("bad header")?;
            at += 1;
            let skip = |n: usize, at: &mut usize| -> Result<(), String> {
                if *at + n > raw.len() {
                    return Err("bad header".into());
                }
                *at += n;
                Ok(())
            };
            match kind {
                0 | 1 => {}
                2 => skip(1, &mut at)?,
                3 => skip(2, &mut at)?,
                4 => skip(4, &mut at)?,
                5 | 8 => skip(8, &mut at)?,
                9 => skip(16, &mut at)?,
                6 | 7 => {
                    let len = u16::from_be_bytes(
                        raw.get(at..at + 2).ok_or("bad header")?.try_into().unwrap(),
                    ) as usize;
                    at += 2;
                    let value = raw.get(at..at + len).ok_or("bad header")?;
                    if kind == 7 {
                        headers.insert(name, String::from_utf8_lossy(value).into_owned());
                    }
                    at += len;
                }
                _ => return Err(format!("unknown event-stream header type {kind}")),
            }
        }
        let payload = frame[12 + headers_len..total - 4].to_vec();
        Ok(Some(EventMessage { headers, payload }))
    }
}

// ---------------------------------------------------------------------------
// Streaming
// ---------------------------------------------------------------------------

enum BlockKind {
    Text,
    Thinking,
    Tool { arguments: String },
}

struct Block {
    content_index: usize,
    kind: BlockKind,
}

struct StreamState {
    output: AssistantMessage,
    blocks: BTreeMap<u64, Block>,
    stop: Option<DoneReason>,
    stop_error: Option<String>,
    started: bool,
}

fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

impl StreamState {
    fn new(model: &Model) -> Self {
        Self {
            output: AssistantMessage::empty(
                Api::BedrockConverseStream,
                model.provider.clone(),
                model.id.clone(),
                now_ms(),
            ),
            blocks: BTreeMap::new(),
            stop: None,
            stop_error: None,
            started: false,
        }
    }

    fn partial(&self) -> Arc<AssistantMessage> {
        Arc::new(self.output.clone())
    }

    async fn start(&mut self, producer: &mut AssistantMessageEventStreamProducer) {
        if !self.started {
            self.started = true;
            producer
                .push(AssistantMessageEvent::Start {
                    partial: self.partial(),
                })
                .await;
        }
    }

    async fn open(
        &mut self,
        producer: &mut AssistantMessageEventStreamProducer,
        index: u64,
        kind: BlockKind,
    ) -> usize {
        if let Some(block) = self.blocks.get(&index) {
            return block.content_index;
        }
        let content_index = self.output.content.len();
        let placeholder = self.output.clone();
        let event = match &kind {
            BlockKind::Text => {
                self.output.content.push(Content::text(""));
                AssistantMessageEvent::TextStart {
                    content_index,
                    partial: Arc::new(placeholder.clone()),
                }
            }
            BlockKind::Thinking => {
                self.output.content.push(Content::Thinking(ThinkingContent {
                    kind: ThinkingContentType,
                    thinking: String::new(),
                    thinking_signature: None,
                    redacted: false,
                }));
                AssistantMessageEvent::ThinkingStart {
                    content_index,
                    partial: Arc::new(placeholder.clone()),
                }
            }
            BlockKind::Tool { .. } => AssistantMessageEvent::ToolCallStart {
                content_index,
                partial: Arc::new(placeholder.clone()),
            },
        };
        self.blocks.insert(
            index,
            Block {
                content_index,
                kind,
            },
        );
        let event = match event {
            AssistantMessageEvent::TextStart { content_index, .. } => {
                AssistantMessageEvent::TextStart {
                    content_index,
                    partial: self.partial(),
                }
            }
            AssistantMessageEvent::ThinkingStart { content_index, .. } => {
                AssistantMessageEvent::ThinkingStart {
                    content_index,
                    partial: self.partial(),
                }
            }
            AssistantMessageEvent::ToolCallStart { content_index, .. } => {
                AssistantMessageEvent::ToolCallStart {
                    content_index,
                    partial: self.partial(),
                }
            }
            other => other,
        };
        producer.push(event).await;
        content_index
    }

    async fn apply(
        &mut self,
        producer: &mut AssistantMessageEventStreamProducer,
        event_type: &str,
        payload: &Value,
    ) {
        let index = payload
            .get("contentBlockIndex")
            .and_then(Value::as_u64)
            .unwrap_or(0);
        match event_type {
            "messageStart" => {}
            "contentBlockStart" => {
                if let Some(tool) = payload.pointer("/start/toolUse") {
                    let content_index = self.output.content.len();
                    self.output.content.push(Content::tool_call(
                        tool.get("toolUseId")
                            .and_then(Value::as_str)
                            .unwrap_or_default(),
                        tool.get("name").and_then(Value::as_str).unwrap_or_default(),
                        json!({}),
                    ));
                    self.blocks.insert(
                        index,
                        Block {
                            content_index,
                            kind: BlockKind::Tool {
                                arguments: String::new(),
                            },
                        },
                    );
                    producer
                        .push(AssistantMessageEvent::ToolCallStart {
                            content_index,
                            partial: self.partial(),
                        })
                        .await;
                }
            }
            "contentBlockDelta" => {
                let delta = payload.get("delta").unwrap_or(&Value::Null);
                if let Some(text) = delta.get("text").and_then(Value::as_str) {
                    let content_index = self.open(producer, index, BlockKind::Text).await;
                    if let Some(Content::Text(t)) = self.output.content.get_mut(content_index) {
                        t.text.push_str(text);
                    }
                    producer
                        .push(AssistantMessageEvent::TextDelta {
                            content_index,
                            delta: text.to_string(),
                            partial: self.partial(),
                        })
                        .await;
                } else if let Some(reasoning) = delta.get("reasoningContent") {
                    let content_index = self.open(producer, index, BlockKind::Thinking).await;
                    let text = reasoning.get("text").and_then(Value::as_str);
                    if let Some(Content::Thinking(t)) = self.output.content.get_mut(content_index) {
                        if let Some(text) = text {
                            t.thinking.push_str(text);
                        }
                        if let Some(signature) = reasoning.get("signature").and_then(Value::as_str)
                        {
                            t.thinking_signature = Some(signature.to_string());
                        }
                        if let Some(redacted) =
                            reasoning.get("redactedContent").and_then(Value::as_str)
                        {
                            t.redacted = true;
                            t.thinking_signature = Some(redacted.to_string());
                        }
                    }
                    if let Some(text) = text.filter(|text| !text.is_empty()) {
                        producer
                            .push(AssistantMessageEvent::ThinkingDelta {
                                content_index,
                                delta: text.to_string(),
                                partial: self.partial(),
                            })
                            .await;
                    }
                } else if let Some(input) = delta.pointer("/toolUse/input").and_then(Value::as_str)
                {
                    let Some(block) = self.blocks.get_mut(&index) else {
                        return;
                    };
                    let content_index = block.content_index;
                    if let BlockKind::Tool { arguments } = &mut block.kind {
                        arguments.push_str(input);
                        let parsed = parse_streaming_json(Some(arguments));
                        if let Some(Content::ToolCall(call)) =
                            self.output.content.get_mut(content_index)
                        {
                            call.arguments = parsed;
                        }
                    }
                    producer
                        .push(AssistantMessageEvent::ToolCallDelta {
                            content_index,
                            delta: input.to_string(),
                            partial: self.partial(),
                        })
                        .await;
                }
            }
            "contentBlockStop" => self.close(producer, index).await,
            "messageStop" => {
                let reason = payload
                    .get("stopReason")
                    .and_then(Value::as_str)
                    .unwrap_or("end_turn");
                self.output.raw_stop_reason = Some(reason.to_string());
                match reason {
                    "end_turn" | "stop_sequence" => self.stop = Some(DoneReason::Stop),
                    "tool_use" => self.stop = Some(DoneReason::ToolUse),
                    "max_tokens" | "model_context_window_exceeded" => {
                        self.stop = Some(DoneReason::Length)
                    }
                    other => self.stop_error = Some(format!("Bedrock stopped: {other}")),
                }
            }
            "metadata" => {
                if let Some(usage) = payload.get("usage") {
                    let get = |name: &str| usage.get(name).and_then(Value::as_i64).unwrap_or(0);
                    self.output.usage.input = get("inputTokens");
                    self.output.usage.output = get("outputTokens");
                    self.output.usage.cache_read = get("cacheReadInputTokens");
                    self.output.usage.cache_write = get("cacheWriteInputTokens");
                    self.output.usage.total_tokens = self.output.usage.input
                        + self.output.usage.output
                        + self.output.usage.cache_read
                        + self.output.usage.cache_write;
                }
                producer.commit_metadata(&self.output);
            }
            _ => {}
        }
    }

    async fn close(&mut self, producer: &mut AssistantMessageEventStreamProducer, index: u64) {
        let Some(block) = self.blocks.remove(&index) else {
            return;
        };
        let content_index = block.content_index;
        let event = match block.kind {
            BlockKind::Text => {
                let content = match self.output.content.get(content_index) {
                    Some(Content::Text(t)) => t.text.clone(),
                    _ => String::new(),
                };
                AssistantMessageEvent::TextEnd {
                    content_index,
                    content,
                    partial: self.partial(),
                }
            }
            BlockKind::Thinking => {
                let content = match self.output.content.get(content_index) {
                    Some(Content::Thinking(t)) => t.thinking.clone(),
                    _ => String::new(),
                };
                AssistantMessageEvent::ThinkingEnd {
                    content_index,
                    content,
                    partial: self.partial(),
                }
            }
            BlockKind::Tool { arguments } => {
                let (id, name) = match self.output.content.get(content_index) {
                    Some(Content::ToolCall(call)) => (call.id.clone(), call.name.clone()),
                    _ => (String::new(), String::new()),
                };
                let call = ToolCall {
                    kind: ToolCallType,
                    id,
                    name,
                    arguments: parse_streaming_json(Some(&arguments)),
                    thought_signature: None,
                    namespace: None,
                    recorded: None,
                };
                if let Some(slot) = self.output.content.get_mut(content_index) {
                    *slot = Content::ToolCall(call.clone());
                }
                AssistantMessageEvent::ToolCallEnd {
                    content_index,
                    tool_call: call,
                    partial: self.partial(),
                }
            }
        };
        producer.push(event).await;
    }

    async fn finish(&mut self, producer: &mut AssistantMessageEventStreamProducer, model: &Model) {
        let open: Vec<u64> = self.blocks.keys().copied().collect();
        for index in open {
            self.close(producer, index).await;
        }
        if let Some(message) = self.stop_error.take() {
            self.error(producer, message, false).await;
            return;
        }
        let has_tools = self
            .output
            .content
            .iter()
            .any(|content| matches!(content, Content::ToolCall(_)));
        let reason = self.stop.unwrap_or(if has_tools {
            DoneReason::ToolUse
        } else {
            DoneReason::Stop
        });
        self.output.stop_reason = reason.into();
        self.output.usage.cost = calculate_cost(&model.cost, &self.output.usage);
        producer
            .push(AssistantMessageEvent::Done {
                reason,
                message: self.output.clone(),
            })
            .await;
    }

    async fn error(
        &mut self,
        producer: &mut AssistantMessageEventStreamProducer,
        message: String,
        aborted: bool,
    ) {
        self.output.stop_reason = if aborted {
            StopReason::Aborted
        } else {
            StopReason::Error
        };
        self.output.error_message = Some(message);
        producer
            .push(AssistantMessageEvent::Error {
                reason: if aborted {
                    ErrorReason::Aborted
                } else {
                    ErrorReason::Error
                },
                error: self.output.clone(),
            })
            .await;
    }
}

/// Bedrock's error bodies are `{"message": "…"}` (or `Message`).
fn error_message(body: &str) -> String {
    serde_json::from_str::<Value>(body)
        .ok()
        .and_then(|value| {
            value
                .get("message")
                .or_else(|| value.get("Message"))
                .and_then(Value::as_str)
                .map(str::to_string)
        })
        .unwrap_or_else(|| body.chars().take(500).collect())
}

async fn run_stream(
    producer: &mut AssistantMessageEventStreamProducer,
    http: reqwest::Client,
    model: &Model,
    body: Value,
    opts: &SimpleStreamOptions,
) {
    let mut state = StreamState::new(model);
    let Some(mut credential) = opts.api_key.clone().filter(|key| !key.trim().is_empty()) else {
        state
            .error(
                producer,
                format!("No credentials for provider: {}", model.provider),
                false,
            )
            .await;
        return;
    };
    if let Some(profile) =
        credential.strip_prefix(super::aws_credentials::PROFILE_CREDENTIAL_PREFIX)
    {
        match super::aws_credentials::resolve(&http, profile).await {
            Ok(iam) => credential = encode_iam_credential(&iam),
            Err(error) => {
                state
                    .error(producer, format!("AWS credentials: {error}"), false)
                    .await;
                return;
            }
        }
    }
    let base = model.base_url.trim_end_matches('/');
    let region = region_of(base).unwrap_or_else(|| "us-east-1".into());
    let url = format!("{base}/model/{}/converse-stream", uri_encode(&model.id));
    let Ok(parsed_url) = reqwest::Url::parse(&url) else {
        state
            .error(producer, format!("Invalid Bedrock endpoint: {url}"), false)
            .await;
        return;
    };
    let bytes = match serde_json::to_vec(&body) {
        Ok(bytes) => bytes,
        Err(error) => {
            state
                .error(
                    producer,
                    format!("failed to encode request: {error}"),
                    false,
                )
                .await;
            return;
        }
    };
    drop(body);
    let mut extra = BTreeMap::new();
    for headers in [model.headers.as_ref(), opts.headers.as_ref()]
        .into_iter()
        .flatten()
    {
        for (name, value) in headers {
            if !name.eq_ignore_ascii_case("authorization") {
                extra.insert(name.clone(), value.clone());
            }
        }
    }
    crate::http::ensure_user_agent(&mut extra);
    let timeout = opts.request_timeout();
    let signal = opts.signal.clone();
    let response = retry_provider_request(
        || {
            let http = http.clone();
            let bytes = bytes.clone();
            let url = parsed_url.clone();
            let extra = extra.clone();
            let credential = credential.clone();
            let region = region.clone();
            let signal = signal.clone();
            async move {
                // Signed per attempt: a SigV4 signature carries its timestamp.
                let auth = auth_headers(&credential, &region, "bedrock", "POST", &url, &bytes);
                let mut request = http
                    .post(url)
                    .timeout(timeout)
                    .header("content-type", "application/json")
                    .header("accept", "application/vnd.amazon.eventstream");
                for (name, value) in extra.iter().chain(auth.iter()) {
                    request = request.header(name, value);
                }
                let response = tokio::select! {
                    result = request.body(bytes).send() => result.map_err(|error| AiError::Http { status: None, message: error.to_string() })?,
                    _ = signal.cancelled() => return Err(AiError::Abort { message: "Request aborted".into() }),
                };
                let status = response.status();
                if status.is_success() {
                    Ok(response)
                } else {
                    let text = response.text().await.unwrap_or_default();
                    Err(AiError::Http {
                        status: Some(status.as_u16()),
                        message: error_message(&text),
                    })
                }
            }
        },
        opts.max_retries,
        opts.max_retry_delay,
        &opts.signal,
    )
    .await;
    let response = match response {
        Ok(response) => response,
        Err(error) => {
            state
                .error(producer, error.to_string(), error.is_abort())
                .await;
            return;
        }
    };

    state.start(producer).await;
    let mut body = response.bytes_stream();
    let mut decoder = EventStreamDecoder::default();
    let idle = opts.stream_idle_timeout();
    loop {
        let next = tokio::select! {
            _ = opts.signal.cancelled() => {
                state.error(producer, "Request aborted".into(), true).await;
                return;
            }
            next = async {
                match idle {
                    Some(idle) => tokio::time::timeout(idle, body.next()).await.ok(),
                    None => Some(body.next().await),
                }
            } => next,
        };
        let chunk = match next {
            None => {
                state
                    .error(producer, "Bedrock stream stalled".into(), false)
                    .await;
                return;
            }
            Some(None) => {
                state.finish(producer, model).await;
                return;
            }
            Some(Some(Err(error))) => {
                state
                    .error(producer, format!("Bedrock stream failed: {error}"), false)
                    .await;
                return;
            }
            Some(Some(Ok(chunk))) => chunk,
        };
        decoder.push(&chunk);
        loop {
            let message = match decoder.next() {
                Ok(Some(message)) => message,
                Ok(None) => break,
                Err(error) => {
                    state.error(producer, error, false).await;
                    return;
                }
            };
            let payload: Value = serde_json::from_slice(&message.payload).unwrap_or(Value::Null);
            match message.headers.get(":message-type").map(String::as_str) {
                Some("exception") | Some("error") => {
                    let kind = message
                        .headers
                        .get(":exception-type")
                        .or_else(|| message.headers.get(":error-code"))
                        .cloned()
                        .unwrap_or_else(|| "error".into());
                    let text = payload
                        .get("message")
                        .or_else(|| payload.get("Message"))
                        .and_then(Value::as_str)
                        .unwrap_or("Bedrock stream error");
                    state
                        .error(producer, format!("{kind}: {text}"), false)
                        .await;
                    return;
                }
                _ => {
                    let event_type = message
                        .headers
                        .get(":event-type")
                        .cloned()
                        .unwrap_or_default();
                    state.apply(producer, &event_type, &payload).await;
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn frame(headers: &[(&str, &str)], payload: &[u8]) -> Vec<u8> {
        let mut raw = Vec::new();
        for (name, value) in headers {
            raw.push(name.len() as u8);
            raw.extend_from_slice(name.as_bytes());
            raw.push(7);
            raw.extend_from_slice(&(value.len() as u16).to_be_bytes());
            raw.extend_from_slice(value.as_bytes());
        }
        let total = 12 + raw.len() + payload.len() + 4;
        let mut out = Vec::new();
        out.extend_from_slice(&(total as u32).to_be_bytes());
        out.extend_from_slice(&(raw.len() as u32).to_be_bytes());
        out.extend_from_slice(&[0; 4]);
        out.extend_from_slice(&raw);
        out.extend_from_slice(payload);
        out.extend_from_slice(&[0; 4]);
        out
    }

    #[test]
    fn decodes_split_frames() {
        let bytes = frame(
            &[
                (":message-type", "event"),
                (":event-type", "contentBlockDelta"),
            ],
            br#"{"contentBlockIndex":0,"delta":{"text":"hi"}}"#,
        );
        let mut decoder = EventStreamDecoder::default();
        decoder.push(&bytes[..10]);
        assert_eq!(decoder.next().unwrap(), None);
        decoder.push(&bytes[10..]);
        let message = decoder.next().unwrap().unwrap();
        assert_eq!(message.headers[":event-type"], "contentBlockDelta");
        assert!(message.payload.starts_with(b"{\"contentBlockIndex\""));
        assert_eq!(decoder.next().unwrap(), None);
    }

    #[test]
    fn sigv4_matches_the_aws_reference_vector() {
        // AWS SigV4 test suite "get-vanilla" (service "service", region us-east-1).
        let credential = IamCredential {
            access_key_id: "AKIDEXAMPLE".into(),
            secret_access_key: "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY".into(),
            session_token: None,
        };
        let url = reqwest::Url::parse("https://example.amazonaws.com/").unwrap();
        // 20150830T123600Z
        let headers = sigv4_headers(
            &credential,
            "us-east-1",
            "service",
            "GET",
            &url,
            b"",
            1_440_938_160,
        );
        assert_eq!(headers["x-amz-date"], "20150830T123600Z");
        assert!(headers["authorization"].starts_with(
            "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, SignedHeaders=host;x-amz-content-sha256;x-amz-date, Signature="
        ));
    }

    #[test]
    fn hmac_matches_rfc4231_case_2() {
        let mac = hmac_sha256(b"Jefe", b"what do ya want for nothing?");
        assert_eq!(
            hex(&mac),
            "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"
        );
    }

    #[test]
    fn iam_credentials_round_trip_and_region_parses() {
        let iam = IamCredential {
            access_key_id: "AKIA".into(),
            secret_access_key: "secret".into(),
            session_token: Some("token".into()),
        };
        let decoded = decode_iam_credential(&encode_iam_credential(&iam)).unwrap();
        assert_eq!(decoded.session_token.as_deref(), Some("token"));
        assert!(decode_iam_credential("plain-bedrock-api-key").is_none());
        assert_eq!(
            region_of("https://bedrock-runtime.eu-west-1.amazonaws.com").as_deref(),
            Some("eu-west-1")
        );
    }

    #[test]
    fn builds_alternating_converse_messages_with_tools() {
        use crate::types::{ToolResultMessage, UserMessage};
        let mut model = Model::new(
            "us.anthropic.claude-sonnet-4-6",
            "Claude",
            Api::BedrockConverseStream,
            "bedrock",
            "https://bedrock-runtime.us-east-1.amazonaws.com",
        );
        model.reasoning = true;
        let mut assistant = AssistantMessage::empty(Api::BedrockConverseStream, "bedrock", "m", 0);
        assistant.content = vec![
            Content::text("Let me look."),
            Content::tool_call("t1", "read", json!({"path": "a"})),
        ];
        let tool_result: ToolResultMessage = serde_json::from_value(json!({
            "role": "toolResult", "toolCallId": "t1", "toolName": "read",
            "content": [{"type": "text", "text": "contents"}], "isError": false, "timestamp": 0
        }))
        .unwrap();
        let mut ctx = Context::new(vec![
            Message::User(UserMessage::new("hi", 0)),
            Message::Assistant(Box::new(assistant)),
            Message::ToolResult(Box::new(tool_result)),
        ]);
        ctx.system_prompt = Some("be brief".into());
        let mut opts = SimpleStreamOptions::default();
        opts.reasoning = Some(ThinkingLevel::Medium);
        let body = build_request(&model, &ctx, &opts);
        let messages = body["messages"].as_array().unwrap();
        assert_eq!(messages.len(), 3);
        assert_eq!(messages[1]["content"][1]["toolUse"]["toolUseId"], "t1");
        assert_eq!(messages[2]["content"][0]["toolResult"]["toolUseId"], "t1");
        assert_eq!(body["system"][1]["cachePoint"]["type"], "default");
        assert_eq!(
            body["additionalModelRequestFields"]["thinking"]["budget_tokens"],
            8192
        );
        assert!(body["inferenceConfig"]["maxTokens"].as_u64().unwrap() > 8192);
    }
}
