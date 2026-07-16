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
- (B) Building or extending an AIM-mode UI surface (the board, approval inbox, run monitor, unit detail, chat drawer) in EvoFlux itself.

## When NOT to Use

**When NOT to use:** for a one-off internal tool or throwaway prototype where consistency across screens genuinely doesn't matter. The cost of this discipline is only worth paying when multiple screens or surfaces need to look and behave like one product.

## Part A — Converting legacy screens

1. **No screen conversion before a design system exists.** The target UI kit (component library, layout templates, conventions for validation/error/empty states, i18n) is part of the target base and must be decided and approved before the first screen is converted. Converting screens against a design system that's still being invented is how you get fifty different looks.
2. **Convert by pattern, not by inspiration.** Classify each legacy screen by interaction pattern (search-list, detail-edit, master-detail, wizard, report...) in a screen inventory, and map each pattern to one target template in `ui-patterns/`. Converting a screen means instantiating its pattern's template and mapping fields/validations into it — not composing a new layout from scratch.
3. **Use only the sanctioned kit.** No hand-rolled components or one-off styles "just for this screen" — lint or review should catch deviation from the design tokens, same as any other code-quality check.
4. **UX changes are project-level ADRs, decided once.** If the target genuinely should behave differently from the legacy screen (menu → nav bar, multi-window → tabs, three screens merged into one), that's a decision an architect makes once for the whole project and records as an ADR — individual unit conversions cite it, they don't each re-decide it.
5. **Test UI for task parity, not pixel parity.** Equivalence for a screen means a user can complete the same business task with the same resulting state (drive it with a scenario script, then compare downstream data/output) — not that a screenshot matches pixel-for-pixel. A human still reviews the screen; the golden artifact is the task outcome, not an image diff.
6. **Screens get the same human gate as everything else** — SME/BA sign-off per wave, not an automatic pass just because a script ran clean.

## Part B — Building AIM mode's own UI

1. **Spec before code.** Any new AIM UI surface gets a short UX spec — the user journey by persona, a wireframe, and which events update which region — reviewed before implementation starts.
2. **No invented design system.** Use EvoFlux's existing tokens and components; an AIM surface should look like a natural part of EvoFlux, not a bolt-on with its own visual language.
3. **One job, one place.** Triggering work happens on the board or unit detail; approving happens in the approval inbox; watching progress happens in the run monitor; conversing happens in the chat drawer. Don't duplicate the same action across multiple surfaces — that's how surfaces drift out of sync with each other.
4. **One source of truth for displayed state.** Every surface renders from the same underlying state and event stream — never let one surface derive its own local notion of a unit's phase that could disagree with another surface showing the same unit.

## Verification

For a legacy screen conversion: does it cite an approved pattern from `ui-patterns/` rather than inventing a layout? Does it use only kit components? Is any behavioral deviation from the legacy screen backed by an ADR? For an AIM UI surface: was there a reviewed spec before code was written? Does it reuse existing EvoFlux components and a shared state source rather than introducing its own? If either answer is no, stop and get the missing decision made and reviewed before continuing.
