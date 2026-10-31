//! Port of `build_provider` and `_resolve_config_key_and_url` in
//! `app/agent/providers/factory.py`, for the Chat Completions providers of
//! `app/agent/providers/registry.py` that this server serves.

use std::time::{Duration, SystemTime, UNIX_EPOCH};

use evoflux_core::config::Settings;

use crate::ProviderError;

/// `PROVIDER_MODEL_TOKEN`: the placeholder seeded agents carry until configured.
const PROVIDER_MODEL_TOKEN: &str = "__PROVIDER_MODEL__";

/// `MIMO_FREE_API_ALIASES`.
const MIMO_FREE_API_ALIASES: [&str; 2] = ["mimo:auto", "mimo:mimo-auto"];

/// `MIMO_FREE_API_SUNSET_ISO` (2026-07-26T10:00:00+00:00) as Unix seconds.
const MIMO_FREE_API_SUNSET: u64 = 1_785_060_000;

/// `SUPPORTED_PROVIDERS`: every registry ID, sorted.
const SUPPORTED_PROVIDERS: [&str; 40] = [
    "anthropic",
    "baseten",
    "bedrock",
    "cerebras",
    "cliproxy",
    "codex",
    "cohere",
    "copilot",
    "deepinfra",
    "deepseek",
    "fci",
    "fireworks",
    "foundry",
    "googlegenai",
    "groq",
    "huggingface",
    "kimi",
    "llmgateway",
    "minimax",
    "mistral",
    "moonshot",
    "nvidia",
    "ollama",
    "openai",
    "opencode",
    "opencode-go",
    "openrouter",
    "perplexity",
    "qwencloud",
    "router9",
    "sambanova",
    "stepfun",
    "together",
    "vercel",
    "vertexai",
    "xai",
    "xiaomi",
    "zai",
    "zenmux",
    "zhipuai",
];

/// Which request builder a provider uses.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Flavor {
    /// `ChatCompletionsOnlyProvider` / `Router9Provider`: the base `CompletionsHandler`.
    Completions,
    /// `XiaomiProvider`: `_XiaomiCompletionsHandler`.
    Xiaomi,
}

/// The registry fields one Chat Completions provider needs (`ProviderConfig`).
#[derive(Debug, Clone, Copy)]
pub struct ProviderConfig {
    pub id: &'static str,
    pub label: &'static str,
    pub env_var: &'static str,
    pub base_url: &'static str,
    pub base_url_env_var: &'static str,
    /// The `Settings` field default for the key, where `app/core/config.py` declares one.
    pub default_key_setting: Option<&'static str>,
    /// `request_headers(config)`: static attribution headers.
    pub headers: &'static [(&'static str, &'static str)],
    pub flavor: Flavor,
}

const fn completions(
    id: &'static str,
    label: &'static str,
    env_var: &'static str,
    base_url: &'static str,
    base_url_env_var: &'static str,
) -> ProviderConfig {
    ProviderConfig {
        id,
        label,
        env_var,
        base_url,
        base_url_env_var,
        default_key_setting: None,
        headers: &[],
        flavor: Flavor::Completions,
    }
}

/// The providers served here: router9, xiaomi, and every registry entry that
/// `_build_from_registry` turns into a plain `ChatCompletionsOnlyProvider`
/// with a curated base URL.
pub const PROVIDERS: [ProviderConfig; 12] = [
    ProviderConfig {
        default_key_setting: Some("sk_9router"),
        ..completions(
            "router9",
            "9Router",
            "ROUTER9_API_KEY",
            "http://localhost:20128/v1",
            "ROUTER9_BASE_URL",
        )
    },
    ProviderConfig {
        flavor: Flavor::Xiaomi,
        ..completions(
            "xiaomi",
            "Xiaomi MiMo",
            "XIAOMI_API_KEY",
            "https://api.xiaomimimo.com/v1",
            "XIAOMI_BASE_URL",
        )
    },
    ProviderConfig {
        default_key_setting: Some("sk_cliproxy"),
        ..completions(
            "cliproxy",
            "CLIProxyAPI",
            "CLIPROXY_API_KEY",
            "http://localhost:8317/v1",
            "CLIPROXY_BASE_URL",
        )
    },
    completions(
        "mistral",
        "Mistral AI",
        "MISTRAL_API_KEY",
        "https://api.mistral.ai/v1",
        "MISTRAL_BASE_URL",
    ),
    completions(
        "cohere",
        "Cohere",
        "COHERE_API_KEY",
        "https://api.cohere.ai/compatibility/v1",
        "COHERE_BASE_URL",
    ),
    completions(
        "groq",
        "Groq",
        "GROQ_API_KEY",
        "https://api.groq.com/openai/v1",
        "GROQ_BASE_URL",
    ),
    completions(
        "cerebras",
        "Cerebras",
        "CEREBRAS_API_KEY",
        "https://api.cerebras.ai/v1",
        "CEREBRAS_BASE_URL",
    ),
    completions(
        "together",
        "Together AI",
        "TOGETHER_API_KEY",
        "https://api.together.xyz/v1",
        "TOGETHER_BASE_URL",
    ),
    completions(
        "deepinfra",
        "Deep Infra",
        "DEEPINFRA_API_KEY",
        "https://api.deepinfra.com/v1/openai",
        "DEEPINFRA_BASE_URL",
    ),
    completions(
        "sambanova",
        "SambaNova",
        "SAMBANOVA_API_KEY",
        "https://api.sambanova.ai/v1",
        "SAMBANOVA_BASE_URL",
    ),
    completions(
        "perplexity",
        "Perplexity",
        "PERPLEXITY_API_KEY",
        "https://api.perplexity.ai",
        "PERPLEXITY_BASE_URL",
    ),
    ProviderConfig {
        headers: &[
            ("http-referer", "https://github.com/khuonghung/evoflux"),
            ("x-title", "EvoFlux"),
        ],
        ..completions(
            "vercel",
            "Vercel AI Gateway",
            "AI_GATEWAY_API_KEY",
            "https://ai-gateway.vercel.sh/v1",
            "AI_GATEWAY_BASE_URL",
        )
    },
];

/// What `provider_for` resolved: the provider entry, its wire model, key and endpoint.
#[derive(Clone)]
pub struct Resolved {
    pub config: ProviderConfig,
    pub model: String,
    pub api_key: String,
    pub base_url: String,
}

impl std::fmt::Debug for Resolved {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Resolved")
            .field("provider", &self.config.id)
            .field("model", &self.model)
            .field("api_key", &"**********")
            .field("base_url", &self.base_url)
            .finish()
    }
}

fn mimo_free_api_sunset(now: SystemTime) -> bool {
    now.duration_since(UNIX_EPOCH).unwrap_or(Duration::ZERO)
        >= Duration::from_secs(MIMO_FREE_API_SUNSET)
}

/// `build_provider`'s parsing and resolution, at time `now`.
pub fn resolve(
    settings: &Settings,
    model_str: &str,
    now: SystemTime,
) -> Result<Resolved, ProviderError> {
    if model_str.is_empty() {
        return Err(ProviderError::Config(
            "No model specified. Set 'model' in the agent's .md frontmatter \
             (format: 'provider:model', e.g. 'googlegenai:gemini-3.1-flash')."
                .to_owned(),
        ));
    }
    if model_str.contains(PROVIDER_MODEL_TOKEN) {
        return Err(ProviderError::Unconfigured(
            "Agent '?' has no model configured. Open Settings → Providers in the UI \
             to add a provider, or run `evoflux init` in a terminal."
                .to_owned(),
        ));
    }
    let Some((name, model)) = model_str.split_once(':') else {
        return Err(ProviderError::Config(format!(
            "Invalid model format '{model_str}'. Expected 'provider:model' \
             (e.g. 'zai:glm-5-turbo', 'googlegenai:gemini-3.1-flash')."
        )));
    };
    let mut name = name.trim().to_lowercase();
    let mut model = model.to_owned();
    if MIMO_FREE_API_ALIASES.contains(&format!("{name}:{model}").to_lowercase().as_str()) {
        if mimo_free_api_sunset(now) {
            return Err(ProviderError::Unconfigured(
                "MiMo's free API channel ('mimo:auto') shut down on 2026-07-26. Add a \
                 Xiaomi MiMo API key in Settings > Providers and use a 'xiaomi:<model>' \
                 model instead, or pick another provider."
                    .to_owned(),
            ));
        }
        name = "xiaomi".to_owned();
        model = "mimo-v2-flash".to_owned();
    }
    let Some(config) = PROVIDERS.iter().find(|p| p.id == name).copied() else {
        if SUPPORTED_PROVIDERS.contains(&name.as_str()) {
            return Err(ProviderError::NotPorted(name));
        }
        return Err(ProviderError::Unconfigured(format!(
            "Unsupported provider '{name}'. Supported providers: {}",
            SUPPORTED_PROVIDERS.join(", ")
        )));
    };
    let (api_key, base_url) = resolve_key_and_url(settings, &config)?;
    Ok(Resolved {
        config,
        model,
        api_key,
        base_url,
    })
}

/// `_resolve_config_key_and_url` + `require_api_key`. The key: the configured
/// value (environment over `.env`) or the `Settings` default; the endpoint: a
/// non-blank `*_BASE_URL`, else the registry URL. Python then strips one
/// trailing `/` set (`base_url.rstrip("/")`).
fn resolve_key_and_url(
    settings: &Settings,
    config: &ProviderConfig,
) -> Result<(String, String), ProviderError> {
    let configured = settings
        .provider_var(config.env_var)
        .map(|secret| secret.expose().to_owned())
        .or(config.default_key_setting.map(str::to_owned));
    let api_key = match configured {
        Some(key) if !key.is_empty() => key,
        _ => {
            return Err(ProviderError::Config(format!(
                "{} API key is required. Set {} in your .env file.",
                config.label, config.env_var
            )))
        }
    };
    let base_url = settings
        .provider_var(config.base_url_env_var)
        .map(|secret| secret.expose().trim())
        .filter(|url| !url.is_empty())
        .unwrap_or(config.base_url)
        .trim_end_matches('/')
        .to_owned();
    Ok((api_key, base_url))
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use std::path::Path;

    fn settings(vars: &[(&str, &str)]) -> Settings {
        let vars: HashMap<String, String> = vars
            .iter()
            .map(|(k, v)| ((*k).to_owned(), (*v).to_owned()))
            .collect();
        Settings::from_vars(&vars, Some(Path::new("/home")), Path::new("/work")).unwrap()
    }

    fn before_sunset() -> SystemTime {
        UNIX_EPOCH + Duration::from_secs(MIMO_FREE_API_SUNSET - 1)
    }

    fn after_sunset() -> SystemTime {
        UNIX_EPOCH + Duration::from_secs(MIMO_FREE_API_SUNSET)
    }

    fn err(vars: &[(&str, &str)], model: &str) -> String {
        resolve(&settings(vars), model, after_sunset())
            .unwrap_err()
            .to_string()
    }

    #[test]
    fn router9_defaults_to_the_settings_key_and_local_url() {
        let r = resolve(&settings(&[]), "Router9 :gpt-x:latest", after_sunset()).unwrap();
        assert_eq!(r.config.id, "router9");
        assert_eq!(r.model, "gpt-x:latest");
        assert_eq!(r.api_key, "sk_9router");
        assert_eq!(r.base_url, "http://localhost:20128/v1");
        let debug = format!("{r:?}");
        assert!(!debug.contains("sk_9router"), "{debug}");
        assert!(
            debug.contains("router9") && debug.contains("gpt-x:latest"),
            "{debug}"
        );
        let cliproxy = resolve(&settings(&[]), "cliproxy:m", after_sunset()).unwrap();
        assert_eq!(cliproxy.api_key, "sk_cliproxy");
        assert_eq!(cliproxy.config.flavor, Flavor::Completions);
    }

    #[test]
    fn only_vercel_sends_attribution_headers_and_only_xiaomi_is_mimo() {
        for config in PROVIDERS {
            let attributed = !config.headers.is_empty();
            assert_eq!(attributed, config.id == "vercel", "{}", config.id);
            assert_eq!(
                config.flavor == Flavor::Xiaomi,
                config.id == "xiaomi",
                "{}",
                config.id
            );
            let defaulted = config.default_key_setting.is_some();
            assert_eq!(
                defaulted,
                matches!(config.id, "router9" | "cliproxy"),
                "{}",
                config.id
            );
        }
    }

    #[test]
    fn configured_key_and_url_win() {
        let vars = [
            ("ROUTER9_API_KEY", "k1"),
            ("router9_base_url", "  http://h:1/v1//  "),
        ];
        let r = resolve(&settings(&vars), "router9:m", after_sunset()).unwrap();
        assert_eq!(r.api_key, "k1");
        assert_eq!(r.base_url, "http://h:1/v1");
        let blank = [("ROUTER9_BASE_URL", "   ")];
        let r = resolve(&settings(&blank), "router9:m", after_sunset()).unwrap();
        assert_eq!(r.base_url, "http://localhost:20128/v1");
    }

    #[test]
    fn a_missing_or_empty_key_is_a_config_error() {
        assert_eq!(
            err(&[], "xiaomi:mimo"),
            "Xiaomi MiMo API key is required. Set XIAOMI_API_KEY in your .env file."
        );
        assert_eq!(
            err(&[("ROUTER9_API_KEY", "")], "router9:m"),
            "9Router API key is required. Set ROUTER9_API_KEY in your .env file."
        );
        let r = resolve(
            &settings(&[("XIAOMI_API_KEY", "x")]),
            "xiaomi:m",
            after_sunset(),
        );
        assert_eq!(r.unwrap().base_url, "https://api.xiaomimimo.com/v1");
    }

    #[test]
    fn model_string_errors_match_python() {
        assert!(err(&[], "").starts_with("No model specified."));
        assert!(err(&[], "x:__PROVIDER_MODEL__").starts_with("Agent '?' has no model"));
        assert_eq!(
            err(&[], "gpt"),
            "Invalid model format 'gpt'. Expected 'provider:model' \
             (e.g. 'zai:glm-5-turbo', 'googlegenai:gemini-3.1-flash')."
        );
        assert_eq!(
            err(&[], "openai:gpt-5"),
            "provider 'openai' is not available in the Rust server yet"
        );
        assert!(err(&[], "nope:m")
            .starts_with("Unsupported provider 'nope'. Supported providers: anthropic, baseten,"));
    }

    #[test]
    fn mimo_free_alias_routes_until_the_sunset() {
        let vars = settings(&[("XIAOMI_API_KEY", "x")]);
        let before = resolve(&vars, "MIMO:auto", before_sunset()).unwrap();
        assert_eq!(
            (before.config.id, before.model.as_str()),
            ("xiaomi", "mimo-v2-flash")
        );
        let after = resolve(&vars, "mimo:mimo-auto", after_sunset()).unwrap_err();
        assert!(matches!(after, ProviderError::Unconfigured(m) if m.contains("shut down")));
    }

    #[test]
    fn every_generic_provider_resolves_with_its_key() {
        for config in PROVIDERS {
            let vars = settings(&[(config.env_var, "key")]);
            let r = resolve(&vars, &format!("{}:m", config.id), after_sunset()).unwrap();
            assert_eq!(r.base_url, config.base_url);
            assert!(SUPPORTED_PROVIDERS.contains(&config.id));
        }
    }
}
