# Settling the brief

Most of a deck can be decided from the material and sensible defaults. Two
things cannot, because getting them wrong wastes the whole build:

1. **Visual direction** — which theme, or match an existing template.
2. **Imagery** — whether the deck should carry photographs at all, and whether
   the user is supplying them.

Confirm those two before building. Take everything else yourself and say what
you took.

## Defaults you take without asking

| Decision | Default |
|---|---|
| Slide count | Around 10, never fewer than 8, unless the material or the user says otherwise |
| Aspect ratio | 16:9 — ask only when the venue is known to differ |
| Language | The language the user is writing in |
| Mode | Argument-first (below) whenever a paper, study, dataset, thesis, grant, or report is involved |
| File name | From the subject, in the session workspace |
| Fonts, margins, grid | The skill's typography and layout defaults |

Asking about any of these spends a round trip on something you can state in
the plan and change in seconds.

## Delegation mode

When the user says any of "you decide", "don't ask, just do it", "up to you",
or otherwise hands the whole thing over: ask nothing. Choose the theme from
the subject, assume no photography, build, and list every assumption in the
hand-off.

"Write whatever content you think fits" is not delegation of the *design*. It
delegates the copy only; anything the user already specified stands, and
anything still open follows the rule above.

Non-interactive runs — a scheduled task, a script, any context with no one to
answer — behave as delegation mode. Never stall waiting for an answer that
cannot come.

## The two questions

One `ask_user` call, both questions together, options with a marked
recommendation and a consequence rather than a label:

**Theme.** Offer the two or three from [`themes.md`](themes.md) that fit the
subject, recommendation first, each with who it suits. Skip this question
entirely when the workspace holds a template or brand file — match that
instead and say so.

**Imagery.** Does the deck want photographs, and will the user supply them?
Three real answers: no photographs (diagrams, charts and typography carry it),
user-supplied assets, or stock search. Recommend no photographs for internal,
analytical, and academic decks — they are usually better without.

Stop at two. Audience, length, and purpose come from the request and the
material far more reliably than from a question, and a deck that took four
questions to start feels like a form.

## Mode, decided not asked

Read it off the subject rather than asking:

**Argument-first** — papers, studies, results, reviews, board and policy
material. Priority order is argument, then data, then layout, then aesthetics.
White or light ground, one accent used to direct attention, no decorative
imagery, no icons in coloured circles.

**Visual-first** — launches, keynotes, public engagement, brand. Visual
storytelling leads, and the theme is allowed to be loud.

When both could apply, choose argument-first.

## The plan

Write the outline before building: one line per slide giving its **action
title** — a full sentence stating that slide's takeaway, not a topic label —
plus its evidence and its visual form.

Then run the **ghost deck test**: read only the action titles, in order. They
must tell the complete argument on their own. If they do not, the outline is
wrong and no amount of visual work will fix it. Fix it before building.

List with the outline: the theme, the assumptions you took, and every figure,
quote, logo, or claim the material does not support.

## When the plan needs approval

Stop and get agreement when any of these hold:

- the deck runs beyond about 10 slides;
- the material is complex, contested, or unfamiliar;
- it goes to a board, a customer, a regulator, or a public audience;
- the user has already corrected the direction once.

Otherwise show the outline and keep going — a short internal deck does not
need a ceremony, and the review that matters happens on the rendered result.

Never treat silence as approval when approval was required. After approval the
plan is the contract: if building forces a departure, say so and adjust the
plan rather than shipping something that was never agreed.
