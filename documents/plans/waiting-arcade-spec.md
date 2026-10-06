# Waiting Arcade — Feature Specification

## Status

Approved design for implementation planning. This describes the intended feature; it does not describe shipped behavior.

## Problem and outcome

When a Work or Coding agent spends time thinking or using tools, the chat can feel idle. Waiting Arcade offers a small, optional pixel game inside the active chat while keeping the conversation, stop control, and requests for user input easy to reach.

Success means a user can start a short game if they want, leave it immediately when the agent needs them, and never lose control of the chat or miss a response because the game took over the screen.

## Reference research

- [Meanwaile](https://meanwaile.com/) is a close product reference: it detects work and user idleness, opens a minigame, and pauses when the agent needs a response. Its [GitHub project](https://github.com/uurien/meanwaile) describes a small popup, an on-demand tray entry, an idle threshold, and circle-tap/runner games. For EvoFlux, use the explicit pause/resume behavior but keep the game inside the chat; do not auto-open a separate popup or require OS-level hooks.
- [Chrome's Dinosaur Game](https://blog.google/products-and-platforms/products/chrome/chrome-dino/) is a useful interaction reference for turning an otherwise frustrating offline state into a tiny optional game. Its lightweight, discoverable treatment is more relevant than copying the runner itself.
- [PICO-8's official manual](https://www.lexaloffle.com/dl/docs/pico-8_manual.html) documents a 128×128 display, 16-color palette, and 32 KB cartridge format. This is a useful reference for how a constrained canvas and palette can create a coherent retro look with compact assets; it is not a proposal to embed PICO-8 or copy its palette.
- Classic game references from the prior exploration: [Tetris](https://www.tetris.com/), [PAC-MAN](https://pacman.com/en/history/), [TAITO arcade history](https://www.taito.co.jp/en/corporate/about/history/), [Atari Breakout](https://atari.com/pages/breakout), [Microsoft Minesweeper](https://learn.microsoft.com/en-us/xandr/invest/buying-microsoft-casual-games-windows-o-o-apps), and [Konami Frogger](https://www.konami.com/crossmedia/us/en/products/frogger/). The MVP uses original presentation and small implementations of familiar mechanics rather than branded characters, names, sounds, or copied art.

## Goals

- Offer a small arcade launcher while the active lead agent is working in a Work or Coding chat.
- Keep games opt-in, self-contained, local, and easy to pause.
- Ensure the answer, Stop action, and blocking user requests take visual priority over the game.
- Provide mouse, keyboard, and touch-friendly controls where applicable, with accessible labels and reduced-motion support.

## Non-goals

- No separate native window, tray application, agent hook, external game service, leaderboard, account, telemetry, or model call.
- No games in Side Chat or background/unselected sessions in the first release.
- No claims that game score, animation, or content reflects actual agent progress.
- No licensed game names, characters, sprites, sounds, or other copied assets in the product UI.

## Selected MVP games

1. **Snake** — a low-speed, short-session arcade game controlled by arrow keys or WASD, with on-screen controls available for touch. It offers continuous play for longer waits.
2. **Minesweeper Mini** — a compact 6×6 board with a small, fixed number of mines. Reveal and flag modes work with pointer and touch; the board has no real-time countdown, so an interruption never costs a turn.
3. **Tic-tac-toe** — one local, deterministic match against a lightweight built-in opponent. The opponent does not call an AI provider or delay the agent run.
4. **2048** — a 4×4 local tile puzzle controlled by arrow keys only when its board has focus. It moves only on user input and has no timer or animation loop.

The selector opens on a neutral game-choice screen. Selecting a game shows a clear Start/Restart action; merely opening the selector never starts motion or captures keyboard input.

## Visual direction: quiet pixel arcade

- Keep the outer launcher and popover recognizably EvoFlux: compact workspace panel, existing surface/border/radius tokens, clear status labels, and no full-screen arcade scene.
- Put the 8-bit personality inside the game board: crisp grid, chunky but restrained pixel sprites, simple two-frame motions, and a deliberately limited palette. Prefer original tiny SVG/PNG sprite pieces or procedural canvas drawing; keep them inside the bundle budget below.
- Derive the main game color from the active `--color-accent` token so a user's appearance choice still feels native. Use existing semantic success/error colors for game outcomes; keep the remaining board neutral. This lets the board sit with EvoFlux's dark charcoal surfaces and default clay accent while still working in light mode or with a different selected accent.
- Keep instructions and controls in the app's readable Inter/Geist typography. Use the existing JetBrains Mono only for compact score/status details. Do not add a pixel font.
- Avoid neon gradients, CRT scanlines, heavy glow, noisy backgrounds, loud sound, exaggerated arcade chrome, or continuously moving decoration. The game's board can feel retro while the containing app stays calm and functional.
- Keep animation motion functional (Snake movement or a short start cue), low-frequency, and stopped whenever the board is hidden or the app is waiting for the user.

## User flow and UI states

1. **Idle:** No Waiting Arcade UI is shown.
2. **Working briefly:** The existing working indicator and Stop control remain unchanged. Do not flash a game affordance for a response that finishes quickly.
3. **Working continues:** After 1.5 seconds of continuous `isTeamWorking`, show a compact **Play while waiting** launcher beside the existing chat working/stop controls. It must not reflow the transcript or cover the composer.
4. **Choosing:** Activating the launcher opens a small, non-modal popover/panel anchored to it, constrained to the chat viewport. The user chooses one of the four games. Escape, outside click, or the close control dismisses it.
5. **Playing:** The selected game runs only while its panel is open, the document is visible, the same session remains selected, and no user-action gate is active. The panel does not take focus automatically. Keyboard input affects a game only after the user focuses the game surface or its controls.
6. **Agent completes or asks for input/permission:** Immediately pause the game and close the panel so the response or `question_asked` / `permission_asked` UI has priority. Keep the current board/run in memory for the selected session; if the agent resumes after a gate, the user may reopen the game manually. Never auto-reopen it or resume animation without user action.
7. **Session changes, run is stopped, or game is closed:** Pause timers/animation. Session changes clear the active game state; closing the panel during the same run preserves it so the user can reopen it.

## UX and accessibility requirements

- No modal, automatic game launch, focus steal, sound, flashing, or full-screen takeover.
- Keep the ordinary composer and Stop button usable while the launcher or game is open.
- User-action gates, completion, errors, and cancellation always outrank the game; the game pauses before its UI is covered.
- Use the app's theme tokens, existing popover/panel primitives, motion preset, and localization system. Honor reduced-motion settings and support keyboard dismissal.
- Use short instructions, visible controls, clear win/loss/reset actions, and adequate hit targets. Do not rely on color alone to distinguish Minesweeper state.
- The 1.5-second reveal delay prevents a transient affordance from appearing on fast turns; do not use idle detection or require the user to stop interacting with the desktop.

## Architecture and boundaries

- Frontend-only feature. Read `isTeamWorking` and pending gate/session state already available in `TeamChatView`; no API, SSE, database, migration, or agent-loop changes.
- Keep the launcher/panel in a focused chat component rather than extending `Thinking.tsx`; that component is for displaying model reasoning.
- The panel is anchored to the existing chat working/stop controls and uses existing overlay/popover conventions. Gate overlays remain above it.
- Keep each game's rules and state local and deterministic. Avoid adding a game framework or package dependency for these small boards.
- Any durable user preference must use the centralized `STORAGE_KEYS` registry. No high-score persistence is required for MVP.
- Add user-facing localized strings and update in-app Help, current feature documentation/catalogue, and `CHANGELOG.md` when implementation ships, following repository documentation rules.

## Bundle and runtime budget

- Do not add Phaser, PixiJS, Three.js, a game framework, or any other production dependency. Implement these small games with existing React/TypeScript, CSS, and browser APIs.
- Keep the launcher in the normal frontend entry, but load the selected game implementation with a dynamic import. Vite can emit dynamic imports as separate chunks; this defers game-code parsing/loading until a user opens a game, but does not remove those chunks from the installed app.
- Target at most **50 KiB gzip combined** for all game-specific JavaScript, CSS, and original pixel-art assets. Small original sprites are allowed; do not add audio, font, or WASM assets. Use CSS/DOM or canvas and avoid large sprite sheets.
- Target at most **5 KiB gzip additional startup-loaded frontend assets** for the launcher/status affordance. These are targets to verify from production build output, not measured results yet.
- Tauri's `frontendDist` points at `web/dist` and embeds its files into the application. Therefore report both the change in startup-loaded assets and the exact built-package size change; code splitting improves startup work but does not reduce the files shipped in the installer.
- Compare the clean `origin/main` production build with the feature build using the same Bun/Vite and Tauri packaging configuration. Record raw and gzip sizes per frontend asset and the final platform package size. If the budgets are exceeded, first reduce game code/assets or load each game separately; do not silently raise the budgets or add a new dependency.
- Only run the game animation loop while the selected game is open and visible; cancel animation frames and timers on pause/unmount so a hidden game consumes no ongoing CPU.

## Acceptance criteria

- **AC-1:** No launcher appears when the agent is idle, a different session is selected, or the current run has not worked continuously for 1.5 seconds.
- **AC-2:** During an active lead-agent run in Work or Coding, the launcher appears without shifting chat history or obscuring the composer/Stop control.
- **AC-3:** A user can select and play Snake, Minesweeper Mini, Tic-tac-toe, or 2048 without any backend request or model call.
- **AC-4:** Opening the launcher does not start a game, capture keyboard input, or move focus from the composer; game controls work after intentional focus/activation.
- **AC-5:** Closing/reopening during the same run preserves the board. Session changes clear it.
- **AC-6:** When a run completes/stops/errors or a question/permission gate appears, game timers/animation pause immediately, the panel closes, and the ordinary chat/gate UI is actionable.
- **AC-7:** A gate resolution never automatically reopens the game; the user can manually resume the preserved game if the agent resumes.
- **AC-8:** Reduced motion, keyboard dismissal, responsive layout, touch hit targets, and non-color Minesweeper cues are supported.
- **AC-9:** Focused frontend tests cover trigger delay/cancellation, all game rules and reset flows, gate priority, session changes, pause/resume, keyboard behavior, and reduced-motion-sensitive animation.
- **AC-10:** Shipped user-facing documentation, Help localization, and the Unreleased changelog entry match the implementation.
- **AC-11:** No production game-engine dependency, added font, audio, or WASM asset is introduced; game code/CSS/original sprite art meet the 50 KiB gzip combined and 5 KiB gzip startup-asset targets.
- **AC-12:** Implementation evidence records the exact platform package size before/after; deferred chunks are not described as removing bytes from the shipped app.
- **AC-13:** The game board uses EvoFlux theme tokens and a restrained pixel-art treatment; labels remain legible in the app's normal fonts, and the layout works in both dark and light themes.

## UX risks to check during implementation

- The floating composer and chat panels may constrain available room; the launcher must use existing anchoring/overlay patterns and remain inside the visible chat area on narrow windows.
- Global keyboard shortcuts, composer typing, and Snake key handling can conflict; keyboard capture must be scoped to an explicitly focused game surface and released when it closes or pauses.

## Approved Follow-up (2026-10-07)

- Add 2048 as a fourth, lazy-loaded game using original UI, no external engine/dependency, and no animation loop.
- Minesweeper Mini and Tic-tac-toe use one Tab stop per board; arrow keys move focus within bounds, while native Enter/Space activation retains normal button semantics. Give cell controls an explicit visible focus treatment and a short localized instruction.
- Snake runs at 320 ms per step normally and 480 ms with `prefers-reduced-motion: reduce`. Space pauses/resumes only while the board itself has focus; starting from its button moves focus to the board.
- Keep all input scoped to focused game controls so the composer and app shortcuts remain unaffected.
- SSE reconnects or a fast gate transition can race with the 1.5-second timer; derive eligibility from current session/run state and cancel stale timers on state changes.
