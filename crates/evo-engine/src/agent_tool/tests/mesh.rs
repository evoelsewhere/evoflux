//! A subagent as a node of the session mesh (`crate::mesh`).

use super::*;
use crate::mesh::{self, Address, Level, MeshEvent, NodeState, RunStatus};
use tokio::sync::broadcast::error::TryRecvError;

/// Every mesh event about nodes under `prefix`, in order.
fn events_under(feed: &mut tokio::sync::broadcast::Receiver<(Level, mesh::Envelope)>, prefix: &str) -> Vec<MeshEvent> {
    let mut out = Vec::new();
    loop {
        match feed.try_recv() {
            Ok((_, envelope)) if envelope.from.starts_with(prefix) => {
                out.push(envelope.as_event().expect("an event envelope"))
            }
            Ok(_) | Err(TryRecvError::Lagged(_)) => continue,
            Err(_) => break,
        }
    }
    out
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn a_subagent_is_a_mesh_node_with_live_summary_events() {
    let mut feed = mesh::router().feed();
    let subscriber = mesh::router().subscriber();
    mesh::router().subscribe(&subscriber, Level::Summary, None);

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
    let collector = Arc::new(Collector::default());
    let parent = parent(dir.path(), script, collector.clone()).await;
    parent.lane("main").prompt_text("What is the answer?", Vec::new()).await.unwrap();

    let session = Address::session(&parent.session().storage().metadata().id);
    let events = events_under(&mut feed, &format!("{session}/a_"));
    let (result, _) = agent_end(&collector);
    let call_id = collector
        .0
        .lock()
        .unwrap()
        .iter()
        .find_map(|event| match event {
            AgentEvent::ToolExecutionStart { tool_name, tool_call_id, .. } if tool_name == "agent" => {
                Some(tool_call_id.clone())
            }
            _ => None,
        })
        .unwrap();

    // It appears running, under its parent session, tied to the tool call.
    let MeshEvent::NodeState { node, prev: None } = &events[0] else { panic!("{events:?}") };
    assert_eq!(node.state, NodeState::Running);
    assert_eq!(node.parent.as_ref(), Some(&session));
    assert_eq!(node.title, "Find the answer");
    assert_eq!(node.meta["agentType"], "explore");
    assert_eq!(node.meta["callId"], call_id.as_str());
    assert_eq!(node.id.as_str(), format!("{session}/a_{}", result.details["child"]["agentId"].as_str().unwrap()));
    let address = node.id.clone();

    // Its tool call shows up live, running then done.
    let phases: Vec<(String, String)> = events
        .iter()
        .filter_map(|event| match event {
            MeshEvent::NodeActivity { tool: Some(row), .. } => Some((row.name.clone(), row.phase.clone())),
            _ => None,
        })
        .collect();
    assert_eq!(phases, [("read".to_string(), "running".to_string()), ("read".into(), "done".into())]);
    assert!(events.iter().any(|e| matches!(e, MeshEvent::NodeUsage { node, .. } if *node == address)));

    // It ends with its report, then settles; the report precedes the state.
    let report = events.iter().position(|e| matches!(e, MeshEvent::NodeReport { .. })).expect("a report");
    let MeshEvent::NodeReport { status, text, .. } = &events[report] else { unreachable!() };
    assert_eq!((*status, text.as_str()), (RunStatus::Done, "The answer in notes.md is 42."));
    let MeshEvent::NodeState { node, prev } = events.last().unwrap() else { panic!("{events:?}") };
    assert_eq!((node.state, node.status, *prev), (NodeState::Settled, Some(RunStatus::Done), Some(NodeState::Running)));
    assert!(report < events.len() - 1);

    // The router still knows it (it can be continued) and lists it under the session.
    let known = mesh::router().get(&address).expect("kept");
    assert_eq!(known.meta["resumable"], true);
    assert!(mesh::router()
        .list(mesh::ListScope::Children, Some(&session))
        .unwrap()
        .iter()
        .any(|n| n.id == address));
}
