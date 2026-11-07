//! Agents talking to each other (mesh_tools.rs): ask / reply between
//! siblings, a cyclic ask refused, a message to the parent, list_nodes.
//!
//! One scripted model serves the parent and its agents; each step looks at
//! the conversation to know whom it answers.

use super::*;
use evo_ai::providers::faux::{faux_assistant_message, FauxBlock, FauxStep};
use evo_ai::types::{Content, Context, Message, StopReason, UserContent};
use evo_harness::types::{AgentHarnessOptions, HarnessTool};

fn texts(content: &[Content]) -> String {
    content
        .iter()
        .filter_map(|c| match c {
            Content::Text(t) => Some(t.text.clone()),
            _ => None,
        })
        .collect()
}

fn user_texts(ctx: &Context) -> Vec<String> {
    ctx.messages
        .iter()
        .filter_map(|m| match m {
            Message::User(u) => Some(match &u.content {
                UserContent::Text(text) => text.clone(),
                UserContent::Blocks(blocks) => texts(blocks),
            }),
            _ => None,
        })
        .collect()
}

/// Tool results so far: (tool name, text, is_error).
fn tool_results(ctx: &Context) -> Vec<(String, String, bool)> {
    ctx.messages
        .iter()
        .filter_map(|m| match m {
            Message::ToolResult(r) => Some((r.tool_name.clone(), texts(&r.content), r.is_error)),
            _ => None,
        })
        .collect()
}

fn call(name: &str, args: Value) -> evo_ai::types::AssistantMessage {
    faux_assistant_message(vec![FauxBlock::tool_call(name, args)], StopReason::ToolUse)
}

fn say(text: impl Into<String>) -> evo_ai::types::AssistantMessage {
    faux_assistant_message(text.into(), StopReason::Stop)
}

static NEXT: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

/// A parent with the built-in tools, `agent` and the mesh tools.
async fn parent_with_mesh(
    cwd: &std::path::Path,
    script: FauxScript,
    events: Arc<Collector>,
) -> AgentHarness {
    let provider = evo_ai::providers::faux::FauxProvider::new(script);
    let cell: HarnessCell = Arc::new(OnceLock::new());
    let mut tools = crate::session::builtin_tools_in(cwd);
    tools.push(HarnessTool::new(create_agent_tool(
        cell.clone(),
        cwd.to_path_buf(),
    )));
    tools.extend(
        crate::mesh_tools::create(cell.clone(), None)
            .into_iter()
            .map(HarnessTool::new),
    );
    let active_tool_names = tools
        .iter()
        .map(|tool| tool.tool.schema().name.clone())
        .collect();
    let session = Session::new(
        Arc::new(InMemorySessionStorage::new(
            SessionMetadata {
                id: format!(
                    "peers-{}",
                    NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
                ),
                created_at: 0,
                parent_session_id: None,
            },
            Arc::new(SystemClock),
            Arc::new(DefaultIdGenerator::new()),
        )),
        None,
    );
    let harness = AgentHarness::create(AgentHarnessOptions {
        model: provider.default_model().clone(),
        models: vec![provider],
        tools,
        active_tool_names,
        session,
        agent_emitter: Some(events),
        ..Default::default()
    })
    .await
    .unwrap();
    let _ = cell.set(harness.downgrade());
    harness
}

fn script(
    step: impl Fn(&Context) -> evo_ai::types::AssistantMessage + Send + Sync + 'static,
) -> FauxScript {
    let step = FauxStep::factory(step);
    let script = FauxScript::new();
    script.append_responses(vec![step; 60]);
    script
}

/// Every `agent` call's result, in order.
fn agent_results(events: &Collector) -> Vec<(AgentToolResult, bool)> {
    events
        .0
        .lock()
        .unwrap()
        .iter()
        .filter_map(|event| match event {
            AgentEvent::ToolExecutionEnd {
                tool_name,
                result,
                is_error,
                ..
            } if tool_name == "agent" => Some((result.clone(), *is_error)),
            _ => None,
        })
        .collect()
}

fn report(result: &AgentToolResult) -> String {
    texts_of(&result.content)
}

fn texts_of(content: &[TextContentOrImage]) -> String {
    content
        .iter()
        .filter_map(|c| match c {
            TextContentOrImage::Text(t) => Some(t.text.clone()),
            _ => None,
        })
        .collect()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn a_subagent_asks_its_sibling_and_gets_the_answer() {
    let dir = tempfile::tempdir().unwrap();
    let parent_seen = Arc::new(Mutex::new(Vec::<String>::new()));
    let seen = parent_seen.clone();
    let script = script(move |ctx| {
        let users = user_texts(ctx);
        let first = users.first().cloned().unwrap_or_default();
        let results = tool_results(ctx);
        if first.contains("Remember the code word") {
            // The answerer: first run remembers; a question continues it.
            let asked = users.iter().rev().find(|u| u.contains("kind=\"ask\""));
            let replied = results.iter().any(|(name, _, _)| name == "reply");
            return match asked {
                Some(question) if !replied => {
                    let id = question
                        .split("<mail id=\"")
                        .nth(1)
                        .and_then(|s| s.split('"').next())
                        .unwrap();
                    call("reply", json!({ "askId": id, "answer": "swordfish" }))
                }
                Some(_) => say("replied"),
                None => say("Remembered."),
            };
        }
        if first.contains("Find the code word") {
            // The asker: list who is around, ask the sibling, report.
            return match results.last() {
                None => call("list_nodes", json!({})),
                Some((name, _, _)) if name == "list_nodes" => call(
                    "ask",
                    json!({ "to": "Answerer", "question": "What is the code word?" }),
                ),
                Some((name, text, _)) if name == "ask" => say(format!("The code word: {text}")),
                Some(_) => say("unexpected"),
            };
        }
        // The parent: start the answerer, then the asker.
        seen.lock().unwrap().extend(users.clone());
        match results.len() {
            0 => call(
                "agent",
                json!({ "description": "Answerer", "prompt": "Remember the code word swordfish." }),
            ),
            1 => call(
                "agent",
                json!({ "description": "Asker", "prompt": "Find the code word: ask the Answerer." }),
            ),
            _ => say("done"),
        }
    });
    let events = Arc::new(Collector::default());
    let parent = parent_with_mesh(dir.path(), script, events.clone()).await;
    parent
        .lane("main")
        .prompt_text("go", Vec::new())
        .await
        .unwrap();

    let results = agent_results(&events);
    assert_eq!(results.len(), 2, "{results:?}");
    let (asker, is_error) = &results[1];
    assert!(!is_error, "{asker:?}");
    let text = report(asker);
    assert!(
        text.contains("Answerer answered:") && text.contains("swordfish"),
        "{text}"
    );
    // list_nodes showed the parent and the sibling.
    let rows: Vec<String> = asker.details["child"]["tools"]
        .as_array()
        .unwrap()
        .iter()
        .map(|row| {
            format!(
                "{}:{}",
                row["name"].as_str().unwrap(),
                row["phase"].as_str().unwrap()
            )
        })
        .collect();
    assert_eq!(rows, ["list_nodes:done", "ask:done"]);
    // The answerer's continued run went to the asker, not to the parent as a note.
    tokio::time::sleep(Duration::from_millis(300)).await;
    assert!(
        !parent_seen
            .lock()
            .unwrap()
            .iter()
            .any(|u| u.starts_with(NOTE_TAG)),
        "{:?}",
        parent_seen.lock().unwrap()
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn asking_the_session_that_waits_on_you_is_refused_and_a_message_reaches_it() {
    let dir = tempfile::tempdir().unwrap();
    let parent_seen = Arc::new(Mutex::new(Vec::<String>::new()));
    let seen = parent_seen.clone();
    let script = script(move |ctx| {
        let users = user_texts(ctx);
        let first = users.first().cloned().unwrap_or_default();
        let results = tool_results(ctx);
        if first.contains("Check in with the parent") {
            return match results.last() {
                None => call(
                    "ask",
                    json!({ "to": "parent", "question": "May I delete the cache?" }),
                ),
                Some((name, text, true)) if name == "ask" => {
                    // Refused: tell it instead, without waiting.
                    let _ = text;
                    call(
                        "send_message",
                        json!({ "to": "parent", "message": "FYI: the cache is 3 GB." }),
                    )
                }
                Some((name, _, _)) if name == "send_message" => say("Told the parent."),
                Some(_) => say("unexpected"),
            };
        }
        seen.lock().unwrap().extend(users.clone());
        if results.is_empty() {
            call(
                "agent",
                json!({ "description": "Checker", "prompt": "Check in with the parent." }),
            )
        } else {
            say("ok")
        }
    });
    let events = Arc::new(Collector::default());
    let parent = parent_with_mesh(dir.path(), script, events.clone()).await;
    parent
        .lane("main")
        .prompt_text("go", Vec::new())
        .await
        .unwrap();

    let results = agent_results(&events);
    let (checker, is_error) = &results[0];
    assert!(!is_error, "{checker:?}");
    let rows = checker.details["child"]["tools"]
        .as_array()
        .unwrap()
        .clone();
    assert_eq!(
        (rows[0]["name"].as_str(), rows[0]["phase"].as_str()),
        (Some("ask"), Some("error"))
    );
    assert_eq!(
        (rows[1]["name"].as_str(), rows[1]["phase"].as_str()),
        (Some("send_message"), Some("done"))
    );
    // The message was steered into the parent's run: its next step read it.
    let seen = parent_seen.lock().unwrap().clone();
    let mail = seen
        .iter()
        .find(|u| u.starts_with("<mail "))
        .expect("the parent read the message");
    assert!(
        mail.contains("kind=\"message\"")
            && mail.contains("title=\"Checker\"")
            && mail.contains("3 GB"),
        "{mail}"
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn the_refusal_says_why_and_reply_checks_the_asker() {
    // Unit-level checks on the tools, without a model run.
    let dir = tempfile::tempdir().unwrap();
    let parent = parent_with_mesh(
        dir.path(),
        script(|_| say("ok")),
        Arc::new(Collector::default()),
    )
    .await;
    let cell: HarnessCell = Arc::new(OnceLock::new());
    let _ = cell.set(parent.downgrade());
    let tools = crate::mesh_tools::create(cell, None);
    let by_name = |name: &str| {
        tools
            .iter()
            .find(|t| t.schema().name == name)
            .unwrap()
            .clone()
    };
    let noop: Arc<dyn Fn(ToolResultPartial) + Send + Sync> = Arc::new(|_| {});
    // Nobody to talk to yet.
    let error = by_name("send_message")
        .execute(
            "c1",
            json!({ "to": "nobody", "message": "hi" }),
            CancellationToken::new(),
            noop.clone(),
        )
        .await
        .unwrap_err();
    assert!(
        error.to_string().contains("you can reach: nobody"),
        "{error}"
    );
    // A reply to a question that does not exist.
    let error = by_name("reply")
        .execute(
            "c2",
            json!({ "askId": "m_0", "answer": "x" }),
            CancellationToken::new(),
            noop.clone(),
        )
        .await
        .unwrap_err();
    assert!(error.to_string().contains("no open question"), "{error}");
    let listed = by_name("list_nodes")
        .execute("c3", json!({}), CancellationToken::new(), noop)
        .await
        .unwrap();
    assert_eq!(listed.details["nodes"], json!([]));
}
