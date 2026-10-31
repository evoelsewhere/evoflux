//! Port of the canonical chat schemas in `app/agent/schemas/chat.py`.
//!
//! JSON shapes follow the Python models: messages are tagged by `role`,
//! content blocks by `type`, and optional fields may be absent or `null`.

use serde::{Deserialize, Serialize};

/// One part of a multimodal user or tool message (`ContentBlock`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ContentBlock {
    Text {
        text: String,
    },
    /// An image the provider fetches by URL (or a data URI).
    ImageUrl {
        url: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        media_type: Option<String>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        detail: Option<String>,
    },
    /// Inline base64 image bytes.
    ImageData {
        data: String,
        media_type: String,
    },
}

/// `FunctionCall`: a tool call as stored in history; `arguments` is JSON text.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct FunctionCall {
    pub name: String,
    pub arguments: String,
}

/// `ToolCall` on an assistant message in history.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ToolCall {
    pub id: String,
    #[serde(rename = "type", default = "function_kind")]
    pub kind: String,
    pub function: FunctionCall,
}

fn function_kind() -> String {
    "function".to_owned()
}

/// `ChatMessage`: the system, user, assistant and tool messages.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "role", rename_all = "lowercase")]
pub enum Message {
    System {
        #[serde(default)]
        content: Option<String>,
    },
    User {
        #[serde(default)]
        content: Option<String>,
        /// Multimodal parts; when present they replace `content` on the wire.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        parts: Option<Vec<ContentBlock>>,
    },
    Assistant {
        #[serde(default)]
        content: Option<String>,
        /// Receive-only reasoning trace; only MiMo gets it echoed back.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        reasoning_content: Option<String>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        tool_calls: Option<Vec<ToolCall>>,
    },
    Tool {
        #[serde(default)]
        content: Option<String>,
        tool_call_id: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        name: Option<String>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        parts: Option<Vec<ContentBlock>>,
    },
}

/// The function half of an OpenAI-style tool definition.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct FunctionSpec {
    pub name: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parameters: Option<serde_json::Value>,
}

/// A tool definition as the agent passes it (`{"type": "function", "function": {...}}`).
/// Only `type == "function"` entries reach the wire, as in Python's `convert_tools`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ToolSpec {
    #[serde(rename = "type", default = "function_kind")]
    pub kind: String,
    pub function: FunctionSpec,
}

/// `Usage`: token counts of one model call.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Usage {
    pub prompt_tokens: i64,
    pub completion_tokens: i64,
    pub total_tokens: i64,
    pub cached_tokens: Option<i64>,
    pub cache_write_tokens: Option<i64>,
    pub thoughts_tokens: Option<i64>,
    pub tool_use_tokens: Option<i64>,
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn a_missing_type_means_function() {
        let spec: ToolSpec = serde_json::from_value(json!({"function": {"name": "f"}})).unwrap();
        assert_eq!(spec.kind, "function");
        let call: ToolCall = serde_json::from_value(
            json!({"id": "c", "function": {"name": "f", "arguments": "{}"}}),
        )
        .unwrap();
        assert_eq!(call.kind, "function");
    }

    #[test]
    fn messages_round_trip_the_python_shape() {
        let raw = json!([
            {"role": "system", "content": "s"},
            {"role": "user", "content": null, "parts": [
                {"type": "text", "text": "t"},
                {"type": "image_url", "url": "u", "detail": "low"},
                {"type": "image_data", "data": "d", "media_type": "image/png"}
            ]},
            {"role": "assistant", "content": "a", "reasoning_content": "r",
             "tool_calls": [{"id": "c", "type": "function", "function": {"name": "f", "arguments": "{}"}}]},
            {"role": "tool", "content": "x", "tool_call_id": "c", "name": "f"}
        ]);
        let messages: Vec<Message> = serde_json::from_value(raw.clone()).unwrap();
        assert_eq!(serde_json::to_value(&messages).unwrap(), raw);
    }
}
