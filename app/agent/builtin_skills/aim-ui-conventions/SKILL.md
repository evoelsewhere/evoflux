---
name: aim-ui-conventions
description: Design-first rules for converting legacy screens and for building AIM's own mode UI — prevents the "every screen/surface looks different" failure that happens when UI decisions are made ad hoc, per screen, in parallel. Use when converting any legacy screen in a migration project, or when building a UI surface for AIM mode itself.
---

# AIM UI/UX conventions

## Overview

Running UI conversion (or UI-surface building) "live" — every screen, every surface deciding its own look as it goes — reliably produces conflicting, inconsistent results, especially when work happens in parallel across many units or many contributors. The fix is not more careful individual judgment; it's moving every UI decision earlier, into one place, decided once, and reviewed before anything downstream is built against it. This skill applies to two different things that share the same discipline: (A) converting a customer's legacy screens as part of a migration project, and (B) building AIM mode's own UI inside EvoFlux.

## When to Use

- (A) Converting any legacy screen (VB6 form, Oracle Forms screen, 3270 panel, or anything else with a UI) into the target stack.
- (A) Deciding a migration project's target design system, component library, or screen-pattern mapping.
- (B) Building or extending an AIM-mode UI surface in EvoFlux (the Overview board, Knowledge Base, Rulebook, Pipelines, Runs & Reports, Run Monitor, post-run Discussion).

## When NOT to Use

**When NOT to use:** for a one-off internal tool or throwaway prototype where consistency across screens genuinely doesn't matter. The cost of this discipline is only worth paying when multiple screens or surfaces need to look and behave like one product.

## Part A — Converting legacy screens

1. **No screen conversion before a design system exists.** The target UI kit (component library, layout templates, conventions for validation/error/empty states, i18n) is part of the target base and must be decided and approved before the first screen is converted — recorded in the KB's `ui-conventions.md` by `aim-target-architect`.
2. **Convert by pattern, not by inspiration.** Classify each legacy screen by interaction pattern (search-list, detail-edit, master-detail, wizard, report…) in a screen inventory, and map each pattern to one target template via the rulebook's `ui-patterns/`. Converting a screen means instantiating its pattern's template and mapping fields/validations into it — not composing a new layout from scratch.
3. **Use only the sanctioned kit.** No hand-rolled components or one-off styles "just for this screen" — lint or review should catch deviation from the design tokens, same as any other code-quality check.
4. **UX changes are project-level ADRs, decided once.** If the target genuinely should behave differently from the legacy screen (menu → nav bar, multi-window → tabs, three screens merged into one), an architect decides once for the whole project and records an ADR — unit conversions cite it, they don't each re-decide it.
5. **Test UI for task parity, not pixel parity.** Equivalence for a screen means a user completes the same business task with the same resulting state (drive it with a scenario script, then compare downstream data/output through the normal `aim_compare` harness) — not that a screenshot matches pixel-for-pixel. A human still reviews the screen; the golden artifact is the task outcome, not an image diff.
6. **Screens get the same human gate as everything else** — SME/BA sign-off per wave, not an automatic pass because a script ran clean.

## Part B — Building AIM mode's own UI

1. **Spec before code.** Any new AIM UI surface gets a short UX spec — the user journey by persona, a wireframe, and which events update which region — reviewed before implementation starts (see `documents/plans/aim-mode-shell-ux-spec.md` for the shell's precedent).
2. **No invented design system.** Use EvoFlux's existing tokens and components (and reuse whole components where they fit — the KB browser reuses the coding workspace's tree; the Run Monitor reuses the questions API). An AIM surface should look like a natural part of EvoFlux.
3. **One job, one place.** Triggering pipelines happens in Pipelines; answering gates happens in the Run Monitor's gate box; reading reports happens in Runs & Reports; chat exists only as post-run Discussion. Don't duplicate an action across surfaces — that's how surfaces drift out of sync.
4. **One source of truth for displayed state.** Every surface renders from the same backend state (`aim_units` index, workflow executions, session list) — never let one surface derive its own local notion of a unit's phase or a run's status that could disagree with another surface.

## Verification

For a legacy screen conversion: does it cite an approved pattern from `ui-patterns/` rather than inventing a layout? Does it use only kit components? Is any behavioral deviation backed by an ADR? For an AIM UI surface: was there a reviewed spec before code? Does it reuse existing EvoFlux components and shared state rather than introducing its own? If either answer is no, stop and get the missing decision made and reviewed before continuing.
