---
name: frontend-design
description: Design and implement a distinctive, intentional product interface or website with a coherent visual system, responsive behavior, accessibility, and visual verification. Use for new frontend experiences or substantial visual reshaping; do not use for backend-only changes, static artwork, slide decks, or applying a preselected artifact theme.
---

# Design and build a frontend

Make the interface specific to its subject, audience, and primary job. Preserve
existing product conventions when editing an established application; novelty
must not break usability or brand coherence.

## State machine

### 1. FRAME

Identify the primary user, page or flow job, content hierarchy, required states,
platform constraints, existing design system, and supplied visual direction.
Choose non-blocking details from context. Ask only when missing assets, brand
rules, or incompatible interpretations would materially change the result.

### 2. DIRECT

Write a compact design contract before implementation:

- 4–6 color tokens with semantic roles;
- display, body, and utility type roles;
- layout/grid behavior across desktop and mobile;
- interaction and motion principles;
- one subject-specific signature element;
- accessibility requirements and reduced-motion behavior.

Reject choices that could be reused unchanged for any product. Structural
devices, imagery, copy, and motion must communicate something true about the
subject. Spend visual boldness in one place and keep surrounding elements
disciplined.

### 3. BUILD

Use repository-native components, tokens, routing, state, and dependencies.
Implement real content and all relevant loading, empty, error, disabled, hover,
focus, and success states. Keep control labels action-oriented and consistent
through the flow. Avoid decorative grids, gradients, cards, numbering, and
animation unless they serve the hierarchy or interaction.

Preserve semantic HTML, keyboard navigation, visible focus, contrast, target
sizes, responsive reflow, and reduced motion. Check CSS specificity and avoid
local rules that silently cancel shared component behavior.

### 4. VERIFY

Run the repository's narrow checks, then inspect the rendered interface at
representative desktop and mobile sizes. Exercise keyboard navigation and the
main interaction path. Compare the render with the design contract and correct
generic styling, clipping, overflow, unreadable density, broken states, and
unnecessary decoration.

## Stop conditions

Stop when the primary job is obvious, the implementation follows the declared
visual system, important states work, responsive and keyboard behavior are
verified, and screenshots show no unresolved visual defect.

## Deliverable

Lead with the implemented user-visible result. Summarize the visual direction,
key files, checks and viewport states inspected, and any remaining browser or
asset limitation.
