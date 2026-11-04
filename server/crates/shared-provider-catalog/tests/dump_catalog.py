"""Dump the Python provider catalog to JSON for the Rust differential tests.

Run from the repository root with the project environment::

    uv run python server/crates/shared-provider-catalog/tests/dump_catalog.py \
        --fixture server/crates/shared-provider-catalog/tests/fixtures/python_catalog.json
    uv run python server/crates/shared-provider-catalog/tests/dump_catalog.py \
        --tables server/crates/shared-provider-catalog/src

``--fixture`` writes the oracle the Rust tests compare against. ``--tables``
regenerates ``registry_table.rs`` and ``overrides_table.rs`` from
``PROVIDER_REGISTRY`` and ``_OVERRIDES``. Both run against an empty temporary
config and cache directory so no user state leaks in.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="evoflux-catalog-"))
CONFIG = TMP / "config"
CACHE = TMP / "cache"
CONFIG.mkdir()
CACHE.mkdir()
os.environ["EVOFLUX_CONFIG_DIR"] = str(CONFIG)
os.environ["EVOFLUX_CACHE_DIR"] = str(CACHE)
os.environ["EVOFLUX_DATA_DIR"] = str(TMP / "data")
os.environ["EVOFLUX_STATE_DIR"] = str(TMP / "state")
os.environ["EVOFLUX_WORKSPACE_DIR"] = str(TMP / "workspace")
os.environ["EVOFLUX_MODEL_REGISTRY_REFRESH"] = "false"
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from app.agent.providers import catalog as cat  # noqa: E402
from app.agent.providers import model_registry as mr  # noqa: E402
from app.agent.providers import plugin_registry as pr  # noqa: E402
from app.agent.providers import registry as reg  # noqa: E402
from app.agent.providers.plugin_api import (  # noqa: E402
    ProviderCredentialField,
    ProviderPlugin,
)
from app.api.routes import settings as routes  # noqa: E402


def config_dict(config: reg.ProviderConfig) -> dict:
    return {
        "id": config.id,
        "label": config.label,
        "transport": str(config.transport),
        "env_var": config.env_var,
        "base_url": config.base_url,
        "base_url_env_var": config.base_url_env_var,
        "models_dev_id": config.models_dev_id,
        "attribution_headers": config.attribution_headers,
        "extra_headers": config.extra_headers,
        "default_api_key": config.default_api_key,
        "responses_models": list(config.responses_models),
        "auth": config.auth,
        "docs_url": config.docs_url,
        "extra_transports": [str(t) for t in config.extra_transports],
        "model_transports": [[p, str(t)] for p, t in config.model_transports],
        "browser_login": config.browser_login,
    }


def fresh() -> None:
    mr.reset_catalog_caches()


def plugins() -> dict[str, ProviderPlugin]:
    def field(name, secret=True, required=True, label=None, placeholder=""):
        return ProviderCredentialField(
            name=name,
            label=label or name,
            secret=secret,
            required=required,
            placeholder=placeholder,
        )

    def build(ctx):  # never called
        return None

    return {
        "acme": ProviderPlugin(
            id="acme",
            label="Acme AI",
            description="Acme hosted models.",
            kind="api_key",
            factory=build,
            credentials=[
                field("ACME_API_KEY"),
                field("ACME_REGION", secret=False, required=False, placeholder="eu"),
            ],
            fallback_models=["acme-1", "acme-2"],
            models_dev_provider_id="acme-dev",
            metadata_source_provider="openai",
            model_registry_aliases={"acme-1": "openai:gpt-4.1"},
            docs_url="https://acme.example/keys",
            oauth_command="",
        ),
        "sso-corp": ProviderPlugin(
            id="sso-corp",
            label="Corp SSO",
            description="Corporate gateway.",
            kind="oauth",
            factory=build,
            credentials=[],
            login=lambda sink: None,
            oauth_command="evoflux auth sso-corp",
        ),
        "custom-check": ProviderPlugin(
            id="custom-check",
            label="Custom check",
            description="Has its own is_configured.",
            kind="api_key",
            factory=build,
            credentials=[field("CUSTOM_A"), field("CUSTOM_B", required=False)],
            is_configured=lambda store: bool(
                store.get("CUSTOM_A") or store.get("CUSTOM_B")
            ),
        ),
        # Same id as a curated provider: the curated row wins in the list, but
        # the configured check still goes through the plugin.
        "openai": ProviderPlugin(
            id="openai",
            label="Shadow",
            description="Shadows a builtin id.",
            kind="api_key",
            factory=build,
            credentials=[field("SHADOW_KEY")],
        ),
        # Same id as a models.dev long-tail provider: appears as a plugin and
        # the catalog row is dropped.
        "302ai": ProviderPlugin(
            id="302ai",
            label="302 plugin",
            description="Shadows a catalog id.",
            kind="api_key",
            factory=build,
            credentials=[field("PLUGIN_302_KEY")],
        ),
    }


FETCHED = {
    # Overrides a bundled long-tail provider in place.
    "302ai": {
        "id": "302AI",
        "name": "302.AI renamed",
        "env": ["FETCHED_302_KEY", "FETCHED_302_EXTRA"],
        "npm": "@ai-sdk/anthropic",
        "api": "https://api.fetched.example/v1/",
        "doc": "https://doc.fetched.example",
        "models": {"ignored": {"id": "ignored"}},
    },
    # A brand-new long-tail provider.
    "freshly-added": {
        "name": "Freshly Added",
        "env": ["FRESH_API_KEY"],
        "npm": "@ai-sdk/openai",
        "api": "https://fresh.example/api",
        "doc": "https://fresh.example/docs",
    },
    # Id taken from the key when the id field is empty; no env at all.
    "no-env": {"id": "", "name": "No Env", "api": "https://noenv.example/v1"},
    # Templated endpoint: unreachable without a form.
    "templated": {
        "id": "templated",
        "name": "Templated",
        "env": ["TPL_KEY"],
        "api": "https://${TPL_ACCOUNT}.example/v1",
    },
    # No endpoint.
    "no-api": {"id": "no-api", "name": "No API", "env": ["NOAPI_KEY"]},
    # Base-url variable already among env names; blank name falls back to id.
    "has-base": {
        "id": "has-base",
        "name": "",
        "env": ["HAS_BASE_URL", "HAS_BASE_KEY", "", 7],
        "npm": "venice-ai-sdk-provider",
        "api": "  https://has-base.example/v1  ",
        "doc": 3,
    },
    # A curated provider's catalog row refreshed: curated description follows.
    "google": {
        "id": "google",
        "name": "Google",
        "env": ["GOOGLE_GENERATIVE_AI_API_KEY"],
        "npm": "@ai-sdk/google",
        "api": "https://generativelanguage.example/v1beta",
        "doc": "https://ai.google.dev",
    },
    "ignored-not-a-dict": 5,
}

SCENARIOS = {
    "empty": {},
    "openai_env": {"env": {"OPENAI_API_KEY": "sk"}},
    "openai_saved": {"saved": {"OPENAI_API_KEY": "sk"}},
    "empty_values": {
        "env": {"OPENAI_API_KEY": ""},
        "saved": {"OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": ""},
    },
    "env_empty_saved_set": {
        "env": {"ANTHROPIC_API_KEY": ""},
        "saved": {"ANTHROPIC_API_KEY": "k"},
    },
    "copilot_gh": {"env": {"GH_TOKEN": "t"}},
    "copilot_github_token": {"env": {"GITHUB_TOKEN": "t"}},
    "copilot_copilot_token": {"env": {"COPILOT_GITHUB_TOKEN": "t"}},
    "copilot_copilot_alt": {"env": {"GITHUB_COPILOT_TOKEN": "t"}},
    "oauth_files": {"files": ["codex_oauth.json", "copilot_oauth.json"]},
    "oauth_codex_only": {"files": ["codex_oauth.json"]},
    "oauth_dir_not_file": {"dirs": ["codex_oauth.json"]},
    "foundry_key_only": {"env": {"FOUNDRY_API_KEY": "k"}},
    "foundry_both_split": {
        "env": {"FOUNDRY_API_KEY": "k"},
        "saved": {"FOUNDRY_RESOURCE_NAME": "r"},
    },
    "foundry_saved_both": {
        "saved": {"FOUNDRY_API_KEY": "k", "FOUNDRY_RESOURCE_NAME": "r"}
    },
    "foundry_name_only": {"env": {"FOUNDRY_RESOURCE_NAME": "r"}},
    "bedrock_profile_env": {"env": {"AWS_BEDROCK_PROFILE": "p"}},
    "bedrock_profile_saved": {"saved": {"AWS_BEDROCK_PROFILE": "p"}},
    "bedrock_keys_split": {
        "saved": {"AWS_ACCESS_KEY_ID": "a"},
        "env": {"AWS_SECRET_ACCESS_KEY": "s"},
    },
    "bedrock_keys_env": {
        "env": {"AWS_ACCESS_KEY_ID": "a", "AWS_SECRET_ACCESS_KEY": "s"}
    },
    "bedrock_access_only": {"env": {"AWS_ACCESS_KEY_ID": "a"}},
    "bedrock_secret_only": {"saved": {"AWS_SECRET_ACCESS_KEY": "s"}},
    "vertex_env": {"env": {"VERTEXAI_API_KEY": "k"}},
    "vertex_saved_only": {"saved": {"VERTEXAI_API_KEY": "k"}},
    "plugin_acme_saved": {"saved": {"ACME_API_KEY": "k"}},
    "plugin_acme_region_only": {"env": {"ACME_REGION": "eu"}},
    "plugin_custom_a": {"saved": {"CUSTOM_A": "x"}},
    "plugin_custom_b": {"env": {"CUSTOM_B": "x"}},
    "plugin_shadow": {"env": {"SHADOW_KEY": "x"}},
    "plugin_302": {"saved": {"PLUGIN_302_KEY": "x"}},
    "plugin_openai_real_key": {"env": {"OPENAI_API_KEY": "sk"}},
    "all_env": "ALL_ENV",
    "all_saved": "ALL_SAVED",
}

MANAGED = {
    "COPILOT_GITHUB_TOKEN",
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GITHUB_COPILOT_TOKEN",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_BASE_URL",
    "DEEPSEEK_BASE_URL",
    "OLLAMA_API_KEY",
    "KIMI_API_KEY",
    "MOONSHOT_API_KEY",
}


def all_names(entries) -> set[str]:
    names: set[str] = set()
    for entry in entries:
        if entry.get("env_var"):
            names.add(entry["env_var"])
        names.update(entry.get("env_vars") or [])
        for cred in entry.get("credentials") or []:
            names.add(cred["name"])
    return names


TOUCHED: set[str] = set()


def apply_scenario(spec, names: set[str]) -> None:
    for key in list(os.environ):
        if key in names or key in MANAGED or key in TOUCHED:
            del os.environ[key]
    env_file = CONFIG / ".env"
    if env_file.exists():
        env_file.unlink()
    for child in CACHE.iterdir():
        if child.name.endswith("_oauth.json"):
            if child.is_dir():
                child.rmdir()
            else:
                child.unlink()
    if spec == "ALL_ENV":
        spec = {"env": {n: "v" for n in names}}
    elif spec == "ALL_SAVED":
        spec = {"saved": {n: "v" for n in names}}
    for key, value in (spec.get("env") or {}).items():
        os.environ[key] = value
        TOUCHED.add(key)
    saved = spec.get("saved") or {}
    if saved:
        env_file.write_text(
            "".join(f"{k}={v}\n" for k, v in saved.items()), encoding="utf-8"
        )
    for name in spec.get("files") or []:
        (CACHE / name).write_text("{}", encoding="utf-8")
    for name in spec.get("dirs") or []:
        (CACHE / name).mkdir()


def install_plugins(on: bool) -> None:
    pr._PLUGIN_CACHE = plugins() if on else {}


def configured_table(entries, names) -> dict:
    table = {}
    for name, spec in SCENARIOS.items():
        apply_scenario(spec, names)
        table[name] = {
            entry["id"]: routes._provider_is_configured(entry) for entry in entries
        }
    apply_scenario({}, names)
    return table


def resolve_samples() -> dict:
    out = {}
    for pid in [
        "openai",
        " OpenAI ",
        "ANTHROPIC",
        "302ai",
        "freshly-added",
        "has-base",
        "no-env",
        "templated",
        "no-api",
        "unknown",
        "",
        "  ",
        "google",
        "aihubmix",
        "cloudflare-workers-ai",
    ]:
        config = reg.resolve_provider(pid)
        out[pid] = None if config is None else config_dict(config)
    return out


def helper_table() -> dict:
    out = {}
    for pid, config in reg.PROVIDER_REGISTRY.items():
        out[pid] = {
            "catalog_entry": reg.catalog_entry(config),
            "catalog_base_url": reg.catalog_base_url(config),
            "catalog_env_vars": list(reg.catalog_env_vars(config)),
            "catalog_docs_url": reg.catalog_docs_url(config),
            "provider_label": reg.provider_label(config),
            "request_headers": reg.request_headers(config),
        }
    return out


def key_resolution() -> list:
    cases = []
    specs = [
        ("openai", {}, None, None),
        ("openai", {"OPENAI_API_KEY": "e"}, None, None),
        ("openai", {"OPENAI_API_KEY": "e"}, "explicit", None),
        ("openai", {"OPENAI_API_KEY": ""}, "", None),
        ("openai", {"OPENAI_BASE_URL": "  http://env/  "}, None, None),
        ("openai", {"OPENAI_BASE_URL": "   "}, None, None),
        ("openai", {"OPENAI_BASE_URL": "http://env"}, None, "  http://explicit  "),
        ("openai", {}, None, "   "),
        ("ollama", {}, None, None),
        ("ollama", {"OLLAMA_API_KEY": "mine"}, None, None),
        ("kimi", {"KIMI_API_KEY": "catalog-name"}, None, None),
        (
            "kimi",
            {"MOONSHOT_API_KEY": "own", "KIMI_API_KEY": "catalog-name"},
            None,
            None,
        ),
        ("deepseek", {}, None, None),
        ("deepseek", {"DEEPSEEK_BASE_URL": "http://ds"}, None, None),
        ("copilot", {}, None, None),
        ("bedrock", {}, None, None),
        ("router9", {}, None, None),
    ]
    for pid, env, explicit_key, explicit_url in specs:
        apply_scenario({"env": env}, set())
        config = reg.PROVIDER_REGISTRY[pid]
        cases.append(
            {
                "id": pid,
                "env": env,
                "explicit_key": explicit_key,
                "explicit_url": explicit_url,
                "api_key": reg.resolve_api_key(config, explicit=explicit_key),
                "base_url": reg.resolve_base_url(config, explicit=explicit_url),
            }
        )
    apply_scenario({}, set())
    return cases


def routing_table() -> dict:
    models = [
        "claude-3",
        "CLAUDE-opus",
        "GPT-5-mini",
        "gpt-6",
        "gemini-2",
        "qwen3.8-flash",
        "qwen3.8-max",
        "qwen3.7-plus",
        "grok-4",
        "muse-spark-1",
        "minimax-m2",
        "o3",
        "",
    ]
    out = {}
    for pid, config in reg.PROVIDER_REGISTRY.items():
        row = {}
        for model in models:
            transport = config.transport_for_model(model)
            row[model] = [
                None if transport is None else str(transport),
                config.uses_responses_api(model),
            ]
        out[pid] = {
            "models": row,
            "speaks": {str(t): config.speaks(t) for t in reg.Transport},
            "models_dev_provider_id": config.models_dev_provider_id,
        }
    return out


def dump() -> dict:
    out: dict = {}
    edge_payloads = [
        {"numeric": {"id": 123, "api": "https://x", "env": ["X"]}},
        {"boolean": {"id": True, "api": "https://x", "env": ["X"]}},
        {"zero": {"id": 0}},
        {"false": {"id": False}},
        {"empty": {"id": []}},
    ]
    out["edge_envelopes"] = [
        {"input": payload, "expected": mr.provider_envelopes(payload)}
        for payload in edge_payloads
    ]
    fresh()
    install_plugins(False)
    out["registry"] = [config_dict(c) for c in reg.PROVIDER_REGISTRY.values()]
    out["recommended"] = list(reg.RECOMMENDED_PROVIDERS)
    out["provider_ids"] = list(reg.provider_ids())
    out["rank"] = {
        pid: [reg.provider_rank(pid), reg.is_recommended(pid)]
        for pid in [
            "xiaomi",
            "anthropic",
            "codex",
            "zai",
            "qwencloud",
            " XIAOMI ",
            "ollama",
            "",
            "nope",
        ]
    }
    out["routing"] = routing_table()
    out["scenarios"] = SCENARIOS
    out["npm_transports"] = {k: str(v) for k, v in reg.NPM_TRANSPORTS.items()}
    out["custom_provider"] = [
        config_dict(reg.custom_provider("My-Prov.x", base_url="http://x/v1")),
        config_dict(
            reg.custom_provider(
                " Lab ",
                label="Lab",
                base_url="http://l",
                env_var="LAB_KEY",
                transport=reg.Transport.ANTHROPIC,
            )
        ),
    ]
    out["bundled"] = {
        "helpers": helper_table(),
        "resolve": resolve_samples(),
        "builtin": cat.builtin_providers(),
        "catalog": cat.catalog_providers(),
        "all": cat.all_providers(),
        "all_no_catalog": cat.all_providers(include_catalog=False),
        "key_vars": cat.provider_key_vars(),
        "find": {
            pid: cat.find(pid)
            for pid in ["openai", "codex", "aihubmix", "302ai", "nope", "OpenAI", ""]
        },
        "envelope_count": len(mr.all_provider_envelopes()),
        "key_resolution": key_resolution(),
    }
    names = all_names(cat.all_providers())
    out["bundled"]["configured"] = configured_table(cat.all_providers(), names)

    # Fetched models.dev payload on top of the bundled envelopes, no plugins.
    (CACHE / "models-dev.json").write_text(json.dumps(FETCHED), encoding="utf-8")
    fresh()
    out["fetched_payload"] = FETCHED
    out["fetched"] = {
        "helpers": helper_table(),
        "resolve": resolve_samples(),
        "builtin": cat.builtin_providers(),
        "catalog": cat.catalog_providers(),
        "all": cat.all_providers(),
        "envelope_count": len(mr.all_provider_envelopes()),
        "envelope_ids": sorted(mr.all_provider_envelopes()),
        "entries": {
            pid: mr.models_dev_provider_entry(pid)
            for pid in [
                "302ai",
                " 302AI ",
                "freshly-added",
                "no-env",
                "has-base",
                "google",
                "nope",
                "",
            ]
        },
    }
    (CACHE / "models-dev.json").unlink()

    # Plugins on top of the bundled data.
    fresh()
    install_plugins(True)
    out["plugins"] = {
        "all": cat.all_providers(),
        "all_no_catalog": cat.all_providers(include_catalog=False),
        "find": {pid: cat.find(pid) for pid in ["acme", "sso-corp", "openai", "302ai"]},
    }
    names = all_names(cat.all_providers())
    out["plugins"]["configured"] = configured_table(cat.all_providers(), names)
    install_plugins(False)
    return out


def rust_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def rust_opt(s) -> str:
    return "None" if s is None else f"Some({rust_str(s)})"


def rust_strs(items) -> str:
    return "&[" + ", ".join(rust_str(i) for i in items) + "]"


def rust_pairs(items) -> str:
    return "&[" + ", ".join(f"({rust_str(a)}, {rust_str(b)})" for a, b in items) + "]"


TRANSPORT_VARIANT = {
    "openai-completions": "OpenaiCompletions",
    "openai-responses": "OpenaiResponses",
    "anthropic": "Anthropic",
    "google-genai": "GoogleGenai",
    "google-vertex": "GoogleVertex",
    "bedrock": "Bedrock",
    "azure": "Azure",
}

AUTH_VARIANT = {
    "api_key": "ApiKey",
    "oauth": "Oauth",
    "cloud": "Cloud",
    "local": "Local",
}

KIND_VARIANT = {
    "api_key": "ApiKey",
    "oauth": "Oauth",
    "local": "Local",
    "cloud_creds": "CloudCreds",
}


def gen_registry() -> str:
    lines = [
        "//! Generated from `PROVIDER_REGISTRY` in `app/agent/providers/registry.py`",
        "//! by `tests/dump_catalog.py --tables`. Do not edit by hand.",
        "",
        "use crate::registry::{AuthKind, ConfigRow, Transport};",
        "",
        "pub(crate) const PROVIDER_TABLE: &[ConfigRow] = &[",
    ]
    for config in reg.PROVIDER_REGISTRY.values():
        d = config_dict(config)
        extra = ", ".join(
            f"Transport::{TRANSPORT_VARIANT[x]}" for x in d["extra_transports"]
        )
        mt = ", ".join(
            f"({rust_str(p)}, Transport::{TRANSPORT_VARIANT[x]})"
            for p, x in d["model_transports"]
        )
        lines += [
            "    ConfigRow {",
            f"        id: {rust_str(d['id'])},",
            f"        label: {rust_str(d['label'])},",
            f"        transport: Transport::{TRANSPORT_VARIANT[d['transport']]},",
            f"        env_var: {rust_str(d['env_var'])},",
            f"        base_url: {rust_str(d['base_url'])},",
            f"        base_url_env_var: {rust_opt(d['base_url_env_var'])},",
            f"        models_dev_id: {rust_opt(d['models_dev_id'])},",
            "        attribution_headers: "
            f"{rust_pairs(d['attribution_headers'].items())},",
            f"        extra_headers: {rust_pairs(d['extra_headers'].items())},",
            f"        default_api_key: {rust_str(d['default_api_key'])},",
            f"        responses_models: {rust_strs(d['responses_models'])},",
            f"        auth: AuthKind::{AUTH_VARIANT[d['auth']]},",
            f"        docs_url: {rust_str(d['docs_url'])},",
            f"        extra_transports: &[{extra}],",
            f"        model_transports: &[{mt}],",
            f"        browser_login: {'true' if d['browser_login'] else 'false'},",
            "    },",
        ]
    lines += ["];", ""]
    return "\n".join(lines)


def gen_overrides() -> str:
    lines = [
        "//! Generated from `_OVERRIDES` in `app/agent/providers/catalog.py`",
        "//! by `tests/dump_catalog.py --tables`. Do not edit by hand.",
        "",
        "use crate::catalog::{CredentialRow, Kind, Override};",
        "",
        "pub(crate) const OVERRIDES: &[(&str, Override)] = &[",
    ]
    for pid, ov in cat._OVERRIDES.items():
        fields = []
        for key, value in ov.items():
            if key == "description":
                fields.append(f"description: Some({rust_str(value)})")
            elif key == "kind":
                fields.append(f"kind: Some(Kind::{KIND_VARIANT[value]})")
            elif key == "fallback_models":
                fields.append(f"fallback_models: Some({rust_strs(value)})")
            elif key == "oauth_command":
                fields.append(f"oauth_command: Some({rust_str(value)})")
            elif key == "metadata_source_provider":
                fields.append(f"metadata_source_provider: Some({rust_str(value)})")
            elif key == "metadata_source_exclude":
                fields.append(f"metadata_source_exclude: Some({rust_strs(value)})")
            elif key == "model_registry_aliases":
                fields.append(
                    f"model_registry_aliases: Some({rust_pairs(value.items())})"
                )
            elif key == "live_model_metadata":
                fields.append(f"live_model_metadata: Some({str(value).lower()})")
            elif key == "auto_connect":
                fields.append(f"auto_connect: Some({str(value).lower()})")
            elif key == "credentials":
                creds = ", ".join(
                    "CredentialRow { name: %s, label: %s, secret: %s, "
                    "required: %s, placeholder: %s }"
                    % (
                        rust_str(c["name"]),
                        rust_str(c["label"]),
                        str(c["secret"]).lower(),
                        str(c["required"]).lower(),
                        rust_str(c["placeholder"]),
                    )
                    for c in value
                )
                fields.append(f"credentials: Some(&[{creds}])")
            else:
                raise SystemExit(f"unhandled override key {key}")
        lines.append(
            f"    ({rust_str(pid)}, Override {{ {', '.join(fields)}, ..Override::EMPTY }}),"
        )
    lines += ["];", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture")
    parser.add_argument("--tables")
    parser.add_argument("--helpers")
    args = parser.parse_args()
    if args.helpers:
        from dataclasses import replace

        payload = {
            "catalog-named": {
                "name": "Catalog name",
                "doc": "  https://docs  ",
                "env": ["", "ALT_KEY", 3],
                "api": "  https://api  ",
            },
            "blank-label": {"name": "", "api": "https://${HOST}"},
            "non-string": {"name": 7, "doc": 3, "api": 5, "env": "BAD"},
            "alias": {"id": "DIFFERENT-ID", "api": "https://alias", "env": ["A"]},
        }
        (CACHE / "models-dev.json").write_text(json.dumps(payload), encoding="utf-8")
        fresh()
        cases = []
        for pid in [*payload, "unknown"]:
            config = replace(reg.custom_provider(pid, base_url=""), label="")
            cases.append(
                {
                    "id": pid,
                    "label": reg.provider_label(config),
                    "docs": reg.catalog_docs_url(config),
                    "env": list(reg.catalog_env_vars(config)),
                    "base_url": reg.resolve_base_url(config),
                }
            )
        Path(args.helpers).write_text(
            json.dumps(
                {
                    "payload": payload,
                    "cases": cases,
                    "envelopes": mr.provider_envelopes(payload),
                    "empty_alias": replace(
                        reg.custom_provider("empty-alias", base_url=""),
                        models_dev_id="",
                    ).models_dev_provider_id,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    if args.fixture:
        Path(args.fixture).write_text(
            json.dumps(dump(), ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
    if args.tables:
        base = Path(args.tables)
        (base / "registry_table.rs").write_text(gen_registry(), encoding="utf-8")
        (base / "overrides_table.rs").write_text(gen_overrides(), encoding="utf-8")


if __name__ == "__main__":
    main()
