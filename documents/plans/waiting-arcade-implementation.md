# Waiting Arcade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add an optional, lightweight pixel-game launcher to active Work and Coding chats without interrupting the agent, composer, or user-action gates; provide clear keyboard/motion behavior and a compact fourth game.

**Architecture:** Implement four deterministic local games in small React/TypeScript modules, dynamically imported only when selected. A chat-bound host derives eligibility from the existing team store, delays the launcher 1.5 seconds, and pauses/hides the selected game on run completion, a user-action gate, session change, or document hiding. No backend, database, agent-loop, or native-window changes.

**Tech Stack:** React 19, TypeScript, Vite, Vitest, Tailwind CSS, existing Base UI Popover, EvoFlux i18n catalogs, Tauri 2 packaging.

**Spec:** [`documents/plans/waiting-arcade-spec.md`](waiting-arcade-spec.md)

## Global Constraints

- Work on `feature/waiting-arcade`, based on `origin/main`; keep the original dirty checkout untouched.
- Implement Snake, 6×6 Minesweeper Mini, Tic-tac-toe versus a local deterministic opponent, and 4×4 2048.
- The launcher appears only after 1.5 seconds of active lead-agent work, is explicitly opened, and never steals composer focus.
- Stop/answer/permission UI always wins. Pause immediately on gates, completion, errors, stop, hidden document, or session change; never auto-reopen after a gate.
- Preserve an open game's state while its panel is closed during the same run; clear it when the session changes.
- Use existing theme/accent tokens and normal app fonts for labels. Pixel art stays restrained and legible in dark and light themes.
- Do not add a production dependency, game framework, font, audio, or WASM asset. Keep original game code/CSS/sprites ≤50 KiB gzip combined and startup-loaded launcher assets ≤5 KiB gzip.
- Vite dynamic imports defer load/parse work only; Tauri still embeds all `web/dist` assets. Record frontend and Windows NSIS package size changes using the same build configuration.
- Update localized UI/Help and current feature docs/catalogue plus `CHANGELOG.md` with shipped behavior. Do not document the proposal as implemented before code ships.

## Review Focus

1. A fast response or session switch races the 1.5-second timer — cancel the timer and keep the launcher hidden.
2. A question/permission gate arrives while Snake is moving — stop its timer immediately and put the gate in front.
3. Snake keyboard handling conflicts with composer typing or global shortcuts — only handle keys when the game surface has intentional focus.
4. A closed, backgrounded, or hidden game keeps consuming CPU or loses its board — stop animation and preserve the active run's board.
5. Narrow window/light theme/reduced motion makes controls unusable or unreadable — clamp the popover, retain theme contrast, and avoid nonessential motion.

---

## File Map

- Create `web/src/components/waiting-arcade/games/snake-logic.ts` — pure Snake state creation and tick/direction rules.
- Create `web/src/components/waiting-arcade/games/minesweeper-logic.ts` — 6×6 mine placement, adjacent counts, reveal, flag, and win/loss rules.
- Create `web/src/components/waiting-arcade/games/tic-tac-toe-logic.ts` — move validation, win/draw detection, and deterministic bot choice.
- Create `web/src/components/waiting-arcade/games/2048-logic.ts` — 4×4 merge/move/win/over rules with injected tile placement.
- Create `web/src/components/waiting-arcade/games/SnakeGame.tsx`, `MinesweeperGame.tsx`, `TicTacToeGame.tsx`, and `Game2048.tsx` — accessible game controls and board presentation. Import each only through a dynamic import.
- Create `web/src/components/waiting-arcade/WaitingArcadePanel.tsx` — game chooser, anchored popover, selected-game mount/pause, and close/reopen state.
- Create `web/src/components/waiting-arcade/WaitingArcadeHost.tsx` — delayed eligibility, session binding, gate/visibility pause, and working-action launcher.
- Modify `web/src/components/InputBar.tsx` and `web/src/components/FloatingInputBar.tsx` — accept an optional working-action slot and render it adjacent to the Stop control without shifting transcript layout.
- Modify `web/src/components/TeamChatView/index.tsx` — pass active session, work state, mode, `permissionRequest`, and `askUserQuestion` into the host/working-action slot.
- Create tests under `web/src/__tests__/components/waiting-arcade/`; extend the existing `InputBar` component tests for the working-action slot.
- Add UI strings to `web/src/i18n/messages/en.json`, `vi.json`, and `ja.json`; add Help articles to `web/src/help/locales/en.ts`, `vi.ts`, and `ja.ts`.
- Create `documents/features/waiting-arcade.md`; update `documents/features/README.md` and `CHANGELOG.md` when the feature is implemented.

## Task 1: Capture the origin/main size baseline and implement pure game rules

**Files:**
- Create: `web/src/components/waiting-arcade/games/snake-logic.ts`
- Create: `web/src/components/waiting-arcade/games/minesweeper-logic.ts`
- Create: `web/src/components/waiting-arcade/games/tic-tac-toe-logic.ts`
- Test: `web/src/__tests__/components/waiting-arcade/game-logic.test.ts`

- [x] **Step 1: Record a production baseline before changing game source**

From the clean feature branch (whose application source equals `origin/main`), run:

```powershell
Set-Location web
bun install --frozen-lockfile
bun run build
```

Record the Vite raw/gzip asset sizes. From `desktop/src-tauri`, run the same Windows package command used after implementation and copy the resulting NSIS installer to a temporary baseline filename outside the repository:

```powershell
Set-Location ../desktop/src-tauri
cargo tauri build --bundles nsis
```

Use the newest `.exe` under `target/release/bundle/nsis`, record its byte count, and copy it to `$env:TEMP\waiting-arcade-origin-main.exe`. Do not commit build outputs or the temporary installer.

- [x] **Step 2: Write failing deterministic game-rule tests**

Cover Snake movement/growth/wall collision/reverse-direction rejection; Minesweeper adjacent counts/flagging/reveal/zero expansion/mine loss/win; and Tic-tac-toe occupied-cell rejection/win/draw plus bot win/block/center/corner priority. Inject random placement for Minesweeper so tests use an explicit 6×6 mine list.

Example interface assertions:

```ts
expect(advanceSnake(initialSnake)).toMatchObject({
  body: [{ x: 3, y: 2 }, { x: 2, y: 2 }, { x: 1, y: 2 }],
})
expect(chooseTicTacToeMove(['O', 'O', null, 'X', 'X', null, null, null, null], 'O')).toBe(2)
```

Run: `cd web; bun run test:unit -- src/__tests__/components/waiting-arcade/game-logic.test.ts`
Expected: FAIL because the rules modules do not exist yet.

- [x] **Step 3: Implement pure rules with explicit, testable state types**

Export `createSnakeState`, `advanceSnake`, and `setSnakeDirection`; export `createMinefield`, `revealMineCell`, and `toggleMineFlag`; export `playTicTacToeCell` and `chooseTicTacToeMove`. Keep random generation injected and keep rendering, timers, DOM, and global state out of these modules. Snake uses a fixed-size grid and returns a terminal state on collision; Minesweeper reveal uses a queue for zero-cell expansion; Tic-tac-toe bot checks win, block, center, then corners.

Use typed serializable states rather than implicit UI state:

```ts
export interface GridPoint { x: number; y: number }
export type RunStatus = 'ready' | 'playing' | 'won' | 'lost'
export interface SnakeState {
  width: number
  height: number
  body: GridPoint[]
  direction: GridPoint
  food: GridPoint
  score: number
  status: RunStatus
}
export function advanceSnake(state: SnakeState): SnakeState
```

`MinefieldState` holds a 36-cell array with `mine`, `adjacent`, `revealed`, and `flagged` fields plus `status`; `createMinefield(mineIndices: readonly number[])` is deterministic. `TicTacToeState` holds nine nullable marks and a `status`; `chooseTicTacToeMove(board: readonly Mark[], botMark: Mark): number | null` uses the fixed priority above.

- [x] **Step 4: Run the game-rule tests and frontend typecheck**

Run: `cd web; bun run test:unit -- src/__tests__/components/waiting-arcade/game-logic.test.ts`
Expected: PASS for every pure-rule case.

Run: `cd web; bun run typecheck`
Expected: PASS with no new TypeScript errors.

## Task 2: Build four low-motion, lazy-loaded game views

**Files:**
- Create: `web/src/components/waiting-arcade/games/SnakeGame.tsx`
- Create: `web/src/components/waiting-arcade/games/MinesweeperGame.tsx`
- Create: `web/src/components/waiting-arcade/games/TicTacToeGame.tsx`
- Create: `web/src/components/waiting-arcade/WaitingArcadePanel.tsx`
- Test: `web/src/__tests__/components/waiting-arcade/games.test.tsx`

- [x] **Step 1: Add failing interaction tests for each game**

Verify Start/Restart labels, Snake tick and collision using fake timers, direction controls only after the board is focused, on-screen direction buttons, Minesweeper reveal/flag mode and accessible cell labels, and Tic-tac-toe local opponent response. Also verify the score/result does not claim to represent agent progress.

Run: `cd web; bun run test:unit -- src/__tests__/components/waiting-arcade/games.test.tsx`
Expected: FAIL because game views do not exist yet.

- [x] **Step 2: Implement isolated views with no new dependencies**

Render crisp boards using existing tokens and CSS/DOM or canvas. Use `requestAnimationFrame` or one interval only for active Snake movement; clear it on pause/unmount. Minesweeper has no countdown. Tic-tac-toe bot is synchronous local code and never calls a provider. Use existing Inter/Geist/JetBrains Mono; provide non-color state cues and touch-sized controls.

Keep Snake's loop scoped to `active` and make cleanup unconditional:

```tsx
useEffect(() => {
  if (!active || state.status !== 'playing') return
  const timer = window.setInterval(() => setState(advanceSnake), tickMs)
  return () => window.clearInterval(timer)
}, [active, state.status, tickMs])
```

- [x] **Step 3: Dynamically import one selected game at a time**

Create a typed game-id-to-component loader in `WaitingArcadePanel.tsx` and a small loading state. Keep the chooser and launcher eager, not the board/game logic. Use the existing Base UI popover primitives (`web/src/components/ui/popover.tsx`) with viewport collision padding and a width capped to the chat viewport.

Use a top-level lazy-component map so each game is imported only when React first renders that selected game:

```tsx
import { lazy, type ComponentType, type LazyExoticComponent } from 'react'

type GameId = 'snake' | 'minesweeper' | 'tic-tac-toe'
interface GameProps { active: boolean }

const gameComponents: Record<GameId, LazyExoticComponent<ComponentType<GameProps>>> = {
  snake: lazy(() => import('./games/SnakeGame')),
  minesweeper: lazy(() => import('./games/MinesweeperGame')),
  'tic-tac-toe': lazy(() => import('./games/TicTacToeGame')),
}
```

- [x] **Step 4: Verify interaction tests, typecheck, and split output**

Run the Task 2 Vitest command and `cd web; bun run typecheck`. Then run `cd web; bun run build`; inspect that the four game modules are emitted as deferred chunks and that opening no game does not load their modules.

## Task 3: Integrate the launcher with chat lifecycle and user-action gates

**Files:**
- Create: `web/src/components/waiting-arcade/WaitingArcadeHost.tsx`
- Create: `web/src/__tests__/components/waiting-arcade/WaitingArcadeHost.test.tsx`
- Modify: `web/src/components/InputBar.tsx`
- Modify: `web/src/components/FloatingInputBar.tsx`
- Modify: `web/src/components/TeamChatView/index.tsx`
- Test: `web/src/__tests__/components/InputBarWaitingArcade.test.tsx`

- [x] **Step 1: Write failing lifecycle and composer tests**

Use fake timers to prove the launcher is hidden before 1500 ms, appears at 1500 ms, and is canceled when work stops or the session changes. Verify that a pending `permissionRequest` or `askUserQuestion` closes/pauses an open game, that resolving the gate never reopens it automatically, and that changing session clears game state. Simulate a hidden `document.visibilityState` and ensure Snake timers stop. Verify the optional slot is beside Stop, is absent when idle, and does not take focus from a focused composer.

Run: `cd web; bun run test:unit -- src/__tests__/components/waiting-arcade/WaitingArcadeHost.test.tsx src/__tests__/components/InputBarWaitingArcade.test.tsx`
Expected: FAIL because the host and slot prop do not exist yet.

- [x] **Step 2: Add the optional action slot without changing send/stop behavior**

Add `workingActionSlot?: React.ReactNode` to `InputBarProps` and the forwarded `FloatingInputBarProps`. Render it next to `sendOrStopEl` only while `isStreaming`; leave the existing send/stop handlers and button semantics unchanged. Keep the slot narrow on mobile.

```tsx
{isStreaming && workingActionSlot}
{sendOrStopEl}
```

- [x] **Step 3: Implement session-bound eligibility and pause behavior**

Give `WaitingArcadeHost` explicit props: `isWorking`, `sessionId`, `mode`, `hasUserActionGate`, and `documentVisible`. Start/cancel the 1500 ms timer from those inputs; show the launcher only for Work/Coding chats. Keep selected game state in the host across panel close/gate pause, key/reset it on session change, and do not auto-open when work resumes. Pause clocks/animation immediately when any blocking state becomes true or the page becomes hidden. Mount the host only in the main TeamChatView composer, not Side Chat.

Use an effect with cleanup so stale timers cannot reveal the launcher:

```tsx
useEffect(() => {
  setEligible(false)
  if (!isWorking || !sessionId || (mode !== 'work' && mode !== 'coding') || hasUserActionGate || !documentVisible) return
  const timer = window.setTimeout(() => setEligible(true), 1500)
  return () => window.clearTimeout(timer)
}, [isWorking, sessionId, mode, hasUserActionGate, documentVisible])
```

- [x] **Step 4: Connect current store state and run lifecycle tests**

In `TeamChatView/index.tsx`, select `askUserQuestion` and `permissionRequest` from `useTeamStore`, create `hasUserActionGate = Boolean(askUserQuestion || permissionRequest)`, and pass the current `mode`, `sessionIdState`, and `isTeamWorking` to the host through the composer action slot. Keep the game out of `Thinking.tsx` and do not modify backend/SSE/store contracts.

Run the Task 3 Vitest command and `cd web; bun run typecheck`.
Expected: PASS; quick turns and gates leave the original Stop/composer behavior intact.

## Task 4: Localize the feature and update shipped product documentation

**Files:**
- Modify: `web/src/i18n/messages/en.json`
- Modify: `web/src/i18n/messages/vi.json`
- Modify: `web/src/i18n/messages/ja.json`
- Modify: `web/src/help/locales/en.ts`
- Modify: `web/src/help/locales/vi.ts`
- Modify: `web/src/help/locales/ja.ts`
- Create: `documents/features/waiting-arcade.md`
- Modify: `documents/features/README.md`
- Modify: `CHANGELOG.md`
- Test: `web/src/__tests__/help/waiting-arcade.test.ts`

- [x] **Step 1: Add user-facing catalog and Help coverage tests**

Test that required English/Vietnamese/Japanese UI keys exist and that Help article `waiting-arcade` is searchable in each supported locale. Include localized instructions for opening/closing a game and explain that a gate or completed run pauses it.

Run: `cd web; bun run test:unit -- src/__tests__/help/waiting-arcade.test.ts`
Expected: FAIL before the strings/articles are added.

- [x] **Step 2: Add localized UI copy and Help articles**

Use `useI18n().t(...)` for behavior-sensitive labels, including accessible labels for each board, Start/Restart, close, and game states. Add matching EN/VI/JA JSON messages and matching Help entries in the existing locale files; do not rely on DOM auto-translation for keyboard controls or aria labels.

Add the same key set in all catalogs, with translated values:

```json
{
  "waitingArcade.launch": "Play while waiting",
  "waitingArcade.start": "Start game",
  "waitingArcade.close": "Close game"
}
```

- [x] **Step 3: Add the current feature page and catalogue link**

Document the actual interaction, chosen games, local-only rules, pause/gate behavior, and preference/retention behavior in `documents/features/waiting-arcade.md`; link it from `documents/features/README.md`. Change the existing proposal changelog wording to describe shipped behavior only after implementation is complete.

- [x] **Step 4: Run localization and Help checks**

Run: `cd web; bun run test:unit -- src/__tests__/help/waiting-arcade.test.ts src/__tests__/help/search.test.ts`
Expected: PASS; all three locale articles are discoverable.

Run: `cd web; bun run i18n:audit:vi`
Expected: PASS with no accidental translations of technical terms or keys.

## Task 5: Verify accessibility, responsive visuals, and size budgets

**Files:**
- Modify as needed: `web/src/components/waiting-arcade/**`
- Modify as needed: `web/src/__tests__/components/waiting-arcade/**`
- No new dependency or native/backend files.

- [x] **Step 1: Run the focused full feature test set**

Run: `cd web; bun run test:unit -- src/__tests__/components/waiting-arcade src/__tests__/components/InputBarWaitingArcade.test.tsx src/__tests__/help/waiting-arcade.test.ts`
Expected: PASS for game rules, interactions, chat lifecycle, gates, and Help.

- [ ] **Step 2: Check dark/light, small-window, keyboard, and reduced-motion behavior**

In the running desktop app, inspect the launcher and each game in dark and light themes at the minimum supported window size (760×560), with a narrow/mobile viewport, and with reduced motion enabled. Confirm the composer stays focused/usable, Escape/outside click dismisses, Stop remains reachable, game surfaces are keyboard/screen-reader labeled, and a permission/question gate takes priority. Record visual issues and fix them before continuing. Browser harness coverage is recorded below; minimum-window, narrow/mobile, native desktop, and full keyboard-only application flows remain open.

- [x] **Step 3: Measure frontend bundle against baseline**

Run `cd web; bun run build`. Compare startup-loaded raw/gzip assets and the sum of game-specific JS/CSS/sprite chunks with Task 1's saved Vite baseline. Confirm the launcher delta is ≤5 KiB gzip and game-specific assets are ≤50 KiB gzip combined. If not, remove avoidable code/art or split the selected games into separate chunks; do not add an engine or silently change the budgets.

- [ ] **Step 4: Measure the Windows package and run frontend quality gates**

From `desktop/src-tauri`, run `cargo tauri build --bundles nsis`; measure the resulting `.exe` bytes and compare with `$env:TEMP\waiting-arcade-origin-main.exe`. Report the exact package delta separately from Vite's lazy-load/gzip numbers. Then run:

```powershell
Set-Location ../../web
bun run lint
bun run typecheck
bun run test:unit
bun run build
```

Expected: all frontend checks pass, package and frontend size evidence is recorded, and no game dependency was added.

- [x] **Step 5: Review final diff and changelog alignment**

Run `git diff --check`; inspect `git diff --stat` and the full feature diff. Confirm only the planned frontend, tests, help/docs, and changelog files changed; verify the changelog describes shipped behavior, not merely the proposal.

## Execution Notes

- Avoid a shared or dirty checkout; this plan belongs to the isolated `feature/waiting-arcade` branch.
- Do not run a broad repository backend suite: the accepted design makes no backend, schema, SSE, or agent policy changes.
- If only Windows packaging is available, report that package delta as Windows NSIS evidence; do not extrapolate it to macOS/Linux installer sizes.

## Implementation Evidence

- Clean origin/main Vite baseline: 172 assets, 8,373,545 raw bytes / 3,653,541 gzip bytes. Earlier three-game feature build: 175 assets, 8,390,940 raw / 3,662,091 gzip.
- Earlier three-game startup assets: baseline 19 assets, 3,975,184 raw / 1,133,381 gzip; feature 19 assets, 3,975,958 raw / 1,135,752 gzip: +774 raw / +2,371 gzip bytes, within the 5 KiB gzip target. After adding 2048, startup-referenced output grew a further 180 raw bytes.
- Four lazy game modules: Snake 5,676 raw / 2.18 KiB gzip; Minesweeper 5,023 raw / 1.99 KiB gzip; Tic-tac-toe 3,339 raw / 1.60 KiB gzip; 2048 3,443 raw / 1.63 KiB gzip. Total 17,481 raw / approximately 7.40 KiB gzip, within the 50 KiB gzip target. No engine or production dependency was added.
- Earlier three-game Windows NSIS installer: baseline 93,703,521 bytes; feature 93,707,986 bytes; delta +4,465 bytes (+4.36 KiB). A refreshed package measurement after adding 2048 is pending. Tauri's `beforeBuildCommand` stopped at `bun install --frozen-lockfile` with `EBADF accessing temporary directory`; after building the frontend directly, a package attempt with that redundant prebuild step skipped compiled the Rust app but could not download the NSIS helper from GitHub because the build environment had no DNS/network access.
- Verification after the fourth game and layout fix: lint passed; TypeScript typecheck passed; production build passed; focused feature tests passed (6 files, 37 tests); `git diff --check` passed. Full unit run: 855/856 passed. The sole failure is `notification-activation.test.ts` (same pre-existing failure reproduced on clean origin/main: 1 failed, 7 passed).
- Browser UI QA (2026-10-07) used a temporary isolated harness rendering the real `InputBar` and `WaitingArcadeHost` at 1280×720; it did not connect to a backend or live session. Light-theme Minesweeper and dark-theme 2048 were captured in the browser evidence. Keyboard checks showed arrow navigation and cell interaction in Minesweeper, arrow navigation plus Space moves and local opponent responses in Tic-tac-toe, arrow moves and live move/score announcements in 2048, and Space pause/resume in Snake. The harness simulated reduced motion; Snake visibly reported 480 ms between moves. At 1280×720, the sixth Minesweeper row was clipped by the original 32rem cap; increasing the popover cap to 36rem made all six rows and the status visible.
- Earlier browser QA covered gate-priority, session reset, and idle/end-of-work transitions, and the focused feature tests cover gate resolution without auto-reopen and composer focus. Current browser checks were at 1280×720. Minimum 760×560, narrow/mobile, OS-level reduced-motion preference, full application keyboard-only navigation, and native desktop QA remain unverified; the desktop app was not launched against the live user environment.
- The Vietnamese i18n audit script was not rerun: an earlier invocation rewrote 82 unrelated existing translations. Translation key parity and Help search are covered by passing tests.
