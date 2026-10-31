//! Port of the request side of `app/agent/providers/openai/completions.py`
//! (`build_request`, `convert_messages`, `convert_tools`), of the MiMo handler in
//! `app/agent/providers/xiaomi/xiaomi.py`, and of the helpers they call:
//! `openai/sanitization.py`, `openai/tool_content.py`, and
//! `transform.apply_model_sampling_defaults`.

use std::collections::HashSet;

use serde_json::{json, Map, Value};

use crate::factory::Flavor;
use crate::thinking::{
    clamp_thinking_level, normalize_thinking_level, thinking_request_fields, LEGACY_EFFORT_LEVELS,
};
use crate::{ContentBlock, Message, ProviderError, ToolCall, ToolSpec};

/// `_NO_SERVICE_TIER`: tier values that mean "serve this the normal way".
const NO_SERVICE_TIER: [&str; 6] = ["", "auto", "default", "none", "off", "standard"];

/// `_MODEL_TEMPERATURE_OVERRIDES`, first match wins.
const TEMPERATURE_OVERRIDES: [(&str, f64); 10] = [
    ("gemini", 1.0),
    ("gemma", 1.0),
    ("glm", 0.7),
    ("glm-4", 0.7),
    ("kimi-k2", 0.6),
    ("kimi-k2.5", 0.6),
    ("kimi-k2p5", 0.6),
    ("kimi-k2-5", 0.6),
    ("qwen", 0.7),
    ("minimax-m2", 1.0),
];

/// `_MODEL_TOP_P_OVERRIDES`.
const TOP_P_OVERRIDES: [(&str, f64); 6] = [
    ("qwen", 1.0),
    ("minimax-m2", 0.95),
    ("gemini", 0.95),
    ("kimi-k2.5", 0.95),
    ("kimi-k2p5", 0.95),
    ("kimi-k2-5", 0.95),
];

/// `_MODEL_TOP_K_OVERRIDES`.
const TOP_K_OVERRIDES: [(&str, i64); 5] = [
    ("minimax-m2", 20),
    ("minimax-m25", 40),
    ("minimax-m21", 40),
    ("qwen", 40),
    ("qwen3", 40),
];

/// The inputs `build_request` reads.
pub struct BuildRequest<'a> {
    pub provider_id: &'a str,
    pub model: &'a str,
    pub flavor: Flavor,
    pub messages: &'a [Message],
    pub tools: &'a [ToolSpec],
    /// The merged call options (`temperature`, `max_tokens`, `thinking_level`, ...).
    pub options: &'a Map<String, Value>,
}

/// `sanitize_openai_tool_pairs`: drop orphan tool outputs and strip assistant
/// `tool_calls` whose tool outputs do not all follow.
pub fn sanitize_tool_pairs(messages: &[Message]) -> Vec<Message> {
    let mut result = Vec::with_capacity(messages.len());
    let mut expected: HashSet<&str> = HashSet::new();
    for (idx, msg) in messages.iter().enumerate() {
        match msg {
            Message::Assistant {
                content,
                reasoning_content,
                tool_calls,
            } => {
                expected.clear();
                let Some(calls) = tool_calls.as_ref().filter(|calls| !calls.is_empty()) else {
                    result.push(msg.clone());
                    continue;
                };
                let ids: HashSet<&str> = calls
                    .iter()
                    .map(|tc| tc.id.as_str())
                    .filter(|id| !id.is_empty())
                    .collect();
                let following: HashSet<&str> = messages
                    .iter()
                    .skip(idx + 1)
                    .map_while(|next| match next {
                        Message::Tool { tool_call_id, .. } => Some(tool_call_id.as_str()),
                        _ => None,
                    })
                    .filter(|id| !id.is_empty())
                    .collect();
                if !ids.is_empty() && ids.is_subset(&following) {
                    expected = ids;
                    result.push(msg.clone());
                } else {
                    let mut sorted: Vec<&str> = ids.into_iter().collect();
                    sorted.sort_unstable();
                    tracing::warn!(
                        idx,
                        ids = sorted.join(", "),
                        "openai_strip_incomplete_assistant_tool_calls"
                    );
                    result.push(Message::Assistant {
                        content: content.clone(),
                        reasoning_content: reasoning_content.clone(),
                        tool_calls: None,
                    });
                }
            }
            Message::Tool { tool_call_id, .. } => {
                if !tool_call_id.is_empty() && expected.remove(tool_call_id.as_str()) {
                    result.push(msg.clone());
                } else {
                    tracing::warn!(idx, tool_call_id, "openai_drop_orphan_tool_message");
                }
            }
            _ => {
                expected.clear();
                result.push(msg.clone());
            }
        }
    }
    result
}

/// Content parts as Chat Completions takes them.
fn convert_parts(parts: &[ContentBlock]) -> Value {
    let converted: Vec<Value> = parts
        .iter()
        .map(|part| match part {
            ContentBlock::Text { text } => json!({"type": "text", "text": text}),
            ContentBlock::ImageUrl { url, detail, .. } => {
                let mut image = Map::new();
                image.insert("url".into(), json!(url));
                if let Some(detail) = detail.as_ref().filter(|d| !d.is_empty()) {
                    image.insert("detail".into(), json!(detail));
                }
                json!({"type": "image_url", "image_url": image})
            }
            ContentBlock::ImageData { data, media_type } => json!({
                "type": "image_url",
                "image_url": {"url": format!("data:{media_type};base64,{data}"), "detail": "auto"},
            }),
        })
        .collect();
    Value::Array(converted)
}

/// `content` for a user or tool message: the parts when present, else the text.
fn content_value(content: &Option<String>, parts: &Option<Vec<ContentBlock>>) -> Option<Value> {
    match parts.as_ref().filter(|parts| !parts.is_empty()) {
        Some(parts) => Some(convert_parts(parts)),
        None => content.as_ref().map(|text| json!(text)),
    }
}

fn convert_tool_calls(calls: &[ToolCall]) -> Value {
    Value::Array(
        calls
            .iter()
            .map(|tc| {
                json!({
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                })
            })
            .collect(),
    )
}

/// An `OpenAIMessage`/`XiaomiMessage` dumped with `exclude_none`; the fields
/// keep the schema's declaration order.
fn wire_message(role: &str, fields: [(&str, Option<Value>); 5]) -> Value {
    let mut out = Map::new();
    out.insert("role".into(), json!(role));
    for (key, value) in fields {
        if let Some(value) = value {
            out.insert(key.into(), value);
        }
    }
    Value::Object(out)
}

/// `convert_messages` (base handler) and `_convert_messages_xiaomi`.
fn convert_messages(messages: &[Message], flavor: Flavor) -> Vec<Value> {
    let mut result = Vec::with_capacity(messages.len());
    for msg in messages {
        let none = || None;
        match msg {
            Message::System { content } => result.push(wire_message(
                "system",
                [
                    ("content", content.as_ref().map(|c| json!(c))),
                    ("tool_calls", none()),
                    ("reasoning_content", none()),
                    ("tool_call_id", none()),
                    ("name", none()),
                ],
            )),
            Message::User { content, parts } => result.push(wire_message(
                "user",
                [
                    ("content", content_value(content, parts)),
                    ("tool_calls", none()),
                    ("reasoning_content", none()),
                    ("tool_call_id", none()),
                    ("name", none()),
                ],
            )),
            Message::Assistant {
                content,
                reasoning_content,
                tool_calls,
            } => {
                let calls = tool_calls
                    .as_ref()
                    .filter(|calls| !calls.is_empty())
                    .map(|calls| convert_tool_calls(calls));
                let has_content = content.as_ref().is_some_and(|c| !c.is_empty());
                let (content, reasoning) = match flavor {
                    Flavor::Completions => {
                        // Some providers (e.g. Xiaomi mimo) reject assistant turns
                        // with neither content nor tool_calls (HTTP 400).
                        if !has_content && calls.is_none() {
                            continue;
                        }
                        (content.as_ref().map(|c| json!(c)), None)
                    }
                    Flavor::Xiaomi => {
                        // MiMo needs reasoning_content echoed, and rejects an
                        // assistant message with none of the three fields.
                        let reasoning = reasoning_content
                            .as_ref()
                            .filter(|r| !r.is_empty())
                            .map(|r| json!(r));
                        let content = if !has_content && calls.is_none() && reasoning.is_none() {
                            Some(json!(" "))
                        } else {
                            content.as_ref().map(|c| json!(c))
                        };
                        (content, reasoning)
                    }
                };
                result.push(wire_message(
                    "assistant",
                    [
                        ("content", content),
                        ("tool_calls", calls),
                        ("reasoning_content", reasoning),
                        ("tool_call_id", none()),
                        ("name", none()),
                    ],
                ));
            }
            Message::Tool {
                content,
                tool_call_id,
                name,
                parts,
            } => result.push(wire_message(
                "tool",
                [
                    ("content", content_value(content, parts)),
                    ("tool_calls", none()),
                    ("reasoning_content", none()),
                    ("tool_call_id", Some(json!(tool_call_id))),
                    ("name", name.as_ref().map(|n| json!(n))),
                ],
            )),
        }
    }
    result
}

/// `should_flatten_tool_content`: MiMo, GLM and Xiaomi models take string tool content only.
fn should_flatten_tool_content(model: &str) -> bool {
    let lower = model.to_lowercase();
    ["mimo", "glm", "xiaomi"]
        .iter()
        .any(|marker| lower.contains(marker))
}

/// `_flatten_content_parts_to_string`.
fn flatten_parts(parts: &[Value]) -> String {
    let mut texts: Vec<String> = Vec::new();
    for part in parts {
        let Some(part) = part.as_object() else {
            continue;
        };
        match part.get("type").and_then(Value::as_str) {
            Some("text") => texts.push(
                part.get("text")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_owned(),
            ),
            Some("image_url") => {
                let url = part
                    .get("image_url")
                    .and_then(|image| image.get("url"))
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                if url.starts_with("data:") {
                    texts.push("[image data]".to_owned());
                } else if !url.is_empty() {
                    texts.push(format!("[image: {url}]"));
                }
            }
            _ => {}
        }
    }
    texts.join("\n")
}

/// `flatten_tool_content_for_provider`.
fn flatten_tool_content(messages: &mut [Value], model: &str) {
    if !should_flatten_tool_content(model) {
        return;
    }
    for msg in messages.iter_mut() {
        let Some(obj) = msg.as_object_mut() else {
            continue;
        };
        if obj.get("role").and_then(Value::as_str) != Some("tool") {
            continue;
        }
        let Some(Value::Array(parts)) = obj.get("content") else {
            continue;
        };
        // Python's single-text-part fast path returns that text, which is
        // what the general flattening yields for it too.
        let flat = Value::String(flatten_parts(parts));
        obj.insert("content".into(), flat);
    }
}

/// `convert_tools`: only `function` tools; `None` when nothing is left.
fn convert_tools(tools: &[ToolSpec]) -> Option<Value> {
    let converted: Vec<Value> = tools
        .iter()
        .filter(|tool| tool.kind == "function")
        .map(|tool| {
            let mut function = Map::new();
            function.insert("name".into(), json!(tool.function.name));
            function.insert(
                "description".into(),
                json!(tool.function.description.clone().unwrap_or_default()),
            );
            if let Some(parameters) = tool.function.parameters.as_ref().filter(|p| !p.is_null()) {
                function.insert("parameters".into(), parameters.clone());
            }
            json!({"type": "function", "function": function})
        })
        .collect();
    (!converted.is_empty()).then_some(Value::Array(converted))
}

fn invalid(name: &str, reason: &str) -> ProviderError {
    ProviderError::InvalidOption {
        name: name.to_owned(),
        reason: reason.to_owned(),
    }
}

/// A `float | None` request field: pydantic dumps any number as a float.
fn number_option(options: &Map<String, Value>, name: &str) -> Result<Option<Value>, ProviderError> {
    match options.get(name) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Number(n)) => Ok(n.as_f64().map(Value::from)),
        Some(_) => Err(invalid(name, "expected a number")),
    }
}

/// An `int | None` request field such as `max_tokens`; an integral float becomes an int.
fn integer_option(
    options: &Map<String, Value>,
    name: &str,
) -> Result<Option<Value>, ProviderError> {
    match options.get(name) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Number(n)) if n.is_i64() || n.is_u64() => Ok(Some(Value::Number(n.clone()))),
        Some(Value::Number(n)) => match n.as_f64() {
            #[allow(clippy::cast_possible_truncation)]
            Some(f) if f.is_finite() && f.fract() == 0.0 => Ok(Some(Value::from(f as i64))),
            _ => Err(invalid(name, "expected an integer")),
        },
        Some(_) => Err(invalid(name, "expected an integer")),
    }
}

/// `_service_tier_body` for a model whose catalog lists no tiers.
fn service_tier_body(options: &Map<String, Value>) -> Option<Value> {
    let tier = options.get("service_tier")?.as_str()?.trim();
    if tier.is_empty() {
        return None;
    }
    let normalized = tier.to_lowercase();
    (!NO_SERVICE_TIER.contains(&normalized.as_str())).then(|| json!(normalized))
}

fn first_match<T: Copy>(model: &str, patterns: &[(&str, T)]) -> Option<T> {
    let lower = model.to_lowercase();
    patterns
        .iter()
        .find(|(pattern, _)| lower.contains(pattern))
        .map(|(_, value)| *value)
}

/// `apply_model_sampling_defaults`: fill fields the body does not set yet.
fn apply_model_sampling_defaults(body: &mut Map<String, Value>, model: &str) {
    if !body.contains_key("temperature") {
        if let Some(temp) = first_match(model, &TEMPERATURE_OVERRIDES) {
            body.insert("temperature".into(), json!(temp));
        }
    }
    if !body.contains_key("top_p") {
        if let Some(top_p) = first_match(model, &TOP_P_OVERRIDES) {
            body.insert("top_p".into(), json!(top_p));
        }
    }
    if !body.contains_key("top_k") {
        if let Some(top_k) = first_match(model, &TOP_K_OVERRIDES) {
            body.insert("top_k".into(), json!(top_k));
        }
    }
}

/// `build_request(messages, tools, stream=True, merged)` for either handler.
pub fn build_request(req: &BuildRequest<'_>) -> Result<Value, ProviderError> {
    let options = req.options;
    let temperature = number_option(options, "temperature")?;
    let top_p = number_option(options, "top_p")?;
    let max_tokens = integer_option(options, "max_tokens")?;

    let mut messages = convert_messages(&sanitize_tool_pairs(req.messages), req.flavor);
    flatten_tool_content(&mut messages, req.model);

    let mut body = Map::new();
    body.insert("model".into(), json!(req.model));
    body.insert("messages".into(), Value::Array(messages));
    if let Some(tools) = convert_tools(req.tools) {
        body.insert("tools".into(), tools);
    }
    if let Some(temperature) = temperature {
        body.insert("temperature".into(), temperature);
    }
    if let Some(top_p) = top_p {
        body.insert("top_p".into(), top_p);
    }
    // Both handlers send `max_completion_tokens` (`uses_max_completion_tokens`).
    if let Some(max_tokens) = max_tokens {
        body.insert("max_completion_tokens".into(), max_tokens);
    }
    body.insert("stream".into(), json!(true));
    body.insert("stream_options".into(), json!({"include_usage": true}));

    let thinking = thinking_request_fields(req.provider_id, options.get("thinking_level"));
    match req.flavor {
        Flavor::Completions => {
            if let Some(key) = options.get("prompt_cache_key").filter(|v| !v.is_null()) {
                body.insert("prompt_cache_key".into(), key.clone());
            }
            body.extend(thinking);
            if let Some(tier) = service_tier_body(options) {
                body.insert("service_tier".into(), tier);
            }
            apply_model_sampling_defaults(&mut body, req.model);
        }
        Flavor::Xiaomi => {
            body.extend(thinking);
            // The legacy `reasoning_effort` for proxies that drop `thinking`,
            // clamped to the enum it takes. An enabled budget always comes
            // from an active level. Python also pops a residual field when
            // thinking is off, but nothing else puts one on this body.
            let enabled = body
                .get("thinking")
                .and_then(|t| t.get("type"))
                .and_then(Value::as_str)
                == Some("enabled");
            if enabled {
                let level = normalize_thinking_level(options.get("thinking_level"));
                let effort = clamp_thinking_level(level, LEGACY_EFFORT_LEVELS);
                if !effort.is_empty() {
                    body.insert("reasoning_effort".into(), json!(effort));
                }
            }
        }
    }
    Ok(Value::Object(body))
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::indexing_slicing)]
mod tests {
    use super::*;
    use crate::FunctionCall;

    fn call(id: &str) -> ToolCall {
        ToolCall {
            id: id.to_owned(),
            kind: "function".to_owned(),
            function: FunctionCall {
                name: "f".to_owned(),
                arguments: "{}".to_owned(),
            },
        }
    }

    fn assistant(ids: &[&str]) -> Message {
        Message::Assistant {
            content: Some("a".to_owned()),
            reasoning_content: None,
            tool_calls: Some(ids.iter().map(|id| call(id)).collect()),
        }
    }

    fn tool(id: &str) -> Message {
        Message::Tool {
            content: Some("r".to_owned()),
            tool_call_id: id.to_owned(),
            name: None,
            parts: None,
        }
    }

    fn user() -> Message {
        Message::User {
            content: Some("u".to_owned()),
            parts: None,
        }
    }

    #[test]
    fn sanitize_keeps_complete_pairs_and_drops_orphans() {
        let history = vec![
            assistant(&["a", "b"]),
            tool("b"),
            tool("a"),
            tool("a"),
            user(),
            tool("z"),
            assistant(&["c"]),
            user(),
            tool("c"),
        ];
        let clean = sanitize_tool_pairs(&history);
        assert_eq!(clean.len(), 6);
        assert_eq!(clean[0], history[0]);
        assert_eq!(clean[3], user());
        assert!(matches!(
            &clean[4],
            Message::Assistant {
                tool_calls: None,
                ..
            }
        ));
        assert_eq!(clean[5], user());
    }

    #[test]
    fn sanitize_strips_calls_without_ids() {
        let clean = sanitize_tool_pairs(&[assistant(&[""]), tool("")]);
        assert!(matches!(
            &clean[..],
            [Message::Assistant {
                tool_calls: None,
                ..
            }]
        ));
    }

    #[test]
    fn flattening_applies_only_to_matching_models() {
        let mut messages = vec![json!({"role": "tool", "content": [
            {"type": "text", "text": "a"}, {"type": "image_url", "image_url": {"url": ""}},
            {"type": "other"}, 3
        ]})];
        let original = messages.clone();
        flatten_tool_content(&mut messages, "gpt-4o");
        assert_eq!(messages, original);
        flatten_tool_content(&mut messages, "XiaoMi-chat");
        assert_eq!(messages[0]["content"], json!("a"));
        let mut single = vec![
            json!({"role": "tool", "content": [{"type": "image_url", "image_url": {"url": "https://x/a.png"}}]}),
            json!({"role": "tool", "content": [{"type": "text", "text": "only"}]}),
            json!({"role": "tool", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}}]}),
        ];
        flatten_tool_content(&mut single, "mimo-v2");
        assert_eq!(single[0]["content"], json!("[image: https://x/a.png]"));
        assert_eq!(single[1]["content"], json!("only"));
        assert_eq!(single[2]["content"], json!("[image data]"));
        let mut empty = vec![
            json!({"role": "tool", "content": []}),
            json!({"role": "user", "content": []}),
        ];
        flatten_tool_content(&mut empty, "glm");
        assert_eq!(empty[0]["content"], json!(""));
        assert_eq!(empty[1]["content"], json!([]));
    }

    fn options(value: Value) -> Map<String, Value> {
        value.as_object().cloned().unwrap()
    }

    fn body(flavor: Flavor, opts: Value) -> Result<Value, ProviderError> {
        let opts = options(opts);
        build_request(&BuildRequest {
            provider_id: if flavor == Flavor::Xiaomi {
                "xiaomi"
            } else {
                "router9"
            },
            model: "m",
            flavor,
            messages: &[user()],
            tools: &[],
            options: &opts,
        })
    }

    #[test]
    fn option_types_are_validated() {
        let bad = body(Flavor::Completions, json!({"temperature": "hot"})).unwrap_err();
        assert_eq!(
            bad.to_string(),
            "invalid option temperature: expected a number"
        );
        let frac = body(Flavor::Completions, json!({"max_tokens": 1.5})).unwrap_err();
        assert_eq!(
            frac.to_string(),
            "invalid option max_tokens: expected an integer"
        );
        let whole = body(
            Flavor::Completions,
            json!({"max_tokens": 10.0, "top_p": null, "temperature": 1}),
        )
        .unwrap();
        assert_eq!(whole["max_completion_tokens"], json!(10));
        assert!(whole["max_completion_tokens"].is_i64());
        assert!(whole["temperature"].is_f64());
        assert!(whole.get("top_p").is_none());
        // Python ints are exact at any size.
        for big in [json!(9_007_199_254_740_993_i64), json!(u64::MAX)] {
            let b = body(Flavor::Completions, json!({"max_tokens": big})).unwrap();
            assert_eq!(b["max_completion_tokens"], big);
        }
        let text = body(Flavor::Completions, json!({"max_tokens": "9"})).unwrap_err();
        assert_eq!(
            text.to_string(),
            "invalid option max_tokens: expected an integer"
        );
    }

    #[test]
    fn xiaomi_legacy_effort_follows_thinking() {
        let on = body(Flavor::Xiaomi, json!({"thinking_level": "xhigh"})).unwrap();
        assert_eq!(on["reasoning_effort"], json!("high"));
        let off = body(Flavor::Xiaomi, json!({"thinking_level": "none"})).unwrap();
        assert!(off.get("reasoning_effort").is_none());
        let unset = body(Flavor::Xiaomi, json!({})).unwrap();
        assert!(unset.get("thinking").is_none() && unset.get("reasoning_effort").is_none());
    }

    #[test]
    fn service_tier_and_sampling_defaults() {
        assert_eq!(
            service_tier_body(&options(json!({"service_tier": " Priority "}))),
            Some(json!("priority"))
        );
        assert_eq!(
            service_tier_body(&options(json!({"service_tier": "Standard"}))),
            None
        );
        assert_eq!(
            service_tier_body(&options(json!({"service_tier": 3}))),
            None
        );
        let mut b = Map::new();
        apply_model_sampling_defaults(&mut b, "MiniMax-M25");
        assert_eq!(
            Value::Object(b),
            json!({"temperature": 1.0, "top_p": 0.95, "top_k": 20})
        );
    }
}
