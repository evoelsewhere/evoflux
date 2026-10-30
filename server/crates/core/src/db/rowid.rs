//! Random rowids for inserts into rowid tables (design §3.3).
//!
//! Sequential rowids put every concurrent insert on the table's last page, so
//! `BEGIN CONCURRENT` transactions would conflict. Rowids are invisible to the
//! API and stock SQLite and v3 accept any value, so this keeps the file and
//! behaviour compatible.

use rusqlite::{ffi, params_from_iter, ToSql};

use super::{DbError, Tx};

/// Largest rowid handed out: 2^62.
const MAX_ROWID: i64 = 1 << 62;
/// A collision in 1..=2^62 is already vanishingly rare; this bounds the loop.
const MAX_ATTEMPTS: usize = 8;

/// Uniform random rowid in `1..=2^62`.
pub fn random_rowid() -> i64 {
    fastrand::i64(1..=MAX_ROWID)
}

/// `INSERT INTO table (rowid, columns…) VALUES (random, values…)`.
///
/// Retries with a new rowid only when the rowid itself collided; any other
/// constraint failure (including the table's own primary key) is returned.
///
/// Tables whose primary key is an `INTEGER PRIMARY KEY` (a rowid alias, such
/// as `dream_log.id`) get a plain insert instead: there the rowid is the
/// API-visible id, and v3 hands out ascending values.
pub fn insert(
    tx: &Tx<'_>,
    table: &str,
    columns: &[&str],
    values: &[&dyn ToSql],
) -> Result<(), DbError> {
    let alias = has_rowid_alias(tx, table)?;
    let table = quote_ident(table);
    if alias {
        let names: Vec<String> = columns.iter().map(|c| quote_ident(c)).collect();
        let placeholders: Vec<String> = (1..=columns.len()).map(|i| format!("?{i}")).collect();
        let sql = format!(
            "INSERT INTO {table} ({}) VALUES ({})",
            names.join(", "),
            placeholders.join(", ")
        );
        tx.prepare_cached(&sql)?
            .execute(params_from_iter(values.iter().copied()))?;
        return Ok(());
    }
    let names: String = columns
        .iter()
        .map(|c| format!(", {}", quote_ident(c)))
        .collect();
    let placeholders: String = (2..=columns.len() + 1).map(|i| format!(", ?{i}")).collect();
    let sql = format!("INSERT INTO {table} (rowid{names}) VALUES (?1{placeholders})");
    let mut stmt = tx.prepare_cached(&sql)?;
    for _ in 0..MAX_ATTEMPTS {
        let rowid = random_rowid();
        let params = std::iter::once(&rowid as &dyn ToSql).chain(values.iter().copied());
        match stmt.execute(params_from_iter(params)) {
            Ok(_) => return Ok(()),
            Err(err) if is_primary_key_violation(&err) && rowid_taken(tx, &table, rowid)? => {}
            Err(err) => return Err(err.into()),
        }
    }
    Err(DbError::RowidExhausted)
}

/// Whether the table's primary key is a single `INTEGER` column, which SQLite
/// makes an alias of the rowid.
fn has_rowid_alias(tx: &Tx<'_>, table: &str) -> Result<bool, DbError> {
    let mut stmt = tx.prepare_cached("SELECT type, pk FROM pragma_table_info(?1) WHERE pk > 0")?;
    let pks = stmt
        .query_map([table], |r| r.get::<_, String>(0))?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(matches!(pks.as_slice(), [t] if t.eq_ignore_ascii_case("INTEGER")))
}

fn is_primary_key_violation(err: &rusqlite::Error) -> bool {
    matches!(err, rusqlite::Error::SqliteFailure(e, _)
        if e.extended_code == ffi::SQLITE_CONSTRAINT_PRIMARYKEY
            || e.extended_code == ffi::SQLITE_CONSTRAINT_ROWID)
}

fn rowid_taken(tx: &Tx<'_>, quoted_table: &str, rowid: i64) -> Result<bool, DbError> {
    let sql = format!("SELECT EXISTS (SELECT 1 FROM {quoted_table} WHERE rowid = ?1)");
    Ok(tx.query_row(&sql, [rowid], |r| r.get(0))?)
}

fn quote_ident(name: &str) -> String {
    format!("\"{}\"", name.replace('"', "\"\""))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quotes_identifiers() {
        assert_eq!(quote_ident("a\"b"), "\"a\"\"b\"");
    }
}
