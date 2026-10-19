# Plugin Lifecycle Hooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add trusted, bounded lifecycle hooks for portable plugins and global Settings, with Settings hooks able to augment or replace plugin hooks while protected runtime invariants remain enforced.

**Architecture:** Define one canonical EvoFlux event and output contract for package and Settings hooks. Inspect and trust hook content separately from plugin installation, execute commands in a constrained subprocess, resolve event registrations with explicit Settings precedence, and dispatch them from session and agent lifecycle owners. Add a Settings UI and a Claude compatibility adapter only after the native contract works.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, YAML `RuntimeSettings`, existing EvoFlux `HookPipeline`, plugin platform registry/trust code, React, TypeScript, TanStack Router, pytest, Bun/Vitest.

**Spec:** `documents/architecture/decisions/plugin-lifecycle-hooks.md`

**Security gate:** Do not ship executable hook support on an OS until its isolation backend is proven to enforce the advertised profile. If platform containment cannot be demonstrated, the adapter may inspect and show hooks but must refuse to execute them.

## Global Constraints

- Package hooks must never be imported or executed in the FastAPI sidecar process.
- Hook commands run as bounded subprocesses with bounded input/output, explicit environment allowlist, plugin-root working directory, and cancellation propagation.
- Installation or enabling a plugin never trusts its executable hooks; trust binds to hook-definition and executable content digests.
- Session events stay in the session/service layer and are not aliases for per-agent-run events.
- Hook inputs omit credentials, unrestricted app state, and full transcripts by default.
- Settings precedence applies to configurable plugin hooks only; protected runtime invariants cannot be disabled or shadowed, and deny decisions are sticky.
- A subprocess is not a security boundary. Hooks execute only if a platform backend enforces the approved filesystem/network/resource profile; unsupported hosts fail closed.
- Missing or incomplete isolation is a core security failure and always denies the affected operation, regardless of a hook's `fail_open` setting. Hook failure policy applies only after the isolation profile is established.
- Existing flat `.py` hooks remain a legacy trusted-code path imported in-process; they are not covered by the new isolation guarantee. Settings can filter these plugin registrations, and the UI labels them separately. Managed/Settings hooks never fall back to the legacy loader.
- Hooks may narrow or deny an action but cannot grant permissions. Tool arguments rewritten by hooks are schema-validated and re-authorized by core policy immediately before tool execution.
- Hook-provided text is bounded and provenance-marked in a lower-authority context slot; it never becomes system policy. Treat user, tool, package, and hook text as possible prompt injection.
- Settings edits do not grant execution trust; trust is an explicit, digest- and capability-profile-bound action, and the Settings UI previews which plugin hooks `replace` will suppress.
- Plugin-free packages keep their existing Skills/MCP behavior and existing trusted flat-Python hooks remain supported.
- Do not add a database migration for hook definitions or trust; use `settings.yaml` for Settings-owned definitions and the separate application-managed hook trust store for approvals.

## Review Focus

- A Settings hook in `replace` mode must suppress only configurable plugin hooks for the selected event, not protected runtime hooks.
- Settings shadowing must target an exact `(plugin_id, hook_id)` pair and must not accidentally match a different plugin's hook.
- A deny from any participating hook must not be converted into allow by later Settings or plugin output.
- A symlink, `..` path, or executable replaced after review must not bypass package-root validation or digest re-review.
- A hook command attempting network access, reading credentials/unrelated files, spawning an escaped child process, or exhausting resources must be denied by isolation; if isolation is unavailable, it must not run.
- A prompt injection embedded in hook output or tool data must not bypass tool authorization or rewrite system policy.
- A plugin or hook output attempting to mutate global Settings or approve its own digest must be ignored/rejected.
- Session resume and compaction continuation must not incorrectly fire as a fresh agent start or lose their source metadata.

## File Map

- `app/plugin_platform/validator.py`, `extensions.py`, `installer.py`, `registry.py`, and `trust.py` validate package declarations and expose trust-review disclosures; a new `app/plugin_platform/hook_trust_store.py` persists digest approvals separately from plugin installation and `settings.yaml`.
- `app/agent/plugins/` owns the canonical declarative hook models, effective-registration resolver, subprocess execution, and package/Settings adapter boundary. A new `hook_isolation.py` defines capability profiles and platform-backend protocol; `app/agent/plugins/loader.py` remains the legacy Python loader and must be adapted as a distinct registration source so Settings replacement can filter its handlers.
- `app/agent/hooks/` and `app/agent/agent_loop/core.py` attach agent/model/tool/completion events to existing typed hooks. Session creation/resume/close services own `session.start` and `session.end` dispatch.
- `app/core/runtime_settings.py`, `app/api/schemas/settings.py`, and `app/api/routes/settings.py` persist and expose Settings hook definitions and precedence policy.
- `web/src/api/types.ts`, `web/src/api/client/settings.ts`, `web/src/routes/settings.hooks.tsx`, `web/src/components/SettingsScreen.tsx`, `web/src/components/settings/SettingsSidebar.tsx`, and `web/src/routeTree.gen.ts` expose the Settings editor and route.
- `app/api/routes/plugins.py`, `web/src/api/client/plugins.ts`, `web/src/components/PluginCenterPanel.tsx`, and `web/src/components/PluginTrustReviewDialog.tsx` show package hook inspection, trust, and effective state.
- `app/plugin_platform/hook_trust_store.py` stores separate approvals keyed by owner, hook ID, executable digest, and isolation profile. Settings definitions remain in `settings.yaml`; editing them never creates an approval.
- `tests/plugin_platform/`, `tests/agent/plugins/`, `tests/agent/hooks/`, `tests/api/`, and `web/src/__tests__/` contain focused tests for validation, resolution, dispatch, API, and Settings UI.
- `documents/features/tools-skills-mcp-and-plugins.md`, `documents/features/agent-runtime-and-teams.md`, author-facing plugin docs, and localized Help document the shipped contract and lifecycle.

---

## Tasks

### Task 1: Define hook declarations, event contracts, and precedence resolver

**Files:**
- Create: `app/agent/plugins/hook_contract.py`
- Create: `app/agent/plugins/hook_resolution.py`
- Modify: `app/agent/plugins/__init__.py`
- Test: `tests/agent/plugins/test_hook_contract.py`
- Test: `tests/agent/plugins/test_hook_resolution.py`

**Interfaces:**
- `HookDefinition`: stable `hook_id`, canonical `event`, optional matcher, command argv, timeout, allowlisted `input_fields` and `output_fields` validated against event-specific typed schemas, failure policy, and optional explicit `overrides: [{plugin_id, hook_id}]` targets for Settings-owned definitions.
- `HookRegistration`: `hook_id`, optional stable `plugin_id`, source (`settings`, `managed_plugin`, or `legacy_python`), definition digest, trust state, and parsed definition. Built-in `HookPipeline` registrations are passed separately as protected hooks and are never filtered by Settings policy.
- `HookSettingsPolicy`: mode (`augment` or `replace`), selected `replace_plugin_events`, and explicit disabled plugin-hook identities. Settings-owned definitions are passed separately as trusted or untrusted `HookRegistration` values so their trust state remains visible to the resolver.
- `resolve_event_hooks(event, settings_policy, settings_registrations, plugin_registrations, protected_hooks) -> EffectiveHooks`: returns ordered active hooks plus shadowed/disabled diagnostics. A trusted Settings definition shadows only the exact `(plugin_id, hook_id)` it explicitly targets; `replace` filters managed and legacy plugin registrations for that event. Protected hooks are carried outside configurable filtering.
- `merge_hook_outputs(event, outcomes) -> EventDecision`: applies event-specific output schemas, uses Settings values for replaceable outputs, and preserves any deny as a sticky block.

- [x] Add tests for malformed definitions, unknown events, unsupported output fields, invalid command argv, invalid timeout, duplicate Settings IDs, and matcher validation.
- [x] Add resolver tests for augment order, same-target shadowing, managed/legacy plugin filtering in replace mode, disabled plugin identities, plugin-ID isolation, and built-in hooks surviving replace mode.
- [x] Add output-merge tests proving Settings context/argument/completion values take precedence and a later allow cannot clear a deny.
- [x] Implement immutable Pydantic models and event-specific input/output schemas for all events listed in the spec.
- [x] Implement a pure resolver with deterministic ordering and diagnostics; do not perform filesystem or subprocess work in this module.
- [x] Run focused contract and resolver tests.

### Task 2: Inspect package hook extensions and bind trust to digests

**Files:**
- Modify: `app/plugin_platform/extensions.py`
- Modify: `app/plugin_platform/validator.py`
- Modify: `app/plugin_platform/installer.py`
- Modify: `app/plugin_platform/registry.py`
- Modify: `app/plugin_platform/trust.py`
- Modify: `app/plugin_platform/review.py`
- Create: `app/plugin_platform/hook_trust_store.py`
- Test: `tests/plugin_platform/test_hook_extensions.py`
- Test: `tests/plugin_platform/test_hook_trust.py`
- Test: `tests/plugin_platform/test_marketplace_install.py`

**Interfaces:**
- `inspect_plugin_hooks(plugin_root, manifest) -> HookInspection`: validates `extensions.com.evoflux.hooks`, resolves only package-relative files inside the real plugin root, checks file type/symlinks, parses declarations, and returns diagnostics without executing commands.
- `hook_digest(plugin_root, definition) -> str`: hashes canonical definition bytes and every referenced executable file.
- `HookTrustStore` reads/writes atomic JSON under the application-managed data directory and records `(owner_type, owner_id, hook_id, digest)`, separating package approvals from Settings-owned approvals. Any changed declaration or referenced executable is untrusted until reviewed again.
- Package install and skill/MCP behavior remain unchanged when extension is absent or unsupported.

- [x] Add baseline assertions for packages without the extension and existing Skills/MCP install behavior.
- [x] Cover absolute paths, `..`, symlink escape (platform-gated where symlink creation is unavailable), missing files, non-file commands, malformed declarations, duplicate IDs, and unsupported extension versions. The hook format is JSON-only; malformed manifest JSON is covered by the plugin validator suite.
- [x] Add trust tests proving approvals are bound to the current digest and isolation profile; a changed executable produces a new digest.
- [x] Implement inspection and digest calculation without launching the command.
- [x] Add a runtime registration builder that keeps plugin enabled state separate from digest/profile trust.
- [x] Recompute package-relative inspection metadata from installed package bytes for API and runtime snapshots; persist approvals separately through `HookTrustStore`. This detects linked-package changes without trusting stale registry metadata and never stores absolute executable paths in manifests.
- [x] Extend review data to show event, matcher, argv, timeout/failure policy, declared data, resolved relative files, fixed environment allowlist, isolation profile, and digest.
- [x] Run focused inspection/trust/marketplace/platform regression. Marketplace and hook inspection passed; `test_platform.py` had 46 passes and three Windows-only POSIX-mode/symlink-privilege failures.

### Task 3: Add bounded subprocess runner and runtime event dispatch

**Files:**
- Create: `app/agent/plugins/hook_runner.py`
- Create: `app/agent/plugins/hook_dispatcher.py`
- Modify: `app/agent/agent_loop/core.py`
- Modify: relevant session creation/resume/close service modules discovered by tracing session lifecycle owners
- Modify: `app/agent/hooks/pipeline.py` only where an adapter is needed to preserve ownership/order rules
- Test: `tests/agent/plugins/test_hook_runner.py`
- Test: `tests/agent/plugins/test_hook_dispatcher.py`
- Test: `tests/agent/agent_loop/test_plugin_hook_lifecycle.py`

**Interfaces:**
- `HookIsolationBackend.supports(profile) -> bool` and `launch(argv, cwd, env, limits, cancellation_token) -> IsolatedProcess`: enforce read/write roots, network policy, resource limits, and process-tree containment. A missing or incomplete backend refuses execution; never fall back to an unrestricted subprocess.
- `run_hook(registration, event_input, cancellation_token) -> HookExecutionResult`: invokes argv without a shell, uses the plugin root as cwd, passes only allowlisted non-secret environment variables, enforces wall-time/input/output limits, kills the full child process tree on cancellation, parses JSON, and validates event output.
- `dispatch_hooks(event, event_input, registrations, cancellation_token) -> EventDecision`: resolves effective registrations, runs them in documented deterministic order, merges validated results, and emits sanitized diagnostics/telemetry.
- `authorize_final_tool_call(tool_name, rewritten_args, policy_context) -> AuthorizationDecision`: called after `tool.before` output validation and immediately before the existing tool dispatcher; a hook cannot turn a core denial into allow.
- `adapt_legacy_python_hooks(hooks) -> list[HookRegistration]`: represents existing in-process `.py` hooks in the same precedence resolver without claiming OS isolation or changing their current execution mechanism.
- Adapter functions at existing lifecycle owners translate internal typed hook context to the canonical event input; session events are dispatched by session services, while model/tool/completion/agent events use agent-loop owners.

- [x] Verify and document the packaged Windows runtime against filesystem allow/deny, network denial, Settings-config file denial, child-process limits, and CPU/memory/process limits. Linux/macOS remain disabled until equivalent platform proof exists.
- [x] Add isolation tests proving denied network, Settings-config/unrelated file reads, writes outside the private temp root, child-process creation, and resource-limit violations; assert unsupported isolation and launch failures fail closed.
- [x] Add fail-closed runner tests proving untrusted hooks are rejected and unavailable isolation never calls `launch`; add fake-backend JSON/input-projection/environment/cwd contract coverage.
- [x] Add runner tests for timeout, oversized output, invalid JSON, nonzero exit, and cancellation propagation; verify the backend receives output limits. Native whole-tree enforcement remains gated on a real platform backend.
- [x] Add dispatcher tests for untrusted filtering, unavailable-isolation status, fail-closed behavior, and event matcher behavior.
- [x] Add resolver tests for deterministic order, sticky deny, and Settings replace/shadow behavior.
- [x] Add integration coverage for rewritten tool arguments passing the tool's Pydantic schema before the existing executor revalidates and invokes the tool; tool-level authorization remains authoritative.
- [x] Add injection coverage proving hook context remains a provenance-marked untrusted user message and hook-replaced tool output is marked untrusted.
- [x] Map `prompt.submit`, `agent.start/stop`, `model.before/after`, `tool.before/after`, `completion.before`, `compact.before/after`, and member `subagent.start/stop` to lifecycle owners.
- [x] Map session create/resume/duplicate/side-chat/suggested-task/delete to `session.start/end` with source; vetoed suggested-task creation rolls back its row and removes a just-created managed worktree. Historical imports are not new interactive starts; member rows use subagent events.
- [x] Apply context, argument, result, and completion values only at their owning boundary; validate rewritten tool arguments with the tool schema before execution.
- [x] Add sanitized identity/event/duration/outcome telemetry paths that do not log event payloads or stdout/stderr.
- [x] Add sanitized identity/event/duration/outcome telemetry paths; dispatcher logs exclude input payloads and hook stdout/stderr.
- [x] Run the focused agent/plugin/settings/session lifecycle suites, including the agent-run smoke test. Current focused run: 94 passed, 1 Windows skip; hook API routes: 12 passed.

### Task 4: Persist and manage global Settings hooks

**Files:**
- Modify: `app/core/runtime_settings.py`
- Modify: `app/api/schemas/settings.py`
- Modify: `app/api/routes/settings.py`
- Modify: `web/src/api/types.ts`
- Modify: `web/src/api/client/settings.ts`
- Create: `web/src/routes/settings.hooks.tsx`
- Modify: `web/src/components/SettingsScreen.tsx`
- Modify: `web/src/components/settings/SettingsSidebar.tsx`
- Modify: generated `web/src/routeTree.gen.ts` through the repository's route generation command
- Test: `tests/core/test_runtime_settings.py`
- Test: `tests/api/test_settings_routes.py`
- Test: `web/src/__tests__/routes/settings.hooks.test.tsx`

**Interfaces:**
- `RuntimeSettings.hooks: HookSettings` persists definitions, mode, per-event replacement selection, and disabled plugin-hook identities in `settings.yaml`.
- `GET /api/settings/hooks -> HookSettingsResponse` returns editable values plus validation warnings and effective hook status.
- `PUT /api/settings/hooks` validates and atomically saves settings; hook definitions are explicitly reviewed/trusted and digest-bound before execution.
- TypeScript `HookSettings` mirrors the API schema; the Settings page supports add/edit/remove, enable/disable, `augment`/`replace` per event, and displays protected-hook boundaries.

- [x] Add settings-model round-trip tests, legacy-file-default tests (missing `hooks` becomes an empty augment policy), and invalid-field-pruning tests.
- [x] Add API tests for GET defaults, valid PUT persistence, invalid schema rejection, duplicate IDs, and no trust granted by merely saving a definition.
- [x] Implement typed settings schemas and GET/PUT endpoints using the existing runtime settings load/save flow.
- [x] Add the `hooks` Settings page and sidebar entry using the existing Settings page/layout patterns. The Settings screen is store-routed, so no generated TanStack route entry is needed.
- [x] Add digest-bound Settings trust/revoke API actions and UI confirmation naming the command, event, declared data access, isolation profile, and digest; executable or definition changes require review again.
- [x] Add a read-only replace-mode preview that lists each event and exact `(plugin_id, hook_id)` plugin registration (plus installation identity) that will be suppressed; require a deliberate confirmation before saving the policy.
- [x] Ensure hook output schemas expose no Settings write/trust operations; Settings changes and digest approvals remain explicit route actions, with API tests confirming save does not grant trust.
- [x] Render effective status per hook in Settings/Plugin Center, including blocked execution, trust, disabled, and Settings replacement/shadow states.
- [x] Run settings backend and frontend hook suites (runtime settings tests live in `tests/agent/plugins/test_hook_settings.py`; route/UI tests passed).

### Task 5: Expose plugin trust/effective status in Plugin Center

**Files:**
- Modify: `app/api/routes/plugins.py`
- Modify: `app/api/schemas/plugins.py`
- Modify: `web/src/api/client/plugins.ts`
- Modify: `web/src/components/PluginCenterPanel.tsx`
- Modify: `web/src/components/PluginTrustReviewDialog.tsx`
- Test: `tests/api/test_plugin_routes.py`
- Test: `web/src/__tests__/components/PluginCenterPanel.hooks.test.tsx`
- Test: `web/src/__tests__/components/PluginTrustReviewDialog.hooks.test.tsx`

**Interfaces:**
- Plugin detail responses include declared hook summaries and per-hook trust/effective state, never executable output or secret environment values.
- Trust review/approve action binds approval to the exact definition/executable digest and does not implicitly enable the plugin or hook.
- Settings precedence is represented in returned state so a plugin hook can be shown as shadowed/replaced without changing its installation or trust record.

- [x] Add route coverage for awaiting-trust, trusted-but-isolation-blocked, and Settings-replaced plugin hooks.
- [x] Add route tests for stale digest, Settings replacement, and an exact trusted Settings shadow target.
- [x] Add route/unit coverage for stale digests, disabled hooks, invalid/unsupported declarations, exact Settings-shadowing, and isolation-profile-bound approvals.
- [x] Extend trust review dialog with event, matcher, argv, inputs/outputs, timeout/failure policy, package-relative path, profile, and digest. Effective status now reflects Windows AppContainer + Job Object availability and remains blocked on unsupported hosts.
- [x] Add per-installation hook trust/effective status to the Plugin Center API and inspection details; keep Skills/MCP controls unchanged for packages without hooks.
- [x] Add explicit digest-bound trust/revoke review actions for installed package hooks and Settings hooks, plus per-hook Settings override/shadow preview. Trust remains separate from enablement and cannot imply execution when isolation is unavailable.
- [x] Keep runtime status UI limited to hook identity/event/digest/trust/enabled/status; do not expose prompt payloads, environment values, or hook stdin/stdout.
- [x] Run plugin API/review and frontend package-review, Plugin Center, and Settings-hooks suites.

### Task 6: Add Claude adapter and Superpowers compatibility fixture

**Files:**
- Create: `app/plugin_platform/adapters/claude_hooks.py`
- Create: `tests/fixtures/plugins/claude-superpowers-hooks/` with a minimal manifest, hook declaration, and harmless fixture command
- Test: `tests/plugin_platform/test_claude_hook_adapter.py`
- Test: `tests/agent/plugins/test_superpowers_session_bootstrap.py`
- Modify: `app/plugin_platform/extensions.py` only to register the adapter result with the canonical inspection model

**Interfaces:**
- `adapt_claude_hooks(plugin_root, source_manifest) -> HookInspection` maps only explicitly supported Claude events and outputs into canonical definitions; unsupported declarations return diagnostics.
- The first supported mapping is Claude `SessionStart` additional context when its lifecycle timing matches EvoFlux `session.start`; the adapter supplies the expected plugin-root environment variable without exposing arbitrary host environment.
- Superpowers' Skill remains installable and discoverable if its hook is unsupported or fails.

**Current compatibility/security finding (2026-10-16):** Superpowers 6.4.1 declares a synchronous Claude `SessionStart` shell hook (`startup|clear|compact`) and launches a bash/polyglot wrapper with `${CLAUDE_PLUGIN_ROOT}`. EvoFlux does not copy or run that launcher. The adapter accepts only the exact Superpowers manifest shape and translates it to a separate `static_context` action over `skills/using-superpowers/SKILL.md`; the file is bounded, digest-trusted, and injected once as provenance-marked untrusted context. This narrow read-only path is covered through normalization, linked installation, explicit trust, and real `session.start` dispatch. Other Claude declarations remain unsupported. Windows command hooks now use the verified AppContainer + Job Object backend; other OSes remain fail-closed.

- [x] Add fixture tests for valid `SessionStart`, unsupported event/output, invalid command shape, and context-size limits.
- [x] Add an integration test proving the mapped session bootstrap reaches the intended session context once and does not fire for every agent run.
- [x] Add a fallback test proving Skills remain available when the hook is untrusted; unsupported hook declarations also leave Skills importable.
- [x] Implement only the verified Claude subset; leave Codex declarations unsupported until a separate source mapping is validated.
- [x] Run adapter/bootstrap tests as part of the focused 94-pass backend suite.

### Task 7: Document, run full focused regression, and hand off for review

**Files:**
- Modify: `documents/features/tools-skills-mcp-and-plugins.md`
- Modify: `documents/features/agent-runtime-and-teams.md`
- Modify: plugin authoring documentation under `documents/`
- Modify: localized in-app Help files under `web/src/help/locales/`
- Test: focused backend and frontend suites from Tasks 1–6

- [x] Document the currently available hook inspection, Settings policy, Plugin Center status, trust boundaries, and fail-closed execution status in the feature page and localized Help.
- [x] Document the manifest declaration shape, lifecycle events, trust/isolation gate, and untrusted context boundary. Arbitrary command execution remains disabled; the exact Superpowers bootstrap is a data-only exception.
- [x] Add user Help for reviewing/approving hooks and diagnosing the lifecycle trust/isolation states.
- [x] Verify the Windows AppContainer + Job Object backend against staged-file read access, host file read/write denial, loopback denial, child-process limits, CPU/memory limits, timeout, cancellation, and output caps. Other OSes remain unavailable.
- [x] Run focused backend and frontend unit/integration/smoke suites; record commands and environment-specific exclusions in the implementation handoff. Backend: 94 passed, 1 skipped; hook API: 12 passed; focused UI: 21 passed; TypeScript and Ruff passed.
- [x] Review the complete diff against all fifteen spec acceptance criteria. Managed/Settings command hooks have no in-process path; Windows runs only within the verified OS backend and other hosts remain blocked.
- [x] Report unsupported vendor declarations and reasons; the Superpowers session-bootstrap integration passes for the narrow static-context adapter only.

### Continuation — explicit runtimes and Windows containment

**Approved extension:** executable hook declarations now add an explicit runtime (`native` or `python`) and a package-relative `files` read-set. The command entrypoint plus every declared file are validated as regular non-symlink files, included in the trust digest, and staged per execution. Settings hooks stage only those declared files; never expose the Settings config directory to a child process.

**Initial platform scope:** Windows AppContainer without capabilities plus Job Object. Linux/macOS remain fail-closed until equivalent adversarial integration tests pass. The Windows packaged Python and native command runtimes passed staged-file allow access, host-file/network denial, child-process/resource limits, timeout/cancellation, and output-bound tests. Python uses the explicitly staged EvoFlux interpreter with isolated flags; never resolve `python` through PATH. The trust profile version is bumped to invalidate previous approvals.

- [x] Update canonical definition, inspection, digest, API/review schema, Settings form, and authoring docs for explicit runtime and declared files.
- [x] Add RED tests for runtime validation, file path validation, deterministic multi-file digests, changed auxiliary file invalidating trust, and UI/API disclosure.
- [x] Implement test-first staging that copies only declared files and re-verifies the staged digest; Settings config root is not exposed.
- [x] Implement a Windows-native AppContainer + Job Object backend with bounded pipes, private temp, process-tree kill, and packaged-runtime selection. Linux/macOS remain unavailable.
- [x] Add Windows adversarial integration/smoke tests for reading staged files, denying undeclared/credential files and network, write denial outside private temp, child-process limits, memory/CPU/time limits, cancellation, and output caps.
- [x] Attempt the full repository suites and record platform limits. Made the installer executable-bit assertion POSIX-only and verified it passes on Windows. The latest `uv run pytest --no-cov -q` reached 12% before `KeyboardInterrupt`, with 13 failures across unrelated Windows environment, POSIX mode, and test-fixture assumptions. The team-worktree API failures were reproduced independently and the fixture's `.tests/config/agents/coding` directory is absent. Full backend pytest is not claimed green; hook-specific suites are recorded below. Full frontend Vitest passes 891/891.
- [x] Review final branch diff and spec acceptance criteria. No commit or push was made.

**Ruling:** Windows is the first and only target for executable hooks in this iteration because AppContainer + Job Object is the selected verifiable containment stack. Unsupported hosts retain inspection and static-context behavior but fail closed for executable runtimes. Cost if wrong: Windows API ACL/staging behavior may require a native bundled helper instead of Python ctypes; verify with adversarial tests before enabling.

### Progress ledger — 2026-10-16 continuation

- Fixed the isolation ordering regression found by the smoke tests: command hooks now check for a supporting backend before resolving package paths, so a missing executable cannot be misclassified as an ordinary `fail_open` hook error. The runner/dispatcher/agent-smoke regression tests were observed failing first and then passed.
- Added a prompt-projection regression test and fix: session bootstrap context is excluded when selecting `prompt.submit.prompt_text`, preserving the original user prompt and preventing hook context from being echoed as user input.
- Focused backend unit/integration/smoke: `uv run pytest -q -o addopts='' tests/agent/plugins tests/agent/agent_loop/test_plugin_hook_lifecycle.py tests/plugin_platform/test_claude_hook_adapter.py tests/plugin_platform/test_hook_extensions.py tests/plugin_platform/test_hook_runtime.py tests/plugin_platform/test_hook_trust.py` → 94 passed, 1 skipped.
- Hook API integration: `uv run pytest -q -o addopts='' tests/api/test_plugin_routes.py tests/api/test_settings_routes.py tests/api/routes/test_suggested_tasks.py -k hook` → 12 passed, 94 deselected.
- Session integrations: WebBridge session create/resume/veto → 2 passed; side-chat routes → 20 passed. Focused frontend: Settings Hooks, Plugin Center, and package-review suites → 21 passed; `bun run typecheck`, focused ESLint, and focused Ruff passed.
- Full frontend Vitest rerun: 891 passed. The notification activation test now waits for the async navigation handler instead of assuming one microtask is sufficient.
- `uv run ty check` still reports an existing unrelated `ProviderCredentialStore.delete` attribute issue in the provider credential deletion route; that code is outside this hook change.
- Windows backend continuation: AppContainer launch uses a unique no-capability profile, explicit environment, package/temp ACLs, bounded inherited pipes, and a Job Object assigned before resume. Native and Python runtimes both have Windows smoke coverage; Python runs from the staged EvoFlux interpreter with isolated flags and imports only from the staged read-set. Windows adversarial tests pass for staged helper imports, Settings-config file denial, host write denial, loopback denial, child process creation, CPU/memory limits, timeout, cancellation, and output limits.
- The backend launch path now reports setup/ACL/process-creation errors as `HookIsolationUnavailable`, so a declaration's `fail_open` policy cannot turn a failed security boundary into an allowed operation. Settings and Plugin Center status are based on current host backend availability.
- Final focused regression after cancellation, independent CPU quota, and Win32 handle-prototype fixes: backend/lifecycle/API → 208 passed, 2 skipped, 1 deselected; Windows containment smoke → 8 passed; frontend hook Settings/package review → 9 passed; TypeScript, focused ESLint, and changed-file Ruff passed; `git diff --check` passed.
- Full-suite limits: full frontend Vitest → 891 passed. The Windows/Bash Python executable-path regression in `tests/agent/tools/test_process.py::test_shell_yields_process_and_activates_continuation` was fixed and its targeted test passes. The installer mode test now respects the POSIX-only executable bit, and the run-dev signal test no longer sends SIGINT to pytest; its process-group-only case skips on Windows. The latest full backend run still does not complete: 13 failures were reported by 12%, then pytest received `KeyboardInterrupt`. Failures include Windows permission/mode assumptions, unavailable `.tests/config/agents/coding` fixtures in team-worktree tests, and unrelated baseline suites. Do not claim the full repository backend suite green.
- Final focused verification after formatting and type-narrowing fixes: hook/lifecycle/runtime backend suite → 116 passed, 2 skipped; Windows isolation smoke → 8 passed; plugin/settings/suggested-task hook API tests → 12 passed; WebBridge create/resume lifecycle tests → 2 passed; full frontend Vitest → 891 passed; TypeScript, scoped `ty check app/agent/plugins app/plugin_platform`, Ruff lint/format, and `git diff --check` pass. Portability checks: Git Bash process continuation → 1 passed; installer executable-bit check → 1 passed; run-dev tests → 2 passed, 1 POSIX-only skip. Full backend suite remains incomplete due unrelated Windows/test-fixture failures; unsupported executable-hook hosts remain fail-closed.
