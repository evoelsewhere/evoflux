//! Differential tests against the Python catalog.
//!
//! `fixtures/python_catalog.json` is `tests/dump_catalog.py`'s dump of the
//! real Python code (registry, catalog rows, lookups, merge with a fetched
//! models.dev payload, plugins, and `_provider_is_configured` under many
//! environments). Every provider and every field is compared.

#![allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)]

use evoflux_shared_provider_catalog as sut;
use serde::Serialize;
use serde_json::{json, Value};
use sut::{Catalog, CredentialLookup, EnvMap, Kind, PluginProvider, ProviderConfig, Transport};

fn fixture() -> &'static Value {
    static FIXTURE: std::sync::OnceLock<Value> = std::sync::OnceLock::new();
    FIXTURE.get_or_init(|| {
        let text = include_str!("fixtures/python_catalog.json");
        serde_json::from_str(text).expect("fixture parses")
    })
}

fn to_json<T: Serialize>(value: &T) -> Value {
    serde_json::to_value(value).expect("serializes")
}

/// Compare two JSON arrays of provider rows, naming the first differing
/// provider and field.
fn assert_rows(label: &str, actual: &Value, expected: &Value) {
    let actual = actual.as_array().expect("actual array");
    let expected = expected.as_array().expect("expected array");
    let ids = |rows: &[Value]| -> Vec<String> {
        rows.iter()
            .map(|r| r["id"].as_str().unwrap_or("?").to_owned())
            .collect()
    };
    assert_eq!(
        ids(actual),
        ids(expected),
        "{label}: provider ids and order"
    );
    for (a, e) in actual.iter().zip(expected) {
        let a_map = a.as_object().expect("row object");
        let e_map = e.as_object().expect("row object");
        let mut keys: Vec<&String> = a_map.keys().chain(e_map.keys()).collect();
        keys.sort();
        keys.dedup();
        for key in keys {
            assert_eq!(
                a_map.get(key),
                e_map.get(key),
                "{label}: provider {} field {key}",
                e["id"]
            );
        }
    }
}

fn plugins() -> Vec<PluginProvider> {
    fn field(name: &str, secret: bool, required: bool, placeholder: &str) -> sut::CredentialField {
        sut::CredentialField {
            name: name.to_owned(),
            label: name.to_owned(),
            secret,
            required,
            placeholder: placeholder.to_owned(),
        }
    }
    fn base(id: &str, label: &str, description: &str, kind: Kind) -> PluginProvider {
        PluginProvider {
            id: id.to_owned(),
            label: label.to_owned(),
            description: description.to_owned(),
            kind,
            credentials: Vec::new(),
            fallback_models: Vec::new(),
            models_dev_provider_id: String::new(),
            metadata_source_provider: String::new(),
            model_registry_aliases: Default::default(),
            docs_url: String::new(),
            oauth_command: String::new(),
            is_configured: None,
        }
    }
    let mut acme = base("acme", "Acme AI", "Acme hosted models.", Kind::ApiKey);
    acme.credentials = vec![
        field("ACME_API_KEY", true, true, ""),
        field("ACME_REGION", false, false, "eu"),
    ];
    acme.fallback_models = vec!["acme-1".into(), "acme-2".into()];
    acme.models_dev_provider_id = "acme-dev".into();
    acme.metadata_source_provider = "openai".into();
    acme.model_registry_aliases = [("acme-1".to_owned(), "openai:gpt-4.1".to_owned())]
        .into_iter()
        .collect();
    acme.docs_url = "https://acme.example/keys".into();

    let mut sso = base("sso-corp", "Corp SSO", "Corporate gateway.", Kind::Oauth);
    sso.oauth_command = "evoflux auth sso-corp".into();

    let mut custom = base(
        "custom-check",
        "Custom check",
        "Has its own is_configured.",
        Kind::ApiKey,
    );
    custom.credentials = vec![
        field("CUSTOM_A", true, true, ""),
        field("CUSTOM_B", true, false, ""),
    ];
    custom.is_configured = Some(|lookup: &dyn CredentialLookup| {
        !lookup.stored("CUSTOM_A").is_empty() || !lookup.stored("CUSTOM_B").is_empty()
    });

    let mut shadow = base("openai", "Shadow", "Shadows a builtin id.", Kind::ApiKey);
    shadow.credentials = vec![field("SHADOW_KEY", true, true, "")];

    let mut shadow_catalog = base("302ai", "302 plugin", "Shadows a catalog id.", Kind::ApiKey);
    shadow_catalog.credentials = vec![field("PLUGIN_302_KEY", true, true, "")];

    vec![acme, sso, custom, shadow, shadow_catalog]
}

fn all_names(entries: &[sut::ProviderEntry]) -> Vec<String> {
    let mut names = Vec::new();
    for entry in entries {
        if !entry.env_var.is_empty() {
            names.push(entry.env_var.clone());
        }
        names.extend(entry.env_vars.iter().cloned());
        names.extend(entry.credentials.iter().map(|c| c.name.clone()));
    }
    names
}

type Pairs = Vec<(String, String)>;

fn env_map(spec: &Value, names: &[String]) -> EnvMap {
    let mut map = EnvMap::default();
    let (env, saved): (Pairs, Pairs) = match spec.as_str() {
        Some("ALL_ENV") => (
            names.iter().map(|n| (n.clone(), "v".into())).collect(),
            vec![],
        ),
        Some("ALL_SAVED") => (
            vec![],
            names.iter().map(|n| (n.clone(), "v".into())).collect(),
        ),
        _ => {
            let pairs = |key: &str| -> Vec<(String, String)> {
                spec.get(key)
                    .and_then(Value::as_object)
                    .map(|o| {
                        o.iter()
                            .map(|(k, v)| (k.clone(), v.as_str().unwrap_or_default().to_owned()))
                            .collect()
                    })
                    .unwrap_or_default()
            };
            (pairs("env"), pairs("saved"))
        }
    };
    map.environ.extend(env);
    map.saved.extend(saved);
    if let Some(files) = spec.get("files").and_then(Value::as_array) {
        map.cache_files
            .extend(files.iter().filter_map(Value::as_str).map(str::to_owned));
    }
    map
}

fn check_configured(catalog: &Catalog, section: &Value) {
    let scenarios = fixture()["scenarios"].as_object().expect("scenarios");
    let entries = catalog.all_providers(true);
    let names = all_names(&entries);
    let expected = section["configured"].as_object().expect("configured");
    assert_eq!(
        expected.keys().collect::<Vec<_>>(),
        scenarios.keys().collect::<Vec<_>>()
    );
    for (name, spec) in scenarios {
        let lookup = env_map(spec, &names);
        let table = expected[name].as_object().expect("table");
        assert_eq!(table.len(), entries.len(), "{name}: provider count");
        for entry in &entries {
            let want = table[&entry.id].as_bool().expect("bool");
            assert_eq!(
                catalog.is_entry_configured(entry, &lookup),
                want,
                "scenario {name}, provider {}",
                entry.id
            );
            assert_eq!(
                catalog.is_configured(&entry.id, &lookup),
                want,
                "{name}/{}",
                entry.id
            );
        }
    }
}

fn check_resolve(catalog: &Catalog, section: &Value) {
    for (id, expected) in section["resolve"].as_object().expect("resolve") {
        let actual = catalog.resolve_provider(id);
        assert_eq!(to_json(&actual), *expected, "resolve_provider({id:?})");
    }
}

fn check_helpers(catalog: &Catalog, section: &Value) {
    let configs = sut::provider_registry();
    let helpers = section["helpers"].as_object().expect("helpers");
    assert_eq!(helpers.len(), configs.len());
    for config in &configs {
        let want = &helpers[&config.id];
        let envelope = catalog
            .catalog_entry(config)
            .map_or_else(|| json!({}), |e| Value::Object(e.clone()));
        assert_eq!(
            envelope, want["catalog_entry"],
            "{} catalog_entry",
            config.id
        );
        assert_eq!(
            json!(catalog.catalog_base_url(config)),
            want["catalog_base_url"],
            "{} catalog_base_url",
            config.id
        );
        assert_eq!(
            json!(catalog.catalog_env_vars(config)),
            want["catalog_env_vars"],
            "{} catalog_env_vars",
            config.id
        );
        assert_eq!(
            json!(catalog.catalog_docs_url(config)),
            want["catalog_docs_url"],
            "{} catalog_docs_url",
            config.id
        );
        assert_eq!(
            json!(catalog.provider_label(config)),
            want["provider_label"],
            "{} provider_label",
            config.id
        );
        assert_eq!(
            to_json(&config.request_headers()),
            want["request_headers"],
            "{} request_headers",
            config.id
        );
    }
}

#[test]
fn registry_matches_python_for_every_provider_and_field() {
    let rows = to_json(&sut::provider_registry());
    assert_eq!(rows.as_array().map(Vec::len), Some(40));
    assert_rows("registry", &rows, &fixture()["registry"]);
}

#[test]
fn presentation_order_and_ids_match_python() {
    let f = fixture();
    assert_eq!(to_json(&sut::RECOMMENDED_PROVIDERS), f["recommended"]);
    assert_eq!(to_json(&sut::provider_ids()), f["provider_ids"]);
    for (id, want) in f["rank"].as_object().expect("rank") {
        assert_eq!(
            json!([sut::provider_rank(id), sut::is_recommended(id)]),
            *want,
            "rank of {id:?}"
        );
    }
    let npm: serde_json::Map<String, Value> = sut::NPM_TRANSPORTS
        .iter()
        .map(|(k, v)| ((*k).to_owned(), json!(v.as_str())))
        .collect();
    assert_eq!(Value::Object(npm), f["npm_transports"]);
    let python_order: Vec<&str> = f["npm_transports"]
        .as_object()
        .expect("npm")
        .keys()
        .map(String::as_str)
        .collect();
    let rust_order: Vec<&str> = sut::NPM_TRANSPORTS.iter().map(|(k, _)| *k).collect();
    assert_eq!(rust_order, python_order);
}

#[test]
fn transport_names_match_python_values() {
    for (name, transport) in [
        ("openai-completions", Transport::OpenaiCompletions),
        ("openai-responses", Transport::OpenaiResponses),
        ("anthropic", Transport::Anthropic),
        ("google-genai", Transport::GoogleGenai),
        ("google-vertex", Transport::GoogleVertex),
        ("bedrock", Transport::Bedrock),
        ("azure", Transport::Azure),
    ] {
        assert_eq!(transport.as_str(), name);
        assert_eq!(to_json(&transport), json!(name));
    }
    assert_eq!(sut::DEFAULT_TRANSPORT, Transport::OpenaiCompletions);
}

#[test]
fn per_model_routing_matches_python() {
    let routing = fixture()["routing"].as_object().expect("routing");
    for config in sut::provider_registry() {
        let want = &routing[&config.id];
        for (model, expected) in want["models"].as_object().expect("models") {
            let transport = config.transport_for_model(model).map(Transport::as_str);
            assert_eq!(
                json!([transport, config.uses_responses_api(model)]),
                *expected,
                "{} / {model:?}",
                config.id
            );
        }
        for (name, expected) in want["speaks"].as_object().expect("speaks") {
            let transport = [
                Transport::OpenaiCompletions,
                Transport::OpenaiResponses,
                Transport::Anthropic,
                Transport::GoogleGenai,
                Transport::GoogleVertex,
                Transport::Bedrock,
                Transport::Azure,
            ]
            .into_iter()
            .find(|t| t.as_str() == name)
            .expect("known transport");
            assert_eq!(
                json!(config.speaks(transport)),
                *expected,
                "{} speaks {name}",
                config.id
            );
        }
        assert_eq!(
            json!(config.models_dev_provider_id()),
            want["models_dev_provider_id"]
        );
    }
}

#[test]
fn custom_providers_match_python() {
    let want = fixture()["custom_provider"].as_array().expect("custom");
    let first = sut::custom_provider(
        "My-Prov.x",
        None,
        "http://x/v1",
        None,
        Transport::OpenaiCompletions,
    );
    let second = sut::custom_provider(
        " Lab ",
        Some("Lab"),
        "http://l",
        Some("LAB_KEY"),
        Transport::Anthropic,
    );
    assert_eq!(to_json(&first), want[0]);
    assert_eq!(to_json(&second), want[1]);
}

#[test]
fn bundled_catalog_matches_python() {
    let catalog = sut::catalog();
    let section = &fixture()["bundled"];
    assert_rows(
        "builtin",
        &to_json(&catalog.builtin_providers()),
        &section["builtin"],
    );
    assert_rows(
        "catalog",
        &to_json(&catalog.catalog_providers()),
        &section["catalog"],
    );
    assert_rows(
        "all",
        &to_json(&catalog.all_providers(true)),
        &section["all"],
    );
    assert_rows(
        "all_no_catalog",
        &to_json(&catalog.all_providers(false)),
        &section["all_no_catalog"],
    );
    assert_eq!(catalog.builtin_providers().len(), 40);
    assert_eq!(catalog.catalog_providers().len(), 161);
    assert_eq!(
        json!(catalog.all_provider_envelopes().len()),
        section["envelope_count"]
    );
    assert_eq!(to_json(&catalog.provider_key_vars()), section["key_vars"]);
    for (id, expected) in section["find"].as_object().expect("find") {
        assert_eq!(to_json(&catalog.find(id)), *expected, "find({id:?})");
    }
}

#[test]
fn bundled_lookups_match_python() {
    let catalog = sut::catalog();
    let section = &fixture()["bundled"];
    check_helpers(catalog, section);
    check_resolve(catalog, section);
}

#[test]
fn bundled_key_and_url_resolution_matches_python() {
    let catalog = sut::catalog();
    let registry = sut::provider_registry();
    let cases = fixture()["bundled"]["key_resolution"]
        .as_array()
        .expect("cases");
    assert!(cases.len() >= 17);
    for case in cases {
        let id = case["id"].as_str().expect("id");
        let config = registry.iter().find(|c| c.id == id).expect("curated");
        let lookup = env_map(&json!({"env": case["env"]}), &[]);
        let explicit_key = case["explicit_key"].as_str();
        let explicit_url = case["explicit_url"].as_str();
        assert_eq!(
            json!(catalog.resolve_api_key(config, explicit_key, &lookup)),
            case["api_key"],
            "api key for {case}"
        );
        assert_eq!(
            json!(catalog.resolve_base_url(config, explicit_url, &lookup)),
            case["base_url"],
            "base url for {case}"
        );
    }
}

#[test]
fn bundled_configured_matches_python_in_every_scenario() {
    check_configured(sut::catalog(), &fixture()["bundled"]);
}

#[test]
fn fetched_payload_merges_like_python() {
    let f = fixture();
    let catalog = Catalog::new(Some(&f["fetched_payload"]), Vec::new());
    let section = &f["fetched"];
    assert_rows(
        "builtin",
        &to_json(&catalog.builtin_providers()),
        &section["builtin"],
    );
    assert_rows(
        "catalog",
        &to_json(&catalog.catalog_providers()),
        &section["catalog"],
    );
    assert_rows(
        "all",
        &to_json(&catalog.all_providers(true)),
        &section["all"],
    );
    assert_eq!(
        json!(catalog.all_provider_envelopes().len()),
        section["envelope_count"]
    );
    let mut ids: Vec<&String> = catalog.all_provider_envelopes().keys().collect();
    ids.sort();
    assert_eq!(json!(ids), section["envelope_ids"]);
    for (id, expected) in section["entries"].as_object().expect("entries") {
        let actual = catalog
            .models_dev_provider_entry(id)
            .map_or(Value::Null, |e| Value::Object(e.clone()));
        // Python's lookup returns the stored envelope: the five kept fields.
        assert_eq!(actual, *expected, "models_dev_provider_entry({id:?})");
    }
    check_helpers(&catalog, section);
    check_resolve(&catalog, section);
}

#[test]
fn plugins_merge_like_python() {
    let catalog = Catalog::new(None, plugins());
    let section = &fixture()["plugins"];
    assert_rows(
        "all",
        &to_json(&catalog.all_providers(true)),
        &section["all"],
    );
    assert_rows(
        "all_no_catalog",
        &to_json(&catalog.all_providers(false)),
        &section["all_no_catalog"],
    );
    for (id, expected) in section["find"].as_object().expect("find") {
        assert_eq!(to_json(&catalog.find(id)), *expected, "find({id:?})");
    }
    check_configured(&catalog, section);
}

#[test]
fn the_first_plugin_with_an_id_wins() {
    let mut first = plugins().remove(0);
    first.label = "First".into();
    let mut second = plugins().remove(0);
    second.label = "Second".into();
    let catalog = Catalog::new(None, vec![first, second]);
    let rows = catalog.all_providers(false);
    let acme: Vec<_> = rows.iter().filter(|r| r.id == "acme").collect();
    assert_eq!(acme.len(), 1);
    assert_eq!(acme[0].label, "First");
}

#[test]
fn a_plugin_without_its_own_check_needs_every_required_field() {
    let catalog = Catalog::new(None, plugins());
    let mut map = EnvMap::default();
    assert!(!catalog.is_configured("acme", &map));
    map.saved.insert("ACME_REGION".into(), "eu".into());
    assert!(!catalog.is_configured("acme", &map));
    map.environ.insert("ACME_API_KEY".into(), "k".into());
    assert!(catalog.is_configured("acme", &map));
    assert!(!catalog.is_configured("no-such-provider", &map));
    // An OAuth plugin with no credentials has nothing required, so it is
    // configured as soon as it is installed.
    assert!(catalog.is_configured("sso-corp", &EnvMap::default()));
}

#[test]
fn unknown_provider_is_not_found_or_configured() {
    let catalog = sut::catalog();
    assert!(catalog.find("no-such-provider").is_none());
    assert!(!catalog.is_configured("no-such-provider", &EnvMap::default()));
}

#[test]
fn config_helpers_preserve_python_fallbacks_for_missing_and_malformed_metadata() {
    let f: Value =
        serde_json::from_str(include_str!("fixtures/python_helpers.json")).expect("helpers");
    let catalog = Catalog::new(Some(&f["payload"]), vec![]);
    assert_eq!(
        to_json(&sut::provider_envelopes(&f["payload"])),
        f["envelopes"]
    );
    let mut config = sut::custom_provider("empty-alias", None, "", None, sut::DEFAULT_TRANSPORT);
    config.models_dev_id = Some(String::new());
    assert_eq!(json!(config.models_dev_provider_id()), f["empty_alias"]);
    for case in f["cases"].as_array().expect("cases") {
        let id = case["id"].as_str().expect("id");
        let mut config = sut::custom_provider(id, None, "", None, sut::DEFAULT_TRANSPORT);
        config.label.clear();
        assert_eq!(json!(catalog.provider_label(&config)), case["label"]);
        assert_eq!(json!(catalog.catalog_docs_url(&config)), case["docs"]);
        assert_eq!(json!(catalog.catalog_env_vars(&config)), case["env"]);
        assert_eq!(
            json!(catalog.resolve_base_url(&config, None, &EnvMap::default())),
            case["base_url"]
        );
    }
}

#[test]
fn config_from_models_dev_rejects_unusable_envelopes() {
    let obj = |v: Value| v.as_object().cloned().expect("object");
    let ok = obj(json!({"api": "https://x/v1", "env": ["X_KEY"], "name": "X"}));
    assert!(sut::config_from_models_dev("x", &ok).is_some());
    assert!(sut::config_from_models_dev("x", &obj(json!({"env": ["X_KEY"]}))).is_none());
    assert!(sut::config_from_models_dev("x", &obj(json!({"api": "  ", "env": ["X"]}))).is_none());
    assert!(sut::config_from_models_dev(
        "x",
        &obj(json!({"api": "https://${A}/v1", "env": ["X"]}))
    )
    .is_none());
    assert!(sut::config_from_models_dev("x", &obj(json!({"api": "https://x"}))).is_none());
    assert!(
        sut::config_from_models_dev("x", &obj(json!({"api": "https://x", "env": []}))).is_none()
    );
    assert!(
        sut::config_from_models_dev("x", &obj(json!({"api": "https://x", "env": [""]}))).is_none()
    );
    assert!(
        sut::config_from_models_dev("x", &obj(json!({"api": "https://x", "env": [3]}))).is_none()
    );
    let nameless =
        sut::config_from_models_dev(" Orig ", &obj(json!({"api": "https://x", "env": ["K"]})))
            .expect("config");
    assert_eq!(nameless.label, " Orig ");
    assert_eq!(nameless.id, "orig");
}

#[test]
fn transport_for_npm_defaults() {
    assert_eq!(sut::transport_for_npm(None), Transport::OpenaiCompletions);
    assert_eq!(
        sut::transport_for_npm(Some("")),
        Transport::OpenaiCompletions
    );
    assert_eq!(
        sut::transport_for_npm(Some("unknown")),
        Transport::OpenaiCompletions
    );
    assert_eq!(
        sut::transport_for_npm(Some("@ai-sdk/anthropic")),
        Transport::Anthropic
    );
    assert_eq!(
        sut::transport_for_npm(Some("@ai-sdk/google-vertex")),
        Transport::GoogleVertex
    );
}

#[test]
fn derived_base_url_names_follow_python() {
    assert_eq!(
        sut::derived_base_url_env_var("opencode-go"),
        "OPENCODE_GO_BASE_URL"
    );
    assert_eq!(sut::derived_base_url_env_var("a.b-c"), "A_B_C_BASE_URL");
    assert!(sut::get_provider_config(" OpenAI ").is_some());
    assert!(sut::get_provider_config("nope").is_none());
}

#[test]
fn provider_envelopes_extract_only_the_kept_fields() {
    let payload = json!({
        "Alpha": {"id": "ALPHA", "name": "A", "env": ["A"], "extra": 1, "models": {}},
        "beta": {"name": "B"},
        "gamma": 3,
        "delta": {"id": "", "npm": "n"}
    });
    let out = sut::provider_envelopes(&payload);
    assert_eq!(out.keys().collect::<Vec<_>>(), ["alpha", "beta", "delta"]);
    assert_eq!(
        Value::Object(out["alpha"].clone()),
        json!({"id": "alpha", "name": "A", "env": ["A"]})
    );
    assert_eq!(
        Value::Object(out["beta"].clone()),
        json!({"id": "beta", "name": "B"})
    );
    assert_eq!(
        Value::Object(out["delta"].clone()),
        json!({"id": "delta", "npm": "n"})
    );
    assert!(sut::provider_envelopes(&json!([1, 2])).is_empty());
}

#[test]
fn provider_envelope_ids_use_python_truthiness_and_string_conversion() {
    for case in fixture()["edge_envelopes"].as_array().expect("edge cases") {
        assert_eq!(
            to_json(&sut::provider_envelopes(&case["input"])),
            case["expected"]
        );
    }
}

#[test]
#[allow(clippy::disallowed_methods)]
fn bundled_data_is_a_byte_copy_of_the_python_package_files() {
    let root =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../app/agent/providers");
    let catalog =
        std::fs::read_to_string(root.join("provider_catalog.json")).expect("python catalog");
    assert_eq!(
        sut::bundled_provider_catalog_json().replace("\r\n", "\n"),
        catalog.replace("\r\n", "\n"),
        "refresh data/provider_catalog.json from app/agent/providers/"
    );
    let registry =
        std::fs::read_to_string(root.join("model_registry.json")).expect("python registry");
    assert_eq!(
        sut::bundled_model_registry_json().replace("\r\n", "\n"),
        registry.replace("\r\n", "\n"),
        "refresh data/model_registry.json from app/agent/providers/"
    );
}

#[test]
fn bundled_model_registry_parses_and_is_keyed_by_provider_and_model() {
    let registry = sut::bundled_model_registry();
    assert!(registry.len() > 1000, "{} models", registry.len());
    assert!(registry.keys().all(|key| key.contains(':')));
    assert!(registry.contains_key("302ai:chatgpt-4o-latest"));
}

#[test]
fn bundled_provider_envelopes_are_well_formed() {
    let catalog = sut::catalog();
    assert_eq!(catalog.all_provider_envelopes().len(), 212);
    for (id, envelope) in catalog.all_provider_envelopes() {
        assert_eq!(
            envelope.get("id").and_then(Value::as_str),
            Some(id.as_str())
        );
        assert_eq!(*id, id.to_lowercase());
    }
}

#[test]
fn model_less_provider_config_is_a_clone_safe_value() {
    let configs: Vec<ProviderConfig> = sut::provider_registry();
    assert_eq!(configs, sut::provider_registry());
}
