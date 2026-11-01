//! Port of `list_traces_page` and `get_trace` in app/services/observability_service.py.

use std::collections::HashMap;
use std::path::PathBuf;

use serde_json::{json, Map, Value};

use crate::scan::{self, Limits, Span};
use crate::summary::round_to;

const INPUT: &str = "gen_ai.usage.input_tokens";
const OUTPUT: &str = "gen_ai.usage.output_tokens";
const CACHE_READ: &str = "gen_ai.usage.cache_read.input_tokens";
const COST: &str = "gen_ai.usage.estimated_cost_usd";

#[derive(Default)]
struct RunUsage {
    llm_calls: i64,
    tool_calls: i64,
    error_spans: i64,
    input: i64,
    output: i64,
    cached: i64,
    cost: f64,
}

struct RunKeys {
    count: usize,
    only_run_id: Option<String>,
}

/// One page of `agent_run` rows, newest `end_time` first, and the total number of runs.
pub fn list_page(spans: &[Span], limit: usize, offset: usize) -> (Vec<Value>, usize) {
    let runs: Vec<&Span> = spans.iter().filter(|s| s.is_turn()).collect();
    let total = runs.len();

    let mut keys: HashMap<&str, RunKeys> = HashMap::new();
    for run in &runs {
        let entry = keys.entry(run.trace_id.as_str()).or_insert(RunKeys {
            count: 0,
            only_run_id: None,
        });
        entry.count += 1;
        // Python takes max(attributes['run_id']) but only reads it when the trace
        // has exactly one run, where the maximum is that run's own id.
        if let Some(run_id) = run.attr("run_id") {
            entry.only_run_id = Some(run_id.to_owned());
        }
    }

    let mut usage: HashMap<(&str, String), RunUsage> = HashMap::new();
    for span in spans {
        let Some(run_keys) = keys.get(span.trace_id.as_str()) else {
            continue;
        };
        let run_id = span.attr("run_id").map(str::to_owned).or_else(|| {
            if run_keys.count == 1 {
                run_keys.only_run_id.clone()
            } else {
                None
            }
        });
        let Some(run_id) = run_id else {
            continue;
        };
        let row = usage.entry((span.trace_id.as_str(), run_id)).or_default();
        if span.is_llm() {
            row.llm_calls += 1;
            row.input = row.input.saturating_add(span.int_attr(INPUT).unwrap_or(0));
            row.output = row
                .output
                .saturating_add(span.int_attr(OUTPUT).unwrap_or(0));
            row.cached = row
                .cached
                .saturating_add(span.int_attr(CACHE_READ).unwrap_or(0));
            row.cost += span.float_attr(COST).unwrap_or(0.0);
        }
        if span.is_tool() {
            row.tool_calls += 1;
        }
        if span.is_error() {
            row.error_spans += 1;
        }
    }

    let mut ordered = runs;
    ordered.sort_by_key(|run| std::cmp::Reverse(run.end_ns));
    let items = ordered
        .into_iter()
        .skip(offset)
        .take(limit)
        .map(|run| {
            let run_id = run.attr("run_id");
            let none = RunUsage::default();
            let counts = run_id
                .and_then(|id| usage.get(&(run.trace_id.as_str(), id.to_owned())))
                .unwrap_or(&none);
            let provider = run.attr("gen_ai.provider.name");
            let model = run.attr("gen_ai.request.model");
            let provider_model = match (provider, model) {
                (Some(provider), Some(model)) => Some(format!("{provider}:{model}")),
                _ => None,
            };
            json!({
                "trace_id": run.trace_id,
                "span_id": run.span_id,
                "run_id": run_id,
                "session_id": run.attr("gen_ai.conversation.id"),
                "agent_name": run.attr("gen_ai.agent.name"),
                "provider": provider,
                "model": model,
                "provider_model": provider_model,
                "start_ms": run.start_ns / 1_000_000,
                "end_ms": run.end_ns / 1_000_000,
                "duration_ms": round_to(run.duration_ms.unwrap_or(0.0), 1),
                "input_tokens": counts.input,
                "output_tokens": counts.output,
                "cached_tokens": counts.cached,
                "estimated_cost_usd": round_to(counts.cost, 8),
                "tool_calls": counts.tool_calls,
                "llm_calls": counts.llm_calls,
                "error": run.is_error() || counts.error_spans > 0,
            })
        })
        .collect();
    (items, total)
}

/// The id the exporter wrote: lower-cased, `0x` prefix added when missing.
pub fn normalise_trace_id(raw: &str) -> String {
    let lowered = raw.to_lowercase();
    if lowered.starts_with("0x") {
        lowered
    } else {
        format!("0x{lowered}")
    }
}

struct DetailRow {
    start_ns: i64,
    stored_trace_id: String,
    body: Value,
}

/// Every span of the trace in the window, `start_time` ascending; `None` when there is none.
pub fn get_trace(
    files: &[PathBuf],
    start_ns: i64,
    end_ns: i64,
    limits: &Limits,
    trace_id: &str,
) -> Option<Value> {
    let wanted = normalise_trace_id(trace_id);
    let mut rows: Vec<DetailRow> = Vec::new();
    scan::for_each_record(files, start_ns, end_ns, limits, |record, end| {
        let stored = record
            .get("trace_id")
            .and_then(Value::as_str)
            .unwrap_or_default();
        if stored.to_lowercase() != wanted {
            return true;
        }
        let text = |key: &str| record.get(key).and_then(Value::as_str);
        let start = record
            .get("start_time")
            .and_then(Value::as_i64)
            .unwrap_or(0);
        let attributes: Map<String, Value> = match record.get("attributes") {
            Some(Value::Object(map)) => map
                .iter()
                .filter(|(_, value)| !value.is_null())
                .map(|(key, value)| (key.clone(), value.clone()))
                .collect(),
            _ => Map::new(),
        };
        rows.push(DetailRow {
            start_ns: start,
            stored_trace_id: stored.to_owned(),
            body: json!({
                "span_id": text("span_id").unwrap_or_default(),
                "parent_span_id": text("parent_id"),
                "trace_id": stored,
                "name": text("name").unwrap_or_default(),
                "kind": text("kind").unwrap_or("INTERNAL"),
                "start_ms": start / 1_000_000,
                "end_ms": end / 1_000_000,
                "duration_ms": round_to(
                    record.get("duration_ms").and_then(Value::as_f64).unwrap_or(0.0),
                    1,
                ),
                "status": text("status").unwrap_or("UNSET"),
                "attributes": attributes,
            }),
        });
        true
    });
    rows.sort_by_key(|row| row.start_ns);
    let first = rows.first()?.stored_trace_id.clone();
    let spans: Vec<Value> = rows.into_iter().map(|row| row.body).collect();
    Some(json!({"trace_id": first, "spans": spans}))
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

    fn span(name: &str, trace: &str, end: i64, attrs: &[(&'static str, &str)]) -> Span {
        let mut span = Span {
            name: name.into(),
            trace_id: trace.into(),
            span_id: format!("0x{end}"),
            start_ns: end - 1_000_000,
            end_ns: end,
            duration_ms: Some(1.0),
            status: Some("OK".into()),
            ..Span::default()
        };
        for (key, value) in attrs {
            span.attrs.insert(key, (*value).to_owned());
        }
        span
    }

    fn chat(trace: &str, end: i64, run: Option<&'static str>, input: &str) -> Span {
        let mut attrs = vec![
            (INPUT, input),
            (OUTPUT, "1"),
            (CACHE_READ, "2"),
            (COST, "0.5"),
        ];
        if let Some(run) = run {
            attrs.push(("run_id", run));
        }
        span("chat m", trace, end, &attrs)
    }

    #[test]
    fn rows_are_newest_first_with_a_total_and_pages() {
        let spans = vec![
            span("agent_run A", "0xa", 1_000_000_000, &[("run_id", "r1")]),
            span("agent_run B", "0xb", 3_000_000_000, &[("run_id", "r2")]),
            span("agent_run C", "0xc", 2_000_000_000, &[("run_id", "r3")]),
            span("chat orphan", "0xd", 4_000_000_000, &[]),
        ];
        let (items, total) = list_page(&spans, 2, 0);
        assert_eq!(total, 3);
        let ids: Vec<_> = items
            .iter()
            .map(|i| i["trace_id"].as_str().unwrap())
            .collect();
        assert_eq!(ids, ["0xb", "0xc"]);
        let (items, total) = list_page(&spans, 2, 2);
        assert_eq!((items.len(), total), (1, 3));
        assert_eq!(items[0]["trace_id"], "0xa");
        let (items, total) = list_page(&spans, 2, 50);
        assert_eq!((items.len(), total), (0, 3));
    }

    #[test]
    fn usage_is_joined_by_trace_and_run_id() {
        let spans = vec![
            span("agent_run A", "0xa", 9_000_000_000, &[("run_id", "r1")]),
            span("agent_run B", "0xa", 8_000_000_000, &[("run_id", "r2")]),
            chat("0xa", 1_000_000_000, Some("r1"), "10"),
            chat("0xa", 2_000_000_000, Some("r2"), "100"),
            chat("0xa", 3_000_000_000, Some("r2"), "100"),
            // no run_id in a two-run trace: in no row
            chat("0xa", 4_000_000_000, None, "5000"),
            span(
                "execute_tool read",
                "0xa",
                5_000_000_000,
                &[("run_id", "r1")],
            ),
        ];
        let (items, _) = list_page(&spans, 10, 0);
        assert_eq!(items[0]["run_id"], "r1");
        assert_eq!(items[0]["input_tokens"], 10);
        assert_eq!(items[0]["llm_calls"], 1);
        assert_eq!(items[0]["tool_calls"], 1);
        assert_eq!(items[0]["cached_tokens"], 2);
        assert_eq!(items[1]["run_id"], "r2");
        assert_eq!(items[1]["input_tokens"], 200);
        assert_eq!(items[1]["estimated_cost_usd"], 1.0);
        assert_eq!(items[1]["llm_calls"], 2);
    }

    #[test]
    fn a_child_without_run_id_joins_the_only_run() {
        let spans = vec![
            span("agent_run A", "0xa", 9_000_000_000, &[("run_id", "r1")]),
            chat("0xa", 1_000_000_000, None, "7"),
        ];
        let (items, _) = list_page(&spans, 10, 0);
        assert_eq!(items[0]["input_tokens"], 7);
    }

    #[test]
    fn a_run_without_run_id_has_zero_usage_and_null_fields() {
        let spans = vec![
            span("agent_run A", "0xa", 9_000_000_000, &[]),
            chat("0xa", 1_000_000_000, Some("rx"), "7"),
        ];
        let (items, _) = list_page(&spans, 10, 0);
        assert_eq!(items[0]["run_id"], Value::Null);
        assert_eq!(items[0]["session_id"], Value::Null);
        assert_eq!(items[0]["provider_model"], Value::Null);
        assert_eq!(items[0]["input_tokens"], 0);
        assert_eq!(items[0]["error"], false);
    }

    #[test]
    fn error_is_the_root_status_or_any_errored_span_of_the_run() {
        let mut failed_child = chat("0xa", 1_000_000_000, Some("r1"), "1");
        failed_child.status = Some("ERROR".into());
        let mut failed_root = span("agent_run B", "0xb", 7_000_000_000, &[("run_id", "r2")]);
        failed_root.status = Some("ERROR".into());
        let spans = vec![
            span("agent_run A", "0xa", 9_000_000_000, &[("run_id", "r1")]),
            failed_child,
            failed_root,
            span("agent_run C", "0xc", 5_000_000_000, &[("run_id", "r3")]),
        ];
        let (items, _) = list_page(&spans, 10, 0);
        let errors: Vec<_> = items
            .iter()
            .map(|i| i["error"].as_bool().unwrap())
            .collect();
        assert_eq!(errors, [true, true, false]);
    }

    #[test]
    fn provider_model_needs_both_halves_and_times_are_epoch_ms() {
        let spans = vec![
            span(
                "agent_run A",
                "0xa",
                9_000_000_000,
                &[
                    ("run_id", "r1"),
                    ("gen_ai.provider.name", "p"),
                    ("gen_ai.request.model", "m"),
                    ("gen_ai.conversation.id", "s"),
                    ("gen_ai.agent.name", "Coder"),
                ],
            ),
            span(
                "agent_run B",
                "0xb",
                1_000_000_000,
                &[("run_id", "r2"), ("gen_ai.provider.name", "p")],
            ),
        ];
        let (items, _) = list_page(&spans, 10, 0);
        assert_eq!(items[0]["provider_model"], "p:m");
        assert_eq!(items[0]["session_id"], "s");
        assert_eq!(items[0]["agent_name"], "Coder");
        assert_eq!(items[0]["end_ms"], 9_000);
        assert_eq!(items[0]["start_ms"], 8_999);
        assert_eq!(items[1]["provider_model"], Value::Null);
        assert_eq!(items[1]["provider"], "p");
    }

    #[test]
    fn trace_ids_are_lower_cased_and_prefixed() {
        assert_eq!(normalise_trace_id("ABCD"), "0xabcd");
        assert_eq!(normalise_trace_id("0xABCD"), "0xabcd");
        assert_eq!(normalise_trace_id("0XABCD"), "0xabcd");
        assert_eq!(normalise_trace_id(""), "0x");
    }

    fn write_spans(dir: &std::path::Path, lines: &[&str]) -> Vec<PathBuf> {
        let path = dir.join("2026-10-30-10.jsonl");
        std::fs::write(&path, lines.join("\n") + "\n").unwrap();
        vec![path]
    }

    #[test]
    fn detail_orders_by_start_strips_null_attributes_and_defaults_fields() {
        let dir = tempfile::tempdir().unwrap();
        let files = write_spans(
            dir.path(),
            &[
                r#"{"name":"b","trace_id":"0xAB","span_id":"0x2","parent_id":"0x1","start_time":3000000000,"end_time":4000000000,"duration_ms":12.34,"status":"ERROR","kind":"CLIENT","attributes":{"k":1,"gone":null,"s":"x","o":{"a":[1]}}}"#,
                r#"{"name":"a","trace_id":"0xab","span_id":"0x1","parent_id":null,"start_time":1000000000,"end_time":5000000000,"duration_ms":4000,"attributes":null}"#,
                r#"{"name":"other","trace_id":"0xcd","span_id":"0x3","start_time":1,"end_time":2,"attributes":{}}"#,
                r#"{"name":"no end","trace_id":"0xab","span_id":"0x4","start_time":1,"end_time":null}"#,
            ],
        );
        let body = get_trace(&files, 0, 10_000_000_000, &Limits::default(), "0XAB").unwrap();
        assert_eq!(body["trace_id"], "0xab");
        let spans = body["spans"].as_array().unwrap();
        assert_eq!(spans.len(), 2);
        assert_eq!(spans[0]["name"], "a");
        assert_eq!(spans[0]["parent_span_id"], Value::Null);
        assert_eq!(spans[0]["kind"], "INTERNAL");
        assert_eq!(spans[0]["status"], "UNSET");
        assert_eq!(spans[0]["attributes"], json!({}));
        assert_eq!(spans[0]["start_ms"], 1_000);
        assert_eq!(spans[0]["end_ms"], 5_000);
        assert_eq!(spans[1]["parent_span_id"], "0x1");
        assert_eq!(spans[1]["trace_id"], "0xAB");
        assert_eq!(spans[1]["duration_ms"], 12.3);
        assert_eq!(
            spans[1]["attributes"],
            json!({"k": 1, "s": "x", "o": {"a": [1]}})
        );
    }

    #[test]
    fn detail_of_an_unknown_trace_or_outside_the_window_is_none() {
        let dir = tempfile::tempdir().unwrap();
        let files = write_spans(
            dir.path(),
            &[r#"{"name":"a","trace_id":"0xab","span_id":"0x1","start_time":1,"end_time":50}"#],
        );
        let limits = Limits::default();
        assert!(get_trace(&files, 0, 100, &limits, "ab").is_some());
        assert!(get_trace(&files, 0, 100, &limits, "cd").is_none());
        assert!(get_trace(&files, 51, 100, &limits, "ab").is_none());
        assert!(get_trace(&[], 0, 100, &limits, "ab").is_none());
    }
}
