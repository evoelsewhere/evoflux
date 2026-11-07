//! Tools for working with the person: `ask_user` and `update_todos`.
//!
//! * `ask_user` puts 1–4 questions in the chat input (the app's question
//!   panel), each with options to pick (one or several) and a free answer, and
//!   waits for the answers. It goes through the same dialog channel as
//!   approval prompts (`ui_dialog_request` with `ui.kind = "questions"`). With
//!   no one to ask (a headless run) it says so, and the agent decides.
//! * `update_todos` replaces the run's task list. The engine keeps no state:
//!   the app shows the latest list from the transcript, pinned above the chat
//!   input, so it also survives a restart.

use std::sync::{Arc, OnceLock};
use std::time::Duration;

use async_trait::async_trait;
use evo_agent::agent_tool::AgentTool;
use evo_agent::error::AgentError;
use evo_agent::types::{AgentToolResult, TextContentOrImage, ToolExecutionMode, ToolResultPartial};
use evo_ai::types::{Schema, Tool};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio_util::sync::CancellationToken;

static MAILBOX: OnceLock<evo_extensions::UiDialogMailbox> = OnceLock::new();

/// The session's dialog channel (set once, at session start).
pub fn set_mailbox(mailbox: evo_extensions::UiDialogMailbox) {
    let _ = MAILBOX.set(mailbox);
}

// ── ask_user ─────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct QuestionOption {
    pub label: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Question {
    pub question: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub header: Option<String>,
    #[serde(default)]
    pub options: Vec<QuestionOption>,
    #[serde(default)]
    pub multi_select: bool,
}

#[derive(Deserialize)]
struct AskInput {
    questions: Vec<Question>,
}

/// Check the questions; the message says what to fix.
pub fn validate(questions: &[Question]) -> Result<(), String> {
    if questions.is_empty() || questions.len() > 4 {
        return Err("ask 1 to 4 questions".into());
    }
    for q in questions {
        if q.question.trim().is_empty() {
            return Err("every question needs text".into());
        }
        if q.options.len() == 1 || q.options.len() > 6 {
            return Err(format!("\"{}\": give 2 to 6 options, or none for a free answer", q.question));
        }
        let mut seen = std::collections::HashSet::new();
        for o in &q.options {
            if o.label.trim().is_empty() || !seen.insert(o.label.trim().to_lowercase()) {
                return Err(format!("\"{}\": options need distinct, non-empty labels", q.question));
            }
        }
    }
    Ok(())
}

/// The answers as the model reads them.
pub fn format_answers(questions: &[Question], answers: &Value) -> String {
    let list = answers.as_array().cloned().unwrap_or_default();
    let mut text = String::from("The person answered:\n");
    for (i, q) in questions.iter().enumerate() {
        let a = list.get(i).cloned().unwrap_or(Value::Null);
        let mut parts: Vec<String> = a
            .get("selected")
            .and_then(Value::as_array)
            .map(|s| s.iter().filter_map(Value::as_str).map(|x| format!("\"{x}\"")).collect())
            .unwrap_or_default();
        if let Some(other) = a.get("other").and_then(Value::as_str).filter(|s| !s.trim().is_empty()) {
            parts.push(format!("(their own words) {}", other.trim()));
        }
        let answer = if parts.is_empty() { "(no answer)".to_string() } else { parts.join(", ") };
        text.push_str(&format!("{}. {} → {}\n", i + 1, q.question.trim(), answer));
    }
    text.push_str("\nGo on with these answers.");
    text
}

pub struct AskUserTool {
    schema: Tool,
}

pub fn create_ask_user_tool() -> Arc<dyn AgentTool> {
    Arc::new(AskUserTool {
        schema: Tool {
            name: "ask_user".into(),
            description: "Ask the person 1–4 questions when you are blocked on a choice that is \
                 theirs to make (scope, a trade-off, a preference) and cannot settle it from the \
                 request, the code or a sensible default. Each question gets 2–6 short options \
                 (put the one you recommend first and add \"(Recommended)\"), or none for a free \
                 answer; they can always write their own answer. Do not ask what you can find out \
                 yourself, and do not ask for permission to proceed — just proceed."
                .into(),
            parameters: Schema::new(json!({
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 4,
                        "items": {
                            "type": "object",
                            "properties": {
                                "question": { "type": "string", "description": "The full question, ending with a question mark." },
                                "header": { "type": "string", "description": "A 1–2 word label shown as a chip, e.g. \"Database\"." },
                                "options": {
                                    "type": "array",
                                    "maxItems": 6,
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "label": { "type": "string", "description": "1–5 words." },
                                            "description": { "type": "string", "description": "What choosing it means." }
                                        },
                                        "required": ["label"],
                                        "additionalProperties": false
                                    }
                                },
                                "multi_select": { "type": "boolean", "description": "Allow several options." }
                            },
                            "required": ["question"],
                            "additionalProperties": false
                        }
                    }
                },
                "required": ["questions"],
                "additionalProperties": false
            })),
            constrained_sampling: None,
        },
    })
}

#[async_trait]
impl AgentTool for AskUserTool {
    fn schema(&self) -> &Tool {
        &self.schema
    }

    fn label(&self) -> &str {
        "ask_user"
    }

    fn execution_mode(&self) -> ToolExecutionMode {
        ToolExecutionMode::Sequential
    }

    async fn execute(
        &self,
        tool_call_id: &str,
        params: Value,
        signal: CancellationToken,
        _on_update: Arc<dyn Fn(ToolResultPartial) + Send + Sync>,
    ) -> Result<AgentToolResult, AgentError> {
        let input: AskInput =
            serde_json::from_value(params).map_err(|e| AgentError::Validation(format!("ask_user input: {e}")))?;
        validate(&input.questions).map_err(AgentError::Validation)?;
        let no_one = || {
            AgentError::Tool(
                "No one is available to answer right now. Decide yourself with the most sensible \
                 choice, and say which assumption you made."
                    .into(),
            )
        };
        let mailbox = MAILBOX.get().ok_or_else(no_one)?;
        let request_id = format!("ask:{tool_call_id}");
        let opened = mailbox.handle(json!({
            "op": "open",
            "requestId": request_id,
            "toolCallId": tool_call_id,
            "ui": {
                "kind": "questions",
                "title": input.questions[0].question,
                "questions": input.questions,
                "options": [],
            },
        }));
        if opened.is_err() {
            return Err(no_one());
        }
        let answers = loop {
            if signal.is_cancelled() {
                let _ = mailbox.cancel(&request_id);
                return Err(AgentError::Tool("cancelled".into()));
            }
            match mailbox.poll(&request_id) {
                Ok(state) => match state.get("status").and_then(Value::as_str) {
                    Some("answered") => {
                        break state
                            .get("answer")
                            .and_then(|a| a.get("answers"))
                            .cloned()
                            .unwrap_or(Value::Array(Vec::new()));
                    }
                    Some("cancelled") => {
                        return Ok(AgentToolResult {
                            content: vec![TextContentOrImage::text(
                                "The person dismissed the questions without answering. Do not ask \
                                 again; go on with the most sensible choice and say which you made.",
                            )],
                            details: json!({ "questions": input.questions, "dismissed": true }),
                            ..Default::default()
                        });
                    }
                    _ => {}
                },
                Err(error) => return Err(AgentError::Tool(error.to_string())),
            }
            tokio::time::sleep(Duration::from_millis(150)).await;
        };
        Ok(AgentToolResult {
            content: vec![TextContentOrImage::text(format_answers(&input.questions, &answers))],
            details: json!({ "questions": input.questions, "answers": answers }),
            ..Default::default()
        })
    }
}

// ── update_todos ─────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct Todo {
    pub content: String,
    pub status: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub active_form: Option<String>,
}

#[derive(Deserialize)]
struct TodosInput {
    todos: Vec<Todo>,
}

/// Check the list; returns a one-line summary.
pub fn summarize(todos: &[Todo]) -> Result<String, String> {
    if todos.len() > 30 {
        return Err("keep the list to 30 tasks or fewer".into());
    }
    for t in todos {
        if t.content.trim().is_empty() {
            return Err("every task needs text".into());
        }
        if !matches!(t.status.as_str(), "pending" | "in_progress" | "completed") {
            return Err(format!("\"{}\": status must be pending, in_progress or completed", t.content));
        }
    }
    let done = todos.iter().filter(|t| t.status == "completed").count();
    let active: Vec<&str> = todos.iter().filter(|t| t.status == "in_progress").map(|t| t.content.as_str()).collect();
    let mut text = format!("Tasks updated: {done} of {} done.", todos.len());
    match active.len() {
        0 if done < todos.len() => text.push_str(" Mark the next task in_progress when you start it."),
        0 => {}
        1 => text.push_str(&format!(" In progress: {}.", active[0])),
        _ => text.push_str(" Keep only one task in_progress at a time."),
    }
    Ok(text)
}

pub struct UpdateTodosTool {
    schema: Tool,
}

pub fn create_update_todos_tool() -> Arc<dyn AgentTool> {
    Arc::new(UpdateTodosTool {
        schema: Tool {
            name: "update_todos".into(),
            description: "Keep a visible task list for work with several steps (three or more, or \
                 when the person lists several things). Send the whole list each time: each task \
                 `pending`, `in_progress` (exactly one while you work) or `completed`. Mark a task \
                 completed as soon as it is done, not in batches; add tasks you discover. Skip it for \
                 a single quick step or a plain question."
                .into(),
            parameters: Schema::new(json!({
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": { "type": "string", "description": "What to do, imperative: \"Add the login form\"." },
                                "status": { "type": "string", "enum": ["pending", "in_progress", "completed"] },
                                "active_form": { "type": "string", "description": "Shown while in progress: \"Adding the login form\"." }
                            },
                            "required": ["content", "status"],
                            "additionalProperties": false
                        }
                    }
                },
                "required": ["todos"],
                "additionalProperties": false
            })),
            constrained_sampling: None,
        },
    })
}

#[async_trait]
impl AgentTool for UpdateTodosTool {
    fn schema(&self) -> &Tool {
        &self.schema
    }

    fn label(&self) -> &str {
        "update_todos"
    }

    fn execution_mode(&self) -> ToolExecutionMode {
        ToolExecutionMode::Sequential
    }

    async fn execute(
        &self,
        _tool_call_id: &str,
        params: Value,
        _signal: CancellationToken,
        _on_update: Arc<dyn Fn(ToolResultPartial) + Send + Sync>,
    ) -> Result<AgentToolResult, AgentError> {
        let input: TodosInput =
            serde_json::from_value(params).map_err(|e| AgentError::Validation(format!("update_todos input: {e}")))?;
        let text = summarize(&input.todos).map_err(AgentError::Validation)?;
        Ok(AgentToolResult {
            content: vec![TextContentOrImage::text(text)],
            details: json!({ "todos": input.todos }),
            ..Default::default()
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn q(text: &str, options: &[&str]) -> Question {
        Question {
            question: text.into(),
            header: None,
            options: options.iter().map(|l| QuestionOption { label: l.to_string(), description: None }).collect(),
            multi_select: false,
        }
    }

    #[test]
    fn questions_are_checked() {
        assert!(validate(&[q("Which?", &["A", "B"])]).is_ok());
        assert!(validate(&[q("Free answer?", &[])]).is_ok());
        assert!(validate(&[q("One?", &["A"])]).is_err());
        assert!(validate(&[q("Dupes?", &["A", "a"])]).is_err());
        assert!(validate(&[]).is_err());
        assert!(validate(&vec![q("x?", &["A", "B"]); 5]).is_err());
    }

    #[test]
    fn answers_read_well() {
        let qs = [q("Which DB?", &["Postgres", "SQLite"]), q("Name?", &[])];
        let text = format_answers(&qs, &json!([{ "selected": ["SQLite"] }, { "selected": [], "other": "evo-db" }]));
        assert!(text.contains("1. Which DB? → \"SQLite\""), "{text}");
        assert!(text.contains("2. Name? → (their own words) evo-db"), "{text}");
    }

    #[test]
    fn todos_are_summarized() {
        let t = |c: &str, s: &str| Todo { content: c.into(), status: s.into(), active_form: None };
        let s = summarize(&[t("A", "completed"), t("B", "in_progress"), t("C", "pending")]).unwrap();
        assert_eq!(s, "Tasks updated: 1 of 3 done. In progress: B.");
        assert!(summarize(&[t("A", "doing")]).is_err());
        assert!(summarize(&[t("A", "in_progress"), t("B", "in_progress")]).unwrap().contains("only one"));
    }
}
