# Intelligent Motion Production Research

**Reviewed:** 2026-10-15
**Status:** Research and architecture proposal; no implementation changes
**Target:** EvoFlux `feat/intelligent-ui`

## Executive finding

The recent “video looks like slides” result is not explained by frame rate or by missing FFmpeg alone. EvoFlux already renders deterministic 30 fps frames in the browser. The larger gap is that the model writes nearly all visual choreography as raw canvas code from advisory instructions; EvoFlux has no shared, tested motion-design vocabulary that makes a strong continuous composition the easy default. Music and voice are a separate gap: the current exporter can synthesize short cue sounds, but it does not make a music bed or voiceover.

Model capability can contribute. EvoFlux's checked-in model registry gives `xiaomi:mimo-v2.5-pro` a 1,048,576-token context limit but does not declare image input, while `xiaomi:mimo-v2.5` declares vision input. `motion_review` gates frame images on that capability and returns `samples_unavailable` otherwise. If the active model is MiMo Pro, the agent may write the animation but cannot perform the product's image-based frame review through this tool. The exact provider/model used in the reported run has not been confirmed, and the registry may not reflect every provider deployment.

Claude's public material describes editable, code-authored motion that can be revised in an adjacent artifact editor and exported to MP4. It does not disclose the engine, storyboard prompt, or internal render pipeline. We should copy those observable product behaviors and proven production principles, not claim to know or reproduce Claude's private implementation.

## Evidence from the current EvoFlux branch

The current `intelligent-ui` skill already contains a semantic format-selection policy, motion gates, story sections, a persistent visual anchor, a beat timeline, transitions/hits, deterministic `drawAt(timeMs)`, reduced-motion behavior, and instructions for targeted review. It also says not to use a model call for every encoded frame. The detailed references are [SKILL.md](../../app/agent/builtin_skills/intelligent-ui/SKILL.md), [motion-authoring.md](../../app/agent/builtin_skills/intelligent-ui/reference/motion-authoring.md), and [motion-production.md](../../app/agent/builtin_skills/intelligent-ui/reference/motion-production.md).

The runtime has already implemented much of the production plumbing:

- `motion-video-export.ts` samples the sandbox renderer at absolute timestamps and encodes at 30 fps using WebCodecs and Mediabunny. It selects MP4/AVC when supported and WebM alternatives otherwise, with 720p and 1080p caps.
- `MotionArtifact.tsx` reports completed-frame progress and representative sample frames to the Workbench timeline. The `motion_progress` and `motion_review` tools provide lifecycle and bounded sample review; review images are only returned when the active model capability says it accepts vision.
- `motion-soundtrack.ts` synthesizes bounded short waveform cues. The exporter can mux those cues when the browser supports an audio codec and reports whether audio was included. There is no music/voice/stem pipeline in this route.

These facts make “more frames” the wrong primary fix. A 15-second artifact already produces 450 frames. The renderer can make smooth frames from a timeline; it cannot invent a compelling camera path, connected subject, meaningful anticipation, or varied transition grammar if the generated composition has none.

## What the public references establish

### Claude Motion

Anthropic's Motion guide describes a short-animation artifact built from code that animates text, charts, shapes, and images. Users can revise it in chat or directly in an editor, export MP4, and find it later in the Artifacts tab. Motion is not a video-generation model and does not make realistic footage or people. Anthropic's separate artifact help page describes the adjacent workspace and live editing. None of these pages discloses whether Motion uses Remotion, FFmpeg, or another internal stack.

The guide currently lists Motion as a beta for Team and Enterprise plans; Enterprise owners can enable it and limit access to groups.

The Motion guide makes the product workflow more specific:

- **Intent brief:** ask who will watch, where it will play, and roughly how long it should run; attach the report, data, or images the animation should use.
- **Multiple entry points:** start from any chat, choose Motion in the message-box Output selector, or begin from a Motion template in the Artifacts tab. This makes natural-language intent the default while leaving an explicit format override available.
- **Focused revision:** change a word, number, or scene timing by chat or in the editor while preserving the rest of the animation. The guide describes this as an outcome; it does not explain the internal patch mechanism.
- **Artifact lifecycle:** animations appear in a persistent Artifacts tab and start private; sharing and MP4 export are explicit actions.
- **Cost awareness:** longer or more complex animations use more plan capacity than a typical message.

**Implications for EvoFlux:** carry audience, playback destination, duration, and attached source materials into the compact motion brief when known, without turning every missing field into a clarification round. Keep intent-based routing from chat and add an explicit user override for cases where the model chooses poorly. EvoFlux already uses stable artifact IDs and updates a revised artifact in the chat history, but the inspected Workbench tabs are transient client state and there is no dedicated Artifacts library, privacy/share lifecycle, or guarantee that a narrow edit preserves unrelated generated code. Those are separate product gaps; they should not be confused with the current renderer or frame-quality problem. Usage cost also supports bounded storyboard, sample-review, and revision passes rather than model calls per encoded frame.

### Remotion

Remotion's core model is a pure mapping from a frame number to an image. `useCurrentFrame()`, frame-based timing, springs, and `TransitionSeries` make sequencing and overlaps explicit. Its flicker guidance says each frame should be reproducible independently and should not depend on render order, wall-clock animation, or unsynchronized assets.

Remotion's client renderer runs in the browser and uses WebCodecs plus Mediabunny. That is very close to EvoFlux's current export route, so adopting it would not by itself add FFmpeg, solve unsupported browser codecs, or improve the generated choreography. Remotion's Node renderer is a different route using its server rendering stack. Remotion's current pricing page also has a “Remotion for Automators” category for automated video products, so product integration needs a licensing review before adoption. Browser rendering sends a telemetry event for every render according to its docs.

**Takeaway:** borrow Remotion's frame-pure composition rules, explicit track/transition model, and tested motion helpers. Do not migrate the whole renderer as a presumed quality fix.

### Motion Canvas

Motion Canvas is oriented toward authoring vector scenes in TypeScript with a timeline and generator-based tweens. Its documentation covers easing, chaining, and interpolation of values such as position and color. Its FFmpeg exporter can be added as a package and says FFmpeg is installed with the exporter; audio can be included when the project has audio configured. The docs describe this exporter as relatively new.

**Takeaway:** Motion Canvas is a useful reference for timelines and explainer choreography, and a possible separately evaluated engine for a richer authoring surface. It is a larger integration than a small runtime animation kit because it has its own project/editor/exporter assumptions.

### GSAP and Anime.js

GSAP timelines can contain sequenced and overlapping tweens, labels, and nested timelines; timelines can be paused and sought to a specific time. Anime.js also exposes a timeline `seek(time)` API. A seekable timeline can drive preview and deterministic frame capture, provided export explicitly seeks to each timestamp and avoids dependence on an autonomous ticker or callbacks that mutate state irreversibly.

**Takeaway:** a timeline library could help a DOM/SVG composition backend, but it does not supply story structure, asset quality, sound, or a video encoder. EvoFlux currently renders one marked canvas, so integrating a DOM animation library would also require a defined capture contract or a deliberate move to SVG/HTML-in-canvas.

### Skills and distilled knowledge

Anthropic's public skill guidance uses a small always-visible description/frontmatter, a core skill body loaded when relevant, and linked references or assets loaded only as needed. Its public skills repository demonstrates specialist skills, while warning that examples do not necessarily match product implementation. Remotion's own skill repository splits knowledge into best practices, markup, rendering, maps, captions, and app integration. This is a useful pattern: route with a small policy, then load only the relevant production recipe.

The EvoFlux skill already follows part of this pattern. The missing layer is executable, tested know-how: a reusable animation kit, well-formed storyboard schema, motion-specific validation, and a model-evaluation set. More prose alone is unlikely to move the quality ceiling.

## Why the current result can still feel static

The current instructions specify good principles, but the model still has to invent the drawing code and choreography from scratch. A model can describe “motion” in its storyboard while rendering mostly title cards; the runtime currently does not require every beat to contain an observable state change, a moving anchor, or a transition connecting it to the next beat. The review tool can identify visible defects only if the model accepts images and actually uses the tool.

The audio outcome is independently constrained. A few oscillator cues are not a soundtrack. If the model omits the optional cue field, or the browser cannot encode audio, the resulting video is silent and the status should say so. The current route has no licensed music assets, voice track, ducking, stem mix, or loudness pass.

## Recommended EvoFlux pipeline

Keep the current browser renderer for the first quality iteration. Make the model choose and assemble a constrained, frame-pure motion system instead of inventing low-level canvas code for every artifact.

1. **Semantic intent and capability preflight.** Decide from the user's outcome whether motion adds understanding, using temporal causality and state change rather than keywords. Resolve the user's chosen destination (Workbench, export, save) and read runtime capabilities: model tool calling, image input, browser WebCodecs, audio codec, and available local render backend. Never promise visual review or audio before these checks.
2. **Story treatment.** Produce a compact structured brief: audience, takeaway, duration/aspect ratio, style, visual metaphor/anchor, narrative sections, causal sequence, and sound plan. Use 3–5 story sections; split them into overlapping actions. For a 15–30 second explainer, start with roughly 10–20 actionable beats rather than only one static card per section. This is an authoring range, not a hard rule.
3. **Beat and track data.** Give each beat a stable ID, start/end frame, subject, before/after state, path or transform, easing, anticipation/action/impact/settle/hold, attached label, transition rule, and optional sound cue. Let tracks overlap: a subject can move while a route draws and a caption follows. A single anchor should travel through scenes so cuts preserve spatial continuity.
4. **Reusable motion kit.** Provide reviewed, deterministic primitives such as path-follow, route-trace, masked reveal, shape morph, camera push/pan, parallax layers, kinetic type, scan/success hit, particle trail, and settle. Give each primitive a small parameter schema and a clear expected visual result. Render each frame from `(timeline, frameIndex)` without `Date.now()`, render-order state, or unseeded randomness. The model chooses composition and parameters; the kit supplies tested motion behavior.
5. **Preview and visual QA.** Render style/key-state samples before full export, then select bounded images around each section, hit, and transition. If the active model is vision-capable, send those images to `motion_review`, ask for concrete findings (time, expected state, observed defect, affected beat), and apply at most one or two targeted revisions. If it is text-only, show the contact sheet/timeline for human review and never report that the agent inspected frames.
6. **Final render and audio mix.** Keep WebCodecs/Mediabunny as the low-friction local path. If real music, user-supplied audio, TTS, or multi-stem mix is requested, add an optional managed FFmpeg backend with a pinned version, per-platform source, checksum/signature validation, clear install progress, and license metadata. Keep video-only export available when the optional backend or audio codec is unavailable. Align music, speech, SFX, and picture from one master timebase.
7. **Workbench delivery.** Keep the artifact editable and visible beside chat; preserve stable artifact IDs and revisions. Show story/beat stages and actual frame counts, representative previews, review findings, audio status, cancellation/failure, and final file. Save generated source and media into a project only after the user chooses to save them.

A useful progress sequence is `intent → storyboard → style sample → composing → review → targeted revision → final frames → audio/mux → playback verification`. Exact frame counts belong to export; story and review stages should be reported as completed work, never as invented frame percentages.

## Engine decision

| Candidate | Good fit | What it will not solve by itself | EvoFlux recommendation |
|---|---|---|---|
| Current Canvas + WebCodecs/Mediabunny | In-app preview, seekable canvas, local deterministic export | Story quality, shared motion primitives, real music/voice | Keep as the default while adding the motion kit and evaluation |
| Remotion | React/SVG compositions, frame-based sequencing, reusable transitions and assets | Model taste/choreography; browser codec limits on its client path | Borrow architecture and skills first; prototype a backend only if product needs justify licensing and runtime cost |
| Motion Canvas | Vector explainer scenes, authored tween/timeline workflow, FFmpeg export | Automatic content choice and a drop-in fit with the current sandbox | Evaluate for a dedicated advanced authoring mode, not as the first fix |
| GSAP/Anime.js | Seekable tweens for DOM/SVG timelines | Scene design, canvas capture contract, audio mix, output encoding | Consider only with an explicit DOM/SVG composition route; preserve deterministic seek |

FFmpeg can improve muxing and codec consistency; it will not turn static cards into animation. FFmpeg's own download page provides source code and points to third-party compiled builds. If EvoFlux distributes binaries or downloads them at runtime, select and verify the source, pin versions, and track the enabled LGPL/GPL components and corresponding compliance requirements.

## Is it a model limit?

Partly, and capability-aware evaluation will tell us how much. The registry currently gives `xiaomi:mimo-v2.5-pro` a 1M-token context window but does not set its `input.vision` capability. EvoFlux's `motion_review` checks this flag before it will return images. The regular `xiaomi:mimo-v2.5` entry declares vision. So a Pro run may have ample text context yet lack the in-product visual feedback loop. This is a registry/runtime capability statement, not proof that every provider serving MiMo Pro lacks vision.

More context is unlikely to fix a weak animation by itself. The model needs concise routing context, a beat schema, usable primitives, examples of good causal motion, and an inspection route. To identify model limits, run the same prompts and tool schema across the exact MiMo variants/providers available, then compare (a) correct format choice, (b) storyboard quality, (c) whether generated code uses actual movement and continuity, (d) render validity, (e) visual QA findings when vision is available, and (f) audio output. Keep the runtime and prompt fixed when comparing models.

Use failure location to pick the fix:

- Wrong output type or missed tool: routing context/tool availability.
- Good intent but static storyboard: planning skill/examples or model reasoning.
- Moving storyboard but still title cards: primitives and authoring constraints.
- Good preview but choppy export: deterministic timing/assets/encoder.
- Good animation but no audio: soundtrack assets, audio codec, or mux pipeline.
- No self-review: model capability metadata or review-tool orchestration.

A prior MiMo live probe in EvoFlux did not complete, so this document does not claim a measured model-quality result. A small paired evaluation should come before selecting a model or changing the base context budget.

## Proposed implementation order

1. Add a short always-on motion routing/tool contract with positive and negative examples; keep detailed craft references on demand.
2. Define a validated storyboard/beat DSL and implement the first reusable 2D motion primitives inside the existing sandbox and frame renderer.
3. Add deterministic lints and a small prompt/render evaluation set that catches static-card output, missing continuity, invalid timeline, and inaccurate capability claims.
4. Make the review loop capability-aware and evidence-driven; display frame samples in Workbench when no vision model is available.
5. Add real audio tracks through an optional managed local backend, with provenance, licensing, progress, mux verification, and graceful fallback.
6. Compare the same benchmark on current Canvas, a small GSAP/SVG experiment, and a Motion Canvas/Remotion prototype only if the first iteration still hits a renderer limitation.

Initial quality gates should require: correct media choice on intent-boundary prompts; a clear state change in each explanatory beat; at least one continuous visual anchor where the story has a natural subject; no accidental long static gaps; deterministic out-of-order seeking; no false claim of visual review or audio; and successful playback of the final encoded file. Pixel-difference scores may flag suspicious stillness but must not penalize intentional holds or substitute for visual judgment.

## Sources

**Official product and framework references**

- Anthropic, [Build live dashboards and animate explainers with Claude](https://claude.com/resources/articles/dashboards-and-motion) (2026-10-08).
- Anthropic Help Center, [Get started with Claude Motion](https://support.claude.com/en/articles/17454997-get-started-with-claude-motion) (updated this week when checked 2026-10-15).
- Anthropic Help Center, [What are artifacts and how do I use them?](https://support.claude.com/en/articles/17153992-what-are-artifacts-and-how-do-i-use-them).
- Anthropic, [The Complete Guide to Building Skills for Claude](https://resources.anthropic.com/hubfs/The-Complete-Guide-to-Building-Skill-for-Claude.pdf), especially progressive disclosure and testing.
- Anthropic, [public Agent Skills repository](https://github.com/anthropics/skills); examples are references, not guaranteed copies of product behavior.
- Remotion, [The core idea](https://www.remotion.dev/docs/idea), [Flickering and deterministic frames](https://www.remotion.dev/docs/flickering), [Transitions](https://www.remotion.dev/docs/transitions/transitionseries), [Client-side rendering](https://www.remotion.dev/docs/client-side-rendering), and [License & Pricing](https://www.remotion.dev/docs/license/pricing).
- Remotion, [Agent Skills repository](https://github.com/remotion-dev/skills).
- Motion Canvas, [Tweening](https://motioncanvas.io/docs/tweening/) and [FFmpeg video exporter](https://motioncanvas.io/docs/rendering/video/).
- GSAP, [Timeline](https://gsap.com/docs/v3/GSAP/Timeline/) and [seek](https://gsap.com/docs/v3/GSAP/Tween/seek%28%29/).
- FFmpeg, [Downloads and release verification](https://www.ffmpeg.org/download.html) and [license considerations](https://www.ffmpeg.org/legal.html).

**EvoFlux evidence inspected**

- `app/agent/builtin_skills/intelligent-ui/SKILL.md`
- `app/agent/builtin_skills/intelligent-ui/reference/motion-authoring.md`
- `app/agent/builtin_skills/intelligent-ui/reference/motion-production.md`
- `app/agent/providers/model_registry.json`
- `app/agent/tools/builtin/visualize/motion_review.py`
- `web/src/lib/motion-video-export.ts`
- `web/src/lib/motion-soundtrack.ts`
- `web/src/components/visual-artifact/MotionArtifact.tsx`
- `web/src/components/VisualArtifactRenderer.tsx`
- `web/src/components/workbench/VisualArtifactWorkbench.tsx`
- `web/src/stores/useUIStore.ts`
- `web/src/__tests__/utils/visual-artifact-history.test.ts`
