# Plugin Lifecycle Hooks

Status: Implemented in part. Lifecycle dispatch, trust review, and one
data-only Superpowers bootstrap adapter are active. Arbitrary command hooks
remain disabled until a verified platform isolation backend exists.

## Problem

EvoFlux has two separate plugin contracts. Portable Agent Plugin packages provide Skills and MCP servers through `app/plugin_platform/`. Trusted Python hook modules are separately discovered from `settings.plugin_dirs()` and loaded by `app/agent/plugins/loader.py`. The marketplace adapter translates only the exact Superpowers SessionStart bootstrap to a bounded, read-only static-context action; it does not run the upstream launcher. Other Claude hook shapes remain unsupported.

The agent loop already exposes typed callbacks for agent start/stop, model before/after, tool before/after, completion validation, compaction, and subagent start/stop. What is missing is package discovery, a bounded execution contract, mapping from host events to EvoFlux lifecycle boundaries, settings-level management, and deterministic precedence.

## Goal

Allow an enabled EvoFlux plugin package to contribute reviewed lifecycle hooks that run at documented points in the EvoFlux agent lifecycle. Let users add hooks in global Settings and choose whether those settings hooks augment or replace plugin hooks for selected events. Preserve the existing portable Skills/MCP contract and trusted Python hook path.

## Non-goals

- Replacing `BaseAgentHook` or the internal `HookPipeline`.
- Executing package Python inside the FastAPI sidecar process.
- Claiming all Claude Code or Codex events have equivalent EvoFlux semantics.
- Treating prompt instructions as deterministic enforcement.
- Making settings hooks capable of disabling protected runtime security, permission, sandbox, persistence, or correctness invariants.
- Adding hooks to public marketplace policy without a separate product and security review.

## Security model and threat boundaries

Treat command hooks as executable code, including Settings-owned commands. Explicit trust permits the declared command to run but does not grant authority over EvoFlux policy. The `static_context` action is a separate data-only capability: it reads one digest-bound package file, accepts no event input, and adds bounded text as untrusted context; it never starts a process. Timeouts and output limits protect availability but a subprocess alone is not an OS security boundary.

The existing flat `.py` hook loader is a legacy trusted-code path: it imports modules in-process under its current hash-trust behavior and does not gain the new isolation guarantee in this feature. Keep it distinct in status and review surfaces; do not use it as a fallback for managed package or Settings hooks. Settings `replace` can suppress legacy plugin registrations at the event resolver, but cannot suppress EvoFlux's built-in `HookPipeline` invariants.

Executable hooks run only through a platform isolation backend that enforces an approved capability profile. The default profile allows access only to the staged runtime, entrypoint, declared read-set, and a private temporary directory; it denies network access, blocks credentials and unrelated user/project files, limits CPU/memory/process creation, and terminates the whole child process tree on timeout or cancellation. Do not grant the sandbox access to a Settings config root: stage only the entrypoint and explicitly declared files. If a host cannot provide the required isolation, the hook remains inspectable but does not execute. Never silently fall back to an unrestricted subprocess. Any future expansion, such as network access or additional readable paths, requires a separate explicit capability grant and review.

EvoFlux's core permission, sandbox, and tool authorization policy is authoritative. Hooks may add a denial or narrow a validated action; they cannot grant a capability, suppress a core denial, or approve a tool call. After a hook rewrites tool arguments, EvoFlux validates the result and reruns core authorization on the final arguments immediately before execution. Settings `replace` affects configurable plugin hooks only and cannot remove these checks.

Hook inputs and outputs are untrusted data at the model boundary. Pass only the event's minimum typed fields, never ambient credentials or the full transcript by default. Mark hook-provided text with provenance and put it in a bounded, lower-authority context slot; never splice it into system policy or a privileged instruction role. Treat text from users, tools, packages, and hooks as possible prompt injection. Natural-language instructions cannot authorize tools; only core policy can. This reduces injection impact but does not claim prompt injection can be eliminated by prompt wording.

Settings edits do not imply execution trust. Trust is a separate user action bound to the exact definition, executable digest, and capability profile. Editing the command, files, data access, or isolation profile invalidates approval. A replace operation shows affected events and plugin hooks before save. Plugin hooks cannot change global Settings or grant themselves trust through hook output.

## Design

### Package contract

Keep the portable Agent Plugins manifest for identity, Skills, and MCP. Add an EvoFlux-owned extension at `extensions.com.evoflux.hooks`. It references package-relative, versioned declarative hook definitions; every referenced file begins with `./` and resolves inside the package root. A definition contains a stable hook ID, event, optional matcher, execution kind, explicit runtime (`native` or `python`), source/command path, additional package-relative `files` read-set, timeout, bounded input/output contract, and failure policy. The entrypoint and every declared file must be regular, non-symlink files inside the package. The canonical definition digest includes their normalized relative paths and bytes. `native` invokes the staged entrypoint directly; `python` invokes the bundled Python runtime in isolated mode (`-I -S`) against the staged entrypoint. No shell runtime or implicit package imports are supported. `command` hooks invoke argv only through verified OS containment. `static_context` is limited to `session.start`, one file, no event inputs, and the `context` output only.

A plugin without this extension behaves as it does today. Existing flat Python hooks remain supported through their current trusted-plugin directory and loader. The marketplace install state and hook trust state remain separate: installation or enabling alone never authorizes executable code.

### Canonical lifecycle events

Define EvoFlux event names and semantics rather than silently adopting vendor names:

- `session.start` / `session.end`: chat/work session creation, resume, fork, compaction continuation, and close; carry a source field.
- `prompt.submit`: immediately before the user prompt enters the agent loop; may add bounded context or block with a reason.
- `agent.start` / `agent.stop`: one agent run, separate from a longer-lived session.
- `model.before` / `model.after`.
- `tool.before` / `tool.after`: before may deny or replace validated arguments; after may return a bounded result update.
- `completion.before`: inspect a tool-free candidate and either allow it or return bounded feedback for another model iteration.
- `compact.before` / `compact.after` and `subagent.start` / `subagent.stop`.

Inputs are typed JSON containing only fields needed by the event. Do not include credentials, unrestricted application state, or complete transcripts by default. Validate outputs against event-specific schemas and reject fields outside the declared contract.

### Settings hooks and precedence

Add a `hooks` section to persisted `RuntimeSettings`, exposed through the normal settings API and a dedicated Settings page. It holds user-authored hook definitions, the hook-layer mode (`augment` or `replace`), and explicit per-event/plugin-hook disable entries. A Settings definition can target a plugin hook by the exact pair `(plugin_id, hook_id)` to shadow it. Definitions use the same declarative command format and bounded runner as package hooks; settings are not a separate execution mechanism.

Precedence is scoped to configurable plugin hooks, including managed package hooks and legacy trusted Python plugin registrations:

1. Protected EvoFlux runtime invariants always execute and cannot be shadowed, disabled, or reordered by plugin or Settings hooks.
2. Settings hooks have the highest user-configurable priority. A Settings hook shadows only the exact plugin definition it targets by `(plugin_id, hook_id)`; for a legacy Python module, `plugin_id` is its stable module identity. In `replace` mode, Settings hooks are the only configurable plugin hooks dispatched for the selected events; `augment` mode keeps enabled plugin hooks and adds Settings hooks.
3. Plugin hooks run only when enabled, trusted, supported, and not shadowed or disabled by Settings.

For event outputs, Settings output takes precedence for replaceable values such as context enrichment, argument rewrite, or completion feedback. A deny/block decision is monotonic: no later hook can turn a denial into an allow. Protected invariants run at their required boundary regardless of mode. The UI and API must show which registrations are active, shadowed, disabled, or protected.

### Compatibility adapters

Keep the EvoFlux contract canonical. Add source adapters for supported subsets of Codex and Claude hook declarations. Each adapter maps only events and output shapes with defined equivalents. Unknown declarations and non-equivalent outputs produce inspection diagnostics and do not run. Keep vendor-specific formats at the adapter boundary.

The first compatibility target is Claude hooks, to support the Superpowers session-start bootstrap. Adapt only the exact Superpowers declaration: synchronously read the installed `skills/using-superpowers/SKILL.md`, add the upstream intro wrapper, bound the result, and pass it once at the first prompt after `session.start`. Do not copy or run `hooks/run-hook.cmd`, Bash, or any vendor command. The file action is separately digest-trusted and provenance-marked untrusted. If manifest fields, event shapes, paths, or size differ, report hooks as unsupported while keeping Skills installable.

### Runtime attachment and execution

Keep session events in the session/service layer; do not alias them to `before_agent`, which runs once per agent invocation. At plugin enable or run initialization, resolve enabled installations, Settings policy, current hook digests, and event registrations. Dispatch at the exact lifecycle boundary in deterministic order alongside current typed agent hooks.

Stage only the entrypoint and explicit read-set into an isolated per-run directory, re-hash staged bytes against the reviewed digest, and never grant the sandbox access to the package root or Settings config root. Run command hooks in a subprocess with bounded wall time, input/output size, private working/temp directory, explicit non-secret environment allowlist, and cancellation on run/session cancellation. Require the platform isolation backend described above; a subprocess by itself is not sandboxing. Send structured JSON on stdin and accept structured JSON on stdout. Never import package Python into the sidecar. Invoke argv directly without a shell, validate path containment and symlinks at approval, staging, and immediately before execution, and bind the running content to the reviewed digest. Static context reads no more than 64 KiB from one reviewed file and rechecks the digest against the bytes it returns.

### Initial native isolation backend

The first executable backend targets Windows only: launch inside a dedicated AppContainer with no capabilities, assign the process to a Job Object before resuming it, enforce process/memory/CPU limits and kill-on-close, and expose only a per-run staged file set plus private writable temporary storage. The Windows integration suite verifies staged helper-file reads; denied host-file reads/writes and loopback; denied child-process creation; CPU/memory limits; timeout, cancellation, and output bounds. The bundled Python runtime uses `-I -S` and a fixed bootstrap that adds only the staged entrypoint directory and staged package root to `sys.path`; the package stage contains only digest-bound files. Linux and macOS remain fail-closed until their own filesystem/network/process/resource controls pass equivalent tests. The trust profile version changes whenever these enforced capabilities change.

### Trust, failure, and observability

- Installing or enabling a package does not trust its hooks. Trust review is separate from the explicit enable action.
- The review surface shows event, matcher, command, declared inputs/outputs, resolved package-relative paths, requested environment, and effective isolation/capability profile. Settings replacement shows which plugin hooks it will suppress.
- Bind plugin trust to the hook definition, referenced executable content hashes, and isolation/capability profile. Any changed digest or profile requires review again. Settings-owned executable hooks receive an explicit trust action and the same digest invalidation behavior. Keep definitions in `settings.yaml` and approvals in a separate application-managed hook trust store so editing settings cannot silently grant execution trust.
- Disabling a plugin, hook, or event policy prevents it from future dispatch without deleting user data.
- Context-enrichment failures may continue with a visible diagnostic. An enforcement hook follows its declared fail-open/fail-closed policy; fail-closed stops the affected operation with an actionable reason. Core authorization and isolation failures always fail closed, regardless of a hook's failure policy.
- Record plugin/hook identity, event, duration, outcome, and failure category. Do not log prompt bodies, credentials, or complete hook stdin/stdout by default.

## Acceptance criteria

1. A plugin without hooks still inspects, installs, enables, and contributes Skills/MCP as before.
2. Native package and Settings hooks run only when enabled, supported, and trusted against their current digests.
3. Hooks fire exactly at their declared lifecycle boundary with deterministic ordering and documented JSON shapes.
4. Settings hooks shadow only the exact targeted `(plugin_id, hook_id)`; `replace` mode suppresses managed and legacy configurable plugin hooks for selected events; `augment` mode retains them.
5. Settings wins for replaceable outputs, while deny decisions remain sticky and protected runtime invariants cannot be overridden.
6. Session-start and agent-run-start are distinct; resume/compact source is preserved where available.
7. Definition or executable changes invalidate trust; disabling a plugin/hook/event prevents subsequent execution.
8. Invalid paths, symlinks, oversized payloads, invalid JSON, timeouts, process errors, unknown events, and unsupported vendor outputs produce bounded diagnostics and follow the declared failure policy.
9. The exact Claude Superpowers bootstrap is translated into the read-only static-context action and covered by an installed-package lifecycle integration; other Claude hooks are clearly unsupported while Skills remain installable.
10. Settings and Plugin Center expose effective hook state and trust decisions without exposing secrets or full prompt/transcript data.
11. Hooks cannot execute unless the platform isolation backend enforces the approved profile; unsupported hosts fail closed instead of using an unrestricted subprocess.
12. A tool argument rewrite is schema-validated and re-authorized by core policy before execution; no hook output can grant permission.
13. Hook-provided text is provenance-marked, bounded, and lower authority than system policy; untrusted prompt/tool data cannot directly approve tools.
14. Editing a Settings hook or replacing plugin hooks does not automatically trust code, bypass tool policy, or change protected runtime checks.
15. Managed package and Settings hooks never fall back to the legacy in-process Python loader; the UI distinguishes legacy in-process trust from OS-isolated execution.

## Rollout

1. Verify an enforced isolation profile and child-process behavior on each supported OS; disable execution on any platform that cannot meet it.
2. Define the canonical hook schema, package extension, Settings data model, event contracts, and precedence resolver.
3. Add inspection and trust review for package and Settings-owned definitions.
4. Implement the isolation backend, bounded subprocess runner, and typed event dispatch.
5. Add the Settings management surface and effective-state visibility in Plugin Center.
6. Add the Claude adapter and Superpowers fixture; add Codex mappings only for events with verified equivalent semantics.
7. Update feature, architecture, authoring, and in-app Help documentation.

Ship the EvoFlux-native contract first. Enable each vendor adapter only after focused mapping and execution evidence.

## Decisions for implementation

- Canonical package extension: `extensions.com.evoflux.hooks`.
- Canonical executable runtimes: `native` and `python`; entrypoint plus declared package-relative `files` are included in trust digests and staged read-only. Python uses the packaged EvoFlux runtime, never a host `python` resolved from PATH.
- First executable containment target: Windows AppContainer without capabilities plus Job Object; Linux/macOS remain fail-closed pending independent verification.
- First compatibility adapter: Claude hooks, specifically the Superpowers bootstrap path.
- Settings hooks are global and have the highest precedence among configurable plugin hooks, with explicit `augment`/`replace` behavior per selected event.
- Runtime invariants and sticky deny decisions are outside user-configurable precedence.
- A subprocess is not accepted as a security boundary; executable hook support is gated on enforced OS-level isolation, with fail-closed behavior when unavailable.

## Security implementation references

- Windows AppContainer restricts file, network, credential, and process access according to granted capabilities: [Microsoft AppContainer isolation](https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation) and [launching an AppContainer](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer).
- macOS App Sandbox restricts filesystem/network access; child tools inherit the containing app sandbox, and Apple documents helper-process constraints: [App Sandbox](https://developer.apple.com/documentation/security/app-sandbox) and [embedding a command-line tool](https://developer.apple.com/documentation/xcode/embedding-a-helper-tool-in-a-sandboxed-app).
- Linux seccomp filters reduce syscall surface and cgroup v2 provides resource control; these are separate controls that must be validated together with filesystem and network isolation: [Linux seccomp filter](https://docs.kernel.org/userspace-api/seccomp_filter.html) and [cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html).
