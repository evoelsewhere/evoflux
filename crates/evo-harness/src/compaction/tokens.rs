//! Mirrors the token-estimation + file-operation + conversation-serialization
//! pieces of `packages/agent/src/harness/compaction/utils.ts`, plus
//! `estimate_tokens`/`estimate_context_tokens` (from `compaction.ts`).
//!
//! The context-builder pieces (`build_session_context`/
//! `default_context_entry_transform`/`SessionContext`) are re-exported from
//! the canonical `session::context` module (the authoritative
//! `session/context.ts` port) — compaction's `tokens_before` path delegates to
//! that module's no-options wrapper so the two never diverge.

use std::collections::BTreeSet;

use evo_agent::message::AgentMessage;
use evo_ai::types::{AssistantMessage, Content, Message, Usage};

use crate::messages::{bash_execution_data, branch_summary_data, compaction_summary_data};
use crate::session::types::Entry;

// ---------------------------------------------------------------------------
// File operations — mirrors utils.ts FileOperations / extractFileOpsFromMessage
// / computeFileLists / formatFileOperations
// ---------------------------------------------------------------------------

/// Files touched by a session branch or compaction range. Mirrors TS
/// `FileOperations`. `BTreeSet` (not `HashSet`) so derived lists are sorted and
/// deterministic — the TS code sorts at `computeFileLists` time; we keep the
/// sets unsorted and sort once at list-computation, matching that.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct FileOperations {
    pub read: BTreeSet<String>,
    pub written: BTreeSet<String>,
    pub edited: BTreeSet<String>,
}

/// `createFileOps()` — an empty accumulator.
pub fn create_file_ops() -> FileOperations {
    FileOperations::default()
}

/// Add file operations from an assistant message's tool calls. Mirrors
/// `extractFileOpsFromMessage`: only `assistant` messages, only `toolCall`
/// blocks, classified by tool `name` (`read`/`write`/`edit`) using
/// `arguments.path`.
pub fn extract_file_ops_from_message(message: &AgentMessage, file_ops: &mut FileOperations) {
    let assistant = match message {
        AgentMessage::Assistant(a) => a,
        _ => return,
    };
    for block in &assistant.content {
        if let Content::ToolCall(call) = block {
            let path = match call.arguments.get("path") {
                Some(v) => match v.as_str() {
                    Some(s) => s,
                    None => continue,
                },
                None => continue,
            };
            match call.name.as_str() {
                "read" => {
                    file_ops.read.insert(path.to_string());
                }
                "write" => {
                    file_ops.written.insert(path.to_string());
                }
                "edit" => {
                    file_ops.edited.insert(path.to_string());
                }
                _ => {}
            }
        }
    }
}

/// Compute sorted read-only and modified file lists from accumulated operations.
/// Mirrors `computeFileLists`: `modified = edited ∪ written`; `readOnly = read
/// − modified`.
pub fn compute_file_lists(file_ops: &FileOperations) -> (Vec<String>, Vec<String>) {
    let modified: BTreeSet<String> = file_ops.edited.union(&file_ops.written).cloned().collect();
    let read_only: Vec<String> = file_ops
        .read
        .iter()
        .filter(|f| !modified.contains(*f))
        .cloned()
        .collect();
    let modified_files: Vec<String> = modified.into_iter().collect();
    (read_only, modified_files)
}

/// Format file lists as summary metadata XML tags. Mirrors
/// `formatFileOperations`: empty input → `""`; non-empty → `"\n\n"` + sections
/// joined `"\n\n"`.
pub fn format_file_operations(read_files: &[String], modified_files: &[String]) -> String {
    let mut sections: Vec<String> = Vec::new();
    if !read_files.is_empty() {
        sections.push(format!(
            "<read-files>\n{}\n</read-files>",
            read_files.join("\n")
        ));
    }
    if !modified_files.is_empty() {
        sections.push(format!(
            "<modified-files>\n{}\n</modified-files>",
            modified_files.join("\n")
        ));
    }
    if sections.is_empty() {
        String::new()
    } else {
        format!("\n\n{}", sections.join("\n\n"))
    }
}

// ---------------------------------------------------------------------------
// serializeConversation — mirrors utils.ts (operates on provider Message[])
// ---------------------------------------------------------------------------

const TOOL_RESULT_MAX_CHARS: usize = 2000;

/// `safeJsonStringify` — `JSON.stringify` with a fallback. Rust's
/// `serde_json::to_string` can fail on non-finite floats / cycles (cycles
/// impossible for `Value`); mirror the fallback string.
fn safe_json_stringify(value: &serde_json::Value) -> String {
    serde_json::to_string(value).unwrap_or_else(|_| "[unserializable]".to_string())
}

fn truncate_for_summary(text: &str, max_chars: usize) -> String {
    if text.len() <= max_chars {
        return text.to_string();
    }
    // TS slices by UTF-16 code units; for ASCII-heavy tool output this matches.
    // For multibyte content we slice by char boundary to stay valid UTF-8.
    let truncated: String = text.chars().take(max_chars).collect();
    let more = text.chars().count().saturating_sub(max_chars);
    format!("{truncated}\n\n[... {more} more characters truncated]")
}

/// Serialize LLM messages to plain text for summarization prompts. Mirrors
/// `serializeConversation`: `[User]`/`[Assistant]`/`[Assistant thinking]`/
/// `[Assistant tool calls]`/`[Tool result]` blocks joined `\n\n`.
pub fn serialize_conversation(messages: &[Message]) -> String {
    let mut parts: Vec<String> = Vec::new();
    for msg in messages {
        match msg {
            Message::User(u) => {
                let content = user_content_text(&u.content);
                if !content.is_empty() {
                    parts.push(format!("[User]: {content}"));
                }
            }
            Message::Assistant(a) => {
                let mut thinking_parts: Vec<String> = Vec::new();
                let mut tool_calls: Vec<String> = Vec::new();
                for block in &a.content {
                    match block {
                        Content::Thinking(t) => thinking_parts.push(t.thinking.clone()),
                        Content::ToolCall(call) => {
                            let args_str = match &call.arguments {
                                serde_json::Value::Object(map) => map
                                    .iter()
                                    .map(|(k, v)| format!("{k}={}", safe_json_stringify(v)))
                                    .collect::<Vec<_>>()
                                    .join(", "),
                                other => safe_json_stringify(other),
                            };
                            tool_calls.push(format!("{}({})", call.name, args_str));
                        }
                        _ => {}
                    }
                }
                if !thinking_parts.is_empty() {
                    parts.push(format!(
                        "[Assistant thinking]: {}",
                        thinking_parts.join("\n")
                    ));
                }
                if a.content.iter().any(|b| matches!(b, Content::Text(_))) {
                    parts.push(format!(
                        "[Assistant]: {}",
                        Content::text_only(&a.content, "\n")
                    ));
                }
                if !tool_calls.is_empty() {
                    parts.push(format!("[Assistant tool calls]: {}", tool_calls.join("; ")));
                }
            }
            Message::ToolResult(t) => {
                let content = Content::text_only(&t.content, "");
                if !content.is_empty() {
                    parts.push(format!(
                        "[Tool result]: {}",
                        truncate_for_summary(&content, TOOL_RESULT_MAX_CHARS)
                    ));
                }
            }
        }
    }
    parts.join("\n\n")
}

fn user_content_text(content: &evo_ai::types::UserContent) -> String {
    match content {
        evo_ai::types::UserContent::Text(s) => s.clone(),
        evo_ai::types::UserContent::Blocks(blocks) => Content::text_only(blocks, ""),
    }
}

// ---------------------------------------------------------------------------
// estimateTokens / estimateContextTokens — mirrors compaction.ts
// ---------------------------------------------------------------------------

const ESTIMATED_IMAGE_CHARS: usize = 4800;

/// Char count for text+image content (string or content blocks). Mirrors
/// `estimateTextAndImageContentChars`.
fn estimate_text_and_image_chars_content(content: &[Content]) -> usize {
    let mut chars = 0;
    for block in content {
        match block {
            Content::Text(t) => chars += t.text.len(),
            Content::Image(_) => chars += ESTIMATED_IMAGE_CHARS,
            _ => {}
        }
    }
    chars
}

/// Estimate token count for one message using the conservative chars/4
/// heuristic. Mirrors `estimateTokens(message)` per role.
pub fn estimate_tokens(message: &AgentMessage) -> i64 {
    let chars = estimate_message_chars(message);
    div_ceil(chars as i64, 4)
}

fn estimate_message_chars(message: &AgentMessage) -> usize {
    match message {
        AgentMessage::User(u) => match &u.content {
            evo_ai::types::UserContent::Text(s) => s.len(),
            evo_ai::types::UserContent::Blocks(blocks) => {
                estimate_text_and_image_chars_content(blocks)
            }
        },
        AgentMessage::Assistant(a) => estimate_assistant_chars(a),
        AgentMessage::ToolResult(t) => estimate_text_and_image_chars_content(&t.content),
        AgentMessage::Custom(c) => estimate_custom_chars(c),
    }
}

fn estimate_assistant_chars(a: &AssistantMessage) -> usize {
    let mut chars = 0;
    for block in &a.content {
        match block {
            Content::Text(t) => chars += t.text.len(),
            Content::Thinking(t) => chars += t.thinking.len(),
            Content::ToolCall(call) => {
                chars += call.name.len() + safe_json_stringify(&call.arguments).len();
            }
            _ => {}
        }
    }
    chars
}

fn estimate_custom_chars(c: &evo_agent::message::CustomMessage) -> usize {
    match c.role.as_str() {
        crate::messages::BASH_EXECUTION_ROLE => {
            if let Some(d) = bash_execution_data(&AgentMessage::Custom(c.clone())) {
                d.command.len() + d.output.len()
            } else {
                0
            }
        }
        crate::messages::BRANCH_SUMMARY_ROLE | crate::messages::COMPACTION_SUMMARY_ROLE => {
            if let Some(d) = branch_summary_data(&AgentMessage::Custom(c.clone())) {
                d.summary.len()
            } else if let Some(d) = compaction_summary_data(&AgentMessage::Custom(c.clone())) {
                d.summary.len()
            } else {
                0
            }
        }
        // Generic `custom` + unregistered roles → text+image chars of stored
        // content (mirrors the TS `custom`/`toolResult` arm).
        _ => estimate_text_and_image_chars_content(&c.content),
    }
}

fn div_ceil(a: i64, b: i64) -> i64 {
    // `Math.ceil(chars / 4)` — integer ceil division. Written by hand (not
    // `i64::div_ceil`) to keep the crate's MSRV (1.78) happy; `div_ceil`
    // stabilized only in 1.87.
    (a + b - 1) / b
}

/// The messages whose usage measured a context that is gone: those the
/// newest compaction kept.
///
/// After a compaction the context is its summary followed by the messages it
/// kept. An assistant message kept from before reports the usage of the
/// request it answered, which carried the whole conversation before the
/// compaction; only usage reported after them describes this context. The
/// summary says how many it kept (`retainedMessages`); a summary from before
/// that was recorded falls back to timestamps (kept messages are older).
enum Stale {
    None,
    /// Indices `..end` (the summary and its retained messages).
    Before(usize),
    /// Messages written at or before this time.
    Until(i64),
}

fn stale_usage(messages: &[AgentMessage]) -> Stale {
    let found = messages
        .iter()
        .enumerate()
        .rev()
        .find_map(|(index, message)| match message {
            AgentMessage::Custom(custom)
                if custom.role == crate::messages::COMPACTION_SUMMARY_ROLE =>
            {
                Some((index, custom))
            }
            _ => None,
        });
    match found {
        None => Stale::None,
        Some((index, custom)) => match custom
            .data
            .get("retainedMessages")
            .and_then(serde_json::Value::as_u64)
        {
            Some(retained) => Stale::Before(index + 1 + retained as usize),
            None => Stale::Until(custom.timestamp),
        },
    }
}

/// Return the last valid assistant usage (stop_reason not aborted/error,
/// `context_tokens > 0`, not measured before the newest compaction) along
/// with its index, or `None`. Mirrors `getLastAssistantUsageInfo`.
fn last_assistant_usage_info(messages: &[AgentMessage]) -> Option<(Usage, usize)> {
    let stale = stale_usage(messages);
    for (i, msg) in messages.iter().enumerate().rev() {
        if let AgentMessage::Assistant(a) = msg {
            let current = match stale {
                Stale::None => true,
                Stale::Before(end) => i >= end,
                Stale::Until(at) => a.timestamp > at,
            };
            if a.stop_reason != evo_ai::types::StopReason::Aborted
                && a.stop_reason != evo_ai::types::StopReason::Error
                && a.usage.context_tokens() > 0
                && current
            {
                return Some((a.usage.clone(), i));
            }
        }
    }
    None
}

/// Estimated context-token usage for a message list. Mirrors
/// `estimateContextTokens` + `ContextUsageEstimate`.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ContextUsageEstimate {
    pub tokens: i64,
    pub usage_tokens: i64,
    pub trailing_tokens: i64,
    pub last_usage_index: Option<usize>,
}

/// How much the provider's count exceeded the character estimate for the
/// context the newest compaction in `messages` replaced (its `tokensBefore`
/// over its `estimatedBefore`), within `1.0..=8.0`. The same content runs
/// on in the compacted context, and the estimate leaves out what only a
/// provider counts (system prompt, tools) and undercounts text that is not
/// English. `1.0` without a compaction or its estimate.
fn compaction_calibration(messages: &[AgentMessage]) -> f64 {
    let data = messages
        .iter()
        .rev()
        .find_map(crate::messages::compaction_summary_data);
    match data {
        Some(data) => match data.estimated_before {
            Some(estimated) if estimated > 0 && data.tokens_before > 0 => {
                (data.tokens_before as f64 / estimated as f64).clamp(1.0, 8.0)
            }
            _ => 1.0,
        },
        None => 1.0,
    }
}

pub fn estimate_context_tokens(messages: &[AgentMessage]) -> ContextUsageEstimate {
    match last_assistant_usage_info(messages) {
        None => {
            let mut estimated = 0i64;
            for m in messages {
                estimated += estimate_tokens(m);
            }
            // A compacted context nobody has measured yet: scale the estimate
            // the way the compacted content was measured before.
            let calibration = compaction_calibration(messages);
            if calibration > 1.0 {
                estimated = (estimated as f64 * calibration).ceil() as i64;
            }
            ContextUsageEstimate {
                tokens: estimated,
                usage_tokens: 0,
                trailing_tokens: estimated,
                last_usage_index: None,
            }
        }
        Some((usage, index)) => {
            let usage_tokens = usage.context_tokens();
            let mut trailing_tokens = 0i64;
            for m in messages.iter().skip(index + 1) {
                trailing_tokens += estimate_tokens(m);
            }
            ContextUsageEstimate {
                tokens: usage_tokens + trailing_tokens,
                usage_tokens,
                trailing_tokens,
                last_usage_index: Some(index),
            }
        }
    }
}

// ---------------------------------------------------------------------------
// build_session_context — compaction's tokensBefore path delegates to the
// canonical `session::context` module (the authoritative `session/context.ts`
// port). The no-options shape compaction needs is `build_session_context_default`.
// ---------------------------------------------------------------------------

/// `defaultContextEntryTransform` — re-exported from the canonical context
/// module so compaction callers reach it without a second path. Mirrors
/// `defaultContextEntryTransform`.
pub use crate::session::context::default_context_entry_transform;

/// `SessionContext` — re-exported from the canonical context module. Mirrors TS
/// `SessionContext`. Carried in `compaction::tokens` for tokens-path callers.
pub use crate::session::context::SessionContext;

/// `buildSessionContext(pathEntries)` (no options) — the shape compaction uses
/// for `tokensBefore`. Delegates to the canonical context builder. Mirrors TS
/// `buildSessionContext`.
pub fn build_session_context(path_entries: &[Entry]) -> SessionContext {
    crate::session::context::build_session_context(path_entries, &Default::default())
}

#[cfg(test)]
mod tests {
    use super::*;
    use evo_agent::message::AgentMessage;
    use evo_ai::types::{UserContent, UserMessage};

    fn user(text: &str) -> AgentMessage {
        AgentMessage::User(UserMessage::new(UserContent::Text(text.into()), 1))
    }

    #[test]
    fn estimate_tokens_user_chars_div_4_ceil() {
        // 8 chars → ceil(8/4)=2.
        assert_eq!(estimate_tokens(&user("abcdefgh")), 2);
        // 9 chars → ceil(9/4)=3.
        assert_eq!(estimate_tokens(&user("abcdefghi")), 3);
        assert_eq!(estimate_tokens(&user("")), 0);
    }

    #[test]
    fn extract_file_ops_classifies_read_write_edit() {
        // Build a real assistant with three tool calls.
        let mut a =
            evo_ai::types::AssistantMessage::empty(evo_ai::types::Api::Faux, "faux", "faux", 1);
        a.content.push(Content::tool_call(
            "c1",
            "read",
            serde_json::json!({"path": "/a"}),
        ));
        a.content.push(Content::tool_call(
            "c2",
            "write",
            serde_json::json!({"path": "/b"}),
        ));
        a.content.push(Content::tool_call(
            "c3",
            "edit",
            serde_json::json!({"path": "/c"}),
        ));
        let msg = AgentMessage::Assistant(Box::new(a));
        let mut ops = create_file_ops();
        extract_file_ops_from_message(&msg, &mut ops);
        assert!(ops.read.contains("/a"));
        assert!(ops.written.contains("/b"));
        assert!(ops.edited.contains("/c"));
        let (read, modified) = compute_file_lists(&ops);
        assert_eq!(read, vec!["/a".to_string()]);
        assert_eq!(modified, vec!["/b".to_string(), "/c".to_string()]);
    }

    #[test]
    fn format_file_operations_empty_and_nonempty() {
        assert_eq!(format_file_operations(&[], &[]), "");
        let s = format_file_operations(&["/a".into(), "/b".into()], &["/c".into()]);
        assert!(s.starts_with("\n\n"));
        assert!(s.contains("<read-files>"));
        assert!(s.contains("/a"));
        assert!(s.contains("<modified-files>"));
        assert!(s.contains("/c"));
    }

    #[test]
    fn serialize_conversation_renders_roles() {
        let msgs = vec![Message::User(UserMessage::new(
            UserContent::Text("hello".into()),
            1,
        ))];
        let s = serialize_conversation(&msgs);
        assert_eq!(s, "[User]: hello");
    }

    #[test]
    fn estimate_context_tokens_no_usage_sums_all() {
        let msgs = vec![user("abcdefgh"), user("abcdefgh")]; // 2 + 2 = 4.
        let est = estimate_context_tokens(&msgs);
        assert_eq!(est.tokens, 4);
        assert_eq!(est.usage_tokens, 0);
        assert!(est.last_usage_index.is_none());
    }

    #[test]
    fn estimate_context_tokens_uses_last_assistant_usage_plus_trailing() {
        let mut a =
            evo_ai::types::AssistantMessage::empty(evo_ai::types::Api::Faux, "faux", "faux", 1);
        a.usage = Usage {
            input: 100,
            output: 10,
            cache_read: 0,
            cache_write: 0,
            cache_write_1h: None,
            reasoning: None,
            total_tokens: 110,
            cost: evo_ai::types::UsageCost::default(),
        };
        a.stop_reason = evo_ai::types::StopReason::Stop;
        let msgs = vec![
            user("abcdefgh"),                     // 2
            AgentMessage::Assistant(Box::new(a)), // usage 110, index 1
            user("abcdefghi"),                    // 3 trailing
        ];
        let est = estimate_context_tokens(&msgs);
        assert_eq!(est.usage_tokens, 110);
        assert_eq!(est.trailing_tokens, 3);
        assert_eq!(est.tokens, 113);
        assert_eq!(est.last_usage_index, Some(1));
    }

    /// After a compaction, a kept assistant message's usage measured the whole
    /// conversation before it: the context is estimated instead, until a
    /// newer request reports usage.
    #[test]
    fn usage_from_before_a_compaction_is_not_the_compacted_context() {
        let assistant = |input: i64, timestamp: i64| {
            let mut a = evo_ai::types::AssistantMessage::empty(
                evo_ai::types::Api::Faux,
                "faux",
                "faux",
                timestamp,
            );
            a.usage = Usage {
                input,
                output: 0,
                cache_read: 0,
                cache_write: 0,
                cache_write_1h: None,
                reasoning: None,
                total_tokens: input,
                cost: evo_ai::types::UsageCost::default(),
            };
            a.stop_reason = evo_ai::types::StopReason::Stop;
            AgentMessage::Assistant(Box::new(a))
        };
        let summary =
            crate::messages::create_compaction_summary_message("earlier work", 90_000, 50);
        // The summary, then a kept assistant message whose request saw 90k tokens.
        let compacted = vec![summary.clone(), user("abcdefgh"), assistant(90_000, 40)];
        let est = estimate_context_tokens(&compacted);
        assert!(est.last_usage_index.is_none(), "the kept usage is stale");
        assert!(
            est.tokens < 1_000,
            "estimated from the compacted messages: {}",
            est.tokens
        );
        // A request after the compaction reports the context again.
        let later = vec![
            summary,
            user("abcdefgh"),
            assistant(90_000, 40),
            user("abcd"),
            assistant(12_000, 60),
        ];
        let est = estimate_context_tokens(&later);
        assert_eq!((est.usage_tokens, est.last_usage_index), (12_000, Some(4)));

        // The summary says how many messages it kept: that decides, even when
        // every timestamp is the same.
        let counted = crate::messages::with_compaction_facts(
            crate::messages::create_compaction_summary_message("earlier work", 90_000, 1),
            2,
            None,
        );
        let same_time = vec![
            counted,
            user("abcdefgh"),
            assistant(90_000, 1),
            user("abcd"),
            assistant(12_000, 1),
        ];
        let est = estimate_context_tokens(&same_time);
        assert_eq!((est.usage_tokens, est.last_usage_index), (12_000, Some(4)));
        assert!(estimate_context_tokens(&same_time[..3])
            .last_usage_index
            .is_none());
    }

    /// An unmeasured compacted context is scaled by how the provider counted
    /// the context the compaction replaced, compared with the estimate.
    #[test]
    fn a_compacted_context_is_estimated_the_way_it_was_measured() {
        let entry = crate::session::types::CompactionEntry {
            base: crate::session::types::EntryBase {
                entry_type: "compaction".into(),
                id: "c".into(),
                seq: 1,
                parent_id: None,
                timestamp: 50,
            },
            summary: "earlier work".into(),
            retained_tail: vec![user(&"x".repeat(4_000))], // 1,000 estimated
            tokens_before: 90_000,
            details: Some(
                serde_json::json!({ "readFiles": [], "modifiedFiles": [], "estimatedBefore": 30_000 }),
            ),
            usage: None,
        };
        let summary = crate::messages::compaction_summary_message_of(&entry);
        assert_eq!(
            crate::messages::compaction_summary_data(&summary)
                .unwrap()
                .estimated_before,
            Some(30_000)
        );
        let mut messages = vec![summary];
        messages.extend(entry.retained_tail.clone());
        let plain: i64 = messages.iter().map(estimate_tokens).sum();
        let est = estimate_context_tokens(&messages);
        // 90,000 measured for 30,000 estimated: three times the estimate.
        assert_eq!(est.tokens, plain * 3);
        assert!(est.last_usage_index.is_none());

        // Entries written before the estimate was stored are not scaled.
        let old = crate::session::types::CompactionEntry {
            details: None,
            ..entry.clone()
        };
        let mut messages = vec![crate::messages::compaction_summary_message_of(&old)];
        messages.extend(old.retained_tail.clone());
        assert_eq!(estimate_context_tokens(&messages).tokens, plain);

        // A wild ratio is bounded.
        let wild = crate::session::types::CompactionEntry {
            details: Some(serde_json::json!({ "estimatedBefore": 1 })),
            ..entry
        };
        let mut messages = vec![crate::messages::compaction_summary_message_of(&wild)];
        messages.extend(wild.retained_tail.clone());
        assert_eq!(estimate_context_tokens(&messages).tokens, plain * 8);
    }
}
