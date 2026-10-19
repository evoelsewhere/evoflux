# Automatic Workflows UX Implementation Plan

> **For implementation agents:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to carry out this plan task-by-task. Keep the security and trust boundary intact. This plan is intentionally implementation-ready; do not combine plugin enablement with hook approval.

**Goal:** Replace the JSON-first lifecycle-hook experience with a plain-language Agent Hooks experience, including plugin workflow summaries, understandable trust review, visual policy controls, and a no-code session-guidance builder.

**Architecture:** Keep `HookSettingsBody`, digest-bound hook trust, the replacement-preview endpoint, and the runtime resolver as authorities. Add one narrow Settings API for atomically writing bounded Markdown into a fixed directory under `EVOFLUX_CONFIG_DIR`; the builder then saves the existing `static_context` definition pointing at that file. Build the UI on existing React Query/settings patterns and place technical JSON and metadata behind Advanced disclosures.

**Tech stack:** FastAPI/Pydantic, pathlib and atomic file replacement, React/TypeScript, TanStack Query, Vitest/Testing Library, pytest, existing app/browser smoke setup.

**Design source:** `documents/plans/2026-10-16-plugin-lifecycle-hooks-ux-design-spec.md`.

## Constraints and invariants

- Importing/enabling a plugin, approving a hook, and defining Settings policy remain separate user actions.
- Hook approvals remain bound to the exact current definition digest and isolation profile. Editing Markdown invalidates the previous approval through the existing digest check.
- The guided builder creates only `session.start` + `static_context`, with no command, event input, or arbitrary read access.
- The Markdown endpoint accepts content, never a caller-selected filesystem destination. It writes only under a dedicated fixed subdirectory of `EVOFLUX_CONFIG_DIR`, rejects symlink/path escape, enforces the documented small size limit, and uses an atomic replace.
- Hook contents remain untrusted session context. No hook, policy, or Settings override can bypass authorization, sandbox, isolation, or protected runtime checks.
- Replace mode continues to affect only configurable plugin hooks; show the existing exact replacement preview and require confirmation, including when the Settings workflow list for an event is empty.
- Per-hook pause uses the exact `(plugin_id, hook_id)` identity already represented by `disabled_plugin_hooks`.
- Keep existing unrelated dirty worktree changes and the isolated smoke fixture intact.

## Task 1: Add confined Settings workflow Markdown storage

**Files:** `app/api/routes/settings.py`, `app/api/schemas/settings.py`, focused tests in `tests/api/test_settings_routes.py` (or a dedicated `tests/api/test_settings_hook_content.py` if that keeps fixtures clearer).

1. **Test first:** add API cases for create/update returning a stable package-relative path, UTF-8 Markdown round trip, empty/oversized/non-text rejection, invalid identifier rejection, traversal rejection, pre-existing symlink rejection, and atomic-write failure leaving the previous file intact.
2. Add a strict request/response schema. The client supplies a stable opaque workflow identifier and Markdown body; it does not supply a path or filename. Set an explicit byte limit aligned with the static-context runner limit and document it in one constant.
3. Implement a helper that resolves the configured root, creates a fixed workflow directory, verifies the directory and target are not symlinks and remain under the root, writes to a same-directory temporary file, flushes, then atomically replaces the target. Clean up only the temporary file on failure.
4. Add a dedicated endpoint such as `PUT /api/settings/hooks/workflows/{workflow_id}/content`; validate identifier format and return only the fixed relative path needed by `HookDefinition.command`.
5. Confirm the endpoint neither edits settings nor grants trust. The existing settings update, hook digest, and trust-review flow remain subsequent independent steps.

**Verification:** focused API tests, including platform-appropriate symlink behavior; inspect failure cases to ensure no file is written outside the test config root.

## Task 2: Expose the content API to the frontend

**Files:** `web/src/api/types.ts`, `web/src/api/client/settings.ts`, `web/src/queries/keys.ts` only if a distinct query is needed, a focused client test under `web/src/__tests__`.

1. **Test first:** verify the client sends the identifier and Markdown JSON to the fixed route, returns the relative path, and surfaces non-2xx API detail consistently with neighboring settings functions.
2. Add request/response types and a typed client function. Do not add a query for file content; the mutation response is sufficient.
3. Add a mutation hook in `web/src/queries/useHookSettingsQuery.ts` (or a small adjacent module) and export it from `web/src/queries/index.ts` if the page should not call the client directly.

**Verification:** focused frontend client/mutation tests and TypeScript typecheck for touched modules.

## Task 3: Replace JSON-first Settings with visual Automatic Workflows controls

**Files:** `web/src/routes/settings.hooks.tsx`, `web/src/__tests__/routes/settings.hooks.test.tsx`, `web/src/components/SettingsScreen.tsx`, `web/src/components/settings/SettingsSidebar.tsx`, route metadata only if the visible route title is stored separately.

1. **Test first:** extend page tests for translated event labels; default augment selection; selecting replace events; preview confirmation; preview failure leaving settings unchanged; empty preview copy; empty Settings workflow warning; exact-target pause/resume; dirty-state/save behavior; Advanced editor expand/collapse and invalid JSON behavior.
2. Make the page’s primary title/navigation “Agent hooks”; retain “Lifecycle hooks” as secondary technical context where useful.
3. Render two explicit policy choices with explanatory copy: run plugin workflows alongside mine (augment) and use my workflows for selected moments (replace). Render event moments in plain language with canonical IDs only in technical disclosure.
4. Fetch plugin registrations/status using the available existing API types/endpoints; show plugin/source, trigger, friendly effect, state, and state-appropriate action. Confirm whether the existing hook status payload contains enough display metadata; if not, make the smallest additive response change with API tests rather than inferring from raw IDs.
5. Map pause/resume to exact `(plugin_id, hook_id)` entries. Preserve other targets and deduplicate on save. Preview trusted legacy local Python extensions without importing/running them; label statically known callbacks as local code and dynamic declarations as possible impact.
6. On replace changes, call the existing preview endpoint before saving. Display exact affected registrations in readable language. If preview errors, do not save. If no user-owned Settings workflow exists for a selected event, warn that plugin workflows stop and nothing runs for that moment.
7. Move the current JSON textarea and event-level raw configuration into a collapsed Advanced disclosure. Preserve schema/error handling, dirty registration, and confirmation logic.

**Verification:** focused Settings route tests, keyboard interaction tests for radio/card controls, and TypeScript/lint checks on touched files.

## Task 4: Build the no-code “My workflow” guidance flow

**Files:** `web/src/routes/settings.hooks.tsx` or a focused component under `web/src/components/settings/`, `web/src/api/types.ts`, the hook query/mutation module, route tests, and API tests from Task 1.

1. **Test first:** builder validation, stable generated hook ID, title/content fields, the session-start explanation, save-disabled behavior, review/allow as a separate action, edit causing approval to become stale, delete behavior, and preventing command/event/input fields from entering a guided definition.
2. Add a Create workflow flow asking for a name and guidance Markdown. Generate a stable safe identifier in the client or server, but never accept a path from the client.
3. Save content through the confined endpoint, then save a `HookDefinition` using the returned relative path and fixed `session.start`/`static_context` fields through the existing settings endpoint.
4. Keep the new definition untrusted and present “Review and allow” separately. Reuse the current trust API and show the existing digest-bound review; for this static-context guided path, lead with readable effects and put technical details behind disclosure.
5. If content write succeeds but settings save fails, retain the draft and offer retry; avoid automatic trust. If a workflow is removed, revoke its trust via the existing settings update behavior. Do not add recursive cleanup or delete unrelated files.

**Verification:** route/component tests for save/retry, trust separation, modified-content re-review, and removal; API tests verify constrained writes.

## Task 5: Improve Plugin Center summaries and hook review language

**Files:** `web/src/components/PluginCenterPanel.tsx`, `web/src/components/PluginPackageReview.tsx`, `web/src/components/PluginTrustReviewDialog.tsx`, corresponding component tests.

1. **Test first:** component counts and status summaries for Skills/MCP/workflows; no empty-hook warning when there are no hooks; plain-language status and event/action copy for valid, invalid, untrusted, changed, blocked, trusted, and disabled hooks; trust action remains separate from plugin enablement.
2. Show compact component summaries on plugin cards/inspection surfaces using “Skills”, “MCP servers”, and “Automatic workflows,” with count and readiness state. Keep the Settings destination named “Agent hooks.”
3. Reorder the default hook review information to when/what/data/code/device-isolation. Put argv, files, matcher, timeout, environment field names, isolation profile, and digest under Technical details. Never display credential values.
4. Use distinct actions for enabling the plugin and allowing/revoking one workflow. Ensure the plugin enable dialog does not imply that hook trust is included.
5. Preserve existing plugin diagnostics and component disclosures; do not create a second review or consent authority.

**Verification:** focused component tests and accessible-name/keyboard assertions for disclosures and actions.

## Task 6: Localize, document, and update changelog

**Files:** `web/src/help/locales/en.ts`, `web/src/help/locales/vi.ts`, `web/src/help/locales/ja.ts`, relevant `documents/features/` or `documents/guides/agent-plugins.md`, `CHANGELOG.md`.

1. **Test first:** add/extend localization coverage ensuring the new Settings and Plugin Center labels have EN/VI/JA values and event canonical IDs are not accidentally translated in Advanced output.
2. Add consistent localized strings for every new user-facing label, status, confirmation, empty state, validation message, and warning.
3. Update user-facing plugin help and feature documentation to explain the visual workflow experience and preserve accurate trust/security behavior.
4. Add a changelog entry describing the user-visible Automatic Workflows experience and constrained custom static guidance flow.

**Verification:** localization test(s), relevant docs checks, and review that no new visible text is hard-coded in the UI.

## Task 7: End-to-end verification and browser smoke

**Files:** existing tests plus a smoke script/fixture only if the repository has a suitable established pattern; do not change the existing isolated fixture unnecessarily.

1. Run targeted backend unit/API tests for confined content writes, hook status/trust, replace preview, and settings persistence.
2. Run targeted frontend tests for Settings policy, guided builder, Plugin Center summaries, trust review, and localization; run frontend typecheck/lint/build as the repo’s standard scripts permit.
3. Run broader plugin lifecycle integration tests for session-start static-context injection, digest invalidation, exact-hook pause, replace/augment precedence, and protected authorization/safety invariants.
4. Launch the app against the isolated EvoFlux config/provider environment already established for this task. In browser, verify the route label, import/inspect the Superpowers static-context package, see its workflow summary, enable the plugin without auto-trusting, allow the workflow separately, observe it listed in Automatic Workflows, pause/resume it, then create/allow a Settings guidance workflow and verify it appears alongside plugin workflows.
5. Verify changed Markdown requires review again, replace preview names affected workflows and confirms before save, and empty replacement explains that nothing runs at that moment.
6. Record exact commands and results. Report focused checks separately from browser smoke and any broader checks that could not complete. Stop only app processes created for this smoke run and preserve provider configuration and unrelated user processes.

## Review checklist

- [x] Every acceptance criterion in the UX design spec maps to a task and a verification step.
- [x] Settings file-write API is fixed-root, path-independent, bounded, symlink-safe, and atomic.
- [x] No flow combines plugin enablement with hook trust.
- [x] Static context stays untrusted context; commands remain behind existing isolation and trust gates.
- [x] Replacement preview is mandatory before changed replacement policy is saved.
- [x] Exact pause identity is `(plugin_id, hook_id)`.
- [x] Advanced editor remains available and preserves existing behavior.
- [x] All visible text exists in EN/VI/JA; keyboard and narrow layouts are covered.
- [x] Worktree changes unrelated to this UX remain untouched.

## Implementation execution note

Work in `D:\evoelsewhere\evoflux\.evoflux\worktrees\plugin-lifecycle-hooks` on `feature/plugin-lifecycle-hooks`. The checkout already contains user-authorized lifecycle-hook implementation changes and an isolated browser smoke fixture. Preserve them. Execute tasks in order because the builder depends on the content API and typed client; the policy UI and Plugin Center clarity work can be parallelized only after this plan is approved and ownership/file boundaries are agreed.
