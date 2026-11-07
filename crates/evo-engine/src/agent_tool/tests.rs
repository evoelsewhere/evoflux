//! The `agent` tool end to end, with a scripted model shared by the parent and
//! its subagent (one queue: the parent's call, the child's steps, the
//! parent's closing reply).

use super::*;
use evo_ai::providers::faux::{FauxProvider, FauxScript};
use evo_harness::agent_harness::AgentHarness;
use evo_harness::types::{AgentHarnessOptions, HarnessTool};

/// Every tool event the parent emits.
#[derive(Default)]
struct Collector(Mutex<Vec<AgentEvent>>);
impl AgentEmitter for Collector {
    fn emit(&self, event: AgentEvent) -> futures::future::BoxFuture<'static, ()> {
        self.try_emit(event);
        Box::pin(async {})
    }
    fn try_emit(&self, event: AgentEvent) {
        if matches!(
            event,
            AgentEvent::ToolExecutionStart { .. }
                | AgentEvent::ToolExecutionUpdate { .. }
                | AgentEvent::ToolExecutionEnd { .. }
        ) {
            self.0.lock().unwrap().push(event);
        }
    }
}

static NEXT_PARENT: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

/// A parent with the built-in tools and `agent`, working in `cwd`.
async fn parent(cwd: &std::path::Path, script: FauxScript, events: Arc<Collector>) -> AgentHarness {
    let provider = FauxProvider::new(script);
    let cell: HarnessCell = Arc::new(OnceLock::new());
    let mut tools = crate::session::builtin_tools_in(cwd);
    tools.push(HarnessTool::new(create_agent_tool(
        cell.clone(),
        cwd.to_path_buf(),
    )));
    let active_tool_names = tools
        .iter()
        .map(|tool| tool.tool.schema().name.clone())
        .collect();
    let session = Session::new(
        Arc::new(InMemorySessionStorage::new(
            // One session per test: agent limits are per session.
            SessionMetadata {
                id: format!(
                    "parent-{}",
                    NEXT_PARENT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
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

fn agent_end(events: &Collector) -> (AgentToolResult, bool) {
    events
        .0
        .lock()
        .unwrap()
        .iter()
        .find_map(|event| match event {
            AgentEvent::ToolExecutionEnd {
                tool_name,
                result,
                is_error,
                ..
            } if tool_name == "agent" => Some((result.clone(), *is_error)),
            _ => None,
        })
        .expect("the agent call ended")
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn a_subagent_works_and_reports_back() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("notes.md"), "the answer is 42\n").unwrap();
    let script = FauxScript::new()
        .with_tool_call(
            "agent",
            json!({"description":"Find the answer","prompt":"Read notes.md and report the answer.","agentType":"explore"}),
        )
        .with_tool_call("read", json!({"path":"notes.md"}))
        .with_text("The answer in notes.md is 42.")
        .with_text("The subagent says 42.");
    let events = Arc::new(Collector::default());
    let parent = parent(dir.path(), script, events.clone()).await;
    parent
        .lane("main")
        .prompt_text("What is the answer?", Vec::new())
        .await
        .unwrap();

    let (result, is_error) = agent_end(&events);
    assert!(!is_error, "{result:?}");
    // The parent sees only the report.
    let text: String = result
        .content
        .iter()
        .filter_map(|c| match c {
            TextContentOrImage::Text(t) => Some(t.text.clone()),
            _ => None,
        })
        .collect();
    assert_eq!(text, "The answer in notes.md is 42.");
    // The snapshot records what the child did.
    let child = &result.details["child"];
    assert_eq!(child["status"], "done");
    assert_eq!(child["agentType"], "explore");
    assert_eq!(child["description"], "Find the answer");
    assert_eq!(child["toolUses"], 1);
    assert_eq!(child["tools"][0]["name"], "read");
    assert_eq!(child["tools"][0]["args"]["path"], "notes.md");
    assert_eq!(child["tools"][0]["phase"], "done");
    assert!(child["turns"].as_u64().unwrap() >= 2);
    assert!(child["endedAt"].as_u64().unwrap() >= child["startedAt"].as_u64().unwrap());
    // The child's usage is the call's usage, so the parent's cost includes it.
    assert!(result.usage.is_some());
    // Live updates went out while it ran, the last one finished.
    let updates: Vec<Value> = events
        .0
        .lock()
        .unwrap()
        .iter()
        .filter_map(|event| match event {
            AgentEvent::ToolExecutionUpdate {
                tool_name,
                partial_result,
                ..
            } if tool_name == "agent" => Some(partial_result.details["child"].clone()),
            _ => None,
        })
        .collect();
    assert!(updates.len() >= 2, "{updates:?}");
    assert_eq!(updates[0]["status"], "running");
    assert!(
        updates.iter().any(|u| u["tools"][0]["phase"] == "running"),
        "{updates:?}"
    );
    assert_eq!(updates.last().unwrap()["status"], "done");
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn explore_agents_cannot_write() {
    let dir = tempfile::tempdir().unwrap();
    // The explore type has no `write`: the child's call is refused, it reports anyway.
    let script = FauxScript::new()
        .with_tool_call(
            "agent",
            json!({"description":"Try to write","prompt":"Create a.txt","agentType":"explore"}),
        )
        .with_tool_call("write", json!({"path":"a.txt","content":"x"}))
        .with_text("I could not write.")
        .with_text("ok");
    let events = Arc::new(Collector::default());
    let parent = parent(dir.path(), script, events.clone()).await;
    parent
        .lane("main")
        .prompt_text("go", Vec::new())
        .await
        .unwrap();
    let (result, is_error) = agent_end(&events);
    assert!(!is_error, "{result:?}");
    assert!(
        !dir.path().join("a.txt").exists(),
        "an explore agent must not write files"
    );
    assert_eq!(result.details["child"]["tools"][0]["phase"], "error");
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn read_only_agents_cannot_write_through_the_shell_or_their_tools() {
    let dir = tempfile::tempdir().unwrap();
    // A read-only type that keeps every tool, `write` included.
    let agents = dir.path().join(".evo/agents");
    std::fs::create_dir_all(&agents).unwrap();
    std::fs::write(
        agents.join("auditor.md"),
        "---\ndescription: Audits.\naccess: read-only\n---\nAudit.\n",
    )
    .unwrap();
    let script = FauxScript::new()
        .with_tool_call(
            "agent",
            json!({"description":"Shell","prompt":"Create a.txt","agentType":"explore"}),
        )
        .with_tool_call("bash", json!({"command":"echo x > a.txt"}))
        .with_text("Refused.")
        .with_tool_call(
            "agent",
            json!({"description":"Tools","prompt":"Create b.txt","agentType":"auditor"}),
        )
        .with_tool_call("write", json!({"path":"b.txt","content":"x"}))
        .with_text("Refused too.")
        .with_text("ok");
    let events = Arc::new(Collector::default());
    let parent = parent(dir.path(), script, events.clone()).await;
    parent
        .lane("main")
        .prompt_text("go", Vec::new())
        .await
        .unwrap();
    assert!(!dir.path().join("a.txt").exists() && !dir.path().join("b.txt").exists());
    let ends: Vec<AgentToolResult> = events
        .0
        .lock()
        .unwrap()
        .iter()
        .filter_map(|event| match event {
            AgentEvent::ToolExecutionEnd {
                tool_name, result, ..
            } if tool_name == "agent" => Some(result.clone()),
            _ => None,
        })
        .collect();
    assert_eq!(ends.len(), 2);
    for end in ends {
        let row = &end.details["child"]["tools"][0];
        assert_eq!(row["phase"], "error", "{end:?}");
    }
}

#[test]
fn long_reports_are_cut_with_a_way_to_the_rest() {
    let short = "all good".to_string();
    assert_eq!(capped(short.clone(), "a1"), short);
    let long = "é".repeat(MAX_REPORT);
    let cut = capped(long, "a1");
    assert!(cut.len() < MAX_REPORT + 200);
    assert!(
        cut.contains("Ask agent a1 with message_agent"),
        "{}",
        &cut[cut.len() - 120..]
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn unknown_types_and_models_are_refused() {
    let dir = tempfile::tempdir().unwrap();
    let script = FauxScript::new()
        .with_tool_call(
            "agent",
            json!({"description":"x","prompt":"p","agentType":"wizard"}),
        )
        .with_tool_call(
            "agent",
            json!({"description":"x","prompt":"p","model":"no-such-model"}),
        )
        .with_text("done");
    let events = Arc::new(Collector::default());
    let parent = parent(dir.path(), script, events.clone()).await;
    parent
        .lane("main")
        .prompt_text("go", Vec::new())
        .await
        .unwrap();
    let ends: Vec<String> = events
        .0
        .lock()
        .unwrap()
        .iter()
        .filter_map(|event| match event {
            AgentEvent::ToolExecutionEnd {
                tool_name,
                result,
                is_error: true,
                ..
            } if tool_name == "agent" => Some(format!("{:?}", result.content)),
            _ => None,
        })
        .collect();
    assert_eq!(ends.len(), 2, "{ends:?}");
    assert!(ends[0].contains("unknown agent type `wizard`"), "{ends:?}");
    assert!(
        ends[1].contains("model `no-such-model` is not available"),
        "{ends:?}"
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn an_agent_file_added_later_is_usable_at_once() {
    let dir = tempfile::tempdir().unwrap();
    let script = FauxScript::new()
        .with_tool_call(
            "agent",
            json!({"description":"Review","prompt":"Review it","agentType":"reviewer"}),
        )
        .with_text("Looks fine.")
        .with_text("ok");
    let events = Arc::new(Collector::default());
    let parent = parent(dir.path(), script, events.clone()).await;
    // Written after the tool was built.
    let agents = dir.path().join(".evo/agents");
    std::fs::create_dir_all(&agents).unwrap();
    std::fs::write(
        agents.join("reviewer.md"),
        "---\ndescription: Reviews changes.\ntools: [read]\n---\nYou review code.\n",
    )
    .unwrap();
    parent
        .lane("main")
        .prompt_text("go", Vec::new())
        .await
        .unwrap();
    let (result, is_error) = agent_end(&events);
    assert!(!is_error, "{result:?}");
    assert_eq!(result.details["child"]["agentType"], "reviewer");
}

mod background;

mod mesh;

mod peers;

/// The JSON transcript of a background agent's call: it returned at once,
/// leaving the agent running.
fn started(id: &str, description: &str) -> Value {
    json!({ "role": "toolResult", "toolName": "agent", "details": { "child": {
        "agentId": id, "description": description, "background": true, "status": "running" } } })
}

fn note(text: String) -> Value {
    json!({ "role": "user", "content": [{ "type": "text", "text": text }] })
}

#[test]
fn background_agents_without_a_report_are_found() {
    let reported = note(format!(
        "{NOTE_TAG} id=\"a\" description=\"A\" status=\"done\">\nok\n</background-agent>"
    ));
    let foreground = json!({ "role": "toolResult", "toolName": "agent", "details": { "child": {
        "agentId": "f", "background": false, "status": "done" } } });
    let messages = vec![
        started("a", "A"),
        started("b", "B \"quoted\""),
        foreground,
        reported.clone(),
        json!({ "role": "user", "content": "plain prompt" }),
    ];
    assert_eq!(
        unreported_background_agents(&messages, ""),
        vec![("b".to_string(), "B \"quoted\"".to_string())]
    );
    // A finished agent continued in the background (`message_agent`) is open again.
    let mut continued = messages.clone();
    continued.push(started("a", "A"));
    assert_eq!(unreported_background_agents(&continued, "").len(), 2);
    // A report already queued for the next run is on its way.
    let queued = serde_json::to_string(&json!({ "text": lost_agent_note("b", "B") })).unwrap();
    assert!(unreported_background_agents(&messages, &queued).is_empty());
    // The note reads like a real report, quotes made safe for its attribute.
    let text = lost_agent_note("b", "B \"quoted\"");
    assert!(text.starts_with(&format!(
        "{NOTE_TAG} id=\"b\" description=\"B 'quoted'\" status=\"error\">"
    )));
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn lost_background_agents_are_reported_once_to_the_next_run() {
    let dir = tempfile::tempdir().unwrap();
    let events = Arc::new(Collector::default());
    let parent = parent(dir.path(), FauxScript::new().with_text("Noted."), events).await;
    let messages = vec![started("gone-1", "Long task")];
    assert_eq!(
        report_lost_background_agents(&parent, &messages).await,
        vec!["gone-1".to_string()]
    );
    // The queued report is durable: a second start does not queue it again.
    assert!(report_lost_background_agents(&parent, &messages)
        .await
        .is_empty());
    // The next run reads it before the prompt.
    parent
        .lane("main")
        .prompt_text("hello", Vec::new())
        .await
        .unwrap();
    let history = serde_json::to_string(
        &parent
            .session()
            .storage()
            .find_entries(&Default::default())
            .await
            .unwrap(),
    )
    .unwrap();
    assert!(
        history.contains("id=\\\"gone-1\\\""),
        "the lost agent's report is in the history"
    );
    assert!(history.contains("status=\\\"error\\\""));
}
