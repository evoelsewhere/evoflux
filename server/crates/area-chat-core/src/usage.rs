//! Port of app/agent/turn_usage.py (`TurnUsageTracker`) and
//! `usage_to_dict` in app/agent/usage.py. Cost is never priced: the Rust
//! server has no model catalog (KNOWN_DIFFERENCES).

use std::collections::{BTreeMap, BTreeSet};

use evoflux_area_providers::Usage;
use serde_json::{json, Map, Value};

#[derive(Debug, Clone, Default, PartialEq)]
struct Totals {
    input: i64,
    output: i64,
    cache: i64,
    cache_write: i64,
    thoughts: i64,
    tool_use: i64,
    calls: i64,
    models: BTreeSet<String>,
}

impl Totals {
    fn add(&mut self, u: &[i64; 6], model: &str) {
        self.input += u[0];
        self.output += u[1];
        self.cache += u[2];
        self.cache_write += u[3];
        self.thoughts += u[4];
        self.tool_use += u[5];
        self.calls += 1;
        if !model.is_empty() {
            self.models.insert(model.to_owned());
        }
    }

    fn snapshot(&self) -> Map<String, Value> {
        let mut out = Map::new();
        out.insert("input".into(), json!(self.input));
        out.insert("output".into(), json!(self.output));
        out.insert("cache".into(), json!(self.cache));
        out.insert("cache_write".into(), json!(self.cache_write));
        out.insert("calls".into(), json!(self.calls));
        if self.thoughts != 0 {
            out.insert("thoughts".into(), json!(self.thoughts));
        }
        if self.tool_use != 0 {
            out.insert("tool_use".into(), json!(self.tool_use));
        }
        if !self.models.is_empty() {
            out.insert("models".into(), json!(self.models));
        }
        out
    }
}

/// `TurnUsageTracker`.
#[derive(Debug, Default)]
pub(crate) struct TurnUsage {
    total: Totals,
    phases: BTreeMap<String, Totals>,
}

/// `_normalize_usage`: `None` when every count is zero.
fn normalize(u: &Usage) -> Option<[i64; 6]> {
    let values = [
        u.prompt_tokens,
        u.completion_tokens,
        u.cached_tokens.unwrap_or(0),
        u.cache_write_tokens.unwrap_or(0),
        u.thoughts_tokens.unwrap_or(0),
        u.tool_use_tokens.unwrap_or(0),
    ]
    .map(|v| v.max(0));
    values.iter().any(|v| *v != 0).then_some(values)
}

impl TurnUsage {
    /// `record`: add one completed call; the new snapshot, or `None` when the
    /// usage was empty.
    pub(crate) fn record(&mut self, usage: &Usage, phase: &str, model: &str) -> Option<Value> {
        let values = normalize(usage)?;
        self.total.add(&values, model);
        self.phases
            .entry(phase.to_owned())
            .or_default()
            .add(&values, model);
        self.snapshot()
    }

    /// `current_turn_usage_snapshot`.
    pub(crate) fn snapshot(&self) -> Option<Value> {
        if self.total.calls == 0 {
            return None;
        }
        let mut out = self.total.snapshot();
        let phases: Map<String, Value> = self
            .phases
            .iter()
            .map(|(name, totals)| (name.clone(), Value::Object(totals.snapshot())))
            .collect();
        out.insert("phases".into(), Value::Object(phases));
        Some(Value::Object(out))
    }
}

/// The `usage` event `record_turn_usage` publishes for a snapshot.
pub(crate) fn turn_total_event(snapshot: &Value, agent: &str) -> Value {
    let get = |key: &str| snapshot.get(key).cloned().unwrap_or(Value::Null);
    let input = snapshot.get("input").and_then(Value::as_i64).unwrap_or(0);
    let output = snapshot.get("output").and_then(Value::as_i64).unwrap_or(0);
    json!({
        "type": "usage",
        "prompt_tokens": input,
        "completion_tokens": output,
        "total_tokens": input + output,
        "cached_tokens": get("cache"),
        "cache_write_tokens": get("cache_write"),
        "thoughts_tokens": get("thoughts"),
        "tool_use_tokens": get("tool_use"),
        "cost": null,
        "metadata": {
            "turn_total": true,
            "agent": agent,
            "calls": get("calls"),
            "phases": get("phases"),
            "models": get("models"),
        },
    })
}

/// `usage_to_dict` (without cost).
pub(crate) fn usage_to_dict(u: &Usage) -> Value {
    let mut out = Map::new();
    out.insert("input".into(), json!(u.prompt_tokens));
    out.insert("output".into(), json!(u.completion_tokens));
    for (key, value) in [
        ("cache", u.cached_tokens),
        ("cache_write", u.cache_write_tokens),
        ("thoughts", u.thoughts_tokens),
        ("tool_use", u.tool_use_tokens),
    ] {
        if let Some(value) = value {
            out.insert(key.into(), json!(value));
        }
    }
    Value::Object(out)
}

/// The per-call `usage` event `StreamPublisherHook.on_model_delta` publishes.
pub(crate) fn call_usage_event(u: &Usage, agent: &str, model: &str) -> Value {
    let total = if u.total_tokens != 0 {
        u.total_tokens
    } else {
        u.prompt_tokens + u.completion_tokens
    };
    json!({
        "type": "usage",
        "prompt_tokens": u.prompt_tokens,
        "completion_tokens": u.completion_tokens,
        "total_tokens": total,
        "cached_tokens": u.cached_tokens,
        "cache_write_tokens": u.cache_write_tokens,
        "thoughts_tokens": u.thoughts_tokens,
        "tool_use_tokens": u.tool_use_tokens,
        "cost": null,
        "metadata": {"agent": agent, "model": model},
    })
}

/// `_fold_call_usage`: the latest block, keeping the widest detail counts.
pub(crate) fn fold(previous: Option<Usage>, current: &Usage) -> Usage {
    let Some(previous) = previous else {
        return current.clone();
    };
    let widest = |a: Option<i64>, b: Option<i64>| match (a, b) {
        (Some(a), Some(b)) => Some(a.max(b)),
        (a, b) => a.or(b),
    };
    Usage {
        cached_tokens: widest(previous.cached_tokens, current.cached_tokens),
        cache_write_tokens: widest(previous.cache_write_tokens, current.cache_write_tokens),
        thoughts_tokens: widest(previous.thoughts_tokens, current.thoughts_tokens),
        tool_use_tokens: widest(previous.tool_use_tokens, current.tool_use_tokens),
        ..current.clone()
    }
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    clippy::disallowed_methods
)]
mod tests {
    use super::*;

    fn usage(p: i64, c: i64) -> Usage {
        Usage {
            prompt_tokens: p,
            completion_tokens: c,
            total_tokens: p + c,
            ..Usage::default()
        }
    }

    #[test]
    fn tracker_matches_the_python_snapshot() {
        let mut t = TurnUsage::default();
        assert_eq!(t.snapshot(), None);
        assert_eq!(t.record(&Usage::default(), "main", "m"), None);
        t.record(&usage(20, 5), "main", "router9:mock-model");
        let mut second = usage(30, 6);
        second.thoughts_tokens = Some(4);
        let snap = t.record(&second, "main", "router9:mock-model").unwrap();
        assert_eq!(
            crate::pyjson::dumps(&snap),
            r#"{"input": 50, "output": 11, "cache": 0, "cache_write": 0, "calls": 2, "thoughts": 4, "models": ["router9:mock-model"], "phases": {"main": {"input": 50, "output": 11, "cache": 0, "cache_write": 0, "calls": 2, "thoughts": 4, "models": ["router9:mock-model"]}}}"#
        );
        let mut neg = usage(-3, 2);
        neg.tool_use_tokens = Some(7);
        let snap = t.record(&neg, "title", "").unwrap();
        assert_eq!(snap["tool_use"], 7);
        assert_eq!(snap["input"], 50);
        assert!(snap["phases"]["title"].get("models").is_none());
    }

    #[test]
    fn turn_total_event_shape() {
        let mut t = TurnUsage::default();
        let snap = t
            .record(&usage(10, 4), "main", "router9:mock-model")
            .unwrap();
        assert_eq!(
            crate::pyjson::dumps(&turn_total_event(&snap, "evoflux")),
            r#"{"type": "usage", "prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14, "cached_tokens": 0, "cache_write_tokens": 0, "thoughts_tokens": null, "tool_use_tokens": null, "cost": null, "metadata": {"turn_total": true, "agent": "evoflux", "calls": 1, "phases": {"main": {"input": 10, "output": 4, "cache": 0, "cache_write": 0, "calls": 1, "models": ["router9:mock-model"]}}, "models": ["router9:mock-model"]}}"#
        );
    }

    #[test]
    fn call_usage_and_dict() {
        let mut u = usage(12, 9);
        u.thoughts_tokens = Some(5);
        assert_eq!(
            crate::pyjson::dumps(&call_usage_event(&u, "evoflux", "mock-model")),
            r#"{"type": "usage", "prompt_tokens": 12, "completion_tokens": 9, "total_tokens": 21, "cached_tokens": null, "cache_write_tokens": null, "thoughts_tokens": 5, "tool_use_tokens": null, "cost": null, "metadata": {"agent": "evoflux", "model": "mock-model"}}"#
        );
        assert_eq!(
            usage_to_dict(&u),
            json!({"input": 12, "output": 9, "thoughts": 5})
        );
        let mut all = usage(1, 2);
        all.total_tokens = 0;
        all.cached_tokens = Some(3);
        all.cache_write_tokens = Some(4);
        all.tool_use_tokens = Some(6);
        assert_eq!(call_usage_event(&all, "a", "m")["total_tokens"], 3);
        assert_eq!(
            crate::pyjson::dumps(&usage_to_dict(&all)),
            r#"{"input": 1, "output": 2, "cache": 3, "cache_write": 4, "tool_use": 6}"#
        );
    }

    #[test]
    fn fold_keeps_the_widest_details() {
        let mut first = usage(5, 1);
        first.cached_tokens = Some(40);
        first.thoughts_tokens = Some(2);
        first.cache_write_tokens = Some(7);
        first.tool_use_tokens = Some(12);
        let mut last = usage(5, 3);
        last.thoughts_tokens = Some(1);
        last.tool_use_tokens = Some(9);
        last.cache_write_tokens = Some(3);
        let folded = fold(Some(first), &last);
        assert_eq!(folded.completion_tokens, 3);
        assert_eq!(folded.cached_tokens, Some(40));
        assert_eq!(folded.thoughts_tokens, Some(2));
        assert_eq!(folded.tool_use_tokens, Some(12));
        assert_eq!(folded.cache_write_tokens, Some(7));
        assert_eq!(fold(None, &last), last);
        let mut only_last = usage(1, 1);
        only_last.cached_tokens = Some(4);
        assert_eq!(fold(Some(usage(1, 1)), &only_last).cached_tokens, Some(4));
    }

    #[test]
    fn cache_counts_add_up() {
        let mut t = TurnUsage::default();
        let mut u = usage(1, 1);
        u.cached_tokens = Some(3);
        u.cache_write_tokens = Some(5);
        t.record(&u, "main", "m");
        let snap = t.record(&u, "main", "m").unwrap();
        assert_eq!(snap["cache"], 6);
        assert_eq!(snap["cache_write"], 10);
        assert_eq!(snap["phases"]["main"]["cache"], 6);
    }
}
