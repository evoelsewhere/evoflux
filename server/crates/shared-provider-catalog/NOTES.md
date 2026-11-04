# Shared provider catalog (P-004)

Port of `app/agent/providers/catalog.py`, the declarative/lookup portions of
`registry.py` and `model_registry.py`, and `_provider_is_configured` in
`app/api/routes/settings.py`. No filesystem, environment, network, process,
or installed-plugin discovery happens in this crate. Callers inject fetched
JSON, plugin descriptors and a `CredentialLookup` (process env, saved dotenv,
and OAuth cache-file presence). The default catalog uses bundled data only.

## Contract

- `catalog()` is a shared offline catalog. `Catalog::new` overlays fetched
  provider envelopes on the bundle; replacement retains insertion position.
- Curated rows win over plugins, plugins win over long-tail rows; long-tail
  rows are sorted by id and exclude curated ids, aliases and overrides.
- `find` is exact/case sensitive. Registry resolution trims and lowercases.
- Every provider field, omission vs null, credential order, fallback model,
  recommendation, transport and alias is compared against Python JSON.
- Configured checks preserve local optimism, OAuth token-file presence,
  Copilot env fallback, Foundry saved credentials and Bedrock profile-or-pair.
  A plugin's configured callback wins even when a builtin shadows its row.
- Model metadata is embedded unchanged, exposed as raw JSON and a parsed map.
  This task does not port model capability normalization, live refresh,
  user YAML overlays or OAuth/plugin execution; those stay in their owners.

## Bundles and refresh

`data/provider_catalog.json`: 42,254 bytes, 212 provider envelopes.
`data/model_registry.json`: 4,463,354 bytes of flattened provider:model metadata.
The settings catalog has 40 builtin and 161 usable long-tail rows (201 total).
Upstream is `https://models.dev/api.json`. The repository refresh source is
`scripts/update_model_registry.py`; refresh Python's two bundles there first,
then copy the two files from `app/agent/providers/` into `data/` here. The Rust
byte-copy test detects drift (normalizing Git's Windows CRLF only). Do not
fetch from the network during tests or catalog access.

Regenerate the Python oracle from the repository root:

```powershell
uv run python server/crates/shared-provider-catalog/tests/dump_catalog.py --fixture server/crates/shared-provider-catalog/tests/fixtures/python_catalog.json
uv run python server/crates/shared-provider-catalog/tests/dump_catalog.py --tables server/crates/shared-provider-catalog/src
uv run python server/crates/shared-provider-catalog/tests/dump_catalog.py --helpers server/crates/shared-provider-catalog/tests/fixtures/python_helpers.json
```

The script creates isolated config/cache folders, disables refresh, substitutes
fixture plugins and uses synthetic values. It never reads installed credentials.
The first command records behavior; the second regenerates declarative tables;
the third records config-helper fallbacks under missing/malformed metadata.

## Python test map

`tests/agent/providers/test_catalog.py` (21 parametrized cases):

| Python cases | Rust proof in tests/parity.rs |
|---|---|
| every_registry_provider_gets_a_row, connection_facts_come_from_the_registry | registry_matches_python_for_every_provider_and_field, bundled_catalog_matches_python |
| overrides_never_restate_a_derivable_fact | n/a: Python source-table maintenance rule; generated tables are copied from that oracle |
| a_hand_written_description_wins, a_missing_description_is_derived_not_blank | bundled_catalog_matches_python (every field) |
| credentials_are_generated_from_the_registry, a_cloud_provider_keeps_its_hand_written_form, env_vars_mirror_the_credential_form | bundled_catalog_matches_python |
| a_rename_is_only_claimed_when_the_id_is_free, a_genuine_rename_is_claimed | bundled_catalog_matches_python (optional alias fields) |
| openai_models_survive_codex_being_configured | n/a: merged capability/model-registry aliasing belongs to model metadata, outside provider catalog; bundled bytes remain identical |
| the_catalog_tier_excludes_curated_providers, no_duplicate_rows | bundled_catalog_matches_python, plugins_merge_like_python |
| the_long_tail_is_not_auto_connected, curated_providers_keep_their_connect_behaviour | bundled_catalog_matches_python |
| unusable_envelopes_are_not_listed (4), a_usable_envelope_becomes_a_row | fetched_payload_merges_like_python, config_from_models_dev_rejects_unusable_envelopes |
| a_secret_looking_variable_is_masked | bundled_catalog_matches_python, fetched_payload_merges_like_python |

Additional differential tests cover configured checks under 33 environments,
plugins, recommendation order, all registry transports and model dispatch,
key/URL precedence, fetched envelope merge, exact lookup behavior and bundles.
Security review is appropriate for credential-resolution behavior; this crate
itself performs no credential/file writes or outbound requests.

## Verification (2026-11-04)

- Python catalog tests: 21 passed; fresh isolated JSON oracle equals the
  checked-in catalog fixture for all 201 providers and 33 configured scenarios.
- Catalog nextest: 24 passed. Final pinned-base workspace nextest: all 937 passed
  together, including the known timing case. On an earlier gateway-base run,
  `sixteen_mebibytes_in_one_byte_deltas_is_fast` passed alone, then the other 929
  passed with `--no-fail-fast`, as the bridge rules prescribe. The first shared
  gate run passed all 926 cases before those upstream additions.
- Shared gate script: lint fixture, fmt, workspace clippy/all-targets,
  nextest, cargo-deny and shared path check passed. Locked metadata passed.
- A landing rerun exhausted the build volume and failed to link (`LNK1180` /
  `LNK1318`). No build files were deleted by this worker. Space recovered
  externally; the default-profile workspace rebuild then passed. An additional
  isolated-target clippy check also passed with debug information level 1 and
  incremental compilation disabled. No repository profile was changed.
- All 240 mutation candidates resolved (217 caught, 23 unviable, zero missed);
  see [MUTANTS.md](MUTANTS.md) for the scopes and retests.
- Side-by-side source review: provider facts, optional fields, ordering,
  normalization, merge precedence, transport routing, defaults and configured
  checks agree with the Python oracle. No unsafe code, runtime I/O, request
  bodies, DB changes or server/routing mounts were introduced.
