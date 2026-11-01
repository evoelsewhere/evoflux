//! Database-backed tests of the session and message access.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::disallowed_methods,
    clippy::type_complexity
)]

use std::sync::Arc;

use chrono::Utc;
use evoflux_core::db::Db;

use super::*;
use crate::testkit::open_db;

fn ts(n: usize) -> String {
    format!("2026-11-01 00:{:02}:{:02}.000000", n / 60, n % 60)
}

fn id(n: usize) -> String {
    format!("{n:032x}")
}

const LEAD: usize = 0xaaa;
const MEMBER: usize = 0xbbb;

fn msg(n: usize, session: usize, role: &str) -> MessageRow {
    MessageRow {
        id: id(n),
        session_id: id(session),
        role: role.into(),
        content: Some(format!("m{n}")),
        created_at: ts(n),
        ..MessageRow::default()
    }
}

async fn fixture() -> (tempfile::TempDir, Arc<Db>) {
    let dir = tempfile::tempdir().unwrap();
    let db = open_db(dir.path()).await;
    (dir, db)
}

async fn exec(db: &Db, sql: String) {
    db.write_exclusive(move |tx| {
        tx.execute_batch(&sql)?;
        Ok(())
    })
    .await
    .unwrap();
}

async fn put_rows(db: &Db, rows: Vec<MessageRow>) {
    db.write_exclusive(move |tx| {
        for row in &rows {
            insert_message(tx, row)?;
        }
        Ok(())
    })
    .await
    .unwrap();
}

fn new_session(n: usize) -> NewSession {
    NewSession {
        id: id(n),
        title: "First".into(),
        agent_name: "evoflux".into(),
        workspace: Some("/w".into()),
        folder_id: Some(id(0xf)),
        permission_mode: "ask".into(),
        now: ts(5),
    }
}

async fn put_sessions(db: &Db) {
    exec(
        db,
        format!(
            "INSERT INTO chat_sessions (id, parent_session_id, agent_name, title, created_at, updated_at, mode, permission_mode) VALUES \
             ('{lead}', NULL, 'evoflux', 'lead', '{t0}', '{t0}', 'work', 'auto'), \
             ('{m2}', '{lead}', 'second', 't2', '{t2}', '{t2}', 'work', 'auto'), \
             ('{m1}', '{lead}', 'first', 't1', '{t1}', '{t1}', 'work', 'auto')",
            lead = id(LEAD),
            m1 = id(MEMBER),
            m2 = id(MEMBER + 1),
            t0 = ts(0),
            t1 = ts(1),
            t2 = ts(2),
        ),
    )
    .await;
}

#[test]
fn uuid7_fields_are_where_the_spec_puts_them() {
    let before = Utc::now().timestamp_millis();
    let ids: Vec<String> = (0..40).map(|_| uuid7_hex()).collect();
    let after = Utc::now().timestamp_millis();
    for hex in &ids {
        assert_eq!(hex.len(), 32);
        let millis = i64::from_str_radix(&hex[0..12], 16).unwrap();
        assert!((before - 1..=after + 1).contains(&millis), "{hex} {millis}");
        assert_eq!(&hex[12..13], "7");
        assert!(matches!(&hex[16..17], "8" | "9" | "a" | "b"), "{hex}");
    }
    let randoms: std::collections::HashSet<&str> = ids.iter().map(|h| &h[16..]).collect();
    assert!(randoms.len() > 30, "random bits must vary");
    let mut sorted = ids.clone();
    sorted.sort();
    assert_eq!(sorted, ids);
}

#[test]
fn json_columns_read_back_only_real_values() {
    assert_eq!(json_column(None), None);
    assert_eq!(json_column(Some("null".into())), None);
    assert_eq!(json_column(Some("not json".into())), None);
    assert_eq!(
        json_column(Some(r#"{"a": 1}"#.into())),
        Some(json!({"a": 1}))
    );
    assert_eq!(json_column(Some("[]".into())), Some(json!([])));
}

#[test]
fn json_text_is_python_dumps_or_null() {
    assert_eq!(json_text(None), "null");
    assert_eq!(
        json_text(Some(&json!({"a": [1, "é"]}))),
        r#"{"a": [1, "\u00e9"]}"#
    );
}

#[test]
fn in_list_numbers_placeholders() {
    assert_eq!(in_list(0), "");
    assert_eq!(in_list(1), "?1");
    assert_eq!(in_list(3), "?1, ?2, ?3");
}

#[tokio::test]
async fn sessions_are_created_once_and_read_back() {
    let (_dir, db) = fixture().await;
    let s = new_session(1);
    let again = NewSession {
        title: "Other".into(),
        ..s.clone()
    };
    db.write(move |tx| {
        ensure_session(tx, &s)?;
        ensure_session(tx, &again)
    })
    .await
    .unwrap();
    let missing = db.read(|c| get_session(c, &id(9))).await.unwrap();
    assert!(missing.is_none());
    let row = db.read(|c| get_session(c, &id(1))).await.unwrap().unwrap();
    assert_eq!(row.id, id(1));
    assert_eq!(row.title.as_deref(), Some("First"));
    assert_eq!(row.agent_name.as_deref(), Some("evoflux"));
    assert_eq!(row.mode, "work");
    assert_eq!(row.workspace.as_deref(), Some("/w"));
    assert_eq!(row.folder_id, Some(id(0xf)));
    assert_eq!(row.permission_mode, "ask");
    assert_eq!(row.created_at, ts(5));
    assert_eq!(row.updated_at, ts(5));
    assert_eq!(row.revert, None);
    assert_eq!(row.tags, None);
    assert_eq!(row.model, None);
    assert_eq!(row.scheduled_task_name, None);
    assert_eq!(row.source, None);
    assert_eq!(row.imported_at, None);
    assert_eq!(row.project_id, None);
}

#[tokio::test]
async fn every_session_column_is_mapped() {
    let (_dir, db) = fixture().await;
    exec(
        &db,
        format!(
            "INSERT INTO chat_sessions (id, parent_session_id, agent_name, title, scheduled_task_name, created_at, \
             updated_at, mode, workspace, revert, model, thinking_level, permission_mode, project_id, tags, \
             folder_id, source, imported_at) VALUES ('{}', NULL, 'a', 't', 'task', '{}', '{}', 'coding', '/w', \
             '{{\"k\": 1}}', 'p:m', 'high', 'bypass', '{}', '[\"x\"]', '{}', 'import', '{}')",
            id(1),
            ts(1),
            ts(2),
            id(7),
            id(8),
            ts(3)
        ),
    )
    .await;
    let row = db.read(|c| get_session(c, &id(1))).await.unwrap().unwrap();
    assert_eq!(row.scheduled_task_name.as_deref(), Some("task"));
    assert_eq!(row.mode, "coding");
    assert_eq!(row.revert, Some(json!({"k": 1})));
    assert_eq!(row.model.as_deref(), Some("p:m"));
    assert_eq!(row.thinking_level.as_deref(), Some("high"));
    assert_eq!(row.permission_mode, "bypass");
    assert_eq!(row.project_id, Some(id(7)));
    assert_eq!(row.tags, Some(json!(["x"])));
    assert_eq!(row.folder_id, Some(id(8)));
    assert_eq!(row.source.as_deref(), Some("import"));
    assert_eq!(row.imported_at, Some(ts(3)));
    assert_eq!(row.updated_at, ts(2));
}

#[tokio::test]
async fn child_sessions_and_folder_modes() {
    let (_dir, db) = fixture().await;
    put_sessions(&db).await;
    exec(
        &db,
        format!(
            "INSERT INTO session_folders (id, mode) VALUES ('{}', 'coding')",
            id(0xf)
        ),
    )
    .await;
    let kids = db.read(|c| child_sessions(c, &id(LEAD))).await.unwrap();
    let kid_ids: Vec<&str> = kids.iter().map(|k| k.id.as_str()).collect();
    assert_eq!(kid_ids, [id(MEMBER).as_str(), id(MEMBER + 1).as_str()]);
    assert_eq!(kids[0].agent_name.as_deref(), Some("first"));
    let none = db.read(|c| child_sessions(c, &id(MEMBER))).await.unwrap();
    assert!(none.is_empty());
    assert_eq!(
        db.read(|c| folder_mode(c, &id(0xf)))
            .await
            .unwrap()
            .as_deref(),
        Some("coding")
    );
    assert_eq!(db.read(|c| folder_mode(c, &id(0xe))).await.unwrap(), None);
}

#[tokio::test]
async fn a_turn_updates_the_lead_row() {
    let (_dir, db) = fixture().await;
    db.write(|tx| ensure_session(tx, &new_session(1)))
        .await
        .unwrap();
    exec(
        &db,
        format!(
            "UPDATE chat_sessions SET mode = 'coding', model = 'old:m', thinking_level = 'low' WHERE id = '{}'",
            id(1)
        ),
    )
    .await;
    type Opt = Option<Option<&'static str>>;
    let touch = |ws: Option<&'static str>, model: Opt, level: Opt| {
        let db = db.clone();
        async move {
            db.write(move |tx| touch_session_for_turn(tx, &id(1), ws, model, level, &ts(9)))
                .await
                .unwrap();
            db.read(|c| get_session(c, &id(1))).await.unwrap().unwrap()
        }
    };
    let row = touch(Some("/new"), None, None).await;
    assert_eq!(row.mode, "work");
    assert_eq!(row.workspace.as_deref(), Some("/new"));
    assert_eq!(row.updated_at, ts(9));
    assert_eq!(row.model.as_deref(), Some("old:m"));
    assert_eq!(row.thinking_level.as_deref(), Some("low"));
    let row = touch(None, Some(Some("p:m")), Some(Some("high"))).await;
    assert_eq!(row.workspace, None);
    assert_eq!(row.model.as_deref(), Some("p:m"));
    assert_eq!(row.thinking_level.as_deref(), Some("high"));
    let row = touch(None, Some(None), Some(None)).await;
    assert_eq!((row.model, row.thinking_level), (None, None));
}

#[tokio::test]
async fn messages_round_trip_through_the_columns() {
    let (_dir, db) = fixture().await;
    let full = MessageRow {
        reasoning_content: Some("why".into()),
        tool_calls: Some(json!([{"id": "c"}])),
        tool_call_id: Some("c".into()),
        name: Some("date".into()),
        extra: Some(json!({"a": 1})),
        is_summary: true,
        exclude_from_context: true,
        ..msg(1, LEAD, "assistant")
    };
    let plain = msg(2, LEAD, "user");
    put_rows(&db, vec![full.clone(), plain.clone()]).await;
    let raw: Vec<(String, String)> = db
        .read(|c| {
            let mut stmt =
                c.prepare("SELECT tool_calls, extra FROM session_messages ORDER BY created_at")?;
            let rows = stmt.query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?;
            Ok(rows.collect::<Result<_, _>>()?)
        })
        .await
        .unwrap();
    assert_eq!(
        raw[0],
        (r#"[{"id": "c"}]"#.to_owned(), r#"{"a": 1}"#.to_owned())
    );
    assert_eq!(raw[1], ("null".to_owned(), "null".to_owned()));
    let back: Vec<MessageRow> = db
        .read(|c| {
            let mut stmt = c.prepare(&format!(
                "SELECT {MESSAGE_COLUMNS} FROM session_messages ORDER BY created_at"
            ))?;
            let rows = stmt.query_map([], message_from_row)?;
            Ok(rows.collect::<Result<_, _>>()?)
        })
        .await
        .unwrap();
    assert_eq!(back, vec![full, plain]);
}

#[tokio::test]
async fn the_late_turn_total_lands_on_the_newest_reply() {
    let (_dir, db) = fixture().await;
    let stamp = |db: Arc<Db>, snap: Value| async move {
        db.write(move |tx| stamp_latest_assistant(tx, &id(LEAD), &snap))
            .await
            .unwrap()
    };
    assert!(!stamp(db.clone(), json!({"calls": 2})).await);
    let mut old = msg(1, LEAD, "assistant");
    old.extra = Some(json!({"keep": true}));
    let mut newest = msg(2, LEAD, "assistant");
    newest.extra = Some(json!({"model": "m"}));
    let mut summary = msg(3, LEAD, "assistant");
    summary.is_summary = true;
    let user = msg(4, LEAD, "user");
    put_rows(&db, vec![old, newest, summary, user]).await;
    assert!(stamp(db.clone(), json!({"calls": 2})).await);
    let extras: Vec<Option<Value>> = db
        .read(|c| {
            let mut stmt = c.prepare(&format!(
                "SELECT {MESSAGE_COLUMNS} FROM session_messages ORDER BY created_at"
            ))?;
            let rows = stmt.query_map([], message_from_row)?;
            Ok(rows.map(|r| r.map(|m| m.extra)).collect::<Result<_, _>>()?)
        })
        .await
        .unwrap();
    assert_eq!(extras[0], Some(json!({"keep": true})));
    assert_eq!(
        extras[1],
        Some(json!({"model": "m", "turn_usage": {"calls": 2}}))
    );
    assert_eq!(extras[2], None);
    // An `extra` that is not an object is replaced.
    db.write_exclusive(|tx| update_message_extra(tx, &id(2), &json!([1])))
        .await
        .unwrap();
    assert!(stamp(db.clone(), json!({"calls": 3})).await);
    let again = db
        .read(|c| {
            Ok(c.query_row(
                "SELECT extra FROM session_messages WHERE id = ?1",
                [id(2)],
                |r| r.get::<_, String>(0),
            )?)
        })
        .await
        .unwrap();
    assert_eq!(again, r#"{"turn_usage": {"calls": 3}}"#);
}

#[tokio::test]
async fn titles_update_the_row_that_exists() {
    let (_dir, db) = fixture().await;
    db.write(|tx| ensure_session(tx, &new_session(1)))
        .await
        .unwrap();
    let (hit, miss) = db
        .write(|tx| {
            Ok((
                set_title(tx, &id(1), "New", &ts(8))?,
                set_title(tx, &id(2), "x", &ts(8))?,
            ))
        })
        .await
        .unwrap();
    assert!(hit);
    assert!(!miss);
    let row = db.read(|c| get_session(c, &id(1))).await.unwrap().unwrap();
    assert_eq!(row.title.as_deref(), Some("New"));
    assert_eq!(row.updated_at, ts(8));
}

#[tokio::test]
async fn llm_rows_start_at_the_latest_visible_summary() {
    let (_dir, db) = fixture().await;
    let mut old_summary = msg(1, LEAD, "assistant");
    old_summary.is_summary = true;
    let mut new_summary = msg(4, LEAD, "assistant");
    new_summary.is_summary = true;
    let mut hidden_summary = msg(7, LEAD, "assistant");
    hidden_summary.is_summary = true;
    hidden_summary.exclude_from_context = true;
    let mut hidden = msg(5, LEAD, "user");
    hidden.exclude_from_context = true;
    put_rows(
        &db,
        vec![
            msg(2, LEAD, "user"),
            old_summary,
            msg(3, LEAD, "assistant"),
            new_summary,
            hidden,
            msg(6, LEAD, "user"),
            hidden_summary,
            msg(8, MEMBER, "user"),
        ],
    )
    .await;
    let ids = |rows: Vec<MessageRow>| rows.into_iter().map(|r| r.id).collect::<Vec<_>>();
    let with = ids(db.read(|c| llm_rows(c, &id(LEAD))).await.unwrap());
    assert_eq!(with, [id(4), id(2), id(3), id(6)]);
    let other = ids(db.read(|c| llm_rows(c, &id(MEMBER))).await.unwrap());
    assert_eq!(other, [id(8)]);
    assert!(db.read(|c| llm_rows(c, &id(1))).await.unwrap().is_empty());
}

#[tokio::test]
async fn llm_rows_without_a_summary_are_every_visible_row() {
    let (_dir, db) = fixture().await;
    let mut hidden = msg(2, LEAD, "user");
    hidden.exclude_from_context = true;
    put_rows(
        &db,
        vec![msg(3, LEAD, "assistant"), hidden, msg(1, LEAD, "user")],
    )
    .await;
    let rows = db.read(|c| llm_rows(c, &id(LEAD))).await.unwrap();
    assert_eq!(
        rows.iter().map(|r| r.id.clone()).collect::<Vec<_>>(),
        [id(1), id(3)]
    );
}

fn weighted(n: usize, weight: usize) -> MessageRow {
    MessageRow {
        content: Some("x".repeat(weight - 256)),
        ..msg(n, LEAD, "user")
    }
}

#[test]
fn a_page_may_fill_the_budget_exactly() {
    let mut rows: Vec<MessageRow> = (0..24).map(|n| weighted(n, 8000)).collect();
    rows.push(weighted(24, HISTORY_TARGET_BYTES - 24 * 8000));
    rows.push(weighted(25, 300));
    assert_eq!(bounded_page(&rows).len(), 25);
}

type Before = Option<(String, Option<String>)>;
type Floor = Option<(String, String)>;

#[tokio::test]
async fn rows_before_applies_cursor_floor_and_limit() {
    let (_dir, db) = fixture().await;
    put_rows(
        &db,
        (1..=6)
            .map(|n| msg(n, if n % 2 == 0 { MEMBER } else { LEAD }, "user"))
            .collect(),
    )
    .await;
    let both = vec![id(LEAD), id(MEMBER)];
    let run = |before: Before, floor: Floor, limit: Option<usize>, sessions: Vec<String>| {
        let db = db.clone();
        async move {
            db.read(move |c| {
                rows_before(
                    c,
                    &sessions,
                    before.as_ref().map(|(a, b)| (a.as_str(), b.as_deref())),
                    floor.as_ref().map(|(a, b)| (a.as_str(), b.as_str())),
                    limit,
                )
            })
            .await
            .unwrap()
            .into_iter()
            .map(|r| r.id)
            .collect::<Vec<_>>()
        }
    };
    let want = |ns: &[usize]| ns.iter().map(|n| id(*n)).collect::<Vec<_>>();
    assert_eq!(
        run(None, None, None, both.clone()).await,
        want(&[6, 5, 4, 3, 2, 1])
    );
    assert_eq!(run(None, None, Some(2), both.clone()).await, want(&[6, 5]));
    assert_eq!(
        run(None, None, None, vec![id(LEAD)]).await,
        want(&[5, 3, 1])
    );
    assert_eq!(
        run(Some((ts(4), None)), None, None, both.clone()).await,
        want(&[3, 2, 1])
    );
    assert_eq!(
        run(Some((ts(4), Some(id(4)))), None, None, both.clone()).await,
        want(&[3, 2, 1])
    );
    assert_eq!(
        run(
            Some((ts(4), Some(id(4)))),
            Some((ts(2), id(2))),
            None,
            both.clone()
        )
        .await,
        want(&[3, 2])
    );
    assert_eq!(
        run(None, Some((ts(3), id(3))), None, both.clone()).await,
        want(&[6, 5, 4, 3])
    );
    assert_eq!(
        run(Some((ts(5), None)), Some((ts(2), id(3))), Some(2), both).await,
        want(&[4, 3])
    );
}

async fn history_of(db: &Arc<Db>, before: Before) -> History {
    db.read(move |c| history(c, &id(LEAD), before.clone()))
        .await
        .unwrap()
        .unwrap()
}

fn contents(rows: &[MessageRow]) -> Vec<&str> {
    rows.iter().map(|r| r.content.as_deref().unwrap()).collect()
}

#[tokio::test]
async fn history_of_a_missing_session_is_none() {
    let (_dir, db) = fixture().await;
    assert!(db
        .read(|c| history(c, &id(LEAD), None))
        .await
        .unwrap()
        .is_none());
}

#[tokio::test]
async fn history_extends_a_cut_turn_back_to_its_user_message() {
    let (_dir, db) = fixture().await;
    put_sessions(&db).await;
    let mut rows = vec![msg(0, LEAD, "user")];
    rows.extend((1..=200).map(|n| msg(n, LEAD, "assistant")));
    put_rows(&db, rows).await;
    let h = history_of(&db, None).await;
    assert_eq!(h.lead_messages.len(), 201);
    assert_eq!(h.lead_messages[0].id, id(0));
    assert_eq!(h.lead_messages[200].id, id(200));
    assert!(!h.has_more);
    assert_eq!(h.next_cursor, None);
    assert_eq!(h.lead.id, id(LEAD));
    assert_eq!(h.members.len(), 2);
    assert_eq!(h.goal, None);
}

#[tokio::test]
async fn history_stops_at_a_summary_and_pages_with_a_cursor() {
    let (_dir, db) = fixture().await;
    put_sessions(&db).await;
    let mut summary = msg(1, LEAD, "assistant");
    summary.is_summary = true;
    let mut rows = vec![msg(0, LEAD, "user"), summary];
    rows.extend((2..=160).map(|n| msg(n, LEAD, "assistant")));
    put_rows(&db, rows).await;
    let h = history_of(&db, None).await;
    assert_eq!(h.lead_messages.len(), 160);
    assert_eq!(h.lead_messages[0].id, id(1));
    assert!(h.has_more);
    assert_eq!(
        h.next_cursor,
        Some(format!("2026-11-01T00:00:01|{}", dashed(&id(1))))
    );
    let older = history_of(&db, Some((ts(1), Some(id(1))))).await;
    assert_eq!(contents(&older.lead_messages), ["m0"]);
    assert!(!older.has_more);
    let before_time = history_of(&db, Some((ts(1), None))).await;
    assert_eq!(contents(&before_time.lead_messages), ["m0"]);
}

#[tokio::test]
async fn history_extends_each_session_to_its_own_turn_start() {
    let (_dir, db) = fixture().await;
    put_sessions(&db).await;
    let mut rows = vec![msg(0, MEMBER, "user")];
    rows.extend((1..=170).map(|n| msg(n, MEMBER, "assistant")));
    rows.push(msg(171, LEAD, "user"));
    rows.push(msg(172, LEAD, "assistant"));
    put_rows(&db, rows).await;
    let h = history_of(&db, None).await;
    assert_eq!(contents(&h.lead_messages), ["m171", "m172"]);
    let (first, first_rows) = &h.members[0];
    assert_eq!(first.id, id(MEMBER));
    assert_eq!(first_rows.len(), 171);
    assert_eq!(first_rows[0].id, id(0));
    assert!(h.members[1].1.is_empty());
    assert!(!h.has_more);
}

#[tokio::test]
async fn history_finds_a_cut_member_turn_below_an_older_lead_row() {
    let (_dir, db) = fixture().await;
    put_sessions(&db).await;
    let mut rows = vec![msg(0, MEMBER, "user")];
    rows.extend((1..=9).map(|n| msg(n, MEMBER, "assistant")));
    rows.push(msg(10, LEAD, "user"));
    rows.extend((11..=169).map(|n| msg(n, MEMBER, "assistant")));
    put_rows(&db, rows).await;
    let h = history_of(&db, None).await;
    assert_eq!(contents(&h.lead_messages), ["m10"]);
    assert_eq!(h.members[0].1.len(), 169);
    assert_eq!(h.members[0].1[0].id, id(0));
    assert!(!h.has_more);
}

#[tokio::test]
async fn hidden_rows_stay_out_of_history() {
    let (_dir, db) = fixture().await;
    put_sessions(&db).await;
    let mut hidden = msg(2, LEAD, "assistant");
    hidden.extra = Some(json!({"hidden_from_user": true}));
    let mut shown = msg(3, LEAD, "assistant");
    shown.extra = Some(json!({"hidden_from_user": false}));
    put_rows(&db, vec![msg(1, LEAD, "user"), hidden, shown]).await;
    let h = history_of(&db, None).await;
    assert_eq!(contents(&h.lead_messages), ["m1", "m3"]);
    assert!(!h.has_more);
    assert_eq!(h.next_cursor, None);
}

async fn put_goal(db: &Db, status: &str, started: Option<String>, seconds: f64) {
    let started = started.map_or("NULL".to_owned(), |s| format!("'{s}'"));
    exec(
        db,
        format!(
            "INSERT INTO session_goals VALUES ('{}', 'ship it', '{status}', 1000, 42, {seconds}, {started}, 'why', 2, \
             '{{\"note\": 1}}', 3, '{}', '{}', NULL)",
            id(LEAD),
            ts(1),
            ts(2)
        ),
    )
    .await;
}

#[tokio::test]
async fn an_active_goal_counts_the_running_time() {
    let (_dir, db) = fixture().await;
    put_sessions(&db).await;
    let started = (Utc::now() - chrono::Duration::seconds(100))
        .naive_utc()
        .format(DB_TS)
        .to_string();
    put_goal(&db, "active", Some(started), 10.0).await;
    let goal = history_of(&db, None).await.goal.unwrap();
    let used = goal["time_used_seconds"].as_f64().unwrap();
    assert!((109.5..140.0).contains(&used), "{used}");
    assert_eq!(goal["session_id"], dashed(&id(LEAD)));
    assert_eq!(goal["objective"], "ship it");
    assert_eq!(goal["status"], "active");
    assert_eq!(goal["token_budget"], 1000);
    assert_eq!(goal["tokens_used"], 42);
    assert_eq!(goal["pause_reason"], "why");
    assert_eq!(goal["blocker_streak"], 2);
    assert_eq!(goal["status_details"], json!({"note": 1}));
    assert_eq!(goal["version"], 3);
    assert_eq!(goal["created_at"], "2026-11-01T00:00:01Z");
    assert_eq!(goal["updated_at"], "2026-11-01T00:00:02Z");
    assert_eq!(goal["completed_at"], Value::Null);
}

#[tokio::test]
async fn a_paused_goal_keeps_its_stored_time() {
    let (_dir, db) = fixture().await;
    put_sessions(&db).await;
    put_goal(&db, "paused", Some(ts(1)), 10.0).await;
    let found = db.read(|c| goal(c, &id(LEAD))).await.unwrap().unwrap();
    assert_eq!(found["time_used_seconds"], 10.0);
    assert!(db.read(|c| goal(c, &id(1))).await.unwrap().is_none());
}
