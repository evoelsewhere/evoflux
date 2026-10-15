# Visual artifacts in the EvoFlux Workbench

**Date:** 2026-10-15
**Status:** Implemented on `feat/intelligent-ui`; desktop UI and motion-export smoke pending
**Branch:** `feat/intelligent-ui`

## Goal

Generated dashboards, motion explainers, and 3D scenes should open as working
views inside EvoFlux's Workbench, separate from assistant prose. The transcript
keeps a compact artifact card for reopening historical output. Generated source
stays in session history by default, outside the user's repository. In Coding
mode, the user can explicitly save source into a chosen project path and then
review/commit it with normal Git tools.

## Design

- Replace the inline rich renderer with a compact card showing title, type,
  summary, and an **Open in Workbench** action. A newly received artifact opens
  automatically; historical cards do not auto-open on session load.
- Add a session-scoped `visual-artifact` Workbench tab. Its tab carries the
  current payload from persisted message history; opening an older card
  restores that exact artifact, and revisions with the same stable ID replace
  the payload for subsequent opens.
- Render existing dashboard, motion, and scene3d components in the Workbench
  surface, retaining theme, reduced-motion, sandbox, playback, and 3D behavior.
- Add **Save to project** for Desktop Coding mode. Use the native save dialog,
  constrain the chosen location to the active repository, and write through the
  existing coding-workspace endpoint. Existing-file confirmation is delegated
  to the native save dialog. In other environments, offer a normal file
  download instead.
- Do not write generated output into the repository automatically and do not
  modify project `.gitignore`. The explicit Coding save path is the point where
  a user chooses to create commit-eligible source.
- Do not add an artifact database table, preview server, or new backend tool;
  transcript tool-call history remains the source of truth.

## Implementation tasks

1. Add regression tests for the transcript card, Workbench tab payload/scope,
   save-path containment, source export, and all three artifact render kinds.
2. Add a typed Workbench tab kind and route artifact cards into it. Keep cards
   in transcript history and render actual artifact content only inside the
   Workbench.
3. Implement explicit source save/export, with Desktop Coding writes
   constrained to the active project and other environments downloading
   outside the repository.
4. Update the intelligent-ui Skill/tool description so agents know rich output
   opens in Workbench, plus user Help, the feature page/catalogue, and
   `[Unreleased]` changelog copy.
5. Run focused frontend tests, typecheck, lint, build, backend tests for any
   touched backend behavior, and `git diff --check`.

## Acceptance checks

- Assistant prose no longer embeds rich dashboard/motion/3D content.
- A newly received artifact opens automatically only in its active session.
- Opening a card creates or activates a Workbench artifact tab and displays
  the selected artifact there with the existing theme/runtime behavior.
- Historical cards can reopen their artifact after transcript reconstruction.
- No repository file is created by artifact generation or preview alone.
- Saving in Desktop Coding mode requires a user-selected path inside the active repo;
  paths outside it are rejected and an accepted file appears in normal Git
  Source Control. Other environments save only through a user-initiated
  download.
- Existing ui_block, show_widget, artifact revision replay, and Workbench tabs
  continue to work.


## Follow-up research: motion graphics and video authoring

The Workbench integration above does not complete advanced motion authoring or
frame-based video rendering. The dated
[code-driven motion graphics research](../research/2026-10-15-code-driven-motion-graphics.md)
compares official Claude Motion behavior, rendering frameworks and community
experience, records current exporter gaps, and proposes experiments and acceptance
checks for a separate implementation plan. Its runtime choices remain proposals.
