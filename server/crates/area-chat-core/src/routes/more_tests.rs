//! Request parsing, response shaping and the stream route.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::disallowed_methods,
    clippy::type_complexity
)]

use std::time::Duration;

use super::*;
use crate::testkit::{sse_text, Env};

#[test]
fn find_locates_the_needle_anywhere_in_the_haystack() {
    assert_eq!(find(b"abc", b"abc", 0), Some(0));
    assert_eq!(find(b"abc", b"c", 0), Some(2));
    assert_eq!(find(b"abcabc", b"bc", 2), Some(4));
    assert_eq!(find(b"abc", b"b", 2), None);
    assert_eq!(find(b"ab", b"abc", 0), None);
    assert_eq!(find(b"abc", b"", 0), None);
    assert_eq!(find(b"abc", b"x", 0), None);
    assert_eq!(find(b"xxab", b"ab", 0), Some(2));
}

#[test]
fn multipart_parsing_stops_at_the_closing_delimiter() {
    let mut headers = HeaderMap::new();
    headers.insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("multipart/form-data; boundary=B"),
    );
    let body = "--B\r\nContent-Disposition: form-data; name=\"a\"\r\n\r\n1\r\n\
                --B\r\nContent-Disposition: form-data; name=\"b\"\r\n\r\n2\r\n\
                --B--\r\nContent-Disposition: form-data; name=\"late\"\r\n\r\nx\r\n--B--\r\n";
    let form = parse_form(&headers, body.as_bytes());
    assert_eq!(form.get("a"), Some("1"));
    assert_eq!(form.get("b"), Some("2"));
    assert_eq!(form.get("late"), None);
    assert_eq!(form.fields.len(), 2);
}

#[test]
fn slash_commands_may_carry_a_dashed_sub_command() {
    assert_eq!(slash_command("/goal:a-b_c"), Some("goal"));
    assert_eq!(slash_command("/goal:a_b run"), Some("goal"));
    assert_eq!(slash_command("/goal:ab!"), None);
    assert_eq!(slash_command("/goal:a-b!"), None);
    assert_eq!(slash_command("/goal:-x"), Some("goal"));
    assert_eq!(slash_command("/goal:_"), Some("goal"));
    assert_eq!(slash_command("/a_b-c:d"), Some("a_b-c"));
}

#[test]
fn a_tilde_expands_only_as_a_whole_path_segment() {
    let dir = tempfile::tempdir().unwrap();
    let home = dir.path().join("home");
    let config = dir.path().join("config");
    let resolve = |p: &str| resolve_work_workspace(p, &home, &config);
    assert!(resolve("~foo").is_err());
    assert!(resolve("~/w").is_ok());
    assert!(resolve("~\\w").is_ok());
}

#[test]
fn frames_are_written_as_sse() {
    let frame = Frame {
        event: "message".into(),
        data: "{\"a\": 1}".into(),
    };
    assert_eq!(
        sse_frame(&frame),
        Bytes::from_static(b"event: message\r\ndata: {\"a\": 1}\r\n\r\n")
    );
}

#[test]
fn a_session_row_becomes_the_api_object() {
    let row = SessionRow {
        id: "06ae6ab0636d720e8000b0d548016ce8".into(),
        agent_name: Some("evoflux".into()),
        title: Some("T".into()),
        scheduled_task_name: Some("task".into()),
        created_at: "2026-11-01 02:59:20.000000".into(),
        updated_at: "2026-11-01 03:00:00.500000".into(),
        mode: "forge".into(),
        workspace: Some("/w".into()),
        revert: Some(json!({"r": 1})),
        model: Some("p:m".into()),
        thinking_level: Some("low".into()),
        permission_mode: "ask".into(),
        project_id: Some("06ae6ab0833f7bd68000744dcbeedc81".into()),
        tags: Some(json!(["x"])),
        folder_id: Some("06ae6ab0833f7bd68000744dcbeedc82".into()),
        source: Some("import".into()),
        imported_at: Some("2026-11-01 01:00:00.000000".into()),
    };
    assert_eq!(
        Value::Object(session_json(&row, true)),
        json!({
            "id": "06ae6ab0-636d-720e-8000-b0d548016ce8",
            "title": "T",
            "agent_name": "evoflux",
            "scheduled_task_name": "task",
            "mode": "work",
            "workspace": "/w",
            "project_id": "06ae6ab0-833f-7bd6-8000-744dcbeedc81",
            "folder_id": "06ae6ab0-833f-7bd6-8000-744dcbeedc82",
            "permission_mode": "ask",
            "model": "p:m",
            "thinking_level": "low",
            "revert": {"r": 1},
            "tags": ["x"],
            "running": true,
            "source": "import",
            "imported_at": "2026-11-01T01:00:00Z",
            "created_at": "2026-11-01T02:59:20Z",
            "updated_at": "2026-11-01T03:00:00.500000Z",
        })
    );
    let bare = SessionRow {
        id: row.id.clone(),
        mode: "coding".into(),
        permission_mode: "auto".into(),
        created_at: row.created_at.clone(),
        updated_at: row.updated_at.clone(),
        ..SessionRow::default()
    };
    let out = session_json(&bare, false);
    assert_eq!(out["mode"], "coding");
    assert_eq!(out["tags"], json!([]));
    assert_eq!(out["running"], false);
    assert!(!out.contains_key("title") && !out.contains_key("revert"));
}

#[tokio::test]
async fn the_stream_route_carries_the_turn_as_sse() {
    let env = Env::with_delay(Duration::from_millis(300)).await;
    env.script(sse_text("streamed"));
    let (status, body) = env.post("message=hi").await;
    assert_eq!(status, 202);
    let sid = body["session_id"].as_str().unwrap().to_owned();
    let (status, stream) = env.get(&format!("/api/team/{sid}/stream")).await;
    assert_eq!(status, 200);
    let text = stream.as_str().unwrap();
    assert!(text.starts_with("event: agent_status\r\ndata: {"), "{text}");
    assert!(text.contains("event: message\r\ndata: {"), "{text}");
    assert!(text.ends_with("event: done\r\ndata: {\"type\": \"done\", \"metadata\": {}}\r\n\r\n"));
    env.idle().await;
}

#[test]
fn database_errors_map_to_busy_or_internal() {
    use evoflux_core::db::DbError;
    let busy = db_error(DbError::Busy);
    assert_eq!(busy.status, StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(busy.detail, json!("database_busy"));
    let other = db_error(DbError::Wal2);
    assert_eq!(other.status, StatusCode::INTERNAL_SERVER_ERROR);
    assert_eq!(other.detail, json!("Internal Server Error"));
}
