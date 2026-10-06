# Waiting Arcade

Waiting Arcade offers a small, optional local game while a lead agent is actively working in a Work or Coding chat.

## How it works

- After 1.5 seconds of uninterrupted work, a compact **Play while waiting** launcher appears beside the composer Stop control. Fast turns do not flash it, and it does not move the transcript or take focus by itself.
- The non-modal panel offers Snake, Minesweeper Mini (6×6), Tic-tac-toe against a deterministic local opponent, and 2048 (4×4). Opening the panel does not start a game. There are no provider calls, network requests, audio, scores tied to agent activity, or game-engine dependencies.
- The panel is constrained to the chat viewport and uses the app's theme tokens. Snake has low-speed movement and arrow/WASD controls after the board is focused; Space pauses or resumes it. Minesweeper has reveal and flag modes and no timer. Minesweeper and Tic-tac-toe boards use arrow keys to move between cells while keeping one Tab stop per board. 2048 moves only when you focus its board and press an arrow key.
- Snake moves every 320 ms normally and every 480 ms when reduced motion is preferred. The other games have no animation loop.
- Closing the panel pauses play and preserves the selected board during the same session. Hiding the document stops the animation loop. Session changes clear the board.
- A question, permission request, stopped run, or completed run closes the panel and pauses the game so chat actions stay available. Resolving a gate never reopens it automatically; if the agent resumes, the user may open the launcher again.

## Source ownership

- `web/src/components/waiting-arcade/` owns launcher eligibility, panel, games, and pure game rules.
- `web/src/components/InputBar.tsx` and `FloatingInputBar.tsx` provide the optional working-action slot; `TeamChatView` supplies current work/session/gate state.
- UI strings and in-app Help are localized in English, Vietnamese, and Japanese.

The frontend game code and original presentation are kept small and split into on-demand chunks. Tauri still packages those chunks with the app; lazy loading reduces startup work, not installer contents.
