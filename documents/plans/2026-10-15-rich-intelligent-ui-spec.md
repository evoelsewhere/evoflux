# Rich Intelligent UI: Dashboards, Motion, and 3D

**Date:** 2026-10-15
**Status:** Proposed implementation scope
**Repository baseline:** `feat/intelligent-ui-runtime` at `4dda4993`

## Goal

Extend EvoFlux's current task-aware `ui_block` feature so an agent can judge when a richer interface materially helps, then create a useful in-chat dashboard, animated explainer, or 3D scene that matches EvoFlux's theme, survives transcript reloads, and remains interactive.

This plan targets an EvoFlux-native equivalent of the user-visible workflows described for Claude Dashboards and Claude Motion. It does not claim parity with Claude's private implementation, hosted data platforms, or sharing model.

## Current behavior and gaps

- `ui_block` offers 14 validated native block types, including layout and sandboxed custom HTML, with stable block identity and history reconstruction from persisted tool arguments.
- `show_widget` streams custom HTML. `WidgetRenderer` injects theme variables and a `sendPrompt` bridge, but permits `allow-same-origin`, allows external script CDNs, uses wildcard `postMessage`, and does not receive EvoFlux's reduced-motion preference.
- The `intelligent-ui` Skill preloads when the active run has `ui_block`, and teaches task-utility judgment. Its present contract centers on the native block catalog; it does not define dashboards with evidence/freshness, motion timelines, or 3D.
- A model can request a tool absent from its run-local tool map; `tool_executor.py` returns `Tool '<name>' not found.` This failure is observable in the user's transcript and must be prevented by capability-aware prompting and tested for unsupported runtimes.
- Existing theme preferences are `light`, `dark`, and `system`. Theme values are exposed as CSS tokens. The frontend also has a reduced-motion preference.
- Historical Artifact Fabric migrations `00000047` and `00000051` show that a generalized artifact-job control plane was tried and later retired. This feature must not revive that job/revision/review schema. Existing message tool-call arguments already provide session history and update identity.

## Design decisions

### One rich-artifact tool contract

Keep `ui_block` as the default for small, declarative, low-risk interactions. Add a separately described `visual_artifact` tool only for work where a custom dashboard, motion composition, or 3D scene materially improves the result. Its validated envelope contains:

- `artifact_id`: stable snake-case identity used for in-place replacement;
- `kind`: `dashboard`, `motion`, or `scene3d`;
- `title` and `summary`;
- `source_html` for dashboards and motion; a declarative `scene` for 3D;
- optional dashboard `sources` references containing a successful `tool_call_id` and query summary; the frontend resolves the source tool name and links it to the saved call/result;
- required motion `duration_ms`.

The tool emits a single complete SSE frame. Dashboard and motion artifacts carry `source_html`; 3D artifacts carry a declarative `scene` object instead of model-authored executable JavaScript. Dashboard source references are successful tool-call IDs plus a short query summary; the frontend joins each reference to that tool call in transcript history to display the actual tool name and link to its arguments/result. The same tool arguments are stored in normal assistant tool-call history and reconstruct the artifact after reload. Updates use the same stable-id replacement protocol as native UI. No new artifact table, background worker, or scheduler is introduced.

Server validation limits HTML source to **200,000 UTF-8 bytes**, dashboard sources to **12 records**, each title to **120 characters**, summary to **500 characters**, motion duration to **120,000 ms**, and a 3D scene to **100 nodes**. Each 3D node uses a supported primitive (`box`, `sphere`, `cylinder`, or `torus`), position values in `[-100, 100]`, rotation radians in `[-6.2832, 6.2832]`, positive scale values in `[0.01, 100]`, a theme semantic color (`accent`, `foreground`, `muted`, `success`, `warning`, `danger`, or `info`), and an optional label of at most **120 characters**; no node can supply a URL, shader, or script. Dashboard/motion require `source_html`; `scene3d` requires `scene`; mismatched/unknown payloads are rejected. The renderer rejects unknown kinds, malformed source records, and over-limit payloads with a user-visible fallback rather than a blank frame.

### Runtime, theme, and safety

- Render rich source in a dedicated artifact iframe/runtime so it does not silently inherit the legacy widget's looser contract. The frame has no same-origin privilege, no arbitrary network by default, no storage access, no top navigation, and no camera/microphone/clipboard permissions.
- Establish the host bridge with a one-time `MessageChannel` handshake; validate the schema and size of every message. Only explicit artifact actions (resize, send prompt, playback state, export chunks) cross the bridge.
- The injected frame bootstrap exposes `window.evofluxArtifact.onCommand(handler)`, `reportPlayback(state, currentTimeMs)`, and `startCanvasExport(mimeType)`. Motion source must mark its recording surface with `data-evoflux-motion-canvas`, and motion duration is required; playback commands are `play`, `pause`, `restart`, and `seek` with `currentTimeMs`. If no marked canvas is present, the player remains usable but export is disabled with a clear explanation. The host sends one initialization message to the owning iframe only; thereafter both directions use the transferred port.
- Map EvoFlux's current theme tokens and `light`/`dark`/`system` choice into CSS custom properties. Propagate theme changes and reduced-motion state while the artifact is open. Generated output must use those tokens unless the user asks for another palette.
- Keep `ui_block.custom` and legacy `show_widget` working during migration. Do not silently widen the sandbox of existing widgets as part of the rich-artifact renderer.
- Load an exact-version-pinned Three.js build only for `scene3d`. If WebGL is unavailable or context creation fails, render an explanatory static/2D fallback. Pause rendering when offscreen or hidden, honor reduced motion, and cap pixel ratio at **2**, canvas size at **1920 × 1080**, scene nodes at **100**, and animation at **30 fps**.

### Output behavior

**Dashboard.** The agent uses connected tools to inspect the requested data first, including file-reading tools when the user supplied a file. Each data-backed dashboard source points to an actual successful tool call from the active session; the backend validates the reference and the frontend joins it to its actual tool name and result. The query summary is shown beside that tool-call link. Show a freshness time only when it is present in source output or trusted tool metadata; otherwise say the source did not provide a freshness time. When the runtime cannot verify any source, the dashboard is labeled as illustrative/static and never as live. A **Refresh with agent** action sends a normal prompt so the agent can re-run available source tools. This first implementation does not promise background refresh or connector-independent live data.

**Motion.** A motion artifact has deterministic `play`, `pause`, `restart`, and seek controls, a visible duration/progress indicator, captions/labels, and a concise accessible summary. Agent follow-ups replace the same artifact ID and increment its revision in the conversation history. Export records the artifact's canvas using `captureStream()` and `MediaRecorder`; offer MP4 when a supported MP4 recorder is available, otherwise offer WebM with the actual format clearly named. Export is user initiated.

**3D scene.** A scene is interactive with pointer/keyboard controls and a reset camera action. The model chooses a validated declarative primitive scene, and the local Three.js runtime owns all geometry/material creation. The model can choose 3D only when the task benefits from spatial exploration; a labeled 2D/static fallback remains available.

## Scope and non-goals

In scope: capability-aware base context, task-utility selection guidance, the new rich-artifact schema/tool/event/history path, themed isolated rendering, dashboard evidence and user-triggered refresh, motion controls/export, lazy 3D runtime, focused evals/tests, in-app help, and feature documentation.

Out of scope for this implementation: a direct source-code editor for manual user edits (changes are requested through chat and replace the artifact in place), generic connector authoring, background dashboard polling, artifact sharing/collaboration, standalone artifact library, arbitrary external script URLs, generated video footage, automatic model selection, adding unrelated UI block types, and migration/restoration of retired Artifact Fabric tables.

## Acceptance criteria

1. Simple factual/creative answers remain prose; a multi-variable decision, useful dashboard, motion explanation, or spatial problem receives a visual only when controls improve the next step.
2. MiMo and at least one second available model can see the relevant tool and Skill in supported Work/Coding runs; unsupported runs never receive an instruction to call a missing tool.
3. A rich artifact renders inline, matches light/dark/system theme and reduced-motion preference, and is reconstructed from persisted tool-call history after reload.
4. Dashboard values disclose verified source calls and query summaries; a freshness time is shown only when the source itself provides one, and the refresh action returns to the agent without claiming background liveness.
5. Motion can play, pause, restart, seek, update in place, and export an actual supported format with a named fallback.
6. A 3D scene loads the local runtime on demand, pauses when not visible, honors reduced motion, and falls back when WebGL is unavailable.
7. Untrusted source cannot access the parent DOM, EvoFlux storage, arbitrary network, or privileged browser APIs through the bridge.
8. The existing `ui_block` and `show_widget` contract and old transcript history continue to work.

## Evaluation set

Keep model prompts and expected behavior as fixtures, not keyword-routing rules:

| Prompt/task | Expected judgment |
|---|---|
| “What is 17% of 240?” | Direct prose/math; no artifact |
| “Help me choose between these three plans; let me vary monthly usage and compare total cost.” | Interactive calculator/comparison; use native `ui_block` if sufficient |
| “Use the attached monthly metrics to show signups and churn with the source behind each number.” | Dashboard only after reading the source; provenance visible |
| “Turn this onboarding flow into a 30-second explainer I can pause and export.” | Motion artifact with timeline and export affordance |
| “Show the mechanism as a model I can rotate and inspect.” | 3D only if spatial structure adds value; fallback described |
| “Summarize this paragraph in one sentence.” | Concise prose; do not render UI |
| A run without `visual_artifact` receives an advanced-visual request | Never call the missing tool; explain available alternative or use `ui_block`/prose |

## Research references

- [Anthropic: Build live dashboards and animate explainers with Claude](https://claude.com/resources/articles/dashboards-and-motion) describes dashboards that expose their query and data refresh time, and motion artifacts whose code can be edited and exported as MP4. This plan adapts those visible workflows to EvoFlux's local-first tool/session model rather than assuming Anthropic's connector or sharing infrastructure.
- [Three.js: Creating a scene](https://threejs.org/manual/pages/creating-a-scene.html) documents the scene/camera/renderer model and render loop used for the optional 3D runtime.
- [MDN: iframe sandbox](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe) documents iframe sandbox flags and the isolation boundary.
- [MDN: `HTMLCanvasElement.captureStream()`](https://developer.mozilla.org/en-US/docs/Web/API/HTMLCanvasElement/captureStream) and [MediaStream Recording API](https://developer.mozilla.org/en-US/docs/Web/API/MediaStream_Recording_API) document the browser APIs used for user-initiated canvas export. Container/codec support must be detected at runtime.
