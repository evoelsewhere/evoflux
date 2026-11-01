//! Port of the streaming side of the Chat Completions provider:
//! `iter_sse_data` (`app/agent/providers/streaming.py`), the chunk schema and
//! `CompletionsHandler.stream` / `_usage_from_openai`
//! (`app/agent/providers/openai/{schemas,completions}.py`), and the tool-call
//! assembly of `stream_and_assemble` (`app/agent/agent_loop/streaming.py`).

use std::collections::{BTreeMap, VecDeque};

use serde::{Deserialize, Deserializer};
use serde_json::Value;

use crate::{ProviderError, ProviderEvent, Usage};

/// What one SSE line means to `iter_sse_data`.
#[derive(Debug, PartialEq)]
pub enum SseLine {
    /// A `data: ` line holding JSON.
    Data(Value),
    /// The `[DONE]` sentinel: stop reading.
    Done,
    /// Anything else: blank, `event:`/`id:` lines, or data that is not JSON.
    Skip,
}

/// Classify one line as `iter_sse_data` does (`strip`, the `data: ` prefix, the sentinel).
pub fn classify_line(line: &str) -> SseLine {
    let Some(data) = line.trim().strip_prefix("data: ") else {
        return SseLine::Skip;
    };
    if data == "[DONE]" {
        return SseLine::Done;
    }
    match serde_json::from_str(data) {
        Ok(value) => SseLine::Data(value),
        Err(_) => {
            let prefix: String = data.chars().take(200).collect();
            tracing::debug!(data = prefix, "sse_invalid_json");
            SseLine::Skip
        }
    }
}

/// The longest SSE line buffered, in bytes; Python has no cap.
pub const MAX_LINE_BYTES: usize = 16 << 20;

/// The longest arguments of one tool call, in bytes; Python has no cap.
pub const MAX_ARGUMENTS_BYTES: usize = 16 << 20;

fn too_large(what: &str, limit: usize) -> ProviderError {
    ProviderError::TooLarge {
        what: what.to_owned(),
        limit,
    }
}

/// Splits a byte stream into lines like `httpx`'s `aiter_lines` (`\n`, `\r\n`
/// and `\r` all end a line). The empty lines a `\r\n` split leaves are blank,
/// and blank lines mean nothing to the SSE parser.
#[derive(Debug, Default)]
pub struct LineSplitter {
    pending: Vec<u8>,
}

impl LineSplitter {
    /// The lines `bytes` completes. A line over [`MAX_LINE_BYTES`] ends the
    /// list with an error, after the lines before it.
    pub fn push(&mut self, bytes: &[u8]) -> Vec<Result<String, ProviderError>> {
        let mut lines = Vec::new();
        let mut rest = bytes;
        loop {
            let end = rest.iter().position(|b| matches!(b, b'\n' | b'\r'));
            let part = end.map_or(rest, |end| rest.get(..end).unwrap_or_default());
            if self.pending.len() + part.len() > MAX_LINE_BYTES {
                self.pending = Vec::new();
                lines.push(Err(too_large("an SSE line", MAX_LINE_BYTES)));
                return lines;
            }
            self.pending.extend_from_slice(part);
            let Some(end) = end else {
                return lines;
            };
            lines.push(Ok(String::from_utf8_lossy(&self.pending).into_owned()));
            self.pending.clear();
            rest = rest.get(end + 1..).unwrap_or_default();
        }
    }

    /// The unterminated last line, at the end of the body.
    pub fn finish(&mut self) -> Option<String> {
        if self.pending.is_empty() {
            return None;
        }
        let line = String::from_utf8_lossy(&self.pending).into_owned();
        self.pending.clear();
        Some(line)
    }
}

/// A pydantic lax `int`: an integer, or a float with no fractional part.
fn lax_int<'de, D: Deserializer<'de>>(de: D) -> Result<i64, D::Error> {
    let value = Value::deserialize(de)?;
    as_lax_int(&value).ok_or_else(|| serde::de::Error::custom(format!("expected int, got {value}")))
}

fn as_lax_int(value: &Value) -> Option<i64> {
    if let Some(n) = value.as_i64() {
        return Some(n);
    }
    match value.as_f64() {
        #[allow(clippy::cast_possible_truncation)]
        Some(f) if f.is_finite() && f.fract() == 0.0 => Some(f as i64),
        _ => None,
    }
}

fn lax_opt_int<'de, D: Deserializer<'de>>(de: D) -> Result<Option<i64>, D::Error> {
    match Value::deserialize(de)? {
        Value::Null => Ok(None),
        value => as_lax_int(&value)
            .map(Some)
            .ok_or_else(|| serde::de::Error::custom(format!("expected int, got {value}"))),
    }
}

/// `_none_to_zero`: token-detail fields where `null` means 0.
fn lax_int_or_zero<'de, D: Deserializer<'de>>(de: D) -> Result<i64, D::Error> {
    Ok(lax_opt_int(de)?.unwrap_or(0))
}

/// `OpenAIStreamChunk`.
#[derive(Debug, Deserialize)]
struct StreamChunk {
    #[allow(dead_code)]
    id: String,
    #[allow(dead_code)]
    #[serde(deserialize_with = "lax_int")]
    created: i64,
    #[allow(dead_code)]
    model: String,
    #[serde(default)]
    choices: Vec<StreamChoice>,
    #[serde(default)]
    usage: Option<WireUsage>,
}

#[derive(Debug, Deserialize)]
struct StreamChoice {
    #[allow(dead_code)]
    #[serde(deserialize_with = "lax_int")]
    index: i64,
    delta: StreamDelta,
    #[serde(default)]
    finish_reason: Option<String>,
}

#[derive(Debug, Deserialize)]
struct StreamDelta {
    #[serde(default)]
    content: Option<String>,
    #[serde(default)]
    reasoning_content: Option<String>,
    #[serde(default)]
    reasoning_text: Option<String>,
    #[serde(default)]
    tool_calls: Option<Vec<ToolCallDelta>>,
}

#[derive(Debug, Deserialize)]
struct ToolCallDelta {
    #[serde(default, deserialize_with = "lax_opt_int")]
    index: Option<i64>,
    #[serde(default)]
    id: Option<String>,
    #[serde(default)]
    function: Option<FunctionDelta>,
}

#[derive(Debug, Deserialize)]
struct FunctionDelta {
    #[serde(default)]
    name: Option<String>,
    #[serde(default)]
    arguments: Option<String>,
}

/// `OpenAIUsage` with its detail objects.
#[derive(Debug, Deserialize)]
struct WireUsage {
    #[serde(default, deserialize_with = "lax_int")]
    prompt_tokens: i64,
    #[serde(default, deserialize_with = "lax_int")]
    completion_tokens: i64,
    #[serde(default, deserialize_with = "lax_int")]
    total_tokens: i64,
    #[serde(default)]
    prompt_tokens_details: Option<PromptDetails>,
    #[serde(default)]
    completion_tokens_details: Option<CompletionDetails>,
    #[serde(default, deserialize_with = "lax_int")]
    prompt_cache_hit_tokens: i64,
}

#[derive(Debug, Deserialize)]
struct PromptDetails {
    #[serde(default, deserialize_with = "lax_int_or_zero")]
    cached_tokens: i64,
    #[serde(default, deserialize_with = "lax_int_or_zero")]
    cache_write_tokens: i64,
    #[serde(default, deserialize_with = "lax_int_or_zero")]
    cache_creation_input_tokens: i64,
}

#[derive(Debug, Deserialize)]
struct CompletionDetails {
    #[serde(default, deserialize_with = "lax_int_or_zero")]
    reasoning_tokens: i64,
}

/// `_positive_token_count`.
fn positive(value: i64) -> Option<i64> {
    (value > 0).then_some(value)
}

/// `_usage_from_openai`.
fn usage_from_openai(u: &WireUsage) -> Usage {
    let (mut cached, cache_write) = match &u.prompt_tokens_details {
        Some(d) => (
            positive(d.cached_tokens),
            positive(d.cache_write_tokens).or(positive(d.cache_creation_input_tokens)),
        ),
        None => (None, None),
    };
    if cached.is_none() {
        cached = positive(u.prompt_cache_hit_tokens);
    }
    Usage {
        prompt_tokens: u.prompt_tokens,
        completion_tokens: u.completion_tokens,
        total_tokens: u.total_tokens,
        cached_tokens: cached,
        cache_write_tokens: cache_write,
        thoughts_tokens: u
            .completion_tokens_details
            .as_ref()
            .and_then(|d| positive(d.reasoning_tokens)),
        tool_use_tokens: None,
    }
}

/// One tool call being assembled from deltas.
#[derive(Debug, Default)]
struct ToolBuffer {
    id: String,
    name: String,
    arguments: String,
}

/// A different call landing in a slot that already has an id (logged only).
fn is_index_collision(existing_id: &str, new_id: &str) -> bool {
    !existing_id.is_empty() && new_id != existing_id
}

/// Grow one call's arguments, up to [`MAX_ARGUMENTS_BYTES`].
fn append_arguments(arguments: &mut String, more: &str) -> Result<(), ProviderError> {
    if arguments.len() + more.len() > MAX_ARGUMENTS_BYTES {
        return Err(too_large("a tool call's arguments", MAX_ARGUMENTS_BYTES));
    }
    arguments.push_str(more);
    Ok(())
}

fn is_json(text: &str) -> bool {
    serde_json::from_str::<Value>(text).is_ok()
}

/// Turns validated chunks into events and assembles tool calls the way
/// `stream_and_assemble` does.
#[derive(Debug, Default)]
pub struct Assembler {
    tool_calls: BTreeMap<i64, ToolBuffer>,
    finish_reason: Option<String>,
}

impl Assembler {
    /// Events for one SSE JSON payload, or the validation error Python raises.
    pub fn on_payload(&mut self, payload: Value) -> Result<Vec<ProviderEvent>, ProviderError> {
        let chunk: StreamChunk = serde_json::from_value(payload)
            .map_err(|e| ProviderError::InvalidChunk(e.to_string()))?;
        let mut events = Vec::new();
        let usage = chunk.usage.as_ref().map(usage_from_openai);
        if let Some(choice) = chunk.choices.into_iter().next() {
            let delta = choice.delta;
            let reasoning = delta
                .reasoning_content
                .filter(|r| !r.is_empty())
                .or(delta.reasoning_text)
                .filter(|r| !r.is_empty());
            if let Some(reasoning) = reasoning {
                events.push(ProviderEvent::ReasoningDelta(reasoning));
            }
            if let Some(content) = delta.content.filter(|c| !c.is_empty()) {
                events.push(ProviderEvent::TextDelta(content));
            }
            for tc in delta.tool_calls.unwrap_or_default() {
                self.on_tool_call(tc)?;
            }
            if let Some(reason) = choice.finish_reason.filter(|r| !r.is_empty()) {
                self.finish_reason = Some(reason);
            }
        }
        if let Some(usage) = usage {
            events.push(ProviderEvent::Usage(usage));
        }
        Ok(events)
    }

    fn on_tool_call(&mut self, tc: ToolCallDelta) -> Result<(), ProviderError> {
        let idx = tc.index.unwrap_or(0);
        let id = tc.id.filter(|id| !id.is_empty());
        let name = tc
            .function
            .as_ref()
            .and_then(|f| f.name.clone())
            .filter(|n| !n.is_empty());
        let arguments = tc
            .function
            .as_ref()
            .and_then(|f| f.arguments.clone())
            .filter(|a| !a.is_empty());
        if let (Some(new), Some(existing)) = (&id, self.tool_calls.get(&idx)) {
            if is_index_collision(&existing.id, new) {
                tracing::warn!(
                    idx,
                    existing_id = existing.id,
                    new_id = new,
                    "tool_call_index_collision"
                );
            }
        }
        let last_idx = self.tool_calls.keys().next_back().copied();
        if !self.tool_calls.contains_key(&idx) {
            // Copilot streams arguments as separate chunks with distinct
            // indices and no name or id: drop a repeat, append anything new.
            if id.is_none() && name.is_none() {
                if let Some(last) = self.tool_calls.values_mut().next_back() {
                    if let Some(args) = arguments {
                        if args != last.arguments {
                            append_arguments(&mut last.arguments, &args)?;
                        }
                    }
                    return Ok(());
                }
            }
            let mut buf = ToolBuffer {
                id: id.unwrap_or_default(),
                name: name.unwrap_or_default(),
                arguments: String::new(),
            };
            append_arguments(&mut buf.arguments, &arguments.unwrap_or_default())?;
            self.tool_calls.insert(idx, buf);
            return Ok(());
        }
        let previous_unnamed = idx > 0
            && last_idx == Some(idx)
            && self
                .tool_calls
                .get(&(idx - 1))
                .is_some_and(|prev| prev.name.is_empty());
        let Some(buf) = self.tool_calls.get_mut(&idx) else {
            return Ok(());
        };
        // Only the first id wins.
        if let Some(id) = id {
            if buf.id.is_empty() {
                buf.id = id;
            }
        }
        if let Some(name) = name {
            if buf.name.is_empty() {
                buf.name = name;
            } else if previous_unnamed {
                // Copilot may send the name at a new index when the previous
                // entry already has arguments but no name.
                if let Some(prev) = self.tool_calls.get_mut(&(idx - 1)) {
                    prev.name = name;
                }
            }
        }
        if let Some(args) = arguments {
            if let Some(buf) = self.tool_calls.get_mut(&idx) {
                if buf.arguments.is_empty() || !is_json(&buf.arguments) {
                    append_arguments(&mut buf.arguments, &args)?;
                }
            }
        }
        Ok(())
    }

    /// The assembled tool calls and `Done`. Half-formed calls are dropped: no
    /// name, or arguments that are not JSON (empty arguments are a no-arg
    /// call, sent as `{}`). A call without an id gets a synthesized one.
    pub fn finish(self) -> Vec<ProviderEvent> {
        let mut events = Vec::new();
        for (idx, buf) in self.tool_calls {
            let prefix: String = buf.arguments.chars().take(80).collect();
            if buf.name.is_empty() {
                tracing::warn!(idx, args_prefix = prefix, "drop_partial_tool_call_no_name");
                continue;
            }
            let arguments = if buf.arguments.is_empty() {
                Value::Object(serde_json::Map::new())
            } else {
                match serde_json::from_str(&buf.arguments) {
                    Ok(value) => value,
                    Err(_) => {
                        tracing::warn!(
                            idx,
                            name = buf.name,
                            args_prefix = prefix,
                            "drop_partial_tool_call_bad_json"
                        );
                        continue;
                    }
                }
            };
            let id = if buf.id.is_empty() {
                let id = synthesized_id();
                tracing::warn!(
                    idx,
                    name = buf.name,
                    synthesized_id = id,
                    "tool_call_missing_id"
                );
                id
            } else {
                buf.id
            };
            events.push(ProviderEvent::ToolCall {
                id,
                name: buf.name,
                arguments,
            });
        }
        events.push(ProviderEvent::Done {
            finish_reason: self.finish_reason.unwrap_or_default(),
        });
        events
    }
}

/// `f"call_{uuid.uuid4().hex[:24]}"`.
fn synthesized_id() -> String {
    let hex: String = (0..24)
        .map(|_| char::from_digit(fastrand::u32(0..16), 16).unwrap_or('0'))
        .collect();
    format!("call_{hex}")
}

/// The pending events of one response body, fed line by line. Events decoded
/// before a failing line are still delivered, then the error, then nothing:
/// Python yields each chunk before it parses the next.
#[derive(Debug, Default)]
pub struct EventDecoder {
    lines: LineSplitter,
    assembler: Assembler,
    queue: VecDeque<Result<ProviderEvent, ProviderError>>,
    /// `[DONE]` was seen, or a line failed: the rest of the body is ignored.
    done: bool,
    failed: bool,
}

impl EventDecoder {
    /// Feed body bytes.
    pub fn push(&mut self, bytes: &[u8]) {
        if self.done {
            return;
        }
        for line in self.lines.push(bytes) {
            match line {
                Ok(line) => self.on_line(&line),
                Err(error) => self.fail(error),
            }
        }
    }

    fn on_line(&mut self, line: &str) {
        if self.done {
            return;
        }
        match classify_line(line) {
            SseLine::Done => self.done = true,
            SseLine::Skip => {}
            SseLine::Data(value) => match self.assembler.on_payload(value) {
                Ok(events) => self.queue.extend(events.into_iter().map(Ok)),
                Err(error) => self.fail(error),
            },
        }
    }

    /// End the stream with `error` after the events already decoded.
    pub fn fail(&mut self, error: ProviderError) {
        if !self.failed {
            self.queue.push_back(Err(error));
        }
        self.done = true;
        self.failed = true;
    }

    /// Whether the body needs no more reading.
    pub fn is_done(&self) -> bool {
        self.done
    }

    pub fn pop(&mut self) -> Option<Result<ProviderEvent, ProviderError>> {
        self.queue.pop_front()
    }

    /// End of body: the last line, then the assembled tool calls and `Done`,
    /// unless a line failed.
    pub fn finish(&mut self) {
        if let Some(line) = self.lines.finish() {
            self.on_line(&line);
        }
        if self.failed {
            return;
        }
        let assembler = std::mem::take(&mut self.assembler);
        self.queue.extend(assembler.finish().into_iter().map(Ok));
    }
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::indexing_slicing, clippy::panic)]
mod tests {
    use super::*;
    use serde_json::json;

    fn chunk(delta: Value) -> Value {
        json!({"id": "c", "created": 1, "model": "m", "choices": [{"index": 0, "delta": delta}]})
    }

    fn tool(index: Option<i64>, id: Option<&str>, name: Option<&str>, args: Option<&str>) -> Value {
        let mut tc = json!({"function": {}});
        if let Some(index) = index {
            tc["index"] = json!(index);
        }
        if let Some(id) = id {
            tc["id"] = json!(id);
        }
        if let Some(name) = name {
            tc["function"]["name"] = json!(name);
        }
        if let Some(args) = args {
            tc["function"]["arguments"] = json!(args);
        }
        chunk(json!({"tool_calls": [tc]}))
    }

    fn calls(payloads: Vec<Value>) -> Vec<ProviderEvent> {
        let mut a = Assembler::default();
        for p in payloads {
            a.on_payload(p).unwrap();
        }
        a.finish()
    }

    fn call(id: &str, name: &str, arguments: Value) -> ProviderEvent {
        ProviderEvent::ToolCall {
            id: id.to_owned(),
            name: name.to_owned(),
            arguments,
        }
    }

    fn done() -> ProviderEvent {
        ProviderEvent::Done {
            finish_reason: String::new(),
        }
    }

    fn ok_lines(lines: &[&str]) -> Vec<Result<String, ProviderError>> {
        lines.iter().map(|l| Ok((*l).to_owned())).collect()
    }

    #[test]
    fn lines_split_on_every_terminator() {
        let mut s = LineSplitter::default();
        assert_eq!(s.push(b"a\r\nb"), ok_lines(&["a", ""]));
        assert_eq!(s.push(b"c\rd\n"), ok_lines(&["bc", "d"]));
        assert_eq!(s.push(b"tail"), ok_lines(&[]));
        assert_eq!(s.finish().as_deref(), Some("tail"));
        assert_eq!(s.finish(), None);
    }

    fn line_too_large() -> ProviderError {
        ProviderError::TooLarge {
            what: "an SSE line".into(),
            limit: MAX_LINE_BYTES,
        }
    }

    #[test]
    fn a_line_may_reach_the_cap_but_not_pass_it() {
        assert_eq!(MAX_LINE_BYTES, 16 * 1024 * 1024);
        let mut s = LineSplitter::default();
        let half = vec![b'x'; MAX_LINE_BYTES / 2];
        assert_eq!(s.push(&half), ok_lines(&[]));
        let mut rest = half.clone();
        rest.extend_from_slice(b"\nab");
        let lines = s.push(&rest);
        assert_eq!(lines.len(), 1);
        assert_eq!(lines[0].as_ref().map(String::len), Ok(MAX_LINE_BYTES));

        // "ab" is pending: two lines complete before one byte too many fails.
        let mut over = b"c\nd\n".to_vec();
        over.extend(vec![b'y'; MAX_LINE_BYTES]);
        over.extend_from_slice(b"\nnever");
        let lines = s.push(&over);
        let y = "y".repeat(MAX_LINE_BYTES);
        assert_eq!(lines, ok_lines(&["abc", "d", &y]));
        let mut s = LineSplitter::default();
        s.push(b"z");
        let lines = s.push(&vec![b'y'; MAX_LINE_BYTES]);
        assert_eq!(lines, vec![Err(line_too_large())]);
        assert_eq!(s.finish(), None);
    }

    #[test]
    fn decoder_ends_with_an_error_on_an_over_long_line() {
        let mut d = EventDecoder::default();
        let mut body = format!("data: {}\n", chunk(json!({"content": "a"}))).into_bytes();
        body.extend(vec![b' '; MAX_LINE_BYTES + 1]);
        d.push(&body);
        assert!(d.is_done());
        d.finish();
        assert_eq!(d.pop(), Some(Ok(ProviderEvent::TextDelta("a".into()))));
        assert_eq!(d.pop(), Some(Err(line_too_large())));
        assert_eq!(d.pop(), None);

        // After `[DONE]` the rest of the body is not even buffered.
        let mut d = EventDecoder::default();
        d.push(b"data: [DONE]\n");
        d.push(&vec![b' '; MAX_LINE_BYTES + 1]);
        d.finish();
        assert_eq!(d.pop(), Some(Ok(done())));
        assert_eq!(d.pop(), None);
    }

    fn arguments_too_large() -> ProviderError {
        ProviderError::TooLarge {
            what: "a tool call's arguments".into(),
            limit: MAX_ARGUMENTS_BYTES,
        }
    }

    #[test]
    fn arguments_may_reach_the_cap_but_not_pass_it() {
        assert_eq!(MAX_ARGUMENTS_BYTES, 16 * 1024 * 1024);
        let half = "x".repeat(MAX_ARGUMENTS_BYTES / 2);
        // Appending to an existing call.
        let mut a = Assembler::default();
        a.on_payload(tool(Some(0), Some("a"), Some("f"), Some(&half)))
            .unwrap();
        a.on_payload(tool(Some(0), None, None, Some(&half)))
            .unwrap();
        assert_eq!(
            a.on_payload(tool(Some(0), None, None, Some("y"))),
            Err(arguments_too_large())
        );
        // The Copilot path: a new index with no id or name.
        let mut a = Assembler::default();
        a.on_payload(tool(Some(0), Some("a"), Some("f"), Some(&half)))
            .unwrap();
        a.on_payload(tool(Some(1), None, None, Some(&format!("{half}y"))))
            .unwrap_err();
        let mut a = Assembler::default();
        a.on_payload(tool(Some(0), Some("a"), Some("f"), Some(&half)))
            .unwrap();
        a.on_payload(tool(Some(1), None, None, Some(&half)))
            .unwrap();
        // A first delta that is already too long.
        let mut a = Assembler::default();
        let full = "z".repeat(MAX_ARGUMENTS_BYTES);
        a.on_payload(tool(Some(0), Some("a"), Some("f"), Some(&full)))
            .unwrap();
        assert_eq!(
            a.on_payload(tool(
                Some(1),
                Some("b"),
                Some("g"),
                Some(&format!("{full}z"))
            )),
            Err(arguments_too_large())
        );
    }

    #[test]
    fn classifies_lines_like_iter_sse_data() {
        assert_eq!(classify_line("  data: [DONE]  "), SseLine::Done);
        assert_eq!(
            classify_line("data: {\"a\":1}"),
            SseLine::Data(json!({"a": 1}))
        );
        assert_eq!(classify_line("data:{\"a\":1}"), SseLine::Skip);
        assert_eq!(classify_line("event: x"), SseLine::Skip);
        assert_eq!(classify_line("data: nope"), SseLine::Skip);
        assert_eq!(classify_line(""), SseLine::Skip);
    }

    #[test]
    fn chunk_validation_matches_the_schema() {
        let mut a = Assembler::default();
        assert!(a.on_payload(json!({"created": 1, "model": "m"})).is_err());
        assert!(a
            .on_payload(json!({"id": "c", "created": 1.5, "model": "m"}))
            .is_err());
        assert!(a
            .on_payload(json!({"id": 1, "created": 1, "model": "m"}))
            .is_err());
        assert!(a.on_payload(json!(3)).is_err());
        assert!(a
            .on_payload(json!({"id": "c", "created": 1, "model": "m", "choices": [{"delta": {}}]}))
            .is_err());
        let ok = json!({"id": "c", "created": 2.0, "model": "m", "choices": [], "usage": null});
        assert_eq!(a.on_payload(ok).unwrap(), vec![]);
        let null_tokens =
            json!({"id": "c", "created": 1, "model": "m", "usage": {"prompt_tokens": null}});
        assert!(a.on_payload(null_tokens).is_err());
    }

    #[test]
    fn usage_prefers_details_then_top_level_cache_hits() {
        let mut a = Assembler::default();
        let usage =
            |u: Value| json!({"id": "c", "created": 1, "model": "m", "choices": [], "usage": u});
        let events = a
            .on_payload(usage(json!({
                "prompt_tokens": 5, "completion_tokens": 2.0, "total_tokens": 7,
                "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0, "cache_creation_input_tokens": 3},
                "completion_tokens_details": {"reasoning_tokens": null},
                "prompt_cache_hit_tokens": 2
            })))
            .unwrap();
        assert_eq!(
            events,
            vec![ProviderEvent::Usage(Usage {
                prompt_tokens: 5,
                completion_tokens: 2,
                total_tokens: 7,
                cached_tokens: Some(2),
                cache_write_tokens: Some(3),
                thoughts_tokens: None,
                tool_use_tokens: None,
            })]
        );
        let events = a
            .on_payload(usage(
                json!({"prompt_tokens_details": {"cached_tokens": 4, "cache_write_tokens": 6}}),
            ))
            .unwrap();
        assert_eq!(
            events,
            vec![ProviderEvent::Usage(Usage {
                cached_tokens: Some(4),
                cache_write_tokens: Some(6),
                ..Usage::default()
            })]
        );
    }

    #[test]
    fn text_reasoning_and_finish_reason() {
        let mut a = Assembler::default();
        let events = a
            .on_payload(chunk(
                json!({"content": "", "reasoning_content": "", "reasoning_text": "r"}),
            ))
            .unwrap();
        assert_eq!(events, vec![ProviderEvent::ReasoningDelta("r".into())]);
        let mut with_finish = chunk(json!({"content": "t"}));
        with_finish["choices"][0]["finish_reason"] = json!("length");
        assert_eq!(
            a.on_payload(with_finish).unwrap(),
            vec![ProviderEvent::TextDelta("t".into())]
        );
        let mut empty_finish = chunk(json!({}));
        empty_finish["choices"][0]["finish_reason"] = json!("");
        a.on_payload(empty_finish).unwrap();
        assert_eq!(
            a.finish(),
            vec![ProviderEvent::Done {
                finish_reason: "length".into()
            }]
        );
    }

    #[test]
    fn arguments_stop_growing_once_they_parse() {
        let events = calls(vec![
            tool(Some(0), Some("a"), Some("f"), Some("{\"x\":")),
            tool(Some(0), None, None, Some("1}")),
            tool(Some(0), None, None, Some("{\"y\":2}")),
            tool(Some(0), Some("b"), Some("g"), None),
        ]);
        assert_eq!(events, vec![call("a", "f", json!({"x": 1})), done()]);
    }

    #[test]
    fn first_delta_without_name_or_id_starts_a_call() {
        let events = calls(vec![
            tool(None, None, None, Some("{}")),
            tool(Some(0), Some("late"), Some("f"), None),
        ]);
        assert_eq!(events, vec![call("late", "f", json!({})), done()]);
    }

    #[test]
    fn copilot_name_on_a_new_index_names_the_previous_call() {
        let events = calls(vec![
            tool(Some(0), Some("a"), None, Some("{\"q\":1}")),
            tool(Some(1), Some("b"), Some("second"), None),
            tool(Some(1), None, Some("first"), None),
        ]);
        assert_eq!(
            events,
            vec![
                call("a", "first", json!({"q": 1})),
                call("b", "second", json!({})),
                done()
            ]
        );
        // Not the last index: nothing moves.
        let events = calls(vec![
            tool(Some(0), Some("a"), None, None),
            tool(Some(1), Some("b"), Some("x"), None),
            tool(Some(2), Some("c"), Some("y"), None),
            tool(Some(1), None, Some("z"), None),
        ]);
        assert_eq!(
            events,
            vec![call("b", "x", json!({})), call("c", "y", json!({})), done()]
        );
        // Index 0 has no previous entry.
        let events = calls(vec![
            tool(Some(0), Some("a"), Some("x"), None),
            tool(Some(0), None, Some("y"), None),
        ]);
        assert_eq!(events, vec![call("a", "x", json!({})), done()]);
    }

    #[test]
    fn index_collisions_need_a_different_existing_id() {
        assert!(is_index_collision("a", "b"));
        assert!(!is_index_collision("a", "a"));
        assert!(!is_index_collision("", "b"));
    }

    /// Python only names the previous call when `idx > 0`.
    #[test]
    fn index_zero_never_names_a_negative_slot() {
        let events = calls(vec![
            tool(Some(-1), Some("a"), None, Some("{}")),
            tool(Some(0), Some("b"), Some("x"), None),
            tool(Some(0), None, Some("y"), None),
        ]);
        assert_eq!(events, vec![call("b", "x", json!({})), done()]);
    }

    #[test]
    fn copilot_split_arguments_append_to_the_last_call() {
        let events = calls(vec![
            tool(Some(0), Some("a"), Some("f"), None),
            tool(Some(1), None, None, None),
            tool(Some(2), None, None, Some("{\"q\":")),
            tool(Some(3), None, None, Some("{\"q\":")),
            tool(Some(4), None, None, Some("2}")),
        ]);
        assert_eq!(events, vec![call("a", "f", json!({"q": 2})), done()]);
    }

    #[test]
    fn half_formed_calls_are_dropped_and_missing_ids_synthesized() {
        let events = calls(vec![
            tool(Some(0), Some("a"), None, Some("{}")),
            tool(Some(1), Some("b"), Some("f"), Some("{oops")),
            tool(Some(2), None, Some("g"), Some("[1]")),
        ]);
        let [ProviderEvent::ToolCall {
            id,
            name,
            arguments,
        }, last] = &events[..]
        else {
            panic!("{events:?}");
        };
        assert_eq!((name.as_str(), arguments), ("g", &json!([1])));
        assert!(id.starts_with("call_") && id.len() == 29, "{id}");
        assert!(id[5..]
            .chars()
            .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()));
        assert_eq!(last, &done());
    }

    #[test]
    fn decoder_stops_at_done_and_flushes_the_last_line() {
        let text = |t: &str| {
            format!(
                "data: {}

",
                chunk(json!({"content": t}))
            )
        };
        let mut d = EventDecoder::default();
        d.push(text("a").as_bytes());
        d.push(
            b"data: [DONE]
",
        );
        assert!(d.is_done());
        d.push(text("ignored").as_bytes());
        d.finish();
        assert_eq!(d.pop(), Some(Ok(ProviderEvent::TextDelta("a".into()))));
        assert_eq!(d.pop(), Some(Ok(done())));
        assert_eq!(d.pop(), None);

        let mut d = EventDecoder::default();
        d.push(format!("data: {}", chunk(json!({"content": "x"}))).as_bytes());
        assert!(d.pop().is_none());
        d.finish();
        assert_eq!(d.pop(), Some(Ok(ProviderEvent::TextDelta("x".into()))));
    }

    /// Both chunks in one read: the first is still delivered before the
    /// second fails, and nothing follows the error.
    #[test]
    fn a_bad_chunk_ends_the_stream_after_earlier_events() {
        let good = format!(
            "data: {}

",
            chunk(json!({"content": "ok"}))
        );
        let bad = "data: {\"choices\": []}

";
        let mut d = EventDecoder::default();
        d.push(format!("{good}{bad}{good}").as_bytes());
        assert!(d.is_done());
        d.push(good.as_bytes());
        d.finish();
        assert_eq!(d.pop(), Some(Ok(ProviderEvent::TextDelta("ok".into()))));
        assert!(matches!(d.pop(), Some(Err(ProviderError::InvalidChunk(_)))));
        assert_eq!(d.pop(), None);
        d.fail(ProviderError::RateLimited);
        assert_eq!(d.pop(), None);
    }

    #[test]
    fn a_body_error_drops_the_assembly() {
        let mut d = EventDecoder::default();
        d.push(
            format!(
                "data: {}
",
                tool(Some(0), Some("a"), Some("f"), Some("{}"))
            )
            .as_bytes(),
        );
        d.fail(ProviderError::RateLimited);
        d.finish();
        assert_eq!(d.pop(), Some(Err(ProviderError::RateLimited)));
        assert_eq!(d.pop(), None);
    }
}
