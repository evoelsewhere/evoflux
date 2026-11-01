//! Turn mechanics that only show end to end.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::disallowed_methods,
    clippy::type_complexity
)]

use std::time::Duration;

use super::*;
use crate::testkit::{sse_text, sse_tool, Env};

#[test]
fn durations_are_milliseconds_with_microsecond_precision() {
    let started = Instant::now()
        .checked_sub(Duration::from_millis(2000))
        .unwrap();
    let d = ms_since(started);
    assert!((2000.0..20000.0).contains(&d), "{d}");
}

#[test]
fn agent_status_events_carry_agent_status_and_metadata() {
    assert_eq!(
        status("evoflux", "working", json!({"phase": "x"})),
        json!({"type": "agent_status", "agent": "evoflux", "status": "working", "metadata": {"phase": "x"}})
    );
}

fn frames_named(frames: &[crate::stream_store::Frame], event: &str) -> Vec<Value> {
    frames
        .iter()
        .filter(|f| f.event == event)
        .map(|f| serde_json::from_str(&f.data).unwrap())
        .collect()
}

#[tokio::test]
async fn empty_replies_after_a_tool_end_the_turn_with_an_error() {
    let env = Env::new().await;
    env.script(sse_tool("c1", "date", "{}"));
    for _ in 0..3 {
        env.script(sse_text(""));
    }
    let (_, frames) = env.chat_frames("message=go").await;
    let errors = frames_named(&frames, "error");
    assert_eq!(errors.len(), 1, "{errors:?}");
    assert_eq!(errors[0]["metadata"]["exception"], "AgentLoopError");
    let streamed = env
        .seen
        .lock()
        .unwrap()
        .iter()
        .filter(|b| b["stream"] == json!(true))
        .count();
    assert_eq!(streamed, 4);
}

#[tokio::test]
async fn one_empty_reply_after_a_tool_is_retried() {
    let env = Env::new().await;
    env.script(sse_tool("c1", "date", "{}"));
    env.script(sse_text(""));
    env.script(sse_text("fine"));
    let (_, frames) = env.chat_frames("message=go").await;
    assert!(frames_named(&frames, "error").is_empty());
    assert_eq!(frames_named(&frames, "message")[0]["text"], "fine");
}

#[tokio::test]
async fn an_empty_first_reply_is_not_an_error() {
    let env = Env::new().await;
    env.script(sse_text(""));
    let (_, frames) = env.chat_frames("message=go").await;
    assert!(frames_named(&frames, "error").is_empty());
    let last = frames_named(&frames, "agent_status").pop().unwrap();
    assert_eq!(last["status"], "idle");
}

#[tokio::test]
async fn a_python_only_tool_ends_the_turn_and_an_unknown_one_does_not() {
    let env = Env::new().await;
    env.script(sse_tool("c1", "no_such_tool", "{}"));
    env.script(sse_text("after"));
    let (_, frames) = env.chat_frames("message=go").await;
    assert!(frames_named(&frames, "error").is_empty());
    let end = &frames_named(&frames, "tool_end")[0];
    assert_eq!(end["result"], "Error: Tool 'no_such_tool' not found.");

    let env = Env::new().await;
    env.script(sse_tool("c1", "write", "{}"));
    let (_, frames) = env.chat_frames("message=go").await;
    let errors = frames_named(&frames, "error");
    assert_eq!(errors[0]["metadata"]["exception"], "ToolNotFoundError");
    assert_eq!(
        errors[0]["message"],
        "Lead agent 'evoflux' failed: Tool 'write' not found."
    );
}

async fn finish_with(env: &Env, sql: &str, sid_hex: &str) -> Value {
    let sql = sql.to_owned();
    env.db
        .write_exclusive(move |tx| {
            tx.execute_batch(&sql)?;
            Ok(())
        })
        .await
        .unwrap();
    let sid = crate::store::dashed(sid_hex);
    env.state.store.init_turn(&sid, false);
    let (_, mut rx) = env.state.store.attach(&sid).unwrap();
    assert!(env.state.begin_turn(&sid));
    let turn = Turn {
        state: env.state.clone(),
        input: TurnInput {
            sid_hex: sid_hex.to_owned(),
            sid: sid.clone(),
            content: String::new(),
            lead: LeadAgent {
                name: "evoflux".into(),
                model: None,
                thinking_level: None,
                prompt: String::new(),
            },
            model: None,
            thinking_level: None,
            workspace: None,
            cancel: CancellationToken::new(),
        },
        started: Instant::now(),
        usage: Arc::new(Mutex::new(TurnUsage::default())),
        title_pending: None,
        settings: None,
        tools: Vec::new(),
    };
    turn.finish().await;
    let mut notification = Value::Null;
    let mut names = Vec::new();
    while let Ok(Some(frame)) = tokio::time::timeout(Duration::from_secs(2), rx.recv()).await {
        if frame.event == "desktop_notification" {
            notification = serde_json::from_str(&frame.data).unwrap();
        }
        names.push(frame.event);
    }
    assert_eq!(names, ["desktop_notification", "turn_changes", "done"]);
    assert!(env.state.active().is_empty());
    notification
}

const SESSION_INSERT: &str = "INSERT INTO chat_sessions (id, title, created_at, updated_at, mode, workspace, permission_mode) VALUES";

#[tokio::test]
async fn the_done_notification_names_the_session() {
    let env = Env::new().await;
    let work = "06ae6ab0636d720e8000b0d548016ce8";
    let n = finish_with(
        &env,
        &format!("{SESSION_INSERT} ('{work}', 'My title', '2026-11-01 00:00:00.000000', '2026-11-01 00:00:00.000000', 'work', '/x/proj', 'auto')"),
        work,
    )
    .await;
    assert_eq!(n["title"], "Session completed");
    assert_eq!(n["body"], "My title");
    assert_eq!(n["metadata"]["mode"], "work");
    assert_eq!(n["metadata"]["workspace"], "/x/proj");
    assert_eq!(n["metadata"]["title"], "My title");

    let coding = "06ae6ab0636d720e8000b0d548016ce9";
    let n = finish_with(
        &env,
        &format!("{SESSION_INSERT} ('{coding}', '   ', '2026-11-01 00:00:00.000000', '2026-11-01 00:00:00.000000', 'coding', '/x/proj', 'auto')"),
        coding,
    )
    .await;
    assert_eq!(n["title"], "Session completed - proj");
    assert_eq!(n["body"], "Session 06ae6ab0");

    let none = "06ae6ab0636d720e8000b0d548016cea";
    let n = finish_with(&env, "SELECT 1", none).await;
    assert_eq!(n["title"], "Session completed");
    assert_eq!(n["body"], "Session 06ae6ab0");
    assert_eq!(n["metadata"]["mode"], Value::Null);
}
