# Customize: skills, connectors (MCP), plugins and hooks — Tasks

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Plan | [plan.md](plan.md) |
| Updated | 2026-11-07 |

## 1. Phases

Each phase ships on its own; plugins come after skills, connectors and hooks
because they only bundle the parts the earlier phases add.

### Phase 1 — Skills and commands

Done when: skills and commands run by `/name` and the `skill` tool, the `/`
menu lists them, and **Customize → Skills** and **Agents** work.

- [x] T1 [FR-1, FR-2, FR-3, FR-5] Cross-client skill folders, command files as skills, `skillOverrides`, `describe()` — `crates/evo-engine/src/customize.rs`, `resource_dirs.rs` — check: `cargo test -p evo-engine commands_take_their_path_as_name_and_first_line_as_description`, `a_skill_lists_the_files_of_its_folder`
- [x] T2 [FR-6] The `skill` tool — `crates/evo-engine/src/skill_tool.rs` — check: manual, the model runs a skill
- [x] T3 [FR-4, FR-7, FR-8] `/name args` expansion and substitutions — `crates/evo-harness/src/skills.rs`, `agent_harness.rs` — check: `cargo test -p evo-harness format_invocation_substitutes_command_arguments`
- [x] T4 [FR-9] PascalCase tool names and model family aliases in agent files — `crates/evo-engine/src/agents.rs` — check: plugin subagent end to end (PascalCase tools mapped)
- [x] T5 [FR-5, FR-12] RPC `list_customizations`, `set_skill_override`, `reload_resources` in the `Command` schema — `crates/evo-engine/src/rpc/protocol.rs` — check: manual from Customize
- [x] T6 [P] [FR-10] The `/` menu — `apps/desktop/src/features/chat/command-menu.tsx` — check: manual in the running app
- [x] T7 [P] [FR-11] Accent token and hint, `/name` in the bubble, `typedPrompt`, "Skill · name" row — `apps/desktop/src/components/ai-elements/prompt-input.tsx`, `features/chat/transcript.ts`, `components/ai-elements/tool.tsx` — check: manual in the running app
- [x] T8 [P] [FR-12] Customize page and store (Skills, Agents; Connectors, Plugins, Hooks marked Soon) — `apps/desktop/src/features/customize/customize-page.tsx`, `stores/customize-store.ts` — check: manual in the running app

### Phase 2a — Connectors (MCP)

Done when: connectors added in the app connect once and their tools,
prompts and permissions reach every chat.

- [x] T9 [FR-17] Connectors file — `crates/evo-mcp/src/config.rs` — check: `cargo test -p evo-mcp reads_both_kinds_and_keeps_unknown_keys`, `expands_variables`, `rejects_bad_urls_and_names`
- [x] T10 [FR-18, NFR-2] One connection on `rmcp` — `crates/evo-mcp/src/client.rs` — check: `cargo test -p evo-mcp lists_and_calls_tools_and_prompts` (real round trip against an in-process `rmcp` server)
- [x] T11 [FR-18, FR-19, FR-20, FR-21] The pool — `crates/evo-mcp/src/pool.rs` — check: `cargo test -p evo-mcp exposed_names_are_safe_and_short`, `read_only_tools_are_allowed_by_default`, `a_bad_server_fails_and_the_config_round_trips`
- [x] T12 Developer examples — `crates/evo-mcp/examples/echo_server.rs`, `probe.rs` — check: `probe` lists the echo server's tools
- [x] T13 [FR-18, FR-22] Pool as app state, `mcp://changed`, Tauri commands — `apps/desktop/src-tauri/src/mcp.rs` — check: `cd apps/desktop/src-tauri && cargo check`
- [x] T14 [FR-19, FR-20] Connector tools in every chat, approvals — `apps/desktop/src/lib/mcp.ts`, `stores/connectors-store.ts`, `stores/engine-store.ts` — check: manual in the running app
- [x] T15 [P] [FR-22] **Customize → Connectors** — `apps/desktop/src/features/customize/connectors-section.tsx` — check: manual in the running app
- [x] T16 [P] [FR-23] Connector prompts in `/`, "Called server · tool" rows — `apps/desktop/src/features/chat/command-menu.tsx`, `components/ai-elements/tool.tsx` — check: manual in the running app

### Phase 2b — Sign-in, project servers, resources, per-chat switches

Done when: remote connectors sign in, project servers ask first, `@server:uri`
attaches resources, and the `+` menu switches connectors per chat.

- [x] T17 [FR-24] OAuth 2.1, loopback callback, token store; `mcp_sign_in` / `mcp_sign_out`; Sign in / Sign out — `crates/evo-mcp/src/auth.rs`, `apps/desktop/src-tauri/src/mcp.rs`, `apps/desktop/src/features/customize/connectors-section.tsx` — check: `cargo test -p evo-mcp the_store_keeps_each_connector_apart`, `the_callback_listener_returns_the_redirect_url` (phase 2b brought `evo-mcp` to 10 tests: credential store, the callback listener, project approval and scoping)
- [x] T18 [FR-25, NFR-4] Project servers with approval — `crates/evo-mcp/src/pool.rs`, `apps/desktop/src-tauri/src/mcp.rs`, `connectors-section.tsx` — check: `cargo test -p evo-mcp project_servers_wait_for_approval_and_stay_in_their_project`
- [x] T19 [FR-26] Resources: list, read, `@server:uri` attach — `crates/evo-mcp/src/pool.rs`, `apps/desktop/src-tauri/src/mcp.rs`, `apps/desktop/src/stores/engine-store.ts` — check: manual in the running app
- [x] T20 [FR-27] Composer `+` menu and `chatConnectorsOff` — `apps/desktop/src/features/chat/chat-composer.tsx`, `stores/ui-store.ts` — check: manual in the running app

### Phase 3 — Hooks

Done when: hooks from settings run on agent events and **Customize → Hooks**
shows them with their runs.

- [x] T21 [FR-29, NFR-4] Hook config and matchers — `crates/evo-hooks/src/config.rs` — check: `cargo test -p evo-hooks matchers`, `loads_user_and_project_hooks_and_skips_bad_ones`, `disable_all_hooks`
- [x] T22 [FR-30, NFR-2] Running handlers and outcomes — `crates/evo-hooks/src/run.rs` — check: `cargo test -p evo-hooks exit_codes_and_json_decisions`, `the_event_arrives_on_stdin_and_hooks_run_in_parallel`, `a_missing_command_is_an_error_not_a_block` (6 tests run real processes)
- [x] T23 [FR-31, FR-32] Engine call sites, run log, RPC `list_hooks`, `set_hooks_disabled` — `crates/evo-engine/src/hooks.rs`, `modes.rs` — check: end to end, a `UserPromptSubmit` hook that exits 2
- [x] T24 [FR-32] **Customize → Hooks** — `apps/desktop/src/features/customize/hooks-section.tsx` — check: manual in the running app

### Phase 4 — Plugins and marketplaces

Done when: a plugin installed from a marketplace adds its skills, commands,
subagents, hooks and connectors to every ready chat.

- [x] T25 [FR-33, FR-38] Plugin manifest and layout — `crates/evo-plugins/src/manifest.rs` — check: `cargo test -p evo-plugins layout_without_a_manifest`, `cargo test -p evo-plugins manifest`
- [x] T26 [P] [FR-34] Marketplaces and sources — `crates/evo-plugins/src/marketplace.rs` — check: `cargo test -p evo-plugins sources_parse`, `catalog_in_either_plugin_folder`
- [x] T27 [P] [FR-35, NFR-2] Install store — `crates/evo-plugins/src/store.rs` — check: `cargo test -p evo-plugins folder_marketplace_install_enable_update_uninstall`, `git_sources_clone_and_folders_install_in_place` (5 tests at phase 4, including real clones over `file://`)
- [x] T28 [FR-36] Engine: resources from enabled plugins — `crates/evo-engine/src/plugins.rs` — check: plugin end to end
- [x] T29 [FR-35, FR-36] Shell: plugin commands, `set_plugin_servers`, `plugins://changed` — `apps/desktop/src-tauri/src/plugins.rs`, `crates/evo-mcp/src/pool.rs` — check: `cd apps/desktop/src-tauri && cargo check`
- [x] T30 [FR-37] **Customize → Plugins** — `apps/desktop/src/features/customize/plugins-section.tsx` — check: manual in the running app

### Phase 5 — Polish

Done when: large tool sets sit behind search, skills count their uses and fit
the listing budget, and skill shell lines run.

- [x] T31 [FR-28] Connector tool search — `apps/desktop/src/lib/mcp.ts`, `stores/engine-store.ts` — check: manual, a chat with more than 40 connector tools
- [x] T32 [FR-13, NFR-6] Skill usage counts — `crates/evo-engine/src/skill_runtime.rs` — check: manual, two runs then `list_customizations`
- [x] T33 [FR-14] Listing budget — `crates/evo-engine/src/skill_runtime.rs` — check: `cargo test -p evo-engine the_least_used_skills_lose_their_descriptions_first`, `long_descriptions_are_cut`
- [x] T34 [FR-15, NFR-3] Shell lines in skills — `crates/evo-engine/src/skill_runtime.rs` — check: `cargo test -p evo-engine shell_lines_run_and_arguments_never_do`
- [x] T35 [FR-13, FR-14, FR-16] RPC `set_skill_settings`; uses, "name only", Skill settings card — `crates/evo-engine/src/skill_runtime.rs`, `apps/desktop/src/features/customize/customize-page.tsx` — check: manual in the running app

### Phase 6 — Custom instructions

Done when: **Customize → Instructions** edits the personal and project
instruction files and idle chats use them from their next message.

- [x] T36 [FR-39, FR-40] RPC `list_instructions`, `save_instructions` — `crates/evo-engine/src/instructions.rs` — check: `cargo test -p evo-engine the_file_read_is_the_file_edited`, `saving_writes_and_empty_text_removes`, `parent_folders_are_listed_nearest_last`
- [x] T37 [FR-39] **Customize → Instructions** — `apps/desktop/src/features/customize/instructions-section.tsx` — check: manual in the running app

### Phase 7 — Remaining design work

Done when: every planned requirement (FR-41 to FR-60) is built or struck
out, and sign-in is tried against a real provider.

- [ ] T38 [FR-41] `context: fork` runs a skill in a child agent — `crates/evo-engine/src/skill_tool.rs` — check: a forked skill runs as a subagent
- [ ] T39 [FR-42] `.mcpb` connector bundles — `crates/evo-mcp/src/`, `apps/desktop/src/features/customize/connectors-section.tsx` — check: a bundle installs a connector
- [ ] T40 [FR-43] `allowed-tools` pre-approval and `model` / `effort` per turn — `crates/evo-engine/src/customize.rs`, `skill_tool.rs` — check: listed tools need no approval in that turn
- [ ] T41 [FR-44] Skill catalog in the `skill` tool description, 1% of the context window — `crates/evo-engine/src/skill_tool.rs`, `skill_runtime.rs` — check: catalog fits the budget
- [ ] T42 [FR-45] Shell lines through the sandbox policy, off for untrusted folders — `crates/evo-engine/src/skill_runtime.rs` — check: untrusted folder runs no shell lines
- [ ] T43 [FR-46] Watch skill folders — `crates/evo-engine/src/customize.rs` — check: an edited skill applies without a reload
- [ ] T44 [FR-47] `${PROJECT_DIR}`, `${SESSION_ID}` substitutions — `crates/evo-harness/src/skills.rs` — check: substitution test
- [ ] T45 [FR-48] Elicitation dialog — `crates/evo-mcp/src/client.rs`, `apps/desktop/src-tauri/src/mcp.rs`, `apps/desktop/src/` — check: a server's elicitation shows a dialog
- [ ] T46 [FR-49] Start on first use, restart with backoff, server logs in **Settings → Logs** — `crates/evo-mcp/src/pool.rs`, `apps/desktop/src-tauri/src/mcp.rs` — check: a crashed server restarts
- [ ] T47 [FR-50] Sign-in tokens in the OS keychain — `crates/evo-mcp/src/auth.rs` — check: token stored in the keychain
- [ ] T48 [FR-51] Hook handlers `prompt`, `mcp_tool`, `agent` — `crates/evo-hooks/src/run.rs`, `crates/evo-engine/src/hooks.rs` — check: a `prompt` hook decides an outcome
- [ ] T49 [FR-52] Events `SubagentStart` / `SubagentStop`, `PreCompact` / `PostCompact`, `Notification`; `Stop` continues the run — `crates/evo-engine/src/hooks.rs`, `apps/desktop/src/` — check: each event fires its hooks
- [ ] T50 [FR-53] Hooks from skill and agent frontmatter — `crates/evo-hooks/src/config.rs`, `crates/evo-engine/src/hooks.rs` — check: a skill's hook runs
- [ ] T51 [FR-54] `EVO_PLUGIN_ROOT`, `EVO_PLUGIN_DATA`, `EVO_PLUGIN_OPTION_<KEY>` for plugin hooks — `crates/evo-hooks/src/run.rs`, `crates/evo-engine/src/plugins.rs` — check: a plugin hook sees the variables
- [ ] T52 [FR-55] Hook results in the transcript — `apps/desktop/src/components/ai-elements/tool.tsx`, `features/chat/transcript.ts` — check: manual in the running app
- [ ] T53 [FR-56] Plugin sources `npm` and `archive`; marketplace by URL — `crates/evo-plugins/src/marketplace.rs`, `store.rs` — check: an archive source installs
- [ ] T54 [FR-57] Sensitive plugin options in the OS keychain — `crates/evo-plugins/src/store.rs` — check: a sensitive option is not in the settings file
- [ ] T55 [FR-58] `enabledPlugins` per scope, chosen on install — `crates/evo-engine/src/plugins.rs`, `apps/desktop/src/features/customize/plugins-section.tsx` — check: a project-scope plugin is on only there
- [ ] T56 [FR-59] `.zip` upload with the options form on install — `apps/desktop/src-tauri/src/plugins.rs`, `plugins-section.tsx` — check: a `.zip` installs
- [ ] T57 [FR-60] `@agent-name` mentions, `+` menu Plugins and Manage connectors, connector icons on tool rows — `apps/desktop/src/features/chat/`, `components/ai-elements/tool.tsx` — check: manual in the running app
- [ ] T58 [FR-24] Try sign-in against a real provider — no code — check: a real remote connector signs in and connects

## 2. Verification

| Requirement | Test or check | Result |
| --- | --- | --- |
| FR-1 | `cargo test -p evo-engine a_skill_lists_the_files_of_its_folder`; manual, a skill in `.agents/skills` | not run |
| FR-2 | `cargo test -p evo-engine commands_take_their_path_as_name_and_first_line_as_description` | not run |
| FR-3 | Manual: two skills of one name in project and user folders | not run |
| FR-4 | `cargo test -p evo-harness loads_skill_md_with_frontmatter`, `validate_name_rules`, `validate_description_rules` | not run |
| FR-5 | Manual: set a skill override in Customize | not run |
| FR-6 | Manual: the model runs a skill with the `skill` tool | not run |
| FR-7 | Manual: `/name` with a bare name of a namespaced skill | not run |
| FR-8 | `cargo test -p evo-harness format_invocation_substitutes_command_arguments` | not run |
| FR-9 | End to end with the real engine: an installed plugin's subagent with PascalCase tools mapped | passed (recorded 2026-11-06) |
| FR-10 | Manual: `/` menu in the running app | not run |
| FR-11 | Manual: composer token, bubble and transcript row | not run |
| FR-12 | Manual: **Customize** page in the running app | not run |
| FR-13 | Manual: two runs, then the uses in Customize | not run |
| FR-14 | `cargo test -p evo-engine the_least_used_skills_lose_their_descriptions_first`, `long_descriptions_are_cut` | not run |
| FR-15 | `cargo test -p evo-engine shell_lines_run_and_arguments_never_do` | not run |
| FR-16 | Manual: Skill settings card | not run |
| FR-17 | `cargo test -p evo-mcp reads_both_kinds_and_keeps_unknown_keys`, `expands_variables`, `rejects_bad_urls_and_names` | not run |
| FR-18 | `cargo test -p evo-mcp lists_and_calls_tools_and_prompts`, `a_bad_server_fails_and_the_config_round_trips` | not run |
| FR-19 | `cargo test -p evo-mcp exposed_names_are_safe_and_short` | not run |
| FR-20 | `cargo test -p evo-mcp read_only_tools_are_allowed_by_default`; manual approval prompt | not run |
| FR-21 | Manual: a tool result over 100k characters | not run |
| FR-22 | Manual: **Customize → Connectors** | not run |
| FR-23 | Manual: `/server:prompt` and tool rows | not run |
| FR-24 | `cargo test -p evo-mcp the_store_keeps_each_connector_apart`, `the_callback_listener_returns_the_redirect_url`; sign-in against a real provider (T58) | not run (not yet tried against a real provider) |
| FR-25 | `cargo test -p evo-mcp project_servers_wait_for_approval_and_stay_in_their_project` | not run |
| FR-26 | Manual: `@server:uri` in a message | not run |
| FR-27 | Manual: composer `+` menu | not run |
| FR-28 | Manual: a chat with more than 40 connector tools | not run |
| FR-29 | `cargo test -p evo-hooks matchers`, `loads_user_and_project_hooks_and_skips_bad_ones`, `disable_all_hooks` | not run |
| FR-30 | `cargo test -p evo-hooks exit_codes_and_json_decisions`, `the_event_arrives_on_stdin_and_hooks_run_in_parallel`, `a_missing_command_is_an_error_not_a_block` | not run |
| FR-31 | End to end with the real engine: a `UserPromptSubmit` hook that exits 2 blocked a prompt before any model call | passed (recorded 2026-11-06) for `UserPromptSubmit`; other events not run |
| FR-32 | End to end: `list_hooks` showed the run; manual **Customize → Hooks** | passed (recorded 2026-11-06) for `list_hooks`; page not run |
| FR-33 | `cargo test -p evo-plugins manifest`, `layout_without_a_manifest`; end to end: a plugin hook with `${PLUGIN_ROOT}` filled in | passed (recorded 2026-11-06) end to end; unit tests not run |
| FR-34 | `cargo test -p evo-plugins sources_parse`, `catalog_in_either_plugin_folder` | not run |
| FR-35 | `cargo test -p evo-plugins folder_marketplace_install_enable_update_uninstall`, `git_sources_clone_and_folders_install_in_place` | not run |
| FR-36 | End to end with the real engine: an installed plugin's skill, command (with its argument hint), subagent and hook all appeared | passed (recorded 2026-11-06) |
| FR-37 | Manual: **Customize → Plugins** | not run |
| FR-38 | Manual: a plugin with unsupported parts | not run |
| FR-39 | Manual: **Customize → Instructions** | not run |
| FR-40 | `cargo test -p evo-engine the_file_read_is_the_file_edited`, `saving_writes_and_empty_text_removes`, `parent_folders_are_listed_nearest_last` | not run |
| FR-41 | T38: a forked skill runs as a subagent | not run (not built) |
| FR-42 | T39: a bundle installs a connector | not run (not built) |
| FR-43 | T40: listed tools need no approval in that turn | not run (not built) |
| FR-44 | T41: catalog fits the budget | not run (not built) |
| FR-45 | T42: an untrusted folder runs no shell lines | not run (not built) |
| FR-46 | T43: an edited skill applies without a reload | not run (not built) |
| FR-47 | T44: substitution test | not run (not built) |
| FR-48 | T45: a server's elicitation shows a dialog | not run (not built) |
| FR-49 | T46: a crashed server restarts with backoff | not run (not built) |
| FR-50 | T47: token stored in the keychain | not run (not built) |
| FR-51 | T48: a `prompt` hook decides an outcome | not run (not built) |
| FR-52 | T49: each event fires its hooks | not run (not built) |
| FR-53 | T50: a skill's hook runs | not run (not built) |
| FR-54 | T51: a plugin hook sees the variables | not run (not built) |
| FR-55 | T52: manual in the running app | not run (not built) |
| FR-56 | T53: an archive source installs | not run (not built) |
| FR-57 | T54: a sensitive option is not in the settings file | not run (not built) |
| FR-58 | T55: a project-scope plugin is on only there | not run (not built) |
| FR-59 | T56: a `.zip` installs | not run (not built) |
| FR-60 | T57: manual in the running app | not run (not built) |
| NFR-1 | Review of the formats (plan 3.3) | not run |
| NFR-2 | Manual on Windows: stdio server, hook, shell line and git open no window | not run |
| NFR-3 | `cargo test -p evo-engine shell_lines_run_and_arguments_never_do` | not run |
| NFR-4 | `cargo test -p evo-hooks loads_user_and_project_hooks_and_skips_bad_ones`; `cargo test -p evo-mcp project_servers_wait_for_approval_and_stay_in_their_project` | not run |
| NFR-5 | Manual: add a connector and change a skill with chats open | not run |
| NFR-6 | Review of `skill_runtime.rs` | not run |
| SC-1 | End to end: blocking `UserPromptSubmit` hook | passed (recorded 2026-11-06) |
| SC-2 | End to end: plugin parts appear | passed (recorded 2026-11-06) |
| SC-3 | Manual: add a connector with chats open | not run |
| SC-4 | Manual: a chat with more than 40 connector tools | not run |
