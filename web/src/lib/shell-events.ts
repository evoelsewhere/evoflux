export const SHELL_SIDEBAR_TOGGLE_EVENT = 'evoflux:shell-sidebar-toggle'

/** Request the active AppShell to toggle its docked sidebar or drawer. */
export function requestShellSidebarToggle(): void {
  window.dispatchEvent(new Event(SHELL_SIDEBAR_TOGGLE_EVENT))
}
