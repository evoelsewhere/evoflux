//! What the `lsp` tool does, with answers as plain text for the model.

use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use serde_json::{json, Value};

use crate::client::{path_of, Client};
use crate::pool::Pool;

/// How long a first request waits for indexing to finish.
const INDEX_WAIT: Duration = Duration::from_secs(60);
const DIAGNOSTICS_WAIT: Duration = Duration::from_secs(20);
const MAX_LINES: usize = 150;

/// `path` as shown: relative to `cwd` when inside it, with `/`.
pub fn show(path: &Path, cwd: &Path) -> String {
    path.strip_prefix(cwd)
        .unwrap_or(path)
        .to_string_lossy()
        .replace('\\', "/")
}

fn resolve(path: &str, cwd: &Path) -> PathBuf {
    let p = PathBuf::from(path);
    if p.is_absolute() {
        p
    } else {
        cwd.join(p)
    }
}

fn severity(n: Option<u64>) -> &'static str {
    match n {
        Some(1) => "error",
        Some(2) => "warning",
        Some(3) => "info",
        _ => "hint",
    }
}

fn format_diagnostic(file: &str, d: &Value) -> String {
    let line = d
        .pointer("/range/start/line")
        .and_then(Value::as_u64)
        .unwrap_or(0)
        + 1;
    let col = d
        .pointer("/range/start/character")
        .and_then(Value::as_u64)
        .unwrap_or(0)
        + 1;
    let message = d
        .get("message")
        .and_then(Value::as_str)
        .unwrap_or("")
        .replace('\n', " ");
    let source = d.get("source").and_then(Value::as_str);
    let code = d.get("code").map(|c| {
        c.as_str()
            .map(str::to_string)
            .unwrap_or_else(|| c.to_string())
    });
    let tag = match (source, code) {
        (Some(s), Some(c)) => format!(" [{s} {c}]"),
        (Some(s), None) => format!(" [{s}]"),
        (None, Some(c)) => format!(" [{c}]"),
        _ => String::new(),
    };
    format!(
        "{file}:{line}:{col} {}: {message}{tag}",
        severity(d.get("severity").and_then(Value::as_u64))
    )
}

fn rank(d: &Value) -> u64 {
    d.get("severity").and_then(Value::as_u64).unwrap_or(4)
}

/// Problems the language server reports for `path`, or for every file it has
/// reported on when `path` is `None`.
pub async fn diagnostics(pool: &Pool, cwd: &Path, path: Option<&str>) -> Result<String, String> {
    let Some(path) = path else {
        let mut lines = Vec::new();
        for client in pool.clients().await {
            for (uri, list) in client.all_diagnostics() {
                let file = path_of(&uri).map(|p| show(&p, cwd)).unwrap_or(uri);
                let mut list = list;
                list.sort_by_key(rank);
                lines.extend(
                    list.iter()
                        .filter(|d| rank(d) <= 2)
                        .map(|d| format_diagnostic(&file, d)),
                );
            }
        }
        if lines.is_empty() {
            return Ok("No errors or warnings reported. (Only files a language server has looked at count: pass `path` to check a file.)".into());
        }
        let total = lines.len();
        lines.truncate(MAX_LINES);
        return Ok(format!("{}{}", lines.join("\n"), more(total)));
    };
    let file = resolve(path, cwd);
    let client = pool.client_for(&file, cwd).await?;
    let sent_at = Instant::now();
    let (uri, version) = client.sync_file(&file).await?;
    let mut idle = client.wait_idle(INDEX_WAIT).await;
    let mut list = client
        .diagnostics_for(&uri, version, sent_at, DIAGNOSTICS_WAIT)
        .await;
    // A first, quick report can come before a slower check (`cargo check`):
    // once the server is idle again, take the newest report.
    if list.is_some() {
        tokio::time::sleep(Duration::from_millis(400)).await;
        if client.indexing() {
            idle = client.wait_idle(INDEX_WAIT).await;
        }
        list = client
            .diagnostics_for(&uri, version, sent_at, Duration::ZERO)
            .await
            .or(list);
    }
    let shown = show(&file, cwd);
    let Some(mut list) = list else {
        return Ok(format!(
            "{} has not reported on {shown} yet{}. Try again in a moment.",
            client.server.name,
            if idle {
                ""
            } else {
                " (it is still indexing the project)"
            }
        ));
    };
    if list.is_empty() {
        return Ok(format!("{shown}: no problems ({}).", client.server.name));
    }
    list.sort_by_key(rank);
    let total = list.len();
    let lines: Vec<String> = list
        .iter()
        .take(MAX_LINES)
        .map(|d| format_diagnostic(&shown, d))
        .collect();
    let errors = list.iter().filter(|d| rank(d) == 1).count();
    let warnings = list.iter().filter(|d| rank(d) == 2).count();
    Ok(format!(
        "{errors} errors, {warnings} warnings ({}):\n{}{}",
        client.server.name,
        lines.join("\n"),
        more(total)
    ))
}

fn more(total: usize) -> String {
    if total > MAX_LINES {
        format!("\n… {} more", total - MAX_LINES)
    } else {
        String::new()
    }
}

/// UTF-16 length of `text` (LSP's default position unit).
fn utf16(text: &str) -> u32 {
    text.encode_utf16().count() as u32
}

/// The 0-based line and UTF-16 column for a 1-based `line` and either a
/// `symbol` on it or a 1-based `character`.
pub fn position(
    text: &str,
    line: u32,
    symbol: Option<&str>,
    character: Option<u32>,
) -> Result<(u32, u32), String> {
    let index = line.checked_sub(1).ok_or("lines start at 1")?;
    let row = text
        .split('\n')
        .nth(index as usize)
        .ok_or_else(|| format!("the file has no line {line}"))?
        .trim_end_matches('\r');
    let col = if let Some(symbol) = symbol.filter(|s| !s.is_empty()) {
        let is_word = |c: char| c.is_alphanumeric() || c == '_';
        let mut found = None;
        let mut from = 0;
        while let Some(at) = row[from..].find(symbol) {
            let start = from + at;
            let end = start + symbol.len();
            let before = row[..start].chars().next_back();
            let after = row[end..].chars().next();
            if before.is_none_or(|c| !is_word(c)) && after.is_none_or(|c| !is_word(c)) {
                found = Some(start);
                break;
            }
            from = start + symbol.len().max(1);
        }
        let start = found
            .or_else(|| row.find(symbol))
            .ok_or_else(|| format!("`{symbol}` is not on line {line}: {}", row.trim()))?;
        utf16(&row[..start])
    } else if let Some(character) = character {
        let chars: String = row
            .chars()
            .take(character.saturating_sub(1) as usize)
            .collect();
        utf16(&chars)
    } else {
        let start = row.len() - row.trim_start().len();
        utf16(&row[..start])
    };
    Ok((index, col))
}

fn locations(result: &Value) -> Vec<(String, u64, u64)> {
    let items: Vec<Value> = match result {
        Value::Array(a) => a.clone(),
        Value::Null => Vec::new(),
        other => vec![other.clone()],
    };
    items
        .iter()
        .filter_map(|item| {
            let uri = item
                .get("uri")
                .or_else(|| item.get("targetUri"))?
                .as_str()?
                .to_string();
            let range = item
                .get("range")
                .or_else(|| item.get("targetSelectionRange"))
                .or_else(|| item.get("targetRange"))?;
            let line = range.pointer("/start/line")?.as_u64()?;
            let col = range.pointer("/start/character")?.as_u64()?;
            Some((uri, line, col))
        })
        .collect()
}

async fn line_text(client: &Client, uri: &str, line: u64) -> String {
    let text = match client.text_of(uri).await {
        Some(t) => Some(t),
        None => match path_of(uri) {
            Some(p) => tokio::fs::read_to_string(p).await.ok(),
            None => None,
        },
    };
    text.and_then(|t| {
        t.split('\n')
            .nth(line as usize)
            .map(|l| l.trim().to_string())
    })
    .map(|l| {
        if l.chars().count() > 160 {
            format!("{}…", l.chars().take(160).collect::<String>())
        } else {
            l
        }
    })
    .unwrap_or_default()
}

fn hover_text(result: &Value) -> String {
    fn piece(v: &Value) -> String {
        match v {
            Value::String(s) => s.clone(),
            Value::Object(o) => match (o.get("language"), o.get("value")) {
                (Some(lang), Some(Value::String(value))) => {
                    format!("```{}\n{value}\n```", lang.as_str().unwrap_or(""))
                }
                (_, Some(Value::String(value))) => value.clone(),
                _ => String::new(),
            },
            Value::Array(a) => a
                .iter()
                .map(piece)
                .filter(|s| !s.is_empty())
                .collect::<Vec<_>>()
                .join("\n\n"),
            _ => String::new(),
        }
    }
    result.get("contents").map(piece).unwrap_or_default()
}

const SYMBOL_KINDS: &[&str] = &[
    "",
    "file",
    "module",
    "namespace",
    "package",
    "class",
    "method",
    "property",
    "field",
    "constructor",
    "enum",
    "interface",
    "function",
    "variable",
    "constant",
    "string",
    "number",
    "boolean",
    "array",
    "object",
    "key",
    "null",
    "enum member",
    "struct",
    "event",
    "operator",
    "type parameter",
];

fn kind_name(v: &Value) -> &'static str {
    v.get("kind")
        .and_then(Value::as_u64)
        .and_then(|k| SYMBOL_KINDS.get(k as usize))
        .copied()
        .unwrap_or("symbol")
}

fn outline(symbols: &[Value], depth: usize, out: &mut Vec<String>) {
    for s in symbols {
        let name = s.get("name").and_then(Value::as_str).unwrap_or("?");
        let line = s
            .pointer("/selectionRange/start/line")
            .or_else(|| s.pointer("/range/start/line"))
            .or_else(|| s.pointer("/location/range/start/line"))
            .and_then(Value::as_u64)
            .unwrap_or(0)
            + 1;
        let detail = s
            .get("detail")
            .and_then(Value::as_str)
            .filter(|d| !d.is_empty())
            .map(|d| format!(" — {d}"))
            .unwrap_or_default();
        out.push(format!(
            "{}{} {name} (line {line}){detail}",
            "  ".repeat(depth),
            kind_name(s)
        ));
        if let Some(children) = s.get("children").and_then(Value::as_array) {
            outline(children, depth + 1, out);
        }
    }
}

/// `definition`, `type_definition`, `implementation`, `references` or `hover`
/// at a place in `path`.
pub async fn at(
    pool: &Pool,
    cwd: &Path,
    op: &str,
    path: &str,
    line: u32,
    symbol: Option<&str>,
    character: Option<u32>,
) -> Result<String, String> {
    let file = resolve(path, cwd);
    let client = pool.client_for(&file, cwd).await?;
    let (uri, _) = client.sync_file(&file).await?;
    let text = client.text_of(&uri).await.unwrap_or_default();
    let (row, col) = position(&text, line, symbol, character)?;
    client.wait_idle(INDEX_WAIT).await;
    let method = match op {
        "definition" => "textDocument/definition",
        "type_definition" => "textDocument/typeDefinition",
        "implementation" => "textDocument/implementation",
        "references" => "textDocument/references",
        "hover" => "textDocument/hover",
        other => return Err(format!("unknown operation `{other}`")),
    };
    let mut params =
        json!({ "textDocument": { "uri": uri }, "position": { "line": row, "character": col } });
    if op == "references" {
        params["context"] = json!({ "includeDeclaration": true });
    }
    let result = client.request_default(method, params).await?;
    let what = symbol
        .map(|s| format!("`{s}`"))
        .unwrap_or_else(|| format!("line {line}"));
    if op == "hover" {
        let text = hover_text(&result);
        return Ok(if text.trim().is_empty() {
            format!("No information about {what}.")
        } else {
            text
        });
    }
    let found = locations(&result);
    if found.is_empty() {
        return Ok(format!("No {} found for {what}.", op.replace('_', " ")));
    }
    let total = found.len();
    let mut lines = Vec::new();
    for (uri, l, c) in found.iter().take(MAX_LINES) {
        let file = path_of(uri)
            .map(|p| show(&p, cwd))
            .unwrap_or_else(|| uri.clone());
        lines.push(format!(
            "{file}:{}:{} {}",
            l + 1,
            c + 1,
            line_text(&client, uri, *l).await
        ));
    }
    let head = match op {
        "references" => format!("{total} references to {what}:"),
        _ => format!("{} of {what}:", op.replace('_', " ")),
    };
    Ok(format!("{head}\n{}{}", lines.join("\n"), more(total)))
}

/// The outline of `path`: its symbols with kinds and lines.
pub async fn symbols(pool: &Pool, cwd: &Path, path: &str) -> Result<String, String> {
    let file = resolve(path, cwd);
    let client = pool.client_for(&file, cwd).await?;
    let (uri, _) = client.sync_file(&file).await?;
    client.wait_idle(INDEX_WAIT).await;
    let result = client
        .request_default(
            "textDocument/documentSymbol",
            json!({ "textDocument": { "uri": uri } }),
        )
        .await?;
    let list = result.as_array().cloned().unwrap_or_default();
    if list.is_empty() {
        return Ok(format!("No symbols in {}.", show(&file, cwd)));
    }
    let mut out = Vec::new();
    outline(&list, 0, &mut out);
    let total = out.len();
    out.truncate(MAX_LINES * 2);
    Ok(format!(
        "{}:\n{}{}",
        show(&file, cwd),
        out.join("\n"),
        if total > MAX_LINES * 2 {
            format!("\n… {} more", total - MAX_LINES * 2)
        } else {
            String::new()
        }
    ))
}

/// Symbols named like `query` across the project of `path`'s language.
pub async fn workspace_symbols(
    pool: &Pool,
    cwd: &Path,
    query: &str,
    path: &str,
) -> Result<String, String> {
    let file = resolve(path, cwd);
    let client = pool.client_for(&file, cwd).await?;
    let _ = client.sync_file(&file).await;
    client.wait_idle(INDEX_WAIT).await;
    let result = client
        .request_default("workspace/symbol", json!({ "query": query }))
        .await?;
    let list = result.as_array().cloned().unwrap_or_default();
    if list.is_empty() {
        return Ok(format!("No symbols matching `{query}`."));
    }
    let total = list.len();
    let lines: Vec<String> = list
        .iter()
        .take(MAX_LINES)
        .map(|s| {
            let name = s.get("name").and_then(Value::as_str).unwrap_or("?");
            let uri = s
                .pointer("/location/uri")
                .and_then(Value::as_str)
                .unwrap_or("");
            let line = s
                .pointer("/location/range/start/line")
                .and_then(Value::as_u64)
                .map(|l| format!(":{}", l + 1))
                .unwrap_or_default();
            let file = path_of(uri)
                .map(|p| show(&p, cwd))
                .unwrap_or_else(|| uri.to_string());
            let container = s
                .get("containerName")
                .and_then(Value::as_str)
                .filter(|c| !c.is_empty())
                .map(|c| format!(" in {c}"))
                .unwrap_or_default();
            format!("{} {name}{container} — {file}{line}", kind_name(s))
        })
        .collect();
    Ok(format!("{}{}", lines.join("\n"), more(total)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn positions_find_symbols_on_word_boundaries() {
        let text = "fn main() {\n    let total = sub_total + total_tax;\n}\n";
        assert_eq!(position(text, 2, Some("total"), None).unwrap(), (1, 8));
        assert_eq!(position(text, 2, Some("total_tax"), None).unwrap(), (1, 28));
        assert_eq!(position(text, 2, None, None).unwrap(), (1, 4));
        assert_eq!(position(text, 1, None, Some(4)).unwrap(), (0, 3));
        assert!(position(text, 9, None, None).is_err());
        assert!(position(text, 2, Some("missing"), None).is_err());
        // UTF-16 columns: "é" is one unit, "😀" two.
        assert_eq!(
            position("let é😀 = x;", 1, Some("x"), None).unwrap(),
            (0, 10)
        );
    }

    #[test]
    fn diagnostics_read_well() {
        let d = json!({ "range": { "start": { "line": 4, "character": 2 } }, "severity": 1, "message": "mismatched types", "source": "rustc", "code": "E0308" });
        assert_eq!(
            format_diagnostic("src/a.rs", &d),
            "src/a.rs:5:3 error: mismatched types [rustc E0308]"
        );
    }

    #[test]
    fn locations_take_every_shape() {
        let single =
            json!({ "uri": "file:///a.rs", "range": { "start": { "line": 1, "character": 2 } } });
        let links = json!([{ "targetUri": "file:///b.rs", "targetSelectionRange": { "start": { "line": 3, "character": 0 } } }]);
        assert_eq!(locations(&single).len(), 1);
        assert_eq!(locations(&links)[0].0, "file:///b.rs");
        assert!(locations(&Value::Null).is_empty());
    }
}
