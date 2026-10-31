//! Port of `app/agent/providers/thinking.py` (Chat Completions dialects) and the
//! level helpers of `app/agent/providers/registry.py`.
//!
//! The Rust server has no models.dev catalog yet, so this is the path Python
//! takes when the catalog has no row for the model: the dialect's fallback
//! levels, and budgets from the ceilings alone (see KNOWN_DIFFERENCES.md).

use serde_json::{json, Map, Value};

/// `THINKING_ORDER`: active efforts, weakest first.
pub const THINKING_ORDER: [&str; 6] = ["minimal", "low", "medium", "high", "xhigh", "max"];

/// `_WIDELY_SUPPORTED`: the efforts every `reasoning_effort` endpoint takes.
const WIDELY_SUPPORTED: &[&str] = &["low", "medium", "high"];

/// `_LEGACY_EFFORT_LEVELS` of the MiMo handler.
pub const LEGACY_EFFORT_LEVELS: &[&str] = &["minimal", "low", "medium", "high"];

/// `_MIN_BUDGET`: floor for an enabled budget when the model publishes none.
const MIN_BUDGET: u64 = 1_024;

/// The wire contracts this server speaks (`Dialect`), Chat Completions only.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Dialect {
    /// `reasoning_effort: <level>`, the Chat Completions default.
    ReasoningEffort,
    /// MiMo's `thinking: {type, budget_tokens}`.
    BudgetTokens,
    /// No thinking field at all (Perplexity).
    None,
}

/// `dialect_for` with `transport=OPENAI_COMPLETIONS`: the `PROVIDER_DIALECTS`
/// override, else the transport default.
pub fn dialect_for(provider_id: &str) -> Dialect {
    match provider_id.trim().to_lowercase().as_str() {
        "xiaomi" => Dialect::BudgetTokens,
        "perplexity" => Dialect::None,
        _ => Dialect::ReasoningEffort,
    }
}

/// `DIALECT_FALLBACK_LEVELS`.
fn fallback_levels(dialect: Dialect) -> &'static [&'static str] {
    match dialect {
        Dialect::ReasoningEffort => WIDELY_SUPPORTED,
        Dialect::BudgetTokens => &THINKING_ORDER,
        Dialect::None => &[],
    }
}

/// `normalize_thinking_level`: `"none"` for any "do not reason" spelling, an
/// entry of [`THINKING_ORDER`] for an effort, `""` for no preference.
pub fn normalize_thinking_level(value: Option<&Value>) -> &'static str {
    let Some(Value::String(raw)) = value else {
        return "";
    };
    let normalized = raw.trim().to_lowercase();
    match normalized.as_str() {
        "none" | "off" | "disabled" => "none",
        "ultra" | "maximum" => "max",
        "very-high" | "veryhigh" | "x-high" | "extra-high" => "xhigh",
        "min" | "minimum" => "minimal",
        "light" => "low",
        other => THINKING_ORDER
            .iter()
            .find(|level| **level == other)
            .copied()
            .unwrap_or(""),
    }
}

fn rank(level: &str) -> Option<usize> {
    THINKING_ORDER.iter().position(|name| *name == level)
}

/// `clamp_thinking_level`: snap `level` down to the strongest supported level.
pub fn clamp_thinking_level(level: &str, supported: &[&'static str]) -> &'static str {
    if let Some(found) = supported.iter().find(|name| **name == level) {
        return found;
    }
    let Some(requested) = rank(level) else {
        return "";
    };
    let ranked: Vec<&'static str> = THINKING_ORDER
        .iter()
        .copied()
        .filter(|name| supported.contains(name))
        .collect();
    let weaker = ranked
        .iter()
        .rev()
        .find(|name| rank(name).is_some_and(|r| r <= requested));
    weaker.or(ranked.first()).copied().unwrap_or("")
}

/// `thinking_budget` with no published bounds and no known output cap.
pub fn thinking_budget(level: &str) -> u64 {
    let ceiling = match level {
        "minimal" => 2_048,
        "low" => 4_096,
        "high" => 16_000,
        "xhigh" => 24_576,
        "max" => 31_999,
        _ => 8_192,
    };
    ceiling.max(MIN_BUDGET)
}

/// `thinking_request_fields(provider, model, requested, transport=OPENAI_COMPLETIONS)`
/// for a model the catalog does not describe.
pub fn thinking_request_fields(provider_id: &str, requested: Option<&Value>) -> Map<String, Value> {
    let mut fields = Map::new();
    let dialect = dialect_for(provider_id);
    if dialect == Dialect::None {
        return fields;
    }
    let level = normalize_thinking_level(requested);
    if level.is_empty() {
        return fields;
    }
    // A silent catalog can always disable: both dialects have an off switch.
    if level == "none" {
        match dialect {
            Dialect::ReasoningEffort => {
                fields.insert("reasoning_effort".into(), json!("none"));
            }
            Dialect::BudgetTokens => {
                fields.insert("thinking".into(), json!({"type": "disabled"}));
            }
            Dialect::None => {}
        }
        return fields;
    }
    let level = clamp_thinking_level(level, fallback_levels(dialect));
    if level.is_empty() {
        return fields;
    }
    match dialect {
        Dialect::ReasoningEffort => {
            fields.insert("reasoning_effort".into(), json!(level));
        }
        Dialect::BudgetTokens => {
            fields.insert(
                "thinking".into(),
                json!({"type": "enabled", "budget_tokens": thinking_budget(level)}),
            );
        }
        Dialect::None => {}
    }
    fields
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::indexing_slicing)]
mod tests {
    use super::*;

    fn fields(provider: &str, level: Option<&str>) -> Value {
        let value = level.map(|l| json!(l));
        Value::Object(thinking_request_fields(provider, value.as_ref()))
    }

    /// The table printed from Python's `thinking_request_fields` for `mock-model`.
    #[test]
    fn matches_python_for_a_model_the_catalog_does_not_know() {
        let effort = |l: &str| json!({"reasoning_effort": l});
        let budget = |b: u64| json!({"thinking": {"type": "enabled", "budget_tokens": b}});
        let cases = [
            ("minimal", effort("low"), budget(2048)),
            ("low", effort("low"), budget(4096)),
            ("medium", effort("medium"), budget(8192)),
            ("high", effort("high"), budget(16000)),
            ("xhigh", effort("high"), budget(24576)),
            ("max", effort("high"), budget(31999)),
            ("ultra", effort("high"), budget(31999)),
            (
                "none",
                effort("none"),
                json!({"thinking": {"type": "disabled"}}),
            ),
            (
                "off",
                effort("none"),
                json!({"thinking": {"type": "disabled"}}),
            ),
            ("bogus", json!({}), json!({})),
        ];
        for (level, router9, xiaomi) in cases {
            assert_eq!(fields("router9", Some(level)), router9, "{level}");
            assert_eq!(fields("mistral", Some(level)), router9, "{level}");
            assert_eq!(fields("xiaomi", Some(level)), xiaomi, "{level}");
            assert_eq!(fields("perplexity", Some(level)), json!({}), "{level}");
        }
        assert_eq!(fields("router9", None), json!({}));
        let number = json!(3);
        assert_eq!(
            Value::Object(thinking_request_fields("router9", Some(&number))),
            json!({})
        );
    }

    #[test]
    fn normalizes_every_alias() {
        let n = |s: &str| normalize_thinking_level(Some(&json!(s)));
        assert_eq!(n(" HIGH "), "high");
        assert_eq!(n("disabled"), "none");
        assert_eq!(n("maximum"), "max");
        for alias in ["very-high", "veryhigh", "x-high", "extra-high"] {
            assert_eq!(n(alias), "xhigh");
        }
        assert_eq!(n("min"), "minimal");
        assert_eq!(n("minimum"), "minimal");
        assert_eq!(n("light"), "low");
        assert_eq!(n(""), "");
        assert_eq!(n("weird"), "");
    }

    #[test]
    fn clamps_like_python() {
        assert_eq!(clamp_thinking_level("max", LEGACY_EFFORT_LEVELS), "high");
        assert_eq!(clamp_thinking_level("minimal", WIDELY_SUPPORTED), "low");
        assert_eq!(clamp_thinking_level("medium", WIDELY_SUPPORTED), "medium");
        assert_eq!(clamp_thinking_level("xhigh", WIDELY_SUPPORTED), "high");
        assert_eq!(clamp_thinking_level("none", WIDELY_SUPPORTED), "");
        assert_eq!(clamp_thinking_level("high", &[]), "");
    }

    #[test]
    fn budget_has_a_floor_and_a_medium_default() {
        assert_eq!(thinking_budget("medium"), 8192);
        assert_eq!(thinking_budget("unknown"), 8192);
        assert_eq!(dialect_for(" Xiaomi "), Dialect::BudgetTokens);
    }
}
