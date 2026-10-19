# Intelligent UI and code-driven motion research

Research snapshot consolidated from the Intelligent UI and motion studies
checked on 2026-10-15. Claims below distinguish public product documentation,
repository evidence, and community reports. Re-check upstream versions,
licensing, and WebView support before selecting a new dependency.

## Findings

- **Claude Motion is a useful product reference, not proof of its internal
  pipeline.** Anthropic describes creating and editing animated visual
  artifacts through conversation. Public pages do not establish that it uses
  FFmpeg, Remotion, or any particular private renderer. Learn from the
  inspectable, editable result and iterative workflow; do not infer the
  implementation.
- **Intelligent UI is model judgment paired with runtime affordances.** OpenAI's
  public GPT-6 overview frames it as composing text, visual output, and
  interaction. Treat that as a product reference, not a renderer contract or
  evidence that EvoFlux has the same trained behavior.
- **Motion quality is a pipeline and craft problem as well as a model problem.**
  A model can choose a correct tool and still author a static sequence of cards.
  Direction, action arcs, continuity, timing, easing, typography, image assets,
  and review at the final viewing size all affect the result. MiMo 2.6 Pro should
  be evaluated, but weak output alone does not isolate model limits.
- **Plan narrative scenes and timed action beats.** A frame-by-frame production
  loop should mean deterministic rendering and bounded review of authored
  frames, not one model call per frame. Each beat needs a visible before/after
  state, cause, destination, transition, timing, and optional impact/sound cue.
- **Use one authored composition with explicit time.** A stable timeline and
  deterministic drawAt(timeMs) contract make preview, seeking, review, progress,
  export, and revisions agree. Pin an export to an artifact revision.
- **Treat sound and external renderers as capabilities.** Canvas capture alone
  produces silent video. FFmpeg can help with codec coverage or post-processing,
  but it is not required by EvoFlux's present WebCodecs/Mediabunny frame-export
  path. Probe the actual desktop WebView and report unavailable audio honestly.

## What to learn from Animate

The public [cth9191/animate repository](https://github.com/cth9191/animate)
is a production-strategy reference rather than a renderer to copy. The useful
ideas captured for EvoFlux are:

1. Judge whether the request needs motion and choose the deliverable before
   implementation.
2. Establish story, visual direction, runtime, and constraints before writing
   scene code.
3. Break the story into scenes, then into timed beats with a clear change in
   state; maintain a subject or visual anchor through transitions.
4. Build the composition from code and render representative frames at exact
   times.
5. Inspect, revise, and render again within a bounded loop; keep progress and
   the current revision visible.
6. Plan sound from the scene's emotional and physical cues, then add/mux it only
   when the renderer can produce a valid audio track.

This does not mean every beat requires a separate prompt, that the same visual
style should be reused, or that more cuts and effects automatically improve
quality.

## Framework and renderer trade-offs

| Approach | Strength | Cost or limit | EvoFlux fit |
|---|---|---|---|
| Canvas + WebCodecs + Mediabunny | Deterministic frame drawing and local timestamped MP4/WebM muxing; one in-app preview/export surface | Requires compatible WebView codecs; source must redraw from absolute time; DOM text outside the marked canvas is not captured | Current bounded frame-export path |
| Browser real-time capture | Low setup cost and works for older canvas explainers | Timing varies with the machine; frame totals are unknown; no audio source by default | Compatibility fallback |
| Remotion | React composition, player, sequence/transitions, and server/browser rendering concepts; official AI-generation guidance | Source-available license and deployment/telemetry constraints require review; browser rendering has documented limits | Reference or separately evaluated renderer |
| Motion Canvas / Revideo | Timeline-oriented animation, code-driven scenes, easing, time events, and video export | Adds a separate project/runtime/toolchain and packaging surface | Reference for authored timing and easing; prototype only after measurement |
| HyperFrames | HTML-oriented composition, deterministic time control, and canvas integration | Adds its own composition and rendering conventions | Useful comparison for deterministic HTML/Canvas export |
| Manim | Precise mathematical and diagram animation | Python environment and render pipeline add startup, packaging, and media dependencies | Specialized route for equation-heavy explainers, not the default UI renderer |
| FFmpeg | Mature muxing, transcoding, filtering, and broad format support | Must be installed or bundled and maintained per platform; needs clear license and subprocess boundaries | Optional post-processing/backend when WebCodecs limits are measured |

Use the smallest renderer that satisfies the product requirement. Do not add a
framework just because its demo output is polished.

## Production strategy for EvoFlux

1. **Select by task value.** Prose for direct answers; native blocks for compact
   action; dashboard for sourced data; 3D for spatial inspection; motion when a
   causal state change over time teaches something or video is explicitly requested.
2. **Load the right context.** Preload a short selection rule only when a relevant
   tool is available. Read detailed authoring and production instructions after
   selecting that format. Keep API schemas, one example, and current artifact
   state close to the call; do not append every reference to the base prompt.
3. **Write a small creative brief.** State audience, one-sentence narrative,
   visual metaphor, palette/material, typography, duration, accessibility needs,
   available assets, and constraints.
4. **Storyboard scenes and beats.** Use a few narrative scenes. Within them,
   define timed beats, camera/subject movement, anticipation, acceleration,
   overshoot/settle, secondary motion, transition cause, and boundary-frame
   requirements.
5. **Build a deterministic scene.** Make every frame a function of absolute
   time. Preserve object identity, lighting, camera grammar, and typography
   rules across beats. Avoid one-card-per-step, repeated wipes, decorative
   particles, and text detached from the subject.
6. **Review evidence.** Render bounded samples at opening, midpoint, action,
   transition, and settle points. Let an image-capable model review only the
   requested samples; if unavailable, report that the result was not visually
   inspected. Revise specific beats rather than restarting the whole artifact.
7. **Export and report.** Render fixed-rate frames, track exact completed/total
   frames, allow cancellation, pin revision, and show the final media in
   Workbench. Add only bounded local effects when a compatible audio encoder is
   present.

The intended score is legibility, semantic clarity, continuity, motion quality,
pacing, visual hierarchy, provenance, and honest capability reporting—not raw
frame count.

## Failure signs and likely causes

| Symptom | Likely causes to test |
|---|---|
| Looks like slides | No persistent subject, repeated scene reset, transition is only a wipe/fade, action does not change state |
| Feels stiff | Linear motion, missing anticipation/reaction/settle, camera and subject move without weight |
| Looks generic or “AI” | Generic template, decorative glow/particles, weak material choices, detached captions, no product-specific visual assets |
| Too much text | Storyboard follows source paragraph order instead of one central narrative; hierarchy and reading time are not budgeted |
| Tool not selected | Base context does not expose the tool, Skill does not preload for this run, model interprets the task as static lookup, or eval prompt is ambiguous |
| Correct tool, poor result | Selection works; investigate brief, authoring context, assets, timing, model capability, and render feedback separately |
| Sound absent | No audio source/encoder or result was not finalized with an audio track; never infer sound from a soundtrack plan |

## Evidence boundaries

- Claude's public help establishes product-level motion authoring and artifact
  behavior, not its private renderer or use of FFmpeg.
- Official renderer docs establish APIs and stated limitations; they do not
  establish that EvoFlux has integrated those engines.
- The Animate study is a source-code/workflow reference. Its technique can
  inform prompts and review, but does not establish comparative output quality.
- Social posts report experiences and opinions. They are useful for test
  hypotheses such as slideshow pacing and weak easing, not controlled
  benchmarks.
- A MiMo smoke run establishes behavior for that prompt, provider, and runtime.
  It does not prove a general model limitation.

## References

### Official product and framework documentation

- [OpenAI: GPT-6 for everyone](https://openai.com/index/gpt-6-for-everyone/)
- [Claude dashboards and motion](https://claude.com/resources/articles/dashboards-and-motion)
- [Claude Motion: getting started](https://support.claude.com/en/articles/17454997-get-started-with-claude-motion)
- [Remotion: idea and composition model](https://www.remotion.dev/docs/idea)
- [Remotion Player](https://www.remotion.dev/docs/player)
- [Remotion Renderer](https://www.remotion.dev/docs/renderer)
- [Remotion client-side rendering](https://www.remotion.dev/docs/client-side-rendering) and [limitations](https://www.remotion.dev/docs/client-side-rendering/limitations)
- [Remotion AI generation](https://www.remotion.dev/docs/ai/generate) and [AI skills](https://www.remotion.dev/docs/ai/skills)
- [Remotion transitions](https://www.remotion.dev/docs/transitions/) and [TransitionSeries](https://www.remotion.dev/docs/transitions/transitionseries)
- [Remotion license FAQ](https://www.remotion.dev/docs/license/faq)
- [Motion Canvas documentation](https://motioncanvas.io/docs/), [video rendering](https://motioncanvas.io/docs/rendering/video/), [tweening](https://motioncanvas.io/docs/tweening/), and [time events](https://motioncanvas.io/docs/time-events/)
- [Revideo](https://github.com/midrender/revideo)
- [HyperFrames overview](https://hyperframes.heygen.com/developers/overview), [determinism](https://hyperframes.heygen.com/concepts/determinism), [canvas integration](https://hyperframes.heygen.com/sdk/guides/canvas-integration), and [motion prompting](https://hyperframes.heygen.com/prompting/motion)
- [Manim Community](https://github.com/ManimCommunity/manim) and [installation](https://docs.manim.community/en/stable/installation.html)
- [Mediabunny repository](https://github.com/Vanilagy/mediabunny), [writing media files](https://mediabunny.dev/guide/writing-media-files), and [media sources including audio](https://mediabunny.dev/guide/media-sources)
- [GSAP timeline seek](https://gsap.com/docs/v3/GSAP/Timeline/seek/) and [license](https://gsap.com/community/standard-license/)
- [FFmpeg legal information](https://ffmpeg.org/legal.html)
- [Canvas captureStream](https://developer.mozilla.org/en-US/docs/Web/API/HTMLCanvasElement/captureStream) and [WebCodecs configuration support](https://developer.mozilla.org/en-US/docs/Web/API/VideoEncoder/isConfigSupported_static)
- [Tauri WebView versions](https://v2.tauri.app/reference/webview-versions/)
- [Remotion transition Skill](https://github.com/remotion-dev/skills/blob/main/skills/remotion-markup/transitions.md)

### Community discussions

These are anecdotal reports and workflow examples, not measured comparisons:

- [People are making Claude attempt motion design](https://www.reddit.com/r/MotionDesign/comments/1wq0zvj/people-are-making-claude-attempt-motion-design/)
- [Remotion videos in Claude](https://www.reddit.com/r/ClaudeAI/comments/1ry1azp/remotion_videos_in_claude/)
- [Claude, Remotion, and Figma workflow](https://www.reddit.com/r/ClaudeCode/comments/1r748to/built_this_video_with_claude_remotion_figma_mcp/)
- [HyperFrames composition experience](https://www.reddit.com/r/opencode/comments/1x2zutp/my_short_experience_in_composing_videos_with/)
- [Revideo discussion](https://news.ycombinator.com/item?id=40646741)
- [Prompt-to-video workflow discussion](https://www.reddit.com/r/SaasDevelopers/comments/1u2whml/my_project_humbled_me_completely_i_spent_14_days/)
- [Motion design feedback](https://www.reddit.com/r/VideoEditors/comments/1vlggl3/i_am_so_sick_of_everyone_shoving_ai_video_editing/)
- [Claude Code + HyperFrames + FFmpeg skill](https://www.reddit.com/r/ClaudeCode/comments/1wswg22/i_built_an_opensource_skill_that_directs_motion/)
