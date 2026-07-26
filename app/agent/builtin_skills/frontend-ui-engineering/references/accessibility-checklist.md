# Accessibility checklist

Read this file when implementing or reviewing interactive UI.

## Semantics

- Use native controls before adding ARIA roles.
- Keep one `h1`; do not skip heading levels.
- Give every control an accessible name and every input a label.
- Connect validation messages with `aria-describedby`.
- Mark purely decorative icons `aria-hidden="true"`.

## Keyboard and focus

- Reach every action using Tab and Shift+Tab.
- Preserve a logical focus order without positive `tabIndex`.
- Show a visible focus indicator with at least 3:1 contrast.
- Move focus into dialogs and restore it to the trigger on close.
- Support Escape for dismissible overlays.

## Dynamic UI

- Announce status changes through an appropriate live region.
- Expose expanded, selected, checked, and busy state programmatically.
- Respect `prefers-reduced-motion`.
- Keep touch targets at least 44×44 CSS pixels on touch layouts.

## Visual checks

- Normal text contrast: at least 4.5:1.
- Large text and meaningful UI graphics: at least 3:1.
- Do not use color as the only state indicator.
- Verify content at 200% zoom and a 320 px viewport without loss.

## Verification

Tab through the complete flow, inspect the accessibility tree, and run the
project's automated accessibility checker. Automated checks are a floor, not a
replacement for keyboard and screen-reader verification.
