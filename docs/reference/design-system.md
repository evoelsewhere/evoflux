# Frontend design system

EvoFlux uses Tailwind CSS v4 over semantic CSS tokens in
`web/src/index.css`. Components should consume shared shell/UI primitives and
tokens rather than introduce page-local visual systems.

## Ownership

| Contract | Source |
|---|---|
| color, spacing, typography, safe-area and z-index tokens | `web/src/index.css` |
| reusable controls | `web/src/components/ui/` |
| application/sidebar/panel shell | `web/src/components/shell/` |
| motion constants and presets | `web/src/lib/motion.ts` |
| appearance values/storage | `web/src/lib/appearance.ts` and Settings |
| pre-paint appearance | `web/public/appearance-init.js` |
| native macOS title controls | `MacTitleBar`, `AppHeader`, Tauri config |

## Shell rules

`AppShell` owns the main page frame. `SidebarShell` and its row/section/menu
primitives own sidebars; `SidePanel` and workbench dock own resizable auxiliary
surfaces. New pages should compose these rather than reproduce drawer, backdrop,
resize, mobile overlay or keyboard behavior.

`AppHeader` is the shared 40px application header. On macOS overlay windows it
reserves traffic-light space and exposes a native drag region. Header children
must opt out of drag behavior where they are interactive.

## Tokens

- Use semantic color variables such as background, text, border, accent,
  success/warning/error rather than literal palette values.
- Use the named `--z-*` scale; numeric z-index literals create broken overlays.
- Use safe-area and mobile viewport tokens for fixed headers, drawers and
  composers.
- Persist browser preferences through the `STORAGE_KEYS` registry. The pre-paint
  script is the only place that mirrors keys manually and must stay in sync.

## Motion

Motion durations are `instant` (80ms), `fast` (150ms), `base` (240ms), `slow`
(400ms) and `glacial` (800ms). Shared easing/spring presets live in
`web/src/lib/motion.ts`.

Appearance selects `reduced`, `subtle`, or stronger supported intensity presets.
The same preference affects:

1. CSS `--motion-*` durations;
2. the application `MotionConfig` default;
3. opt-in physical motion distance, spring and stagger;
4. whether decorative ambient loops may run.

System reduced-motion always wins. Functional state changes must not depend on
animation completion.

## Accessibility and responsiveness

Components use visible focus rings, semantic labels/roles, keyboard navigation,
focus trapping for modals and sufficient touch targets. The shell is
mobile-first and supports safe areas, edge swipes and overlay panels. Desktop
hover behavior must have a keyboard/touch equivalent.

## Verification

Run frontend lint/typecheck and focused component tests. For shell, motion,
theme or responsive changes, verify reduced motion, mobile width, macOS overlay
spacing and both light/dark appearance before handoff.
