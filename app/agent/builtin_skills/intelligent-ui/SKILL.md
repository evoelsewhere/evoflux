---
name: intelligent-ui
description: "Helps agents choose prose, native controls, dashboards, motion, or 3D from the user's goal. Use when interaction may improve understanding or action; choose motion only for an explicit video request or when temporal change, sequence, cause-and-effect, or reveal carries the meaning, regardless of prompt length."
metadata:
  runtime-preload-tools: ui_block,visual_artifact
---

# Intelligent UI

`ui_block` renders compact native controls in chat. `visual_artifact` opens a
dashboard, motion explainer, or 3D view in the EvoFlux Workbench. This Skill is
the selection policy: use a visual only when it makes the user's next step
clearer or easier.

## Choose from the task, not its vocabulary

Infer the outcome the user needs and the answer shape that would help. Words
such as “plan,” “compare,” “chart,” “process,” or “calculate” do not select a
tool by themselves. Prefer prose when it communicates the answer more directly.
Use the smallest useful interaction, with controls that change an input, reveal
a relationship, support inspection, or let the user act.

- Use `ui_block` for compact calculations, structured inputs, checklists,
  comparisons, and progress the user can update in chat.
- Use a `chart` or `mermaid` Markdown fence for a standalone chart or diagram.
- Use a dashboard when a richer view helps inspect supplied or retrieved data;
  read external sources first and label unverified sample figures illustrative.
  Use `scene3d` only when spatial structure benefits from rotation or inspection.
- Use motion under the gate below. A timeline, plan, or long source is not by
  itself a reason to make a video.

## Motion gate and context size

Choose `visual_artifact` with `kind="motion"` only when the user explicitly
requests video or animation, or when change over time is necessary to
understand the subject: a sequence, transformation, cause-and-effect
relationship, or reveal. Ask whether the same point would be just as clear in a
static answer; if so, do not animate it. Do not infer motion from prompt length,
detail, or topic words.

The amount of source material controls how much you condense, not which format
you choose. For long material, preserve the central claim, key numbers, order,
and safety conditions; omit supporting detail that does not move the story.
Start with 3–5 scenes and about 12–20 seconds unless the user specifies a
different duration. Do not turn every paragraph into a scene. If motion is
selected, read [reference/motion-authoring.md](reference/motion-authoring.md)
before writing it.

## Author only after selecting a visual

When a user asks to build or render, infer reasonable defaults, make a first
useful result, and offer to revise it. Do not ask for choices the task does not
need. Never write an interactive artifact to a project file just to display
it; the user can explicitly save or download the source. Reuse a stable
`artifact_id` for revisions and `block_id` / `replace_id` for updating an
existing chat block.

Read only the reference needed for the selected format:

- [reference/block-catalog.md](reference/block-catalog.md) for native block
  types, fields, limits, and fit tests.
- [reference/worked-examples.md](reference/worked-examples.md) for adaptable
  UI payloads.
- [reference/rich-artifact-authoring.md](reference/rich-artifact-authoring.md)
  for dashboard provenance, theme, and sandbox rules.
- [reference/motion-authoring.md](reference/motion-authoring.md) for a selected
  motion storyboard, playback, frame rendering, and export.
- [reference/update-protocol.md](reference/update-protocol.md) when changing,
  pausing, or extending an existing chat block.
