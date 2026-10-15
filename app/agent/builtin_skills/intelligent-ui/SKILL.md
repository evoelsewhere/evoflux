---
name: intelligent-ui
description: "Helps agents choose prose, native controls, dashboards, motion, or 3D from the user's goal. Use when a user asks to explain, teach, compare, or present information visually, asks you to choose a format, or an interactive artifact may improve understanding or action. Motion is especially useful when understanding depends on seeing states change or causes lead to effects."
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

When a user asks to explain something visually or choose a useful format, apply
this Skill even if they do not name a UI type. Do not treat “visual” as a request
for a PDF: use PDF when the user asks for a printable or portable document, or
when that format clearly serves the task.

- Use `ui_block` for compact calculations, structured inputs, checklists,
  comparisons, and progress the user can update in chat.
- Use a `chart` or `mermaid` Markdown fence for a standalone chart or diagram.
- Use a dashboard when a richer view helps inspect supplied or retrieved data;
  read external sources first and label unverified sample figures illustrative.
  Use `scene3d` only when spatial structure benefits from rotation or inspection.
- Use motion under the gate below. A timeline, plan, or long source is not by
  itself a reason to make a video.

## Motion gate and context size

Choose `visual_artifact` with `kind="motion"` when the user explicitly asks
for video or animation, or when understanding depends on seeing how one state
changes into another or why one stage enables the next. For a process, ask
whether the learner needs to understand what changes at each stage and why the
next stage depends on the previous one. If yes, motion can be the right choice
even when a static flowchart could list the same steps. Use a static diagram,
checklist, or document when the steps are mainly for lookup, comparison, or
printing, or when their order does not carry the explanation. Do not infer
motion from prompt length, detail, or topic words alone.

The amount of source material controls how much you condense, not which format
you choose. For long material, preserve the central claim, key numbers, order,
and safety conditions; omit supporting detail that does not move the story.
Start with 3–5 narrative sections across about 12–20 seconds unless the user
specifies otherwise, then break them into timed action beats. Carry a subject
or visual anchor across sections so the explainer reads as one moving story,
not a row of title cards. If the user asks for sound, read
[reference/motion-authoring.md](reference/motion-authoring.md): current video
exports are silent and this must be disclosed; never claim audio is embedded.
Read that reference before writing any motion artifact.

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
