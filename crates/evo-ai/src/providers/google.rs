//! Google Gemini API provider (`google-generative-ai`).
//!
//! Ported from EvoFlux's `googlegenai/googlegenai.py`. Gemini's own API, not
//! its OpenAI-compatible shim, because only the native API carries what tool
//! calling and reasoning need:
//!
//! - **Thought signatures.** Gemini 3 signs each function call (and the end of
//!   its text); the signature must come back with the call on the next
//!   request, or the request is rejected. They are kept on
//!   [`ToolCall::thought_signature`] and [`TextContent::text_signature`] and
//!   replayed only to the model that produced them.
//! - **Thinking.** `thinkingConfig` takes `thinkingLevel` on Gemini 3 (named
//!   efforts, from models.dev) and `thinkingBudget` on 2.5; `includeThoughts`
//!   streams the reasoning summary as `thought: true` parts.
//! - **Endpoint.** `POST {base}/models/{model}:streamGenerateContent?alt=sse`
//!   with `x-goog-api-key`, `base` being `…/v1beta`.

use std::collections::BTreeMap;
use std::sync::Arc;

use async_trait::async_trait;
use serde_json::{json, Map, Value};

use crate::event_stream::{
    create_assistant_message_event_stream_with_cancellation, AssistantMessageEventStream,
    AssistantMessageEventStreamProducer,
};
use crate::model::Model;
use crate::provider::{Provider, SimpleStreamOptions};
use crate::providers::anthropic::cost::calculate_cost;
use crate::providers::anthropic::retry::retry_provider_request;
use crate::providers::anthropic::sse::SseEventStream;
use crate::types::{
    Api, AssistantMessage, AssistantMessageEvent, Content, Context, DoneReason, ErrorReason,
    InputModality, Message, StopReason, ThinkingContent, ThinkingContentType, ThinkingLevel,
    ToolCall, ToolCallType, UserContent,
};
use crate::AiError;

/// Accepted in place of a signature for a call Gemini did not sign (one made
/// by another model before a switch); Google documents this value for it.
const SKIP_SIGNATURE: &str = "skip_thought_signature_validator";

/// JSON-Schema keys Gemini's function declarations reject with a 400
/// (EvoFlux `_UNSUPPORTED_SCHEMA_KEYS`).
const UNSUPPORTED_SCHEMA_KEYS: &[&str] = &[
    "discriminator",
    "const",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "additionalProperties",
    "$schema",
    "$id",
    "$ref",
    "contentEncoding",
    "contentMediaType",
];

pub struct GoogleProvider {
    id: String,
    http: reqwest::Client,
    models: Vec<Model>,
}

impl GoogleProvider {
    pub fn with_models(id: impl Into<String>, http: reqwest::Client, models: Vec<Model>) -> Self {
        Self {
            id: id.into(),
            http,
            models,
        }
    }
}

#[async_trait]
impl Provider for GoogleProvider {
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

fn sanitize_schema(schema: &Value) -> Value {
    match schema {
        Value::Object(map) => Value::Object(
            map.iter()
                .filter(|(key, _)| !UNSUPPORTED_SCHEMA_KEYS.contains(&key.as_str()))
                .map(|(key, value)| (key.clone(), sanitize_schema(value)))
                .collect(),
        ),
        Value::Array(items) => Value::Array(items.iter().map(sanitize_schema).collect()),
        other => other.clone(),
    }
}

fn inline_image(data: &str, mime: &str) -> Value {
    json!({"inlineData": {"mimeType": mime, "data": data}})
}

/// Gemini 3 and later sign their reasoning; earlier models never do.
fn requires_signatures(model: &Model) -> bool {
    let id = model.id.to_ascii_lowercase();
    !(id.starts_with("gemini-1") || id.starts_with("gemini-2") || id.contains("gemma"))
}

/// Append `parts` to the last turn when it has `role`, else start a turn:
/// Gemini wants roles to alternate.
fn push_parts(contents: &mut Vec<Value>, role: &str, parts: Vec<Value>) {
    if parts.is_empty() {
        return;
    }
    if let Some(last) = contents.last_mut() {
        if last["role"] == role {
            if let Some(existing) = last["parts"].as_array_mut() {
                existing.extend(parts);
                return;
            }
        }
    }
    contents.push(json!({"role": role, "parts": parts}));
}

/// The named effort to send for `level`, from models.dev's levels: the
/// requested one when the model has it, else the nearest it has (lower first).
fn effort_for(model: &Model, level: ThinkingLevel) -> Option<String> {
    let map = model.thinking_level_map.as_ref()?;
    const ORDER: [ThinkingLevel; 6] = [
        ThinkingLevel::Minimal,
        ThinkingLevel::Low,
        ThinkingLevel::Medium,
        ThinkingLevel::High,
        ThinkingLevel::Xhigh,
        ThinkingLevel::Max,
    ];
    let supported: Vec<(usize, String)> = ORDER
        .iter()
        .enumerate()
        .filter_map(|(rank, level)| map.get(level).cloned().flatten().map(|value| (rank, value)))
        .collect();
    let wanted = ORDER.iter().position(|l| *l == level).unwrap_or(0);
    supported
        .iter()
        .rev()
        .find(|(rank, _)| *rank <= wanted)
        .or_else(|| supported.first())
        .map(|(_, value)| value.clone())
}

fn thinking_budget(model: &Model, level: ThinkingLevel) -> Option<i64> {
    let pro = model.id.to_ascii_lowercase().contains("pro");
    Some(match level {
        ThinkingLevel::Off => return (!pro).then_some(0),
        ThinkingLevel::Minimal => 512,
        ThinkingLevel::Low => 2048,
        ThinkingLevel::Medium => 8192,
        ThinkingLevel::High => 16_384,
        ThinkingLevel::Xhigh | ThinkingLevel::Max => {
            if pro {
                32_768
            } else {
                24_576
            }
        }
    })
}

/// `thinkingConfig` for the requested level, or `None` to leave the model's
/// default (a model with no thinking control).
fn thinking_config(model: &Model, level: ThinkingLevel) -> Option<Value> {
    if !model.reasoning {
        return None;
    }
    if model.thinking_level_map.is_some() {
        // Named efforts (Gemini 3). Thinking cannot be switched off; "off"
        // asks for the least and hides it.
        let effective = if level == ThinkingLevel::Off {
            ThinkingLevel::Minimal
        } else {
            level
        };
        let effort = effort_for(model, effective)?;
        return Some(json!({
            "thinkingLevel": effort,
            "includeThoughts": level != ThinkingLevel::Off,
        }));
    }
    match thinking_budget(model, level) {
        Some(0) => Some(json!({"thinkingBudget": 0})),
        Some(budget) => Some(json!({"thinkingBudget": budget, "includeThoughts": true})),
        // A model that cannot stop thinking: leave its default, hidden.
        None => None,
    }
}

pub(crate) fn build_request(model: &Model, ctx: &Context, opts: &SimpleStreamOptions) -> Value {
    let images = model.input.contains(&InputModality::Image);
    let signed = requires_signatures(model);
    let mut contents: Vec<Value> = Vec::new();
    for message in &ctx.messages {
        match message {
            Message::User(user) => {
                let parts = match &user.content {
                    UserContent::Text(text) if !text.is_empty() => vec![json!({"text": text})],
                    UserContent::Text(_) => Vec::new(),
                    UserContent::Blocks(blocks) => blocks
                        .iter()
                        .filter_map(|block| match block {
                            Content::Text(text) if !text.text.is_empty() => {
                                Some(json!({"text": text.text}))
                            }
                            Content::Image(image) if images => {
                                Some(inline_image(&image.data, &image.mime_type))
                            }
                            _ => None,
                        })
                        .collect(),
                };
                push_parts(&mut contents, "user", parts);
            }
            Message::Assistant(assistant) => {
                // Signatures are only valid for the model that made them.
                let same_model =
                    assistant.provider == model.provider && assistant.model == model.id;
                let mut parts = Vec::new();
                for block in &assistant.content {
                    match block {
                        Content::Thinking(thinking) if same_model && !thinking.redacted => {
                            if let Some(signature) = &thinking.thinking_signature {
                                let mut part = json!({"text": thinking.thinking, "thought": true});
                                part["thoughtSignature"] = json!(signature);
                                parts.push(part);
                            }
                        }
                        Content::Text(text) if !text.text.is_empty() => {
                            let mut part = json!({"text": text.text});
                            if same_model {
                                if let Some(signature) = &text.text_signature {
                                    part["thoughtSignature"] = json!(signature);
                                }
                            }
                            parts.push(part);
                        }
                        Content::ToolCall(call) => {
                            let mut part = json!({"functionCall": {
                                "name": call.name,
                                "args": if call.arguments.is_object() { call.arguments.clone() } else { json!({}) },
                            }});
                            let signature = call
                                .thought_signature
                                .as_deref()
                                .filter(|_| same_model)
                                .or(signed.then_some(SKIP_SIGNATURE));
                            if let Some(signature) = signature {
                                part["thoughtSignature"] = json!(signature);
                            }
                            parts.push(part);
                        }
                        _ => {}
                    }
                }
                push_parts(&mut contents, "model", parts);
            }
            Message::ToolResult(result) => {
                let text: String = result
                    .content
                    .iter()
                    .filter_map(|block| match block {
                        Content::Text(text) => Some(text.text.as_str()),
                        _ => None,
                    })
                    .collect::<Vec<_>>()
                    .join("\n");
                let key = if result.is_error { "error" } else { "output" };
                let mut parts = vec![json!({"functionResponse": {
                    "name": result.tool_name,
                    "response": {key: if text.is_empty() { "(no output)".to_string() } else { text }},
                }})];
                if images {
                    parts.extend(result.content.iter().filter_map(|block| match block {
                        Content::Image(image) => Some(inline_image(&image.data, &image.mime_type)),
                        _ => None,
                    }));
                }
                push_parts(&mut contents, "user", parts);
            }
        }
    }
    // The conversation must open with a user turn (compaction can leave a
    // model turn first).
    if contents
        .first()
        .is_some_and(|first| first["role"] != "user")
    {
        contents.insert(
            0,
            json!({"role": "user", "parts": [{"text": "(continue)"}]}),
        );
    }

    let mut body = Map::new();
    body.insert("contents".into(), Value::Array(contents));
    if let Some(system) = ctx.system_prompt.as_deref().filter(|s| !s.is_empty()) {
        body.insert(
            "systemInstruction".into(),
            json!({"parts": [{"text": system}]}),
        );
    }
    let mut generation = Map::new();
    let max_tokens = opts.max_tokens.unwrap_or(model.max_tokens);
    if max_tokens > 0 {
        generation.insert("maxOutputTokens".into(), json!(max_tokens));
    }
    if let Some(config) = thinking_config(model, opts.reasoning_level()) {
        generation.insert("thinkingConfig".into(), config);
    }
    if !generation.is_empty() {
        body.insert("generationConfig".into(), Value::Object(generation));
    }
    if !ctx.tools.is_empty() {
        let declarations: Vec<Value> = ctx
            .tools
            .iter()
            .map(|tool| {
                json!({
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": sanitize_schema(tool.parameters.as_value()),
                })
            })
            .collect();
        body.insert(
            "tools".into(),
            json!([{"functionDeclarations": declarations}]),
        );
    }
    if let Some(params) = &model.sampling_params {
        for (name, value) in params {
            body.insert(name.clone(), value.clone());
        }
    }
    Value::Object(body)
}

// ---------------------------------------------------------------------------
// Streaming
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, PartialEq)]
enum Open {
    Text,
    Thinking,
}

struct StreamState {
    output: AssistantMessage,
    open: Option<(usize, Open)>,
    calls: usize,
    finish: Option<String>,
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
                Api::GoogleGenerativeAi,
                model.provider.clone(),
                model.id.clone(),
                now_ms(),
            ),
            open: None,
            calls: 0,
            finish: None,
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

    async fn close(&mut self, producer: &mut AssistantMessageEventStreamProducer) {
        let Some((content_index, kind)) = self.open.take() else {
            return;
        };
        let event = match (kind, self.output.content.get(content_index)) {
            (Open::Text, Some(Content::Text(text))) => AssistantMessageEvent::TextEnd {
                content_index,
                content: text.text.clone(),
                partial: self.partial(),
            },
            (Open::Thinking, Some(Content::Thinking(thinking))) => {
                AssistantMessageEvent::ThinkingEnd {
                    content_index,
                    content: thinking.thinking.clone(),
                    partial: self.partial(),
                }
            }
            _ => return,
        };
        producer.push(event).await;
    }

    /// The open block of `kind`, opening one (and closing another) if needed.
    async fn block(
        &mut self,
        producer: &mut AssistantMessageEventStreamProducer,
        kind: Open,
    ) -> usize {
        if let Some((index, open)) = self.open {
            if open == kind {
                return index;
            }
            self.close(producer).await;
        }
        let content_index = self.output.content.len();
        let event = match kind {
            Open::Text => {
                self.output.content.push(Content::text(""));
                AssistantMessageEvent::TextStart {
                    content_index,
                    partial: self.partial(),
                }
            }
            Open::Thinking => {
                self.output.content.push(Content::Thinking(ThinkingContent {
                    kind: ThinkingContentType,
                    thinking: String::new(),
                    thinking_signature: None,
                    redacted: false,
                }));
                AssistantMessageEvent::ThinkingStart {
                    content_index,
                    partial: self.partial(),
                }
            }
        };
        self.open = Some((content_index, kind));
        producer.push(event).await;
        content_index
    }

    /// Keep a signature on the block it belongs to (the last text or
    /// thinking block when a part carries only a signature).
    fn sign(&mut self, signature: &str) {
        let target = self
            .output
            .content
            .iter_mut()
            .rev()
            .find(|content| matches!(content, Content::Text(_) | Content::Thinking(_)));
        match target {
            Some(Content::Text(text)) => text.text_signature = Some(signature.to_string()),
            Some(Content::Thinking(thinking)) => {
                thinking.thinking_signature = Some(signature.to_string())
            }
            _ => {}
        }
    }

    async fn apply_part(
        &mut self,
        producer: &mut AssistantMessageEventStreamProducer,
        part: &Value,
    ) {
        let signature = part.get("thoughtSignature").and_then(Value::as_str);
        if let Some(call) = part.get("functionCall") {
            self.close(producer).await;
            self.calls += 1;
            let name = call
                .get("name")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string();
            let id = call
                .get("id")
                .and_then(Value::as_str)
                .filter(|id| !id.is_empty())
                .map(str::to_string)
                .unwrap_or_else(|| format!("call_{}_{}_{}", name, now_ms(), self.calls));
            let arguments = call
                .get("args")
                .cloned()
                .filter(Value::is_object)
                .unwrap_or_else(|| json!({}));
            let tool_call = ToolCall {
                kind: ToolCallType,
                id,
                name,
                arguments: arguments.clone(),
                thought_signature: signature.map(str::to_string),
                namespace: None,
                recorded: None,
            };
            let content_index = self.output.content.len();
            self.output
                .content
                .push(Content::ToolCall(tool_call.clone()));
            producer
                .push(AssistantMessageEvent::ToolCallStart {
                    content_index,
                    partial: self.partial(),
                })
                .await;
            producer
                .push(AssistantMessageEvent::ToolCallDelta {
                    content_index,
                    delta: arguments.to_string(),
                    partial: self.partial(),
                })
                .await;
            producer
                .push(AssistantMessageEvent::ToolCallEnd {
                    content_index,
                    tool_call,
                    partial: self.partial(),
                })
                .await;
            return;
        }
        let text = part.get("text").and_then(Value::as_str).unwrap_or_default();
        let thought = part
            .get("thought")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        if !text.is_empty() {
            let kind = if thought { Open::Thinking } else { Open::Text };
            let content_index = self.block(producer, kind).await;
            match self.output.content.get_mut(content_index) {
                Some(Content::Text(t)) => t.text.push_str(text),
                Some(Content::Thinking(t)) => t.thinking.push_str(text),
                _ => {}
            }
            let event = if thought {
                AssistantMessageEvent::ThinkingDelta {
                    content_index,
                    delta: text.to_string(),
                    partial: self.partial(),
                }
            } else {
                AssistantMessageEvent::TextDelta {
                    content_index,
                    delta: text.to_string(),
                    partial: self.partial(),
                }
            };
            producer.push(event).await;
        }
        if let Some(signature) = signature {
            self.sign(signature);
        }
    }

    async fn apply(&mut self, producer: &mut AssistantMessageEventStreamProducer, chunk: &Value) {
        if let Some(reason) = chunk
            .pointer("/promptFeedback/blockReason")
            .and_then(Value::as_str)
        {
            self.finish = Some(format!("BLOCKED:{reason}"));
        }
        if let Some(candidate) = chunk.pointer("/candidates/0") {
            for part in candidate
                .pointer("/content/parts")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
            {
                self.apply_part(producer, part).await;
            }
            if let Some(reason) = candidate.get("finishReason").and_then(Value::as_str) {
                self.finish = Some(reason.to_string());
            }
        }
        if let Some(usage) = chunk.get("usageMetadata") {
            let get = |name: &str| usage.get(name).and_then(Value::as_i64).unwrap_or(0);
            // promptTokenCount includes the cached part.
            let cached = get("cachedContentTokenCount");
            self.output.usage.input =
                (get("promptTokenCount") + get("toolUsePromptTokenCount") - cached).max(0);
            self.output.usage.cache_read = cached;
            self.output.usage.output = get("candidatesTokenCount") + get("thoughtsTokenCount");
            self.output.usage.total_tokens =
                self.output.usage.input + self.output.usage.cache_read + self.output.usage.output;
            producer.commit_metadata(&self.output);
        }
    }

    async fn finish(&mut self, producer: &mut AssistantMessageEventStreamProducer, model: &Model) {
        self.close(producer).await;
        let has_tools = self
            .output
            .content
            .iter()
            .any(|c| matches!(c, Content::ToolCall(_)));
        let reason = match self.finish.as_deref() {
            None | Some("STOP") | Some("FINISH_REASON_UNSPECIFIED") => {
                if has_tools {
                    DoneReason::ToolUse
                } else {
                    DoneReason::Stop
                }
            }
            Some("MAX_TOKENS") => DoneReason::Length,
            Some(other) => {
                let message = match other.strip_prefix("BLOCKED:") {
                    Some(reason) => format!("Gemini blocked the prompt ({reason})"),
                    None => format!("Gemini stopped: {other}"),
                };
                self.output.raw_stop_reason = Some(other.to_string());
                self.error(producer, message, false).await;
                return;
            }
        };
        self.output.raw_stop_reason = self.finish.clone();
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

/// Gemini errors are `{"error": {"code", "message", "status"}}`.
fn error_message(body: &str) -> String {
    serde_json::from_str::<Value>(body)
        .ok()
        .and_then(|value| {
            let error = value.get("error").or_else(|| value.pointer("/0/error"))?;
            let message = error.get("message").and_then(Value::as_str)?;
            Some(match error.get("status").and_then(Value::as_str) {
                Some(status) => format!("{status}: {message}"),
                None => message.to_string(),
            })
        })
        .unwrap_or_else(|| body.chars().take(500).collect())
}

pub(crate) fn stream_url(model: &Model) -> String {
    let base = model.base_url.trim_end_matches('/');
    let base = base.strip_suffix("/openai").unwrap_or(base);
    format!("{base}/models/{}:streamGenerateContent?alt=sse", model.id)
}

async fn run_stream(
    producer: &mut AssistantMessageEventStreamProducer,
    http: reqwest::Client,
    model: &Model,
    body: Value,
    opts: &SimpleStreamOptions,
) {
    let mut state = StreamState::new(model);
    let Some(key) = opts.api_key.clone().filter(|key| !key.trim().is_empty()) else {
        state
            .error(
                producer,
                format!("No API key for provider: {}", model.provider),
                false,
            )
            .await;
        return;
    };
    let url = stream_url(model);
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
    let mut headers = BTreeMap::new();
    for extra in [model.headers.as_ref(), opts.headers.as_ref()]
        .into_iter()
        .flatten()
    {
        for (name, value) in extra {
            crate::provider::set_http_header(&mut headers, name, Some(value));
        }
    }
    crate::provider::set_http_header(&mut headers, "authorization", None);
    crate::provider::set_http_header(&mut headers, "x-goog-api-key", Some(&key));
    crate::http::ensure_user_agent(&mut headers);
    let timeout = opts.request_timeout();
    let signal = opts.signal.clone();
    let response = retry_provider_request(
        || {
            let http = http.clone();
            let bytes = bytes.clone();
            let url = url.clone();
            let headers = headers.clone();
            let signal = signal.clone();
            async move {
                let mut request = http
                    .post(&url)
                    .timeout(timeout)
                    .header("content-type", "application/json");
                for (name, value) in &headers {
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
    let mut events = SseEventStream::new(response, opts.signal.clone())
        .with_idle_timeout(opts.stream_idle_timeout());
    loop {
        match events.next_event().await {
            Ok(Some(event)) => {
                let data = event.data.trim();
                if data.is_empty() || data == "[DONE]" {
                    continue;
                }
                match serde_json::from_str::<Value>(data) {
                    Ok(chunk) => {
                        if chunk.get("error").is_some() {
                            state.error(producer, error_message(data), false).await;
                            return;
                        }
                        state.apply(producer, &chunk).await;
                    }
                    Err(error) => {
                        state
                            .error(
                                producer,
                                format!("Gemini sent an unreadable event: {error}"),
                                false,
                            )
                            .await;
                        return;
                    }
                }
            }
            Ok(None) => {
                state.finish(producer, model).await;
                return;
            }
            Err(error) => {
                state
                    .error(producer, error.to_string(), error.is_abort())
                    .await;
                return;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::{AssistantMessage, ToolResultMessage, ToolResultRole, UserMessage};

    fn tool_result(id: &str, name: &str, text: &str) -> Message {
        Message::ToolResult(Box::new(ToolResultMessage {
            role: ToolResultRole,
            tool_call_id: id.into(),
            tool_name: name.into(),
            content: vec![Content::text(text)],
            details: None,
            usage: None,
            added_tool_names: Vec::new(),
            is_error: false,
            timestamp: 0,
        }))
    }

    fn gemini(id: &str) -> Model {
        let mut model = Model::new(
            id,
            id,
            Api::GoogleGenerativeAi,
            "googlegenai",
            "https://generativelanguage.googleapis.com/v1beta",
        );
        model.reasoning = true;
        model.max_tokens = 65_536;
        model
    }

    #[test]
    fn url_targets_stream_generate_content() {
        assert_eq!(
            stream_url(&gemini("gemini-3.5-flash")),
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:streamGenerateContent?alt=sse"
        );
    }

    #[test]
    fn thinking_levels_and_budgets() {
        let mut three = gemini("gemini-3.5-flash");
        let mut map = crate::types::ThinkingLevelMap::new();
        map.insert(ThinkingLevel::Minimal, Some("minimal".into()));
        map.insert(ThinkingLevel::Low, Some("low".into()));
        map.insert(ThinkingLevel::Medium, Some("medium".into()));
        map.insert(ThinkingLevel::High, Some("high".into()));
        map.insert(ThinkingLevel::Xhigh, None);
        map.insert(ThinkingLevel::Off, None);
        three.thinking_level_map = Some(map);
        assert_eq!(
            thinking_config(&three, ThinkingLevel::Xhigh).unwrap(),
            json!({"thinkingLevel": "high", "includeThoughts": true})
        );
        assert_eq!(
            thinking_config(&three, ThinkingLevel::Off).unwrap(),
            json!({"thinkingLevel": "minimal", "includeThoughts": false})
        );
        let flash = gemini("gemini-2.5-flash");
        assert_eq!(
            thinking_config(&flash, ThinkingLevel::Off).unwrap(),
            json!({"thinkingBudget": 0})
        );
        assert_eq!(
            thinking_config(&gemini("gemini-2.5-pro"), ThinkingLevel::Off),
            None
        );
        assert_eq!(
            thinking_config(&flash, ThinkingLevel::Medium).unwrap(),
            json!({"thinkingBudget": 8192, "includeThoughts": true})
        );
    }

    fn assistant(model: &Model, content: Vec<Content>) -> Message {
        let mut message = AssistantMessage::empty(
            Api::GoogleGenerativeAi,
            model.provider.clone(),
            model.id.clone(),
            0,
        );
        message.content = content;
        Message::Assistant(Box::new(message))
    }

    #[test]
    fn replays_signatures_only_to_their_model() {
        let model = gemini("gemini-3.5-flash");
        let mut call = ToolCall {
            kind: ToolCallType,
            id: "c1".into(),
            name: "read".into(),
            arguments: json!({"path": "a"}),
            thought_signature: Some("sig-1".into()),
            namespace: None,
            recorded: None,
        };
        let ctx = Context::new(vec![
            Message::User(UserMessage::new("hi", 0)),
            assistant(&model, vec![Content::ToolCall(call.clone())]),
            tool_result("c1", "read", "file body"),
        ]);
        let body = build_request(&model, &ctx, &SimpleStreamOptions::default());
        let parts = &body["contents"][1]["parts"];
        assert_eq!(parts[0]["thoughtSignature"], "sig-1");
        assert_eq!(
            body["contents"][2]["parts"][0]["functionResponse"]["response"]["output"],
            "file body"
        );

        // Another model's call: its signature is useless, the bypass is sent.
        call.thought_signature = Some("foreign".into());
        let other = gemini("gemini-3.6-flash");
        let ctx = Context::new(vec![
            Message::User(UserMessage::new("hi", 0)),
            assistant(&other, vec![Content::ToolCall(call)]),
        ]);
        let body = build_request(&model, &ctx, &SimpleStreamOptions::default());
        assert_eq!(
            body["contents"][1]["parts"][0]["thoughtSignature"],
            SKIP_SIGNATURE
        );
    }

    #[test]
    fn schema_keys_gemini_rejects_are_removed() {
        let schema = json!({"type": "object", "additionalProperties": false, "$schema": "x",
            "properties": {"a": {"type": "string", "const": "b"}}});
        assert_eq!(
            sanitize_schema(&schema),
            json!({"type": "object", "properties": {"a": {"type": "string"}}})
        );
    }
}
