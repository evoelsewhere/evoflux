/**
 * Shared types for the TeamChatView package.
 *
 * `ViewMode` is the layout mode the user is currently in:
 *   - `agent` — single AgentView pane for the active agent.
 *   - `split` — focused agent workbench with a team rail and 2-pane compare.
 *   - `monitor` — activity and communication overview.
 *
 * `VIEW_MODES` is the rotation order used by the Ctrl+V shortcut and the
 * 3-way segmented control in the header.
 */

export type ViewMode = 'agent' | 'split' | 'monitor'

export const VIEW_MODES: ViewMode[] = ['agent', 'split', 'monitor']
