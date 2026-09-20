/**
 * Shared types for the TeamChatView package.
 *
 * `ViewMode` is the layout mode the user is currently in:
 *   - `agent` — single AgentView pane for the active agent.
 *   - `split` — focused agent workbench with a team rail and 2-pane compare.
 *
 * `VIEW_MODES` is the rotation order used by the Ctrl+V shortcut and the
 * segmented control in the header.
 */

export type ViewMode = 'agent' | 'split'

export const VIEW_MODES: ViewMode[] = ['agent', 'split']
