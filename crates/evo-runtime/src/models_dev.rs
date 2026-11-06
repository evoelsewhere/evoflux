//! models.dev — evo's model database.
//!
//! Which models a provider serves and everything known about each — context
//! window, output cap, pricing (including long-context tiers), vision input,
//! the reasoning controls it accepts, and which wire protocol and endpoint a
//! gateway uses for it — come from https://models.dev/api.json. Nothing about
//! individual models is written in code.
//!
//! Hosts download the document, persist it and hand the text to [`ModelsDev::parse`]
//! (the desktop engine caches it in its application database and refreshes
//! it in the background). [`ModelsDev::bundled`] is a trimmed snapshot that
//! only seeds a machine that has never been online
//! (`scripts/gen_models_dev_snapshot.py`).

use std::collections::BTreeMap;
use std::sync::{Arc, OnceLock};

use evo_ai::model::AnthropicMessagesCompat;
use evo_ai::{InputModality, ModelCost, ModelCostRates, ModelCostTier, ThinkingLevel, ThinkingLevelMap};
use serde_json::Value;

const SNAPSHOT: &str = include_str!("../data/models_dev_snapshot.json");

/// Where hosts download the database from.
pub const MODELS_DEV_URL: &str = "https://models.dev/api.json";

/// One model as models.dev describes it, reduced to what evo uses.
#[derive(Clone, Debug, Default)]
pub struct DevModel {
    pub id: String,
    pub name: String,
    pub reasoning: bool,
    pub tool_call: bool,
    pub vision: bool,
    pub context_window: u64,
    pub max_tokens: u64,
    pub cost: Option<ModelCost>,
    /// Reasoning ladder from `reasoning_options`, weakest first.
    pub efforts: Vec<ThinkingLevel>,
    /// Reasoning can be switched off.
    pub can_disable: bool,
    /// Named efforts (adaptive thinking) rather than only a token budget.
    pub effort_control: bool,
    /// Prior reasoning must be replayed in this field (`reasoning_content`).
    pub interleaved_field: Option<String>,
    /// Per-model adapter override (`provider.npm`).
    pub npm: Option<String>,
    /// Per-model endpoint override (`provider.api`).
    pub api: Option<String>,
    pub deprecated: bool,
}

/// One provider's envelope.
#[derive(Clone, Debug, Default)]
pub struct DevProvider {
    pub id: String,
    pub name: String,
    pub api: Option<String>,
    pub npm: Option<String>,
    pub env: Vec<String>,
    pub doc: Option<String>,
    pub models: Vec<DevModel>,
}

/// The parsed database.
#[derive(Clone, Debug, Default)]
pub struct ModelsDev {
    providers: BTreeMap<String, DevProvider>,
}

fn level(name: &str) -> Option<ThinkingLevel> {
    match name {
        "minimal" => Some(ThinkingLevel::Minimal),
        "low" => Some(ThinkingLevel::Low),
        "medium" => Some(ThinkingLevel::Medium),
        "high" => Some(ThinkingLevel::High),
        "xhigh" => Some(ThinkingLevel::Xhigh),
        "max" => Some(ThinkingLevel::Max),
        _ => None,
    }
}

fn positive(value: Option<&Value>) -> Option<u64> {
    value.and_then(Value::as_f64).filter(|v| *v > 0.0).map(|v| v as u64)
}

fn rates(value: &Value) -> Option<ModelCostRates> {
    let number = |name: &str| value.get(name).and_then(Value::as_f64);
    if number("input").is_none() && number("output").is_none() {
        return None;
    }
    Some(ModelCostRates {
        input: number("input").unwrap_or(0.0),
        output: number("output").unwrap_or(0.0),
        cache_read: number("cache_read").unwrap_or(0.0),
        cache_write: number("cache_write").unwrap_or(0.0),
    })
}

fn cost(value: &Value) -> Option<ModelCost> {
    let base = rates(value)?;
    let mut tiers: Vec<ModelCostTier> = Vec::new();
    if let Some(list) = value.get("tiers").and_then(Value::as_array) {
        for tier in list {
            let (Some(rates), Some(size)) = (rates(tier), positive(tier.pointer("/tier/size")))
            else {
                continue;
            };
            tiers.push(ModelCostTier {
                rates,
                input_tokens_above: size as i64,
            });
        }
    }
    if let Some(over) = value.get("context_over_200k").and_then(rates) {
        if !tiers.iter().any(|tier| tier.input_tokens_above == 200_000) {
            tiers.push(ModelCostTier {
                rates: over,
                input_tokens_above: 200_000,
            });
        }
    }
    tiers.sort_by_key(|tier| tier.input_tokens_above);
    Some(ModelCost { rates: base, tiers })
}

fn parse_model(id: &str, value: &Value) -> DevModel {
    let text = |name: &str| value.get(name).and_then(Value::as_str).map(str::to_string);
    let flag = |name: &str| value.get(name).and_then(Value::as_bool);
    let mut model = DevModel {
        id: text("id").unwrap_or_else(|| id.to_string()),
        name: text("name").unwrap_or_else(|| id.to_string()),
        reasoning: flag("reasoning").unwrap_or(false),
        tool_call: flag("tool_call").unwrap_or(true),
        vision: value
            .pointer("/modalities/input")
            .and_then(Value::as_array)
            .is_some_and(|inputs| inputs.iter().any(|i| i == "image"))
            || (flag("attachment") == Some(true) && value.pointer("/modalities/input").is_none()),
        context_window: positive(value.pointer("/limit/context")).unwrap_or(0),
        max_tokens: positive(value.pointer("/limit/output")).unwrap_or(0),
        cost: value.get("cost").and_then(cost),
        npm: value.pointer("/provider/npm").and_then(Value::as_str).map(str::to_string),
        api: value.pointer("/provider/api").and_then(Value::as_str).map(str::to_string),
        deprecated: text("status").as_deref() == Some("deprecated"),
        ..Default::default()
    };
    model.interleaved_field = match value.get("interleaved") {
        Some(Value::Bool(true)) => Some("reasoning_content".into()),
        Some(Value::Object(object)) => object.get("field").and_then(Value::as_str).map(str::to_string),
        _ => None,
    };
    // `reasoning_options` lists every control a model accepts at once:
    // named efforts, an off toggle, a token budget (EvoFlux's
    // `_thinking_from_model`).
    if let Some(options) = value.get("reasoning_options").and_then(Value::as_array) {
        let mut budget = false;
        for option in options {
            match option.get("type").and_then(Value::as_str) {
                Some("effort") => {
                    model.effort_control = true;
                    for name in option
                        .get("values")
                        .and_then(Value::as_array)
                        .into_iter()
                        .flatten()
                        .filter_map(Value::as_str)
                    {
                        if name == "none" {
                            model.can_disable = true;
                        } else if let Some(level) = level(name) {
                            model.efforts.push(level);
                        }
                    }
                }
                Some("toggle") => model.can_disable = true,
                Some("budget_tokens") => {
                    budget = true;
                    if option.get("min").and_then(Value::as_u64) == Some(0) {
                        model.can_disable = true;
                    }
                }
                _ => {}
            }
        }
        if model.efforts.is_empty() && budget {
            model.efforts = vec![ThinkingLevel::Low, ThinkingLevel::Medium, ThinkingLevel::High];
        }
        model.efforts.sort();
        model.efforts.dedup();
    }
    model
}

impl ModelsDev {
    /// Parse a models.dev `api.json` document (or the trimmed snapshot).
    pub fn parse(text: &str) -> Result<Self, String> {
        let document: Value =
            serde_json::from_str(text).map_err(|error| format!("invalid models.dev JSON: {error}"))?;
        let object = document
            .as_object()
            .ok_or_else(|| "models.dev JSON is not an object".to_string())?;
        let mut providers = BTreeMap::new();
        for (key, value) in object {
            let Some(provider) = value.as_object() else { continue };
            let text = |name: &str| provider.get(name).and_then(Value::as_str).map(str::to_string);
            let id = text("id").unwrap_or_else(|| key.clone()).to_ascii_lowercase();
            let mut models: Vec<DevModel> = provider
                .get("models")
                .and_then(Value::as_object)
                .map(|models| models.iter().map(|(id, model)| parse_model(id, model)).collect())
                .unwrap_or_default();
            models.sort_by(|a, b| a.id.cmp(&b.id));
            providers.insert(
                id.clone(),
                DevProvider {
                    id,
                    name: text("name").unwrap_or_else(|| key.clone()),
                    api: text("api"),
                    npm: text("npm"),
                    env: provider
                        .get("env")
                        .and_then(Value::as_array)
                        .map(|env| env.iter().filter_map(Value::as_str).map(str::to_string).collect())
                        .unwrap_or_default(),
                    doc: text("doc"),
                    models,
                },
            );
        }
        if providers.is_empty() {
            return Err("models.dev JSON lists no providers".into());
        }
        Ok(Self { providers })
    }

    /// The offline seed, parsed once.
    pub fn bundled() -> Arc<ModelsDev> {
        static BUNDLED: OnceLock<Arc<ModelsDev>> = OnceLock::new();
        BUNDLED
            .get_or_init(|| Arc::new(Self::parse(SNAPSHOT).expect("bundled models.dev snapshot parses")))
            .clone()
    }

    pub fn provider(&self, id: &str) -> Option<&DevProvider> {
        self.providers.get(&id.to_ascii_lowercase())
    }

    pub fn providers(&self) -> impl Iterator<Item = &DevProvider> {
        self.providers.values()
    }

    pub fn model(&self, provider: &str, model: &str) -> Option<&DevModel> {
        self.provider(provider)?
            .models
            .iter()
            .find(|candidate| candidate.id.eq_ignore_ascii_case(model))
    }

    pub fn model_count(&self) -> usize {
        self.providers.values().map(|provider| provider.models.len()).sum()
    }
}

impl DevModel {
    /// Usable by an agent: tool calling, not deprecated.
    pub fn usable(&self) -> bool {
        self.tool_call && !self.deprecated
    }

    pub fn input(&self) -> Vec<InputModality> {
        if self.vision {
            vec![InputModality::Text, InputModality::Image]
        } else {
            vec![InputModality::Text]
        }
    }

    /// evo's per-level map: listed efforts map to their wire names, absent
    /// ones are unsupported (`None`), and `off` is unsupported unless the
    /// model can stop reasoning. `None` when models.dev states no controls.
    pub fn thinking_level_map(&self) -> Option<ThinkingLevelMap> {
        if !self.reasoning || self.efforts.is_empty() {
            return None;
        }
        let all = [
            ThinkingLevel::Minimal,
            ThinkingLevel::Low,
            ThinkingLevel::Medium,
            ThinkingLevel::High,
            ThinkingLevel::Xhigh,
            ThinkingLevel::Max,
        ];
        let mut map = ThinkingLevelMap::new();
        for level in all {
            let supported = self.efforts.contains(&level);
            map.insert(
                level,
                supported.then(|| serde_json::to_value(level).ok()?.as_str().map(str::to_string)).flatten(),
            );
        }
        if !self.can_disable {
            map.insert(ThinkingLevel::Off, None);
        }
        Some(map)
    }

    /// Anthropic Messages flags models.dev implies: named efforts mean
    /// adaptive thinking. (evo never sends a temperature, so that flag is moot.)
    pub fn anthropic_compat(&self) -> AnthropicMessagesCompat {
        let mut compat = AnthropicMessagesCompat::default();
        if self.effort_control {
            compat.force_adaptive_thinking = Some(true);
        }
        compat
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn snapshot_parses_with_reasoning_controls_and_tiers() {
        let db = ModelsDev::bundled();
        assert!(db.model_count() > 1000);
        let anthropic = db.provider("anthropic").expect("anthropic is listed");
        let reasoning = anthropic
            .models
            .iter()
            .find(|model| model.effort_control)
            .expect("an anthropic model with named efforts");
        let map = reasoning.thinking_level_map().unwrap();
        assert!(map.values().any(Option::is_some));
        assert!(reasoning.anthropic_compat().force_adaptive_thinking == Some(true));
    }

    #[test]
    fn parses_reasoning_options_like_evoflux() {
        let model = parse_model(
            "m",
            &serde_json::json!({
                "reasoning": true,
                "reasoning_options": [{"type": "toggle"}, {"type": "budget_tokens", "min": 1024}],
                "interleaved": {"field": "reasoning_content"},
                "cost": {"input": 1, "output": 2, "context_over_200k": {"input": 2, "output": 4}},
                "modalities": {"input": ["text", "image"]},
                "provider": {"npm": "@ai-sdk/anthropic", "api": "https://x/anthropic/v1"}
            }),
        );
        assert_eq!(model.efforts, [ThinkingLevel::Low, ThinkingLevel::Medium, ThinkingLevel::High]);
        assert!(model.can_disable && !model.effort_control && model.vision);
        assert_eq!(model.interleaved_field.as_deref(), Some("reasoning_content"));
        assert_eq!(model.cost.as_ref().unwrap().tiers[0].input_tokens_above, 200_000);
        assert_eq!(model.npm.as_deref(), Some("@ai-sdk/anthropic"));
        let map = model.thinking_level_map().unwrap();
        assert_eq!(map[&ThinkingLevel::Medium].as_deref(), Some("medium"));
        assert_eq!(map[&ThinkingLevel::Max], None);
        assert!(!map.contains_key(&ThinkingLevel::Off));
    }
}
