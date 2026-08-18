/**
 * useTeamCommands — assembles the Command Palette command list for
 * the team chat view.
 *
 * The palette commands are pure data, but they close over a lot of
 * parent-owned state and callbacks (current view mode, navigate, the
 * various toggle/cycle handlers). Wrapping the assembly in a hook keeps
 * the parent's render body focused on layout while still threading the
 * closures naturally.
 *
 * Group conventions used by ``CommandPalette``:
 *   - ``Team``       — session lifecycle (new chat, …)
 *   - ``View``       — view-mode + panel toggles
 *   - ``Agents``     — per-agent navigation + cycling
 *   - ``Navigation`` — top-level routes
 *   - ``Settings``   — agent / skill management routes
 */
import type { useNavigate } from '@tanstack/react-router'
import type { Command } from '../CommandPalette'
import type { ViewMode } from './types'
import { useUIStore } from '@/stores/useUIStore'
import { dispatchPrimaryShortcut } from '@/lib/keyboard-shortcuts'

/**
 * Palette actions dispatch through the same platform-native modifier used by
 * the window-level shortcut handler.
 */
interface UseTeamCommandsArgs {
  // View / layout
  viewMode: ViewMode
  cycleViewMode: () => void
  setViewMode: (m: ViewMode) => void
  handleWorkspaceFiles: () => void
  handleCodingSidebarToggle: () => void
  mode?: 'work' | 'coding'

  // Session
  handleNewSession: () => void

  // Dream
  handleDreamRun: () => void

  // Agents
  agentNames: string[]
  leadName: string | null
  cycleActiveAgent: (dir: 'next' | 'prev') => void
  setActiveAgent: (name: string) => void

  // Navigation
  navigate: ReturnType<typeof useNavigate>
}

export function useTeamCommands({
  viewMode,
  cycleViewMode,
  setViewMode,
  handleWorkspaceFiles,
  handleCodingSidebarToggle,
  mode = 'work',
  handleNewSession,
  handleDreamRun,
  agentNames,
  leadName,
  cycleActiveAgent,
  setActiveAgent,
  navigate,
}: UseTeamCommandsArgs): Command[] {
  const switchableAgentNames = agentNames.filter((name) => name !== leadName)
  const commands: Command[] = [
    { id: 'new-chat', group: 'Team', label: 'New Team Chat', description: 'Start a fresh team conversation', shortcut: 'Ctrl+N', action: handleNewSession },
    { id: 'dream-run', group: 'Team', label: 'Run Dream', description: 'Synthesise unprocessed sessions into Memory', action: handleDreamRun },
    {
      id: 'open-guidelines',
      group: 'Navigation',
      label: 'Open Guidelines…',
      description: 'Search setup tips and feature tricks',
      action: () => useUIStore.getState().openGuidelines(),
    },
    {
      id: 'toggle-view', group: 'View',
      label: viewMode === 'agent' ? 'Switch to Split View' : 'Switch to Agent View',
      description: 'Cycle: Agent → Split', shortcut: 'Ctrl+V', action: cycleViewMode,
    },
    { id: 'workspace-files',  group: 'View',       label: mode === 'coding' ? 'Open Changed & Files' : 'Toggle Workspace Files', description: mode === 'coding' ? 'Browse changed files and workspace files' : 'Browse files the agent has produced', shortcut: 'Ctrl+F', action: handleWorkspaceFiles },
    ...(mode === 'coding'
      ? [{
          id: 'workspace-overview',
          group: 'View',
          label: 'Open Workspace Overview',
          description: 'See Git, session, tools, and recent changes',
          action: () => useUIStore.getState().openWorkbenchTool('overview'),
        }]
      : []),
    ...(mode === 'coding'
      ? [{
          id: 'ai-review-changes',
          group: 'Git',
          label: 'Review changes with AI',
          description: 'Review uncommitted changes and publish findings to Problems',
          keywords: ['review thay đổi chưa commit', 'review uncommitted changes'],
          action: () => {
            useUIStore.getState().openWorkbenchTool('source-control')
            window.setTimeout(() => {
              window.dispatchEvent(new CustomEvent('evoflux:git-ai-review'))
            }, 0)
          },
        }]
      : []),
    mode === 'coding'
      ? { id: 'collapse-sidebar', group: 'View', label: 'Toggle Coding Sidebar', description: 'Collapse or expand workspaces and sessions', shortcut: 'Ctrl+B', action: handleCodingSidebarToggle }
      : { id: 'collapse-sidebar', group: 'View', label: 'Toggle Sidebar', description: '', shortcut: 'Ctrl+B', action: () => useUIStore.getState().toggleSidebarCollapsed() },
    { id: 'wiki',             group: 'View',       label: 'Memory',            description: 'Browse curated knowledge and pending notes', shortcut: 'Ctrl+M', action: () => dispatchPrimaryShortcut('m') },
    { id: 'scheduled-tasks',  group: 'View',       label: 'Scheduled Tasks',   description: 'Manage cron and scheduled agent tasks', shortcut: 'Ctrl+S', action: () => dispatchPrimaryShortcut('s') },
    { id: 'plugins',          group: 'View',       label: 'Plugins',           description: 'Manage portable Agent Skills and MCP packages', shortcut: 'Ctrl+K', action: () => dispatchPrimaryShortcut('k') },
    ...switchableAgentNames.map((name) => ({
      id: `switch-${name}`, group: 'Agents',
      label: `View ${name}`,
      description: 'Worker agent',
      action: () => {
        setViewMode('agent'); setActiveAgent(name)
      },
    })),
    { id: 'next-agent', group: 'Agents', label: 'Next Agent',     description: 'Focus the next teammate',     action: () => cycleActiveAgent('next') },
    { id: 'prev-agent', group: 'Agents', label: 'Previous Agent', description: 'Focus the previous teammate', action: () => cycleActiveAgent('prev') },
    { id: 'go-home',     group: 'Navigation', label: 'Go to Home',     description: '', action: () => navigate({ to: '/' }) },
    ...(mode === 'work' ? [{ id: 'go-coding', group: 'Navigation', label: 'Go to Coding Mode', description: 'Open the coding workbench', action: () => navigate({ to: '/coding' }) }] : []),
    { id: 'go-settings', group: 'Navigation', label: 'Open Settings',  description: 'Manage agents & skills', action: () => useUIStore.getState().openSettings('agents') },
    { id: 'settings-agents', group: 'Settings', label: 'Manage Agents', description: 'Edit agent .md files',  action: () => useUIStore.getState().openSettings('agents') },
    { id: 'settings-new-agent', group: 'Settings', label: 'New Agent',  description: 'Create a new agent',    action: () => useUIStore.getState().openSettings('agents/new') },
    { id: 'settings-skills', group: 'Settings', label: 'Manage Skills', description: 'Edit skill .md files',  action: () => useUIStore.getState().openSettings('skills') },
    { id: 'settings-new-skill', group: 'Settings', label: 'New Skill',  description: 'Create a new skill',    action: () => useUIStore.getState().openSettings('skills/new') },
    { id: 'settings-memory', group: 'Settings', label: 'Memory Settings',  description: 'Review memory and configure Dream synthesis', action: () => useUIStore.getState().openSettings('memory') },
    {
      id: 'settings-sandbox',
      group: 'Settings',
      label: 'Sandbox Settings',
      description: 'Manage filesystem, command, and outbound-data policies',
      keywords: ['mở nơi quản lý sandbox', 'open sandbox settings'],
      action: () => useUIStore.getState().openSettings('sandbox'),
    },
    ...agentNames.map((name) => ({
      id: `edit-${name}`, group: 'Settings',
      label: `Edit ${name}…`,
      description: 'Jump to agent editor',
      action: () => useUIStore.getState().openSettings(`agents/${name}`),
    })),
  ]
  return commands
}
