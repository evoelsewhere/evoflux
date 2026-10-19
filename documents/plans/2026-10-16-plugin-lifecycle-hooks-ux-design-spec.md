# Automatic Workflows UX Design Spec

- **Status:** Proposed design; no UI or runtime behavior is changed by this document.
- **Audience:** EvoFlux users who install plugins but do not write code, plus implementers of Plugin Center and Settings.
- **Scope:** Plugin-provided lifecycle hooks and Settings-owned hook policy in the existing plugin lifecycle hooks feature.

## Problem

The current feature exposes implementation terms before it explains the user outcome. **Settings → Lifecycle hooks** leads with a JSON editor and terms such as runtime, entrypoint, read-set, event fields, isolation profile, and digest. In Plugin Center, hook declarations are nested inside **Components**, and the review surface presents command lines, file paths, matchers, timeouts, environment names, and hashes together.

A non-developer installing a workflow such as Superpowers should be able to understand what will happen and turn it on without editing JSON or learning lifecycle event names. They must still make an informed choice about trusting the specific hook.

## Product goal

Make the common task feel like enabling a clearly described automatic workflow:

> “When I start a session, include this plugin’s workflow guidance.”

Users should not need to author hook definitions or commands to use a supported plugin workflow. Technical configuration remains available under **Advanced**.

## Current implementation boundaries

The existing feature already provides the security and policy primitives this design uses:

- Plugin installation starts disabled. Enabling a plugin makes its Skills available and starts its declared MCP resources, but does not approve hook trust.
- Each hook has separate, digest-bound trust. Trust is revoked or must be reviewed again when the approved hook content changes.
- Static-context hooks read one approved Markdown file and add bounded content as untrusted session context. They do not execute a command.
- Command hooks execute only on a host with verified OS isolation. Unsupported hosts fail closed.
- Settings can augment plugin hooks, replace plugin hooks for selected events, or disable exact `(plugin_id, hook_id)` targets. Replacement preview already lists the plugin registrations that will be suppressed.
- Settings precedence cannot bypass EvoFlux authorization, core runtime checks, or sticky deny decisions.

Relevant implementation: `web/src/routes/settings.hooks.tsx`, `web/src/components/PluginPackageReview.tsx`, `web/src/components/PluginTrustReviewDialog.tsx`, `app/api/schemas/settings.py`, and `app/agent/plugins/hook_contract.py`.

## Design principles

1. **Lead with intent.** Say what happens and when before showing event names or command details.
2. **Separate three choices.** Importing a plugin, enabling the plugin, and trusting a hook are distinct decisions with distinct controls.
3. **Explain trust in concrete terms.** Show what the hook reads, whether it runs code, and whether the host can enforce its isolation profile.
4. **Progressive disclosure.** Keep argv, paths, runtime, digest, matcher, timeout, and isolation profile under **Technical details**.
5. **Keep security invariants visible.** Simple controls can change configurable plugin behavior, never authorization or core safety checks.
6. **Make changes reversible.** Users can pause a hook, disable a plugin, revoke trust, or restore the default policy without deleting their package.

## Information architecture

Name the user-facing Settings destination **Agent hooks** so users can find behavior that affects agent chats. Keep “lifecycle hook” in a subtitle and in Advanced details so contributors can still find the technical concept. Plugin Center may describe the package component as an **Automatic workflow**.

The page has three sections:

1. **Plugin workflows** — hooks discovered from installed plugins, grouped by status.
2. **How workflows work together** — the global augment/replace preference and per-hook pause controls.
3. **My workflows** — Settings-owned definitions, with a guided, no-code session-guidance workflow and an Advanced editor for technical definitions.

In Plugin Center, summarize component types at the top level: **Skills**, **MCP servers**, and **Automatic workflows**. Keep detailed component inspection in the existing disclosure.

## Screen specifications

### 1. Plugin Center: package summary

For every inspected or installed plugin, show a compact summary before the technical component details:

| Component | Plain-language explanation |
|---|---|
| Skill | “Teaches the agent a workflow when it matches your task.” |
| MCP server | “Adds tools or connects to an external service.” |
| Automatic workflow | “Runs at a specific point, such as when a session starts.” |

Show the number of each component and whether it is ready, needs review, paused, invalid, or unavailable on this device. A plugin without hooks should not show an empty hook warning.

### 2. Hook review and trust

The default review view answers these questions in order:

- **When does it run?** Example: “When a new session starts.”
- **What does it do?** Example: “Adds the plugin’s workflow guide to the session.”
- **What can it read or change?** Name the declared inputs and outputs in user language; say “No session data is provided” for a static-context hook.
- **Does it run code?** Clearly distinguish reading a Markdown file from running a command.
- **Can this device enforce the required isolation?** If not, explain that the command will remain blocked on this device.

Provide a collapsed **Technical details** area for exact command/entrypoint, package files, matcher, timeout, environment field names, failure policy, isolation profile, and SHA-256. Never show secret values.

Actions must name the decision they make:

- **Keep disabled** — close review without enabling or trusting.
- **Enable plugin** — enable plugin capabilities; state that hook trust remains separate.
- **Allow this workflow** — approve only the displayed hook digest and profile. This does not enable the plugin.
- **Revoke workflow approval** — remove the matching trust grant.

Do not use a combined “Trust and enable” action for hooks. If an existing platform-specific consent is also required to enable MCP access, explain it in its own section and label its action separately.

### 3. Agent hooks Settings

#### Plugin workflows

Show each plugin hook as a row/card containing:

- A readable description, plugin name, and trigger moment.
- State: **Needs review**, **On**, **Paused**, **Blocked on this device**, **Changed; review again**, or **Invalid**.
- A primary action appropriate to the state: **Review workflow**, **Pause**, **Resume**, or **View why it is blocked**.
- A detail disclosure for technical metadata and trust status.

Show the source plainly. Managed package hooks are labeled with the plugin name. If a legacy local Python hook appears in a policy preview, label it as a local-code extension and state that it runs inside EvoFlux; do not present it as having the same isolation as a managed package hook. Preview reads trusted legacy source without importing or running it. If it cannot statically establish callback subscriptions, show a possible impact rather than claiming an exact match.

Pausing one plugin hook maps to the existing exact `disabled_plugin_hooks` target. It must not disable another plugin’s hook with the same hook ID.

#### How workflows work together

Use two descriptive choices instead of an unexplained mode dropdown:

- **Run plugin workflows alongside my workflows** — default; maps to `mode: augment`.
- **Use my workflows at selected moments** — maps to `mode: replace` plus `replace_plugin_events`.

When the second choice is selected, show common moments first and group less common agent and context events under a collapsed **Other moments** disclosure. Use plain language for common moments and show canonical event names only in the expanded technical group. Before saving, show the replacement preview in a confirmation dialog:

```text
For “At the start of a chat,” these plugin workflows will stop running:
• Superpowers — Add its session workflow guide

Your approved Settings workflow will be used for this moment.
EvoFlux permission and safety checks stay on.
```

If the preview is empty, say that no enabled plugin workflows will be replaced. If preview fails, do not save the replacement policy.

If an event is selected for replacement but no matching Settings workflow is both approved and active, explain that the selected plugin workflows will stop and nothing will run at that moment. A saved but unapproved definition is not a valid replacement. Require the same explicit confirmation; never imply that an empty replacement is a working custom workflow.

The existing exact-target disable control remains available per plugin workflow. Do not imply that selecting a moment replaces only one plugin: the current policy replaces configurable managed and legacy plugin hooks for that selected event. Preview every managed registration and statically identified trusted legacy callback. Dynamic legacy declarations are marked as possible impact; preview must never import or execute local code.

#### My workflows: guided session guidance

Provide a **Create workflow** path for one safe, no-code action supported by the current hook contract:

1. Name the workflow.
2. Choose or enter the guidance text.
3. Explain that it is added when a new session starts and is treated as plugin/user-provided content, not as EvoFlux system policy.
4. Save it disabled and show **Review and allow** as a separate trust action.

The guided path is limited to `session.start` static context: no command, event input, or arbitrary file access. Command-based definitions and less common events stay under **Advanced**.

**Implementation dependency:** the current Settings contract references a package-relative file, but Settings does not yet have a guided content-file creation flow. The implementation must add a narrowly scoped API that atomically stores the Markdown under a dedicated directory inside `EVOFLUX_CONFIG_DIR`, rejects traversal/symlinks, enforces a small size limit, and returns the relative path. The UI then writes the existing `static_context` definition shape and uses the existing digest-bound trust flow. Do not broaden the hook runner’s filesystem access.

#### Advanced editor

Keep the current JSON editor and the existing schema validation under a collapsed **Advanced: edit hook settings JSON** disclosure. Show a short warning that this editor is for technical users; do not present JSON as the normal way to enable, pause, or replace plugin workflows.

Advanced editing must preserve current behavior: invalid JSON cannot save; replacement still previews affected registrations; changing definition content requires a new trust review.

## Example: enabling Superpowers

1. The user imports the plugin and sees that it contains Skills and one automatic workflow.
2. The summary says: **“Adds Superpowers guidance when a new session starts.”** It says the supported action reads a Markdown guide and does not run the upstream shell launcher.
3. The user enables the plugin. The Skills become available; the hook remains **Needs review**.
4. The user opens **Review workflow**, reads the plain-language effect, and expands **Technical details** only if desired.
5. The user selects **Allow this workflow**. The approval is for that exact content digest; if the package changes, the state returns to **Changed; review again**.
6. On a later session start, the hook contributes bounded, provenance-marked untrusted guidance. It cannot grant tool permission or override EvoFlux safety rules.

## States and failure copy

| State | User-facing explanation |
|---|---|
| Needs review | “This workflow is paused until you review what it can do.” |
| Changed; review again | “The workflow changed since you approved it. Review the new version before it runs.” |
| Blocked on this device | “This device cannot enforce the isolation this command needs, so it will not run here.” |
| Invalid | “EvoFlux could not verify this workflow. It remains off.” Link to diagnostics. |
| Paused | “This workflow is off. You can resume it at any time.” |
| Trust revoked | “Approval removed. The plugin remains installed; this workflow will not run.” |
| Replacement preview failed | “Could not confirm which plugin workflows would be affected. Nothing was changed.” |

Do not expose stack traces or raw untrusted hook output in these states. Keep detailed diagnostics available through the existing diagnostics surface.

## Accessibility and localization

- All cards, disclosures, radio choices, toggles, and dialogs must work by keyboard and expose clear accessible names and state.
- Do not rely on color alone for trust, blocked, or paused states.
- Keep the primary effect and action visible at narrow panel widths; technical details may scroll inside the dialog.
- Localize user-facing labels and event descriptions in English, Vietnamese, and Japanese. Keep canonical event IDs and JSON keys untranslated in Advanced details.
- Use the existing design tokens and shared Settings/Plugin Center components; do not create a separate visual language for hooks.

## Data and API impact

The policy UI can serialize the existing `HookSettingsBody`: `mode`, `replace_plugin_events`, `disabled_plugin_hooks`, and `definitions`. Existing replacement preview and trust endpoints remain the authority for effect and trust. No database migration is needed.

The no-code guidance editor requires one additional confined file-write capability as described above. This endpoint must not accept arbitrary destinations or commands. The saved definition and file still pass the same validation, digest, trust, and runtime isolation gates as other Settings hooks.

## Out of scope

- Generating or executing shell commands from natural-language instructions.
- Making hooks trusted automatically when a plugin is installed or enabled.
- Allowing Settings or plugin hooks to bypass permissions, sandboxing, isolation, or authorization.
- Executing unsupported Claude hook forms or the Superpowers shell launcher.
- A full hook execution history. A future activity view may be designed separately once the runtime exposes a safe, privacy-bounded event record.

## Acceptance criteria

1. A non-developer can tell the difference between a Skill, an MCP server, and an automatic workflow without reading a manifest.
2. A supported static-context plugin workflow can be enabled without editing JSON, while plugin enablement and hook trust remain separate actions.
3. Before trusting a hook, the user can identify when it runs, what it does, what data it can read/change, and whether it executes code.
4. Exact command, file, digest, matcher, timeout, environment, and isolation details remain available for technical review.
5. The default policy is explained as running plugin workflows alongside Settings workflows.
6. Replacement selection previews every affected managed registration and statically identified trusted legacy callback; dynamic legacy code is shown as a possible impact without being run for inspection. The preview clearly states that core EvoFlux safety checks remain active; if no Settings workflow will run for that moment, the UI says so explicitly.
7. Pausing a hook targets the exact plugin/hook pair; it does not pause unrelated hooks.
8. Changed or invalid content never retains an effective approval for a different digest; unsupported isolation remains fail-closed.
9. The guided Settings workflow can only create static session-start guidance and writes files only inside its dedicated config subdirectory.
10. All states and actions are keyboard-accessible and have English, Vietnamese, and Japanese strings.

## Delivery phases

1. **Clarity pass:** Plugin Center component summaries, plain-language hook status, concise trust review, and consistent separate actions.
2. **Policy controls:** Replace the JSON-first Settings page with visual augment/replace controls, event descriptions, exact-hook pause controls, and affected-hook preview; retain JSON under Advanced.
3. **Guided custom workflow:** Add the confined Markdown content API and no-code static session-guidance builder.
4. **Verification:** UI tests for all states and policy transitions, API tests for confined file creation, and a browser smoke test using the Superpowers static-context package.

The spec changes presentation and adds the no-code guided content path; it does not change the hook trust model or execution contract.
