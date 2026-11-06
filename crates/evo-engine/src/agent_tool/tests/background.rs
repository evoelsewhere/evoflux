//! Background agents and `message_agent`.
//!
//! The parent and a background child call the model at the same time, so a
//! fixed script order would race. Every step is a factory that answers by
//! looking at the conversation instead.

use super::*;
use evo_ai::providers::faux::{faux_assistant_message, FauxBlock, FauxStep};
use evo_ai::types::{Content, Context, Message, StopReason, UserContent};

fn user_texts(ctx: &Context) -> Vec<String> {
    ctx.messages
        .iter()
        .filter_map(|m| match m {
            Message::User(u) => Some(match &u.content {
                UserContent::Text(text) => text.clone(),
                UserContent::Blocks(blocks) => blocks
                    .iter()
                    .filter_map(|b| match b {
                        Content::Text(t) => Some(t.text.clone()),
                        _ => None,
                    })
                    .collect(),
            }),
            _ => None,
        })
        .collect()
}

/// Answers for the parent and its child; `parent_call` is the parent's first move.
fn script(parent_call: Value, log: Arc<Mutex<Vec<Vec<String>>>>, slow: bool) -> FauxScript {
    let script = if slow { FauxScript::new().with_tokens_per_second(4.0) } else { FauxScript::new() };
    let step = FauxStep::factory(move |ctx: &Context| {
        let users = user_texts(ctx);
        log.lock().unwrap().push(users.clone());
        let first = users.first().cloned().unwrap_or_default();
        let last = users.last().cloned().unwrap_or_default();
        let last_is_tool_result = matches!(ctx.messages.last(), Some(Message::ToolResult(_)));
        if first.contains("You are a subagent") {
            let text = if last.contains("FOLLOW-UP") {
                format!("follow-up answer, with {} earlier messages in view", ctx.messages.len() - 1)
            } else if slow {
                "a very long report ".repeat(60)
            } else {
                "background report: three call sites".to_string()
            };
            return faux_assistant_message(text, StopReason::Stop);
        }
        if last_is_tool_result {
            return faux_assistant_message("ok", StopReason::Stop);
        }
        if users.iter().any(|u| u.starts_with(NOTE_TAG)) {
            return faux_assistant_message("got the report", StopReason::Stop);
        }
        if users.len() == 1 {
            return faux_assistant_message(
                vec![FauxBlock::tool_call(
                    parent_call["name"].as_str().unwrap(),
                    parent_call["arguments"].clone(),
                )],
                StopReason::ToolUse,
            );
        }
        faux_assistant_message("ok", StopReason::Stop)
    });
    script.append_responses(vec![step; 40]);
    script
}

/// The agent's mesh node, by its description (each test uses its own).
fn node_by(description: &str) -> Option<crate::mesh::Node> {
    crate::mesh::router()
        .list(crate::mesh::ListScope::All, None)
        .unwrap()
        .into_iter()
        .find(|node| node.title == description)
}

fn settled_as(description: &str, status: crate::mesh::RunStatus) -> bool {
    node_by(description)
        .is_some_and(|n| n.state == crate::mesh::NodeState::Settled && n.status == Some(status))
}

async fn until(mut check: impl FnMut() -> bool) {
    tokio::time::timeout(Duration::from_secs(20), async {
        while !check() {
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
    .await
    .expect("condition not met in time");
}

fn text_of(result: &AgentToolResult) -> String {
    result
        .content
        .iter()
        .filter_map(|c| match c {
            TextContentOrImage::Text(t) => Some(t.text.clone()),
            _ => None,
        })
        .collect()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn a_background_agent_reports_to_the_idle_parent_on_its_next_run() {
    let dir = tempfile::tempdir().unwrap();
    let log = Arc::new(Mutex::new(Vec::new()));
    let call = json!({"name":"agent","arguments":{"description":"bg-report","prompt":"Count call sites.","background":true}});
    let events = Arc::new(Collector::default());
    let parent = parent(dir.path(), script(call, log.clone(), false), events.clone()).await;
    parent.lane("main").prompt_text("start it", Vec::new()).await.unwrap();

    // The call returned at once with the agent's id.
    let (result, is_error) = agent_end(&events);
    assert!(!is_error, "{result:?}");
    assert!(text_of(&result).starts_with("Started background agent"), "{}", text_of(&result));
    assert_eq!(result.details["child"]["background"], json!(true));
    let id = result.details["child"]["agentId"].as_str().unwrap().to_string();

    // It finishes after the parent's run ended, and asks for a wake on the
    // parent's session node.
    let session_id = parent.session().storage().metadata().id.clone();
    let session = crate::mesh::Address::session(&session_id);
    until(|| {
        settled_as("bg-report", crate::mesh::RunStatus::Done)
            && node_by("bg-report").is_some_and(|n| crate::mesh::router().pending_wake(&session).contains(&n.id.to_string()))
    })
    .await;
    let node = node_by("bg-report").unwrap();
    assert!(node.id.as_str().ends_with(&format!("/a_{id}")), "{}", node.id);
    assert_eq!(node.parent.as_ref(), Some(&session));
    assert!(node.meta["callId"].as_str().is_some_and(|c| !c.is_empty()));
    assert_eq!(node.meta["background"], json!(true));

    // The host wakes the parent: the report is in that run's context.
    parent.lane("main").prompt_text("[wake]", Vec::new()).await.unwrap();
    let seen = log.lock().unwrap().clone();
    let woken = seen
        .iter()
        .rev()
        .find(|users| users.iter().any(|u| u == "[wake]"))
        .expect("the wake run");
    let note = woken.iter().find(|u| u.starts_with(NOTE_TAG)).expect("the report was delivered");
    assert!(note.contains("background report: three call sites"), "{note}");
    assert!(note.contains(&id));
    // A run of the session (as the RPC host starts one) clears the request.
    crate::mesh::session_run(&session_id, true, None);
    assert!(crate::mesh::router().pending_wake(&session).is_empty());
    crate::mesh::session_run(&session_id, false, None);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn a_finished_agent_continues_with_its_context() {
    let dir = tempfile::tempdir().unwrap();
    let log = Arc::new(Mutex::new(Vec::new()));
    let call = json!({"name":"agent","arguments":{"description":"resumable","prompt":"Look around."}});
    let events = Arc::new(Collector::default());
    let parent = parent(dir.path(), script(call, log, false), events.clone()).await;
    parent.lane("main").prompt_text("first", Vec::new()).await.unwrap();
    let (result, _) = agent_end(&events);
    let id = result.details["child"]["agentId"].as_str().unwrap().to_string();

    // Continue it through the tool, as the model would.
    let cell: HarnessCell = Arc::new(OnceLock::new());
    let _ = cell.set(parent.downgrade());
    let tool = create_message_agent_tool(cell);
    let updates = Arc::new(Mutex::new(0usize));
    let counter = updates.clone();
    let reply = tool
        .execute(
            "call-2",
            json!({"agentId": id, "message": "FOLLOW-UP: and the tests?"}),
            CancellationToken::new(),
            Arc::new(move |_| *counter.lock().unwrap() += 1),
        )
        .await
        .unwrap();
    // Its first brief, its first reply and the follow-up are all in view.
    let text = text_of(&reply);
    assert!(text.starts_with("follow-up answer, with 2 earlier messages"), "{text}");
    assert!(*updates.lock().unwrap() >= 2, "the continued run streams progress too");
    assert!(reply.usage.is_some());
    // An unknown id is refused.
    let error = tool
        .execute("call-3", json!({"agentId":"nope","message":"hi"}), CancellationToken::new(), Arc::new(|_| {}))
        .await
        .unwrap_err();
    assert!(error.to_string().contains("no subagent `nope`"), "{error}");
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn a_background_agent_can_be_cancelled() {
    let dir = tempfile::tempdir().unwrap();
    let log = Arc::new(Mutex::new(Vec::new()));
    let call = json!({"name":"agent","arguments":{"description":"bg-cancel","prompt":"Write a lot.","background":true}});
    let events = Arc::new(Collector::default());
    let parent = parent(dir.path(), script(call, log, true), events).await;
    parent.lane("main").prompt_text("start", Vec::new()).await.unwrap();
    until(|| node_by("bg-cancel").is_some_and(|n| n.state == crate::mesh::NodeState::Running)).await;
    // Cancelled through the mesh, as a host does.
    let address = node_by("bg-cancel").unwrap().id;
    assert_eq!(crate::mesh::router().cancel(&address, true).unwrap(), vec![address.clone()]);
    until(|| settled_as("bg-cancel", crate::mesh::RunStatus::Cancelled)).await;
    assert!(crate::mesh::router().cancel(&address, true).unwrap().is_empty(), "nothing left to cancel");
}
