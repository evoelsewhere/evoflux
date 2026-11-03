//! Whole-request tests: a form goes in, the database, the SSE stream and
//! the provider request come out.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::disallowed_methods,
    clippy::type_complexity
)]

use std::time::Duration;

use serde_json::{json, Value};

use crate::stream_store::Frame;
use crate::testkit::{sse_text, sse_thinking_tool, sse_tool, sse_tool_calls, Env};

fn names(frames: &[Frame]) -> Vec<&str> {
    frames.iter().map(|f| f.event.as_str()).collect()
}

fn data(frames: &[Frame], event: &str) -> Vec<Value> {
    frames
        .iter()
        .filter(|f| f.event == event)
        .map(|f| serde_json::from_str(&f.data).unwrap())
        .collect()
}

fn hex(sid: &Value) -> String {
    sid.as_str().unwrap().replace('-', "")
}

async fn rows(env: &Env) -> Vec<(String, Option<String>, Value)> {
    env.query(|c| {
        let mut stmt =
            c.prepare("SELECT role, content, extra FROM session_messages ORDER BY created_at, id")?;
        let rows = stmt.query_map([], |r| {
            let extra: String = r.get(2)?;
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, Option<String>>(1)?,
                serde_json::from_str(&extra).unwrap(),
            ))
        })?;
        rows.collect::<Result<Vec<_>, _>>()
    })
    .await
}

async fn session_col(env: &Env, sid_hex: &str, column: &'static str) -> Option<String> {
    let id = sid_hex.to_owned();
    env.query(move |c| {
        c.query_row(
            &format!("SELECT {column} FROM chat_sessions WHERE id = ?1"),
            [id],
            |r| r.get(0),
        )
    })
    .await
}

#[tokio::test]
async fn a_text_turn_is_stored_streamed_and_titled() {
    let env = Env::with_delay(Duration::from_millis(300)).await;
    env.script(sse_text("Hello there"));
    let (body, frames) = env.chat_frames("message=say+hi").await;
    assert_eq!(body["status"], "accepted");
    let sid = body["session_id"].as_str().unwrap().to_owned();

    let events = names(&frames);
    assert_eq!(events.last(), Some(&"done"));
    for expected in ["message", "usage", "desktop_notification", "turn_changes"] {
        assert!(events.contains(&expected), "{expected} in {events:?}");
    }
    let statuses: Vec<String> = data(&frames, "agent_status")
        .iter()
        .map(|d| d["status"].as_str().unwrap().to_owned())
        .collect();
    assert_eq!(statuses.first().map(String::as_str), Some("working"));
    assert_eq!(statuses.last().map(String::as_str), Some("idle"));
    let usage = data(&frames, "usage");
    // The title request may add a third total before `done`.
    assert!(usage.len() >= 2, "{usage:?}");
    assert_eq!(usage[0]["metadata"].get("turn_total"), None);
    assert_eq!(usage[0]["total_tokens"], 5);
    assert_eq!(usage[1]["metadata"]["turn_total"], true);
    let message = &data(&frames, "message")[0];
    assert_eq!(message["text"], "Hello there");
    assert_eq!(message["agent"], "evoflux");
    let notification = &data(&frames, "desktop_notification")[0];
    assert_eq!(notification["session_id"], sid);
    assert_eq!(notification["title"], "Session completed");

    let stored = rows(&env).await;
    assert_eq!(stored.len(), 2);
    assert_eq!(stored[0].0, "user");
    assert_eq!(stored[0].1.as_deref(), Some("say hi"));
    assert_eq!(stored[0].2["model"], "router9:mock-model");
    assert_eq!(stored[1].0, "assistant");
    assert_eq!(stored[1].1.as_deref(), Some("Hello there"));
    let duration = stored[1].2["duration_ms"].as_f64().unwrap();
    assert!((250.0..5000.0).contains(&duration), "{duration}");
    assert_eq!(stored[1].2["usage"], json!({"input": 3, "output": 2}));

    assert_eq!(
        env.wait_title(&hex(&body["session_id"]), "say hi").await,
        "Mock title"
    );
    let request = env.seen.lock().unwrap()[0].clone();
    assert_eq!(request["stream"], true);
    assert_eq!(
        request["messages"],
        json!([
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "say hi"}
        ])
    );
    // The late title usage lands on the reply as the turn total.
    let late = rows(&env).await;
    assert!(late[1].2["turn_usage"]["calls"].as_i64().unwrap() >= 1);
}

#[tokio::test]
async fn a_second_turn_sends_history_and_a_tool_turn_runs_the_tool() {
    let env = Env::new().await;
    env.script(sse_text("first"));
    let (body, _) = env.chat_frames("message=one").await;
    let sid = body["session_id"].as_str().unwrap().to_owned();
    let sid_hex = hex(&body["session_id"]);
    env.script(sse_tool("c1", "date", "{}"));
    env.script(sse_text("done now"));
    let form =
        format!("message=two&session_id={sid}&model=router9%3Amock-model&thinking_level=high");
    let (_, frames) = env.chat_frames(&form).await;
    let events = names(&frames);
    for expected in ["tool_call", "tool_start", "tool_end", "message"] {
        assert!(events.contains(&expected), "{expected} in {events:?}");
    }
    let end = &data(&frames, "tool_end")[0];
    assert_eq!(end["name"], "date");
    assert!(end["result"].as_str().is_some_and(|r| !r.is_empty()));
    assert!(end["metadata"]["duration_ms"].as_f64().unwrap() >= 0.0);

    let roles: Vec<String> = rows(&env).await.into_iter().map(|r| r.0).collect();
    assert_eq!(
        roles,
        [
            "user",
            "assistant",
            "user",
            "assistant",
            "tool",
            "assistant"
        ]
    );
    let seen = env.seen.lock().unwrap().clone();
    let streamed: Vec<&Value> = seen.iter().filter(|b| b["stream"] == json!(true)).collect();
    assert_eq!(streamed.len(), 3);
    let second = streamed[1]["messages"].as_array().unwrap();
    assert_eq!(second[1]["content"], "one");
    assert_eq!(second[2]["content"], "first");
    assert_eq!(second[3]["content"], "two");
    let third = streamed[2]["messages"].as_array().unwrap();
    assert_eq!(third.last().unwrap()["role"], "tool");
    assert_eq!(third.last().unwrap()["tool_call_id"], "c1");

    // The form named model and thinking level, so the session keeps them.
    assert_eq!(
        session_col(&env, &sid_hex, "model").await.as_deref(),
        Some("router9:mock-model")
    );
    assert_eq!(
        session_col(&env, &sid_hex, "thinking_level")
            .await
            .as_deref(),
        Some("high")
    );
    // A blank thinking level in the form clears it again.
    env.script(sse_text("third"));
    env.chat_frames(&format!(
        "message=three&session_id={sid}&thinking_level=%20&model="
    ))
    .await;
    assert_eq!(session_col(&env, &sid_hex, "thinking_level").await, None);
    assert_eq!(session_col(&env, &sid_hex, "model").await, None);
    assert_eq!(
        session_col(&env, &sid_hex, "mode").await.as_deref(),
        Some("work")
    );
}

#[tokio::test]
async fn history_returns_the_stored_session() {
    let env = Env::new().await;
    env.script(sse_text("reply"));
    let (body, _) = env
        .chat_frames("message=question&permission_mode=ask")
        .await;
    let sid = body["session_id"].as_str().unwrap().to_owned();
    env.wait_title(&hex(&body["session_id"]), "question").await;
    let (status, history) = env.get(&format!("/api/team/{sid}/history")).await;
    assert_eq!(status, 200);
    let lead = &history["lead"];
    assert_eq!(lead["id"], sid);
    assert_eq!(lead["title"], "Mock title");
    assert_eq!(lead["agent_name"], "evoflux");
    assert_eq!(lead["mode"], "work");
    assert_eq!(lead["permission_mode"], "ask");
    assert_eq!(lead["running"], false);
    assert_eq!(lead["tags"], json!([]));
    assert_eq!(lead["messages"].as_array().unwrap().len(), 2);
    assert_eq!(lead["messages"][1]["content"], "reply");
    assert_eq!(history["members"], json!([]));
    assert_eq!(history["has_more"], false);
    assert_eq!(history["goal"], Value::Null);
    let (status, body) = env
        .get("/api/team/06ae6ab0-636d-720e-8000-b0d548016ce8/history")
        .await;
    assert_eq!(
        (status, body["detail"].as_str()),
        (404, Some("Lead session not found."))
    );
}

#[tokio::test]
async fn a_running_turn_refuses_a_second_one() {
    let env = Env::with_delay(Duration::from_millis(400)).await;
    env.script(sse_text("slow"));
    let (status, body) = env.post("message=a").await;
    assert_eq!(status, 202);
    let sid = body["session_id"].as_str().unwrap().to_owned();
    let (status, body) = env.post(&format!("message=b&session_id={sid}")).await;
    assert_eq!(status, 409);
    assert!(body["detail"]
        .as_str()
        .unwrap()
        .starts_with("A turn is already running"));
    let (status, body) = env.post(&format!("interrupt=true&session_id={sid}")).await;
    assert_eq!(
        (status, body["status"].as_str()),
        (200, Some("interrupted"))
    );
    env.idle().await;
}

#[tokio::test]
async fn blank_optional_ids_are_ignored() {
    let env = Env::new().await;
    let (status, body) = env
        .post("message=x&session_id=&folder_id=&project_id=")
        .await;
    assert_eq!(
        (status, body["status"].as_str()),
        (202, Some("accepted")),
        "{body}"
    );
    env.idle().await;
}

#[tokio::test]
async fn ids_and_folders_are_checked() {
    let env = Env::new().await;
    let post = |form: &'static str| env.post(form);
    let (status, body) = post("message=x&session_id=nope").await;
    assert_eq!(
        (status, body["detail"].as_str()),
        (422, Some("Invalid session id."))
    );
    let (status, body) = post("message=x&folder_id=nope").await;
    assert_eq!(
        (status, body["detail"].as_str()),
        (422, Some("Invalid folder_id."))
    );
    let (status, body) = post("message=x&project_id=nope").await;
    assert_eq!(
        (status, body["detail"].as_str()),
        (422, Some("Invalid project_id."))
    );
    let missing = "06ae6ab0636d720e8000b0d548016ce8";
    let (status, body) = env.post(&format!("message=x&folder_id={missing}")).await;
    assert_eq!(
        (status, body["detail"].as_str()),
        (404, Some("Folder not found."))
    );

    env.db
        .write_exclusive(|tx| {
            tx.execute_batch(
                "INSERT INTO session_folders (id, mode) VALUES ('11111111111111111111111111111111', 'work'), \
                 ('22222222222222222222222222222222', 'coding'), ('33333333333333333333333333333333', 'forge')",
            )?;
            Ok(())
        })
        .await
        .unwrap();
    let (status, body) = env
        .post("message=x&folder_id=22222222222222222222222222222222")
        .await;
    assert_eq!(
        (status, body["detail"].as_str()),
        (
            422,
            Some("Folder belongs to a different mode than the session.")
        )
    );
    for folder in [
        "11111111111111111111111111111111",
        "33333333333333333333333333333333",
    ] {
        let (status, body) = env.post(&format!("message=x&folder_id={folder}")).await;
        assert_eq!(status, 202, "{body}");
        assert_eq!(
            session_col(&env, &hex(&body["session_id"]), "folder_id")
                .await
                .as_deref(),
            Some(folder)
        );
        env.idle().await;
    }
}

#[tokio::test]
async fn permission_modes_are_validated_and_stored() {
    let env = Env::new().await;
    let (status, body) = env.post("message=x&permission_mode=zzz").await;
    assert_eq!(
        (status, body["detail"].as_str()),
        (422, Some("Unknown permission_mode 'zzz'."))
    );
    for mode in ["ask", "auto", "bypass"] {
        let (status, body) = env.post(&format!("message=x&permission_mode={mode}")).await;
        assert_eq!(status, 202, "{mode}: {body}");
        env.idle().await;
        assert_eq!(
            session_col(&env, &hex(&body["session_id"]), "permission_mode")
                .await
                .as_deref(),
            Some(mode)
        );
    }
    let (_, body) = env.post("message=y").await;
    env.idle().await;
    assert_eq!(
        session_col(&env, &hex(&body["session_id"]), "permission_mode")
            .await
            .as_deref(),
        Some("auto")
    );
}

#[tokio::test]
async fn unsupported_requests_answer_with_the_reason() {
    let env = Env::new().await;
    let detail = |r: (u16, Value)| (r.0, r.1["detail"].as_str().unwrap().to_owned());
    assert_eq!(
        detail(env.post("message=%2Floop+every+5m").await),
        (
            410,
            "/loop has been removed. Use /goal <objective> instead.".to_owned()
        )
    );
    assert_eq!(
        detail(env.post("message=%2Fgoal+ship").await),
        (
            422,
            "/goal is not available in the Rust server yet.".to_owned()
        )
    );
    assert_eq!(
        detail(env.post("message=x&mode=coding&workspace=%2Ftmp").await),
        (
            422,
            "Coding sessions are not available in the Rust server yet.".to_owned()
        )
    );
    assert_eq!(
        detail(env.post("message=ls&shell=true").await),
        (
            422,
            "Shell commands are not available in the Rust server yet.".to_owned()
        )
    );
    assert_eq!(
        detail(env.post("message=%21&shell=true").await),
        (422, "Shell command is required.".to_owned())
    );
    assert_eq!(
        detail(
            env.post_multipart(&[("message", "ls"), ("shell", "true")], true)
                .await
        ),
        (
            422,
            "Shell commands cannot include file uploads.".to_owned()
        )
    );
    assert_eq!(
        detail(env.post_multipart(&[("message", "hi")], true).await),
        (
            422,
            "File uploads are not available in the Rust server yet.".to_owned()
        )
    );
    let (status, body) = env.post_multipart(&[("message", "hi")], false).await;
    assert_eq!((status, body["status"].as_str()), (202, Some("accepted")));
    env.idle().await;
}

#[tokio::test]
async fn an_undo_boundary_or_unknown_mode_blocks_the_session() {
    let env = Env::new().await;
    let (_, body) = env.post("message=x").await;
    env.idle().await;
    let sid = body["session_id"].as_str().unwrap().to_owned();
    let id = hex(&body["session_id"]);
    let set = |sql: String| {
        let db = env.db.clone();
        async move {
            db.write_exclusive(move |tx| {
                tx.execute_batch(&sql)?;
                Ok(())
            })
            .await
            .unwrap();
        }
    };
    set(format!(
        "UPDATE chat_sessions SET revert = '{{\"a\": 1}}' WHERE id = '{id}'"
    ))
    .await;
    let (status, body) = env.post(&format!("message=y&session_id={sid}")).await;
    assert_eq!(status, 409);
    assert!(body["detail"].as_str().unwrap().contains("undo boundary"));
    set(format!(
        "UPDATE chat_sessions SET revert = 'null', mode = 'weird' WHERE id = '{id}'"
    ))
    .await;
    let (status, body) = env.post(&format!("message=y&session_id={sid}")).await;
    assert_eq!(
        (status, body["detail"].as_str()),
        (409, Some("Session has unsupported persisted mode: weird"))
    );
    set(format!(
        "UPDATE chat_sessions SET mode = 'coding' WHERE id = '{id}'"
    ))
    .await;
    let (status, _) = env.post(&format!("message=y&session_id={sid}")).await;
    assert_eq!(status, 422);
}

#[tokio::test]
async fn every_row_of_a_tool_turn_is_stored_whole() {
    let env = Env::new().await;
    env.script(sse_thinking_tool("pondering", "c1", "date", "{}"));
    env.script(sse_text("final"));
    let (body, _) = env.chat_frames("message=go").await;
    let sid = hex(&body["session_id"]);
    #[allow(clippy::type_complexity)]
    let stored: Vec<(String, String, String, Option<String>, Option<String>, Option<String>, Value, Option<String>)> = env
        .query(|c| {
            let mut stmt = c.prepare(
                "SELECT id, session_id, role, content, reasoning_content, tool_call_id, extra, name                  FROM session_messages ORDER BY created_at, id",
            )?;
            let rows = stmt.query_map([], |r| {
                let extra: String = r.get(6)?;
                Ok((
                    r.get(0)?,
                    r.get(1)?,
                    r.get(2)?,
                    r.get(3)?,
                    r.get(4)?,
                    r.get(5)?,
                    serde_json::from_str(&extra).unwrap(),
                    r.get(7)?,
                ))
            })?;
            rows.collect::<Result<Vec<_>, _>>()
        })
        .await;
    assert_eq!(stored.len(), 4);
    let ids: std::collections::HashSet<&str> = stored.iter().map(|r| r.0.as_str()).collect();
    assert_eq!(ids.len(), 4);
    for row in &stored {
        assert_eq!(row.0.len(), 32);
        assert_eq!(row.1, sid);
    }
    let (_, _, role, content, reasoning, _, extra, name) = &stored[1];
    assert_eq!(*name, None);
    assert_eq!(role, "assistant");
    assert_eq!(*content, None);
    assert_eq!(reasoning.as_deref(), Some("pondering"));
    assert_eq!(extra["model"], "router9:mock-model");
    assert_eq!(extra["usage"], json!({"input": 4, "output": 1}));
    assert!(extra["duration_ms"].as_f64().unwrap() >= 0.0);
    let (_, _, role, content, reasoning, call_id, extra, name) = &stored[2];
    assert_eq!(name.as_deref(), Some("date"));
    assert_eq!(role, "tool");
    assert!(content.as_deref().is_some_and(|c| !c.is_empty()));
    assert_eq!(*reasoning, None);
    assert_eq!(call_id.as_deref(), Some("c1"));
    assert!(extra["duration_ms"].as_f64().unwrap() >= 0.0);
    assert_eq!(stored[3].3.as_deref(), Some("final"));
    assert_eq!(stored[3].4, None);
}

#[tokio::test]
async fn the_model_comes_from_the_latest_user_message() {
    let env = Env::new().await;
    let (body, _) = env.chat_frames("message=one").await;
    let sid = body["session_id"].as_str().unwrap().to_owned();
    let hex_id = hex(&body["session_id"]);
    // A newer assistant row naming another model must not win.
    env.db
        .write_exclusive(move |tx| {
            tx.execute(
                "UPDATE session_messages SET extra = '{\"model\": \"router9:other\"}' WHERE role = 'assistant' AND session_id = ?1",
                [hex_id.clone()],
            )?;
            Ok(())
        })
        .await
        .unwrap();
    env.chat_frames(&format!("message=two&session_id={sid}"))
        .await;
    let seen = env.seen.lock().unwrap().clone();
    let last = seen
        .iter()
        .rev()
        .find(|b| b["stream"] == json!(true))
        .unwrap();
    assert_eq!(last["model"], "mock-model");
}

#[tokio::test]
async fn a_blank_session_model_is_skipped_for_the_one_the_history_recorded() {
    let env = Env::new().await;
    let (body, _) = env.chat_frames("message=one").await;
    let sid = body["session_id"].as_str().unwrap().to_owned();
    let hex_id = hex(&body["session_id"]);
    env.db
        .write_exclusive(move |tx| {
            tx.execute(
                "UPDATE chat_sessions SET model = '' WHERE id = ?1",
                [hex_id.clone()],
            )?;
            Ok(())
        })
        .await
        .unwrap();
    // The new user message records the blank model, so the turn has to
    // reach back to the model of the first one.
    let (_, frames) = env
        .chat_frames(&format!("message=two&session_id={sid}"))
        .await;
    assert!(
        data(&frames, "error").is_empty(),
        "{:?}",
        data(&frames, "error")
    );
    let seen = env.seen.lock().unwrap().clone();
    let last = seen
        .iter()
        .rev()
        .find(|b| b["stream"] == json!(true))
        .unwrap();
    assert_eq!(last["model"], "mock-model");
}

#[tokio::test]
async fn a_repeated_tool_call_is_announced_once_and_run_twice() {
    let env = Env::new().await;
    env.script(sse_tool_calls(&[
        ("c1", "date", "{}"),
        ("c1", "date", "{}"),
    ]));
    env.script(sse_text("done"));
    let (_, frames) = env.chat_frames("message=go").await;
    assert_eq!(data(&frames, "tool_call").len(), 1);
    assert_eq!(data(&frames, "tool_start").len(), 2);
    assert_eq!(data(&frames, "tool_end").len(), 2);
}

#[tokio::test]
async fn saved_sandbox_patterns_are_reloaded_each_turn() {
    let env = Env::new().await;
    env.script(sse_text("ready"));
    let (body, _) = env.chat_frames("message=setup").await;
    let sid = body["session_id"].as_str().unwrap();
    let ws = env.state.settings.workspace_dir.join(sid);
    std::fs::create_dir_all(&ws).unwrap();
    std::fs::write(ws.join("secret.txt"), "hidden payload").unwrap();
    let config = env.state.settings.config_dir.join("sandbox.yaml");
    std::fs::write(&config, "denied_patterns: ['**/secret*']\n").unwrap();
    let form = format!("message=inspect&session_id={sid}");
    env.script(sse_tool("c1", "read", r#"{"path":"secret.txt"}"#));
    env.script(sse_text("done"));
    let (body, frames) = env.chat_frames(&form).await;
    let ends = data(&frames, "tool_end");
    let result = ends[0]["result"].as_str().unwrap();
    assert!(
        result.ends_with("is inside a denied sandbox root: **/secret*"),
        "{result}"
    );
    assert!(!result.contains("hidden payload"));
    std::fs::write(&config, "denied_patterns: []\n").unwrap();
    env.script(sse_tool("c2", "read", r#"{"path":"secret.txt"}"#));
    env.script(sse_text("done"));
    let (_, frames) = env
        .chat_frames(&format!(
            "message=again&session_id={}",
            body["session_id"].as_str().unwrap()
        ))
        .await;
    assert!(data(&frames, "tool_end")[0]["result"]
        .as_str()
        .unwrap()
        .contains("hidden payload"));
}
