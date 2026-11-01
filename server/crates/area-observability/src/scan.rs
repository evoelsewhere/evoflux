//! Bounded reader for `{state}/otel/spans/*.jsonl`.
//!
//! Python hands the files to DuckDB `read_json(..., union_by_name=true)` and
//! keeps rows with `end_time BETWEEN window_start AND now` (ns). This reads the
//! same files line by line under hard caps (KNOWN_DIFFERENCES.md) so a huge or
//! hostile trace file cannot exhaust memory.

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};

use serde_json::{Map, Value};

use crate::clock;

/// Caps Python does not have.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Limits {
    pub max_files: usize,
    pub max_file_bytes: u64,
    pub max_total_bytes: u64,
    pub max_line_bytes: usize,
    pub max_spans: usize,
}

impl Default for Limits {
    fn default() -> Self {
        Self {
            // 90 days of hourly partitions plus slack.
            max_files: 2_400,
            max_file_bytes: 64 * 1024 * 1024,
            max_total_bytes: 256 * 1024 * 1024,
            max_line_bytes: 4 * 1024 * 1024,
            max_spans: 500_000,
        }
    }
}

/// The attribute keys the aggregates read (everything else is dropped to save memory).
pub const ATTR_KEYS: [&str; 17] = [
    "gen_ai.operation.name",
    "gen_ai.provider.name",
    "gen_ai.request.model",
    "gen_ai.tool.name",
    "gen_ai.conversation.id",
    "gen_ai.agent.name",
    "run_id",
    "gen_ai.usage.input_tokens",
    "gen_ai.usage.output_tokens",
    "gen_ai.usage.cache_read.input_tokens",
    "gen_ai.usage.cache_write.input_tokens",
    "gen_ai.usage.estimated_cost_usd",
    "gen_ai.usage.cost.input_usd",
    "gen_ai.usage.cost.output_usd",
    "gen_ai.usage.cost.cache_read_usd",
    "gen_ai.usage.cost.cache_write_usd",
    "gen_ai.usage.reasoning_tokens",
];

/// One span inside the window, with the attributes of `ATTR_KEYS` cast to text
/// the way `attributes::MAP(VARCHAR, VARCHAR)` does.
#[derive(Debug, Clone, Default)]
pub struct Span {
    pub name: String,
    pub trace_id: String,
    pub span_id: String,
    pub start_ns: i64,
    pub end_ns: i64,
    pub duration_ms: Option<f64>,
    pub status: Option<String>,
    pub attrs: HashMap<&'static str, String>,
}

impl Span {
    pub fn attr(&self, key: &str) -> Option<&str> {
        self.attrs.get(key).map(String::as_str)
    }

    pub fn is_error(&self) -> bool {
        self.status.as_deref() == Some("ERROR")
    }

    pub fn is_turn(&self) -> bool {
        self.name.starts_with("agent_run")
    }

    pub fn is_tool(&self) -> bool {
        self.name.starts_with("execute_tool")
    }

    pub fn is_llm(&self) -> bool {
        !self.is_turn()
            && (self.name.starts_with("chat")
                || self.name.starts_with("summarization_llm_call")
                || self.name.starts_with("title_generation")
                || matches!(
                    self.attr("gen_ai.operation.name"),
                    Some("chat" | "summarization" | "title_generation")
                ))
    }

    /// `try_cast(attributes[key] AS BIGINT)`: NULL (None) when absent or not an integer.
    pub fn int_attr(&self, key: &str) -> Option<i64> {
        self.attr(key)
            .and_then(|text| text.trim().parse::<i64>().ok())
    }

    /// `try_cast(attributes[key] AS DOUBLE)`.
    pub fn float_attr(&self, key: &str) -> Option<f64> {
        self.attr(key)
            .and_then(|text| text.trim().parse::<f64>().ok())
            .filter(|value| value.is_finite())
    }
}

/// Sorted `*.jsonl` files of `dir` whose stem compares `>=` the window start's
/// `%Y-%m-%d-%H` key. Missing dir: empty. Directories named `*.jsonl` are skipped.
/// Past `max_files` the oldest are dropped.
pub fn candidate_files(dir: &Path, window_start_micros: i64, limits: &Limits) -> Vec<PathBuf> {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return Vec::new();
    };
    let cutoff_key = clock::partition_key(window_start_micros);
    let mut files: Vec<PathBuf> = entries
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .and_then(|name| name.strip_suffix(".jsonl"))
                .is_some_and(|stem| stem >= cutoff_key.as_str())
        })
        .filter(|path| path.is_file())
        .collect();
    files.sort();
    let excess = files.len().saturating_sub(limits.max_files);
    files.drain(..excess);
    files
}

enum Next {
    Eof,
    Complete,
    TooLong,
}

/// `read_until(b'\n')` that stops buffering past `max` bytes (the rest of the
/// line is consumed and discarded). `consumed` counts every byte read.
fn read_line_bounded<R: BufRead>(
    reader: &mut R,
    buf: &mut Vec<u8>,
    max: usize,
    consumed: &mut u64,
) -> std::io::Result<Next> {
    buf.clear();
    let mut too_long = false;
    let mut read_any = false;
    loop {
        let chunk = reader.fill_buf()?;
        if chunk.is_empty() {
            return Ok(match (read_any, too_long) {
                (false, _) => Next::Eof,
                (true, true) => Next::TooLong,
                (true, false) => Next::Complete,
            });
        }
        read_any = true;
        let newline = chunk.iter().position(|byte| *byte == b'\n');
        let part = newline.and_then(|at| chunk.get(..=at)).unwrap_or(chunk);
        let take = part.len();
        if !too_long {
            if buf.len().saturating_add(take) > max {
                too_long = true;
                buf.clear();
            } else {
                buf.extend_from_slice(part);
            }
        }
        reader.consume(take);
        *consumed += take as u64;
        if newline.is_some() {
            return Ok(if too_long {
                Next::TooLong
            } else {
                Next::Complete
            });
        }
    }
}

fn attr_text(value: &Value) -> Option<String> {
    match value {
        Value::Null => None,
        Value::String(text) => Some(text.clone()),
        Value::Bool(flag) => Some(flag.to_string()),
        Value::Number(number) => Some(number.to_string()),
        other => serde_json::to_string(other).ok(),
    }
}

fn str_field(record: &Map<String, Value>, key: &str) -> Option<String> {
    record.get(key).and_then(Value::as_str).map(str::to_owned)
}

/// Read every span of `files` that ended in `start_ns..=end_ns`, handing each
/// record to `visit` (return `false` to stop). Lines that are not JSON objects
/// or have no integer `end_time` are skipped, as are over-long lines.
pub fn for_each_record<F>(
    files: &[PathBuf],
    start_ns: i64,
    end_ns: i64,
    limits: &Limits,
    mut visit: F,
) where
    F: FnMut(&Map<String, Value>, i64) -> bool,
{
    let mut total: u64 = 0;
    let mut kept: usize = 0;
    let mut buf = Vec::new();
    for path in files {
        // Runs on the blocking pool (core::blocking), never on the async runtime.
        let Ok(file) = std::fs::OpenOptions::new().read(true).open(path) else {
            continue;
        };
        let mut reader = BufReader::new(file.take(limits.max_file_bytes));
        let mut file_bytes: u64 = 0;
        loop {
            if total >= limits.max_total_bytes {
                return;
            }
            let before = file_bytes;
            let line = read_line_bounded(
                &mut reader,
                &mut buf,
                limits.max_line_bytes,
                &mut file_bytes,
            );
            total += file_bytes - before;
            match line {
                Ok(Next::Complete) => {}
                Ok(Next::TooLong) => continue,
                Ok(Next::Eof) | Err(_) => break,
            }
            let Ok(Value::Object(record)) = serde_json::from_slice::<Value>(&buf) else {
                continue;
            };
            let Some(end) = record.get("end_time").and_then(Value::as_i64) else {
                continue;
            };
            if end < start_ns || end > end_ns {
                continue;
            }
            if kept >= limits.max_spans {
                return;
            }
            kept += 1;
            if !visit(&record, end) {
                return;
            }
        }
    }
}

/// Spans of the window in compact form, for the aggregates.
pub fn read_spans(files: &[PathBuf], start_ns: i64, end_ns: i64, limits: &Limits) -> Vec<Span> {
    let mut spans = Vec::new();
    for_each_record(files, start_ns, end_ns, limits, |record, end| {
        let mut attrs = HashMap::new();
        if let Some(Value::Object(source)) = record.get("attributes") {
            for key in ATTR_KEYS {
                if let Some(text) = source.get(key).and_then(attr_text) {
                    attrs.insert(key, text);
                }
            }
        }
        spans.push(Span {
            name: str_field(record, "name").unwrap_or_default(),
            trace_id: str_field(record, "trace_id").unwrap_or_default(),
            span_id: str_field(record, "span_id").unwrap_or_default(),
            start_ns: record
                .get("start_time")
                .and_then(Value::as_i64)
                .unwrap_or(0),
            end_ns: end,
            duration_ms: record.get("duration_ms").and_then(Value::as_f64),
            status: str_field(record, "status"),
            attrs,
        });
        true
    });
    spans
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::disallowed_methods
)]
mod tests {
    use super::*;
    use std::io::Cursor;

    fn limits() -> Limits {
        Limits::default()
    }

    fn write(dir: &Path, name: &str, text: &str) {
        std::fs::write(dir.join(name), text).unwrap();
    }

    fn line(name: &str, end: i64) -> String {
        format!(
            "{{\"name\":\"{name}\",\"trace_id\":\"0xaa\",\"span_id\":\"0x01\",\"start_time\":{},\"end_time\":{end},\"duration_ms\":5,\"status\":\"OK\",\"attributes\":{{\"gen_ai.usage.input_tokens\":7,\"gen_ai.request.model\":\"m\",\"other\":1,\"gen_ai.tool.name\":null}}}}\n",
            end - 5
        )
    }

    #[test]
    fn candidate_files_compare_the_stem_and_sort() {
        let dir = tempfile::tempdir().unwrap();
        for name in [
            "2026-10-30-11.jsonl",
            "2026-10-30-09.jsonl",
            "2026-10-30-10.jsonl",
            "2026-10-30-12.txt",
            "notes.jsonl",
        ] {
            write(dir.path(), name, "");
        }
        std::fs::create_dir(dir.path().join("2026-10-31-00.jsonl")).unwrap();
        // 2026-10-30T10:30Z
        let start = 1_793_356_800 * 1_000_000 + 1_800 * 1_000_000;
        let files = candidate_files(dir.path(), start, &limits());
        let names: Vec<_> = files
            .iter()
            .map(|p| p.file_name().unwrap().to_str().unwrap().to_owned())
            .collect();
        assert_eq!(names, ["2026-10-30-11.jsonl", "notes.jsonl"]);
    }

    #[test]
    fn candidate_files_missing_dir_is_empty() {
        let dir = tempfile::tempdir().unwrap();
        assert!(candidate_files(&dir.path().join("none"), 0, &limits()).is_empty());
    }

    #[test]
    fn candidate_files_keep_the_newest_past_the_cap() {
        let dir = tempfile::tempdir().unwrap();
        for hour in 0..5 {
            write(dir.path(), &format!("2026-10-30-{hour:02}.jsonl"), "");
        }
        let capped = Limits {
            max_files: 2,
            ..limits()
        };
        let files = candidate_files(dir.path(), 0, &capped);
        assert_eq!(files.len(), 2);
        assert!(files[0].ends_with("2026-10-30-03.jsonl"));
        assert!(files[1].ends_with("2026-10-30-04.jsonl"));
    }

    #[test]
    fn spans_are_filtered_by_end_time_inclusive() {
        let dir = tempfile::tempdir().unwrap();
        let text = format!(
            "{}{}{}{}not json\n[1]\n{{\"name\":\"x\"}}\n\n{{\"end_time\":null}}\n",
            line("a", 99),
            line("b", 100),
            line("c", 200),
            line("d", 201)
        );
        write(dir.path(), "2026-10-30-10.jsonl", &text);
        let files = candidate_files(dir.path(), 0, &limits());
        let spans = read_spans(&files, 100, 200, &limits());
        let names: Vec<_> = spans.iter().map(|s| s.name.as_str()).collect();
        assert_eq!(names, ["b", "c"]);
    }

    #[test]
    fn attributes_keep_only_known_keys_as_text_and_drop_nulls() {
        let dir = tempfile::tempdir().unwrap();
        write(dir.path(), "2026-10-30-10.jsonl", &line("chat", 100));
        let files = candidate_files(dir.path(), 0, &limits());
        let spans = read_spans(&files, 0, 1_000, &limits());
        let span = spans.first().unwrap();
        assert_eq!(span.attr("gen_ai.usage.input_tokens"), Some("7"));
        assert_eq!(span.int_attr("gen_ai.usage.input_tokens"), Some(7));
        assert_eq!(span.attr("gen_ai.request.model"), Some("m"));
        assert_eq!(span.attr("other"), None);
        assert_eq!(span.attr("gen_ai.tool.name"), None);
        assert_eq!(span.duration_ms, Some(5.0));
        assert_eq!(span.start_ns, 95);
    }

    #[test]
    fn try_cast_semantics() {
        let mut span = Span::default();
        span.attrs
            .insert("gen_ai.usage.input_tokens", "12.5".into());
        span.attrs
            .insert("gen_ai.usage.output_tokens", " 9 ".into());
        span.attrs
            .insert("gen_ai.usage.estimated_cost_usd", "0.25".into());
        span.attrs
            .insert("gen_ai.usage.cost.input_usd", "nan".into());
        assert_eq!(span.int_attr("gen_ai.usage.input_tokens"), None);
        assert_eq!(span.int_attr("gen_ai.usage.output_tokens"), Some(9));
        assert_eq!(
            span.float_attr("gen_ai.usage.estimated_cost_usd"),
            Some(0.25)
        );
        assert_eq!(span.float_attr("gen_ai.usage.cost.input_usd"), None);
        assert_eq!(span.float_attr("missing"), None);
    }

    #[test]
    fn span_classes_follow_the_name_and_operation() {
        let named = |name: &str| Span {
            name: name.into(),
            ..Span::default()
        };
        assert!(named("agent_run Coder").is_turn());
        assert!(!named("agent_run Coder").is_llm());
        assert!(named("execute_tool read").is_tool());
        for name in ["chat gpt", "summarization_llm_call", "title_generation"] {
            assert!(named(name).is_llm(), "{name}");
        }
        assert!(!named("Chat").is_llm());
        let mut by_operation = named("custom");
        by_operation
            .attrs
            .insert("gen_ai.operation.name", "summarization".into());
        assert!(by_operation.is_llm());
        by_operation
            .attrs
            .insert("gen_ai.operation.name", "embeddings".into());
        assert!(!by_operation.is_llm());
        let mut turn = named("agent_run x");
        turn.attrs.insert("gen_ai.operation.name", "chat".into());
        assert!(!turn.is_llm());
    }

    #[test]
    fn over_long_lines_are_skipped_and_the_next_line_is_read() {
        let dir = tempfile::tempdir().unwrap();
        let huge = format!("{{\"name\":\"{}\"}}\n", "x".repeat(300));
        write(
            dir.path(),
            "2026-10-30-10.jsonl",
            &format!("{huge}{}", line("kept", 100)),
        );
        let capped = Limits {
            max_line_bytes: 256,
            ..limits()
        };
        let files = candidate_files(dir.path(), 0, &capped);
        let spans = read_spans(&files, 0, 1_000, &capped);
        assert_eq!(spans.len(), 1);
        assert_eq!(spans[0].name, "kept");
    }

    #[test]
    fn a_line_exactly_at_the_cap_is_kept() {
        let mut consumed = 0;
        let mut buf = Vec::new();
        let mut reader = Cursor::new(b"abcd\nef".to_vec());
        assert!(matches!(
            read_line_bounded(&mut reader, &mut buf, 5, &mut consumed).unwrap(),
            Next::Complete
        ));
        assert_eq!(buf, b"abcd\n");
        assert!(matches!(
            read_line_bounded(&mut reader, &mut buf, 5, &mut consumed).unwrap(),
            Next::Complete
        ));
        assert_eq!(buf, b"ef");
        assert!(matches!(
            read_line_bounded(&mut reader, &mut buf, 5, &mut consumed).unwrap(),
            Next::Eof
        ));
        assert_eq!(consumed, 7);
        let mut reader = Cursor::new(b"abcde\nxy\n".to_vec());
        assert!(matches!(
            read_line_bounded(&mut reader, &mut buf, 5, &mut consumed).unwrap(),
            Next::TooLong
        ));
        assert!(matches!(
            read_line_bounded(&mut reader, &mut buf, 5, &mut consumed).unwrap(),
            Next::Complete
        ));
    }

    #[test]
    fn file_total_and_span_caps_stop_the_scan() {
        let dir = tempfile::tempdir().unwrap();
        let one = line("a", 100);
        write(dir.path(), "2026-10-30-10.jsonl", &one.repeat(10));
        write(dir.path(), "2026-10-30-11.jsonl", &one.repeat(10));
        let files = candidate_files(dir.path(), 0, &limits());

        let spans_cap = Limits {
            max_spans: 3,
            ..limits()
        };
        assert_eq!(read_spans(&files, 0, 1_000, &spans_cap).len(), 3);

        let per_file = Limits {
            max_file_bytes: one.len() as u64 * 2,
            ..limits()
        };
        assert_eq!(read_spans(&files, 0, 1_000, &per_file).len(), 4);

        let total = Limits {
            max_total_bytes: one.len() as u64 * 12,
            ..limits()
        };
        assert_eq!(read_spans(&files, 0, 1_000, &total).len(), 12);
    }

    #[test]
    fn unreadable_files_are_skipped() {
        let files = [PathBuf::from("does-not-exist.jsonl")];
        assert!(read_spans(&files, 0, 1_000, &limits()).is_empty());
    }
}
