//! Port of `summarize` and its DuckDB queries in app/services/observability_service.py.

use std::collections::HashMap;
use std::hash::Hash;

use serde_json::{json, Value};

use crate::clock::{self, MICROS_PER_DAY, MICROS_PER_HOUR};
use crate::scan::Span;

const INPUT: &str = "gen_ai.usage.input_tokens";
const OUTPUT: &str = "gen_ai.usage.output_tokens";
const CACHE_READ: &str = "gen_ai.usage.cache_read.input_tokens";
const CACHE_WRITE: &str = "gen_ai.usage.cache_write.input_tokens";
const COST: &str = "gen_ai.usage.estimated_cost_usd";
const PROVIDER: &str = "gen_ai.provider.name";
const MODEL: &str = "gen_ai.request.model";
const MAX_BUCKETS: i64 = 200;

/// Python's `round(value, digits)`: correctly rounded decimal, ties to even.
pub fn round_to(value: f64, digits: usize) -> f64 {
    format!("{value:.digits$}").parse().unwrap_or(value)
}

/// DuckDB `quantile_cont`: linear interpolation between the closest ranks.
pub fn quantile_cont(values: &[f64], q: f64) -> Option<f64> {
    if values.is_empty() {
        return None;
    }
    let mut sorted = values.to_vec();
    sorted.sort_by(f64::total_cmp);
    let position = q * (sorted.len() - 1) as f64;
    let low = position.floor();
    let high = position.ceil();
    let at = |index: f64| sorted.get(index as usize).copied().unwrap_or(0.0);
    let (lo, hi) = (at(low), at(high));
    Some(lo + (hi - lo) * (position - low))
}

/// `_percent`: share of `total` with one decimal, 0 when there is no total.
pub fn percent(part: f64, total: f64) -> f64 {
    if total <= 0.0 {
        return 0.0;
    }
    round_to(part / total * 100.0, 1)
}

/// `_cache_percent`: hit rate with cached bounded to `0..input`.
pub fn cache_percent(cached: i64, input: i64) -> f64 {
    percent(cached.max(0).min(input.max(0)) as f64, input as f64)
}

/// `_usd_per_mtok`: blended cost per million tokens, 0 without traffic.
pub fn usd_per_mtok(cost: f64, tokens: i64) -> f64 {
    if tokens <= 0 {
        return 0.0;
    }
    round_to(cost / (tokens as f64 / 1_000_000.0), 6)
}

fn quantile_or_zero(values: &[f64], q: f64) -> f64 {
    quantile_cont(values, q).unwrap_or(0.0)
}

/// `OTEL_SPAN_SAMPLE_RATIO` clamped to 0..1; unparsable gives 1.0.
pub fn sample_ratio(raw: Option<&str>) -> f64 {
    match raw {
        None => 1.0,
        Some(text) => match text.trim().parse::<f64>() {
            Ok(value) if !value.is_nan() => value.clamp(0.0, 1.0),
            _ => 1.0,
        },
    }
}

fn group_by<'a, K: Eq + Hash + Clone>(
    spans: impl IntoIterator<Item = &'a Span>,
    key: impl Fn(&Span) -> K,
) -> Vec<(K, Vec<&'a Span>)> {
    let mut index: HashMap<K, usize> = HashMap::new();
    let mut groups: Vec<(K, Vec<&Span>)> = Vec::new();
    for span in spans {
        let key = key(span);
        match index.get(&key) {
            Some(&at) => {
                if let Some((_, members)) = groups.get_mut(at) {
                    members.push(span);
                }
            }
            None => {
                index.insert(key.clone(), groups.len());
                groups.push((key, vec![span]));
            }
        }
    }
    groups
}

fn sum_int(spans: &[&Span], key: &str) -> i64 {
    spans
        .iter()
        .filter_map(|span| span.int_attr(key))
        .fold(0_i64, i64::saturating_add)
}

fn sum_float(spans: &[&Span], key: &str) -> f64 {
    spans.iter().filter_map(|span| span.float_attr(key)).sum()
}

fn durations(spans: &[&Span]) -> Vec<f64> {
    spans.iter().filter_map(|span| span.duration_ms).collect()
}

fn avg_or_zero(values: &[f64]) -> f64 {
    if values.is_empty() {
        0.0
    } else {
        values.iter().sum::<f64>() / values.len() as f64
    }
}

fn or_unknown(span: &Span, key: &str) -> String {
    span.attr(key).unwrap_or("unknown").to_owned()
}

fn bucket_size(window_start: i64, window_end: i64) -> &'static str {
    if window_end - window_start <= MICROS_PER_DAY {
        "hour"
    } else {
        "day"
    }
}

/// `_empty_summary`, serialised.
pub fn empty_summary(window_start: i64, window_end: i64, ratio: f64) -> Value {
    let mut body = summary_body(window_start, window_end, ratio, &[]);
    // No file in the window: Python never runs the queries, so no dense grid either.
    if let Some(map) = body.as_object_mut() {
        map.insert("time_series".to_owned(), json!([]));
    }
    body
}

fn micros(span: &Span) -> i64 {
    span.end_ns / 1_000
}

/// The `to_dict()` of `ObservabilitySummary` over `spans` (already window-filtered).
pub fn summary_body(window_start: i64, window_end: i64, ratio: f64, spans: &[Span]) -> Value {
    let size = bucket_size(window_start, window_end);
    let hourly = size == "hour";
    let all: Vec<&Span> = spans.iter().collect();
    let turns: Vec<&Span> = spans.iter().filter(|s| s.is_turn()).collect();
    let llm: Vec<&Span> = spans.iter().filter(|s| s.is_llm()).collect();
    let tools: Vec<&Span> = spans.iter().filter(|s| s.is_tool()).collect();

    let failed_turns = turns.iter().filter(|s| s.is_error()).count() as i64;
    let error_spans = all.iter().filter(|s| s.is_error()).count() as i64;
    let input = sum_int(&llm, INPUT);
    let cached = sum_int(&llm, CACHE_READ);
    let cost = round_to(sum_float(&llm, COST), 8);
    let turn_ms = durations(&turns);
    let llm_ms = durations(&llm);
    let tool_ms = durations(&tools);
    let latency = |values: &[f64], q: f64| round_to(quantile_or_zero(values, q), 1);

    let daily_turns: Vec<Value> = {
        let mut days = group_by(turns.iter().copied(), |s| clock::day_key(micros(s)));
        days.sort_by(|a, b| a.0.cmp(&b.0));
        days.iter()
            .map(|(day, members)| {
                let errors = members.iter().filter(|s| s.is_error()).count();
                json!({"day": day, "turns": members.len(), "errors": errors})
            })
            .collect()
    };

    json!({
        "window_start": clock::isoformat(window_start),
        "window_end": clock::isoformat(window_end),
        "sample_ratio": ratio,
        "totals": {
            "turns": turns.len(),
            "llm_calls": llm.len(),
            "tool_calls": tools.len(),
            "input_tokens": input,
            "output_tokens": sum_int(&llm, OUTPUT),
            "cached_tokens": cached,
            "cache_write_tokens": sum_int(&llm, CACHE_WRITE),
            "cache_percent": cache_percent(cached, input),
            "estimated_cost_usd": cost,
            "errors": failed_turns,
            "failed_turns": failed_turns,
            "error_spans": error_spans,
            "error_rate": percent(failed_turns as f64, turns.len() as f64),
        },
        "latency_ms": {
            "turn_p50": latency(&turn_ms, 0.5),
            "turn_p95": latency(&turn_ms, 0.95),
            "llm_p50": latency(&llm_ms, 0.5),
            "llm_p95": latency(&llm_ms, 0.95),
            "tool_p50": latency(&tool_ms, 0.5),
            "tool_p95": latency(&tool_ms, 0.95),
        },
        "daily_turns": daily_turns,
        "time_series": time_series(spans, window_start, window_end, hourly),
        "bucket_size": size,
        "by_model": by_model(&llm),
        "cache_by_step": cache_by_step(&llm),
        "by_tool": by_tool(&tools),
        "tokens_by_model": tokens_by_model(&llm, hourly),
    })
}

fn zero_bucket(key: &str) -> Value {
    json!({
        "bucket_start": key, "turns": 0, "llm_calls": 0, "tool_calls": 0,
        "failed_turns": 0, "error_spans": 0, "input_tokens": 0, "output_tokens": 0,
        "estimated_cost_usd": 0.0, "turn_p95_ms": 0.0,
    })
}

/// Bucket rows from the data, then `_fill_time_series` to a dense grid.
fn time_series(spans: &[Span], window_start: i64, window_end: i64, hourly: bool) -> Vec<Value> {
    let mut sparse: HashMap<String, Value> = HashMap::new();
    for (bucket, members) in group_by(spans, |s| clock::bucket_key(micros(s), hourly)) {
        let turns: Vec<&Span> = members.iter().copied().filter(|s| s.is_turn()).collect();
        let llm: Vec<&Span> = members.iter().copied().filter(|s| s.is_llm()).collect();
        let row = json!({
            "bucket_start": bucket,
            "turns": turns.len(),
            "llm_calls": llm.len(),
            "tool_calls": members.iter().filter(|s| s.is_tool()).count(),
            "failed_turns": turns.iter().filter(|s| s.is_error()).count(),
            "error_spans": members.iter().filter(|s| s.is_error()).count(),
            "input_tokens": sum_int(&llm, INPUT),
            "output_tokens": sum_int(&llm, OUTPUT),
            "estimated_cost_usd": round_to(sum_float(&llm, COST), 8),
            "turn_p95_ms": round_to(quantile_or_zero(&durations(&turns), 0.95), 1),
        });
        sparse.insert(bucket, row);
    }
    let step = if hourly {
        MICROS_PER_HOUR
    } else {
        MICROS_PER_DAY
    };
    let first = clock::floor_bucket(window_start, hourly);
    let last = clock::floor_bucket(window_end, hourly);
    // At most 25 hourly or 91 daily buckets; the cap only bounds the loop.
    (0..MAX_BUCKETS)
        .map(|index| first + index * step)
        .take_while(|cursor| *cursor <= last)
        .map(|cursor| {
            let key = clock::bucket_key(cursor, hourly);
            sparse.remove(&key).unwrap_or_else(|| zero_bucket(&key))
        })
        .collect()
}

fn tokens_by_model(llm: &[&Span], hourly: bool) -> Vec<Value> {
    let mut groups = group_by(llm.iter().copied(), |s| {
        (
            clock::bucket_key(micros(s), hourly),
            or_unknown(s, PROVIDER),
            or_unknown(s, MODEL),
        )
    });
    groups.sort_by(|a, b| a.0.cmp(&b.0));
    groups
        .iter()
        .filter_map(|((bucket, provider, model), members)| {
            let input = sum_int(members, INPUT);
            let output = sum_int(members, OUTPUT);
            if input <= 0 && output <= 0 {
                return None;
            }
            let cached = sum_int(members, CACHE_READ);
            let written = sum_int(members, CACHE_WRITE);
            Some(json!({
                "bucket_start": bucket,
                "provider": provider,
                "model": model,
                "provider_model": format!("{provider}:{model}"),
                "input_tokens": input,
                "output_tokens": output,
                "cached_tokens": cached,
                "cache_write_tokens": written,
                "fresh_input_tokens": (input - cached - written).max(0),
                "cache_percent": cache_percent(cached, input),
                "calls": members.len(),
            }))
        })
        .collect()
}

fn by_model(llm: &[&Span]) -> Vec<Value> {
    let mut rows: Vec<(f64, usize, Value)> = group_by(llm.iter().copied(), |s| {
        (or_unknown(s, PROVIDER), or_unknown(s, MODEL))
    })
    .iter()
    .map(|((provider, model), members)| {
        let calls = members.len();
        let input = sum_int(members, INPUT);
        let output = sum_int(members, OUTPUT);
        let cached = sum_int(members, CACHE_READ);
        let cost = sum_float(members, COST);
        let errors = members.iter().filter(|s| s.is_error()).count();
        let ms = durations(members);
        let row = json!({
            "provider": provider,
            "model": model,
            "provider_model": format!("{provider}:{model}"),
            "calls": calls,
            "input_tokens": input,
            "output_tokens": output,
            "cached_tokens": cached,
            "cache_write_tokens": sum_int(members, CACHE_WRITE),
            "reasoning_tokens": sum_int(members, "gen_ai.usage.reasoning_tokens"),
            "cache_percent": cache_percent(cached, input),
            "estimated_cost_usd": round_to(cost, 8),
            "input_usd": round_to(sum_float(members, "gen_ai.usage.cost.input_usd"), 8),
            "output_usd": round_to(sum_float(members, "gen_ai.usage.cost.output_usd"), 8),
            "cache_read_usd": round_to(sum_float(members, "gen_ai.usage.cost.cache_read_usd"), 8),
            "cache_write_usd": round_to(sum_float(members, "gen_ai.usage.cost.cache_write_usd"), 8),
            "usd_per_mtok": usd_per_mtok(cost, input.saturating_add(output)),
            "errors": errors,
            "error_rate": percent(errors as f64, calls as f64),
            "avg_ms": round_to(avg_or_zero(&ms), 1),
            "p50_ms": round_to(quantile_or_zero(&ms, 0.5), 1),
            "p95_ms": round_to(quantile_or_zero(&ms, 0.95), 1),
        });
        (cost, calls, row)
    })
    .collect();
    rows.sort_by(|a, b| b.0.total_cmp(&a.0).then(b.1.cmp(&a.1)));
    rows.into_iter().map(|(_, _, row)| row).collect()
}

fn step_of(span: &Span) -> String {
    if let Some(operation) = span.attr("gen_ai.operation.name") {
        return operation.to_owned();
    }
    let name = span.name.as_str();
    if name.starts_with("summarization") {
        "summarization".to_owned()
    } else if name.starts_with("title_generation") {
        "title_generation".to_owned()
    } else if name.starts_with("chat") {
        "chat".to_owned()
    } else {
        name.to_owned()
    }
}

fn cache_by_step(llm: &[&Span]) -> Vec<Value> {
    let reported = llm.iter().copied().filter(|s| {
        s.attr(INPUT).is_some() || s.attr(CACHE_READ).is_some() || s.attr(CACHE_WRITE).is_some()
    });
    let mut rows: Vec<(f64, i64, Value)> = group_by(reported, |s| {
        (step_of(s), or_unknown(s, PROVIDER), or_unknown(s, MODEL))
    })
    .iter()
    .map(|((step, provider, model), members)| {
        let input = sum_int(members, INPUT);
        let cached = sum_int(members, CACHE_READ);
        let written = sum_int(members, CACHE_WRITE);
        let cost = sum_float(members, COST);
        let row = json!({
            "step": step,
            "provider": provider,
            "model": model,
            "provider_model": format!("{provider}:{model}"),
            "calls": members.len(),
            "input_tokens": input,
            "cached_tokens": cached,
            "cache_write_tokens": written,
            "miss_tokens": (input - cached).max(0),
            "ordinary_input_tokens": (input - cached - written).max(0),
            "cache_percent": cache_percent(cached, input),
            "estimated_cost_usd": round_to(cost, 8),
        });
        (cost, input, row)
    })
    .collect();
    rows.sort_by(|a, b| b.0.total_cmp(&a.0).then(b.1.cmp(&a.1)));
    rows.into_iter().map(|(_, _, row)| row).collect()
}

fn by_tool(tools: &[&Span]) -> Vec<Value> {
    let mut rows: Vec<(usize, Value)> =
        group_by(tools.iter().copied(), |s| or_unknown(s, "gen_ai.tool.name"))
            .iter()
            .map(|(tool, members)| {
                let calls = members.len();
                let errors = members.iter().filter(|s| s.is_error()).count();
                let ms = durations(members);
                let row = json!({
                    "tool": tool,
                    "calls": calls,
                    "errors": errors,
                    "error_rate": percent(errors as f64, calls as f64),
                    "avg_ms": round_to(avg_or_zero(&ms), 1),
                    "p50_ms": round_to(quantile_or_zero(&ms, 0.5), 1),
                    "p95_ms": round_to(quantile_or_zero(&ms, 0.95), 1),
                });
                (calls, row)
            })
            .collect();
    rows.sort_by_key(|row| std::cmp::Reverse(row.0));
    rows.into_iter().map(|(_, row)| row).collect()
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

    // 2026-10-30T12:00:00Z in microseconds
    const NOON: i64 = 1_793_361_600 * 1_000_000;

    fn span(name: &str, end_micros: i64, duration: f64, status: &str) -> Span {
        Span {
            name: name.into(),
            trace_id: "0x01".into(),
            span_id: "0x02".into(),
            start_ns: end_micros * 1_000 - 1,
            end_ns: end_micros * 1_000,
            duration_ms: Some(duration),
            status: Some(status.into()),
            ..Span::default()
        }
    }

    fn with(mut span: Span, attrs: &[(&'static str, &str)]) -> Span {
        for (key, value) in attrs {
            span.attrs.insert(key, (*value).to_owned());
        }
        span
    }

    fn llm(end: i64, provider: &str, model: &str, input: &str, output: &str, cost: &str) -> Span {
        with(
            span("chat x", end, 100.0, "OK"),
            &[
                (PROVIDER, provider),
                (MODEL, model),
                (INPUT, input),
                (OUTPUT, output),
                (COST, cost),
            ],
        )
    }

    #[test]
    fn round_to_matches_python_round() {
        assert_eq!(round_to(0.125, 2), 0.12); // exact tie goes to even
        assert_eq!(round_to(0.375, 2), 0.38);
        assert_eq!(round_to(2.675, 2), 2.67); // 2.675 is below the tie in binary
        assert_eq!(round_to(1234.56789, 1), 1234.6);
        assert_eq!(round_to(0.123_456_789_012, 8), 0.123_456_79);
        assert_eq!(round_to(-0.04, 1), 0.0);
        assert_eq!(round_to(5.0, 1), 5.0);
    }

    #[test]
    fn quantile_cont_interpolates_linearly() {
        assert_eq!(quantile_cont(&[], 0.5), None);
        assert_eq!(quantile_cont(&[7.0], 0.95), Some(7.0));
        assert_eq!(quantile_cont(&[10.0, 20.0], 0.5), Some(15.0));
        assert_eq!(quantile_cont(&[30.0, 10.0, 20.0], 0.5), Some(20.0));
        let values: Vec<f64> = (1..=10).map(f64::from).collect();
        assert!((quantile_cont(&values, 0.95).unwrap() - 9.55).abs() < 1e-9);
        assert_eq!(quantile_cont(&values, 1.0), Some(10.0));
        assert_eq!(quantile_cont(&values, 0.0), Some(1.0));
    }

    #[test]
    fn percent_helpers_follow_the_python_guards() {
        assert_eq!(percent(1.0, 3.0), 33.3);
        assert_eq!(percent(5.0, 0.0), 0.0);
        assert_eq!(percent(5.0, -1.0), 0.0);
        assert_eq!(cache_percent(50, 100), 50.0);
        assert_eq!(cache_percent(150, 100), 100.0);
        assert_eq!(cache_percent(-5, 100), 0.0);
        assert_eq!(cache_percent(5, 0), 0.0);
        assert_eq!(usd_per_mtok(0.5, 1_000_000), 0.5);
        assert_eq!(usd_per_mtok(0.5, 0), 0.0);
        assert_eq!(usd_per_mtok(1.0, 3), 333_333.333_333);
    }

    #[test]
    fn sample_ratio_is_clamped_and_defaults_to_one() {
        assert_eq!(sample_ratio(None), 1.0);
        assert_eq!(sample_ratio(Some("0.25")), 0.25);
        assert_eq!(sample_ratio(Some(" 0.5 ")), 0.5);
        assert_eq!(sample_ratio(Some("7")), 1.0);
        assert_eq!(sample_ratio(Some("-3")), 0.0);
        assert_eq!(sample_ratio(Some("abc")), 1.0);
        assert_eq!(sample_ratio(Some("nan")), 1.0);
        assert_eq!(sample_ratio(Some("")), 1.0);
    }

    #[test]
    fn empty_window_gives_the_zero_body() {
        let body = empty_summary(NOON - 7 * MICROS_PER_DAY, NOON, 0.5);
        assert_eq!(body["sample_ratio"], 0.5);
        assert_eq!(body["bucket_size"], "day");
        assert_eq!(body["totals"]["turns"], 0);
        assert_eq!(body["totals"]["cache_percent"], 0.0);
        assert_eq!(body["time_series"], json!([]));
        assert_eq!(body["by_tool"], json!([]));
        assert_eq!(body["window_end"], "2026-10-30T12:00:00+00:00");
        assert_eq!(body["window_start"], "2026-10-23T12:00:00+00:00");
        let day = empty_summary(NOON - MICROS_PER_DAY, NOON, 1.0);
        assert_eq!(day["bucket_size"], "hour");
    }

    #[test]
    fn totals_count_llm_usage_only_and_classify_spans() {
        let spans = vec![
            span("agent_run A", NOON - 1_000, 5_000.0, "ERROR"),
            span("agent_run B", NOON - 2_000, 1_000.0, "OK"),
            llm(NOON - 3_000, "p", "m", "100", "10", "0.5"),
            llm(NOON - 4_000, "p", "m", "oops", "5", "0.25"),
            with(
                span("custom", NOON - 5_000, 50.0, "ERROR"),
                &[("gen_ai.operation.name", "title_generation"), (INPUT, "7")],
            ),
            span("execute_tool read", NOON - 6_000, 20.0, "ERROR"),
            with(
                span("agent_run C", NOON - 7_000, 1.0, "OK"),
                &[(INPUT, "999")],
            ),
        ];
        let body = summary_body(NOON - MICROS_PER_DAY, NOON, 1.0, &spans);
        let totals = &body["totals"];
        assert_eq!(totals["turns"], 3);
        assert_eq!(totals["llm_calls"], 3);
        assert_eq!(totals["tool_calls"], 1);
        assert_eq!(totals["input_tokens"], 107);
        assert_eq!(totals["output_tokens"], 15);
        assert_eq!(totals["estimated_cost_usd"], 0.75);
        assert_eq!(totals["failed_turns"], 1);
        assert_eq!(totals["errors"], 1);
        assert_eq!(totals["error_spans"], 3);
        assert_eq!(totals["error_rate"], 33.3);
        assert_eq!(body["latency_ms"]["turn_p50"], 1000.0);
        assert_eq!(body["latency_ms"]["turn_p95"], 4600.0);
        assert_eq!(
            body["daily_turns"],
            json!([{"day": "2026-10-30", "turns": 3, "errors": 1}])
        );
    }

    #[test]
    fn time_series_is_dense_and_sparse_rows_carry_data() {
        let spans = vec![
            span("agent_run A", NOON - 3_600_000_000 + 5, 10.0, "OK"),
            llm(NOON - 3_600_000_000, "p", "m", "10", "2", "0.5"),
        ];
        let body = summary_body(NOON - MICROS_PER_DAY, NOON, 1.0, &spans);
        let series = body["time_series"].as_array().unwrap();
        assert_eq!(series.len(), 25);
        assert_eq!(series[0]["bucket_start"], "2026-10-29T12:00:00Z");
        assert_eq!(series[24]["bucket_start"], "2026-10-30T12:00:00Z");
        assert_eq!(series[24]["turns"], 0);
        let row = &series[23];
        assert_eq!(row["bucket_start"], "2026-10-30T11:00:00Z");
        assert_eq!(row["turns"], 1);
        assert_eq!(row["llm_calls"], 1);
        assert_eq!(row["input_tokens"], 10);
        assert_eq!(row["estimated_cost_usd"], 0.5);
        assert_eq!(row["turn_p95_ms"], 10.0);

        let week = summary_body(NOON - 7 * MICROS_PER_DAY, NOON, 1.0, &spans);
        let days = week["time_series"].as_array().unwrap();
        assert_eq!(days.len(), 8);
        assert_eq!(days[0]["bucket_start"], "2026-10-23T00:00:00Z");
        assert_eq!(days[7]["turns"], 1);
    }

    #[test]
    fn by_model_orders_by_cost_then_calls_and_keeps_zero_token_models() {
        let spans = vec![
            llm(NOON - 10, "a", "cheap", "1", "1", "0.1"),
            llm(NOON - 20, "b", "dear", "10", "5", "0.9"),
            llm(NOON - 30, "a", "idle", "0", "0", "0"),
            llm(NOON - 40, "a", "idle", "0", "0", "0"),
            with(span("chat y", NOON - 50, 1.0, "ERROR"), &[]),
        ];
        let body = summary_body(NOON - MICROS_PER_DAY, NOON, 1.0, &spans);
        let models: Vec<_> = body["by_model"]
            .as_array()
            .unwrap()
            .iter()
            .map(|row| row["provider_model"].as_str().unwrap().to_owned())
            .collect();
        assert_eq!(models, ["b:dear", "a:cheap", "a:idle", "unknown:unknown"]);
        let dear = &body["by_model"][0];
        assert_eq!(dear["usd_per_mtok"], 60_000.0);
        assert_eq!(dear["avg_ms"], 100.0);
        assert_eq!(body["by_model"][2]["calls"], 2);
        assert_eq!(body["by_model"][3]["errors"], 1);
        assert_eq!(body["by_model"][3]["error_rate"], 100.0);
        // tokens_by_model drops the groups that reported no tokens
        let split: Vec<_> = body["tokens_by_model"]
            .as_array()
            .unwrap()
            .iter()
            .map(|row| row["provider_model"].as_str().unwrap().to_owned())
            .collect();
        assert_eq!(split, ["a:cheap", "b:dear"]);
    }

    #[test]
    fn cache_split_is_clamped_and_cache_by_step_names_the_step() {
        let spans = vec![
            with(
                llm(NOON - 10, "p", "m", "100", "0", "0"),
                &[(CACHE_READ, "150"), (CACHE_WRITE, "20")],
            ),
            with(
                span("summarization_llm_call", NOON - 20, 1.0, "OK"),
                &[(INPUT, "10")],
            ),
            span("title_generation", NOON - 30, 1.0, "OK"),
            with(
                span("chat z", NOON - 40, 1.0, "OK"),
                &[
                    ("gen_ai.operation.name", "summarization"),
                    (CACHE_WRITE, "3"),
                ],
            ),
        ];
        let body = summary_body(NOON - MICROS_PER_DAY, NOON, 1.0, &spans);
        let split = &body["tokens_by_model"][0];
        assert_eq!(split["fresh_input_tokens"], 0);
        assert_eq!(split["cache_percent"], 100.0);
        let steps = body["cache_by_step"].as_array().unwrap();
        let by_step = |step: &str| steps.iter().find(|row| row["step"] == step).unwrap();
        assert_eq!(by_step("chat")["miss_tokens"], 0);
        assert_eq!(by_step("chat")["ordinary_input_tokens"], 0);
        assert_eq!(by_step("summarization")["calls"], 2);
        // the title span reported no usage attribute, so it has no row
        assert!(steps.iter().all(|row| row["step"] != "title_generation"));
    }

    #[test]
    fn by_tool_counts_errors_and_groups_missing_names() {
        let spans = vec![
            with(
                span("execute_tool read", NOON - 1, 10.0, "OK"),
                &[("gen_ai.tool.name", "read")],
            ),
            with(
                span("execute_tool read", NOON - 2, 30.0, "ERROR"),
                &[("gen_ai.tool.name", "read")],
            ),
            span("execute_tool ?", NOON - 3, 5.0, "OK"),
        ];
        let body = summary_body(NOON - MICROS_PER_DAY, NOON, 1.0, &spans);
        assert_eq!(body["by_tool"][0]["tool"], "read");
        assert_eq!(body["by_tool"][0]["calls"], 2);
        assert_eq!(body["by_tool"][0]["errors"], 1);
        assert_eq!(body["by_tool"][0]["error_rate"], 50.0);
        assert_eq!(body["by_tool"][0]["avg_ms"], 20.0);
        assert_eq!(body["by_tool"][1]["tool"], "unknown");
    }

    #[test]
    fn a_window_with_llm_spans_but_no_turns_does_not_fail() {
        let spans = vec![llm(NOON - 1, "p", "m", "5", "1", "0.5")];
        let body = summary_body(NOON - MICROS_PER_DAY, NOON, 1.0, &spans);
        assert_eq!(body["totals"]["turns"], 0);
        assert_eq!(body["totals"]["failed_turns"], 0);
        assert_eq!(body["totals"]["error_rate"], 0.0);
        assert_eq!(body["daily_turns"], json!([]));
        assert_eq!(body["latency_ms"]["turn_p95"], 0.0);
    }

    #[test]
    fn missing_durations_are_skipped_by_the_statistics() {
        let mut missing = span("execute_tool x", NOON - 1, 0.0, "OK");
        missing.duration_ms = None;
        let spans = vec![missing, span("execute_tool x", NOON - 2, 40.0, "OK")];
        let body = summary_body(NOON - MICROS_PER_DAY, NOON, 1.0, &spans);
        assert_eq!(body["by_tool"][0]["calls"], 2);
        assert_eq!(body["by_tool"][0]["avg_ms"], 40.0);
        assert_eq!(body["latency_ms"]["tool_p50"], 40.0);
    }
}
