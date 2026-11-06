//! Mail between sessions, kept by the desktop shell's mesh hub
//! (`crates/evo-mesh`, `docs/design/session-mesh-protocol.md`). A message is
//! stored before it is sent and marked delivered once the receiving engine
//! answers it; whatever is still undelivered goes out when that engine starts.

use rusqlite::{params, Connection, OptionalExtension};

use crate::DbError;

/// One stored message. `body` is the mesh envelope body, as JSON text.
#[derive(Debug, Clone, PartialEq)]
pub struct StoredMail {
    pub id: String,
    pub from_chat: String,
    pub to_chat: String,
    pub body: String,
    pub created_at: i64,
    pub delivered_at: Option<i64>,
}

fn row(row: &rusqlite::Row<'_>) -> rusqlite::Result<StoredMail> {
    Ok(StoredMail {
        id: row.get(0)?,
        from_chat: row.get(1)?,
        to_chat: row.get(2)?,
        body: row.get(3)?,
        created_at: row.get(4)?,
        delivered_at: row.get(5)?,
    })
}

const COLUMNS: &str = "id, from_chat, to_chat, body, created_at, delivered_at";

/// Store a message (a second insert of the same id changes nothing).
pub fn insert_mail(conn: &Connection, mail: &StoredMail) -> Result<(), DbError> {
    conn.execute(
        "INSERT OR IGNORE INTO mail (id, from_chat, to_chat, body, created_at, delivered_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
        params![mail.id, mail.from_chat, mail.to_chat, mail.body, mail.created_at, mail.delivered_at],
    )?;
    Ok(())
}

/// Undelivered mail for `to_chat`, oldest first.
pub fn pending_mail(conn: &Connection, to_chat: &str) -> Result<Vec<StoredMail>, DbError> {
    let mut statement = conn.prepare(&format!(
        "SELECT {COLUMNS} FROM mail WHERE to_chat = ?1 AND delivered_at IS NULL ORDER BY created_at, id"
    ))?;
    let rows = statement.query_map([to_chat], row)?.collect::<Result<Vec<_>, _>>()?;
    Ok(rows)
}

pub fn get_mail(conn: &Connection, id: &str) -> Result<Option<StoredMail>, DbError> {
    Ok(conn
        .query_row(&format!("SELECT {COLUMNS} FROM mail WHERE id = ?1"), [id], row)
        .optional()?)
}

/// The receiving engine took it.
pub fn mark_mail_delivered(conn: &Connection, id: &str, at: i64) -> Result<(), DbError> {
    conn.execute("UPDATE mail SET delivered_at = ?2 WHERE id = ?1 AND delivered_at IS NULL", params![id, at])?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::chats::{create_chat, delete_chat, NewChat};

    #[test]
    fn mail_waits_until_delivered_and_goes_with_its_receiver() {
        let dir = tempfile::tempdir().unwrap();
        let mut conn = crate::open_at(&dir.path().join("evo.db")).unwrap();
        create_chat(&conn, &NewChat { id: "p".into(), title: "Parent".into(), ..Default::default() }).unwrap();
        let mail = |id: &str, at: i64| StoredMail {
            id: id.into(),
            from_chat: "c".into(),
            to_chat: "p".into(),
            body: format!("{{\"text\":\"{id}\"}}"),
            created_at: at,
            delivered_at: None,
        };
        insert_mail(&conn, &mail("m2", 20)).unwrap();
        insert_mail(&conn, &mail("m1", 10)).unwrap();
        insert_mail(&conn, &mail("m1", 10)).unwrap(); // same id: ignored
        let ids: Vec<_> = pending_mail(&conn, "p").unwrap().into_iter().map(|m| m.id).collect();
        assert_eq!(ids, ["m1", "m2"]);
        assert!(pending_mail(&conn, "nobody").unwrap().is_empty());

        mark_mail_delivered(&conn, "m1", 30).unwrap();
        mark_mail_delivered(&conn, "m1", 40).unwrap(); // the first answer counts
        assert_eq!(get_mail(&conn, "m1").unwrap().unwrap().delivered_at, Some(30));
        assert_eq!(pending_mail(&conn, "p").unwrap().len(), 1);

        // Deleting the receiving chat deletes its mail.
        delete_chat(&mut conn, "p").unwrap();
        assert!(get_mail(&conn, "m2").unwrap().is_none());
    }
}
