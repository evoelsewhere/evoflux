import {
  BrainCircuit,
  CalendarClock,
  Files,
  GitBranch,
  GitPullRequest,
  Globe2,
  LayoutDashboard,
  MessageCirclePlus,
  Network,
  Terminal,
  Timer,
  type LucideIcon,
} from 'lucide-react'
import type { WorkbenchTool } from '@/stores/useUIStore'

export interface WorkbenchContext {
  mode: 'work' | 'coding' | 'aim'
  sessionId: string | null
  workspace: string | null
}

export const WORKBENCH_TOOLS: Record<
  WorkbenchTool,
  { label: string; description: string; icon: LucideIcon; shortcut?: string }
> = {
  overview: {
    label: 'Overview',
    description: 'See workspace, Git, session, and tool status at a glance',
    icon: LayoutDashboard,
  },
  terminal: {
    label: 'Terminal',
    description: 'Run commands in the active workspace',
    icon: Terminal,
  },
  browser: {
    label: 'Browser',
    description: 'View and interact with the agent browser',
    icon: Globe2,
    shortcut: '⌃T',
  },
  files: {
    label: 'Files',
    description: 'Browse workspace files and generated artifacts',
    icon: Files,
    shortcut: '⌘P',
  },
  graph: {
    label: 'Graph',
    description: 'Explore code and cross-repository relationships',
    icon: Network,
  },
  progress: {
    label: 'Progress',
    description: 'Follow tasks and agent execution over time',
    icon: Timer,
  },
  'side-chat': {
    label: 'Side chat',
    description: 'Ask a focused question without interrupting the run',
    icon: MessageCirclePlus,
    shortcut: '⌥⌘S',
  },
  wiki: {
    label: 'Memory',
    description: 'Browse curated knowledge and pending notes',
    icon: BrainCircuit,
    shortcut: '⌃M',
  },
  scheduler: {
    label: 'Scheduler',
    description: 'Create and manage scheduled tasks',
    icon: CalendarClock,
    shortcut: '⌃S',
  },
  'source-control': {
    label: 'Changes',
    description: 'Review and commit local workspace changes',
    icon: GitBranch,
    shortcut: '⌃G',
  },
  'pull-requests': {
    label: 'Review',
    description: 'Review pull requests and merge requests',
    icon: GitPullRequest,
  },
}

export const WORKBENCH_TOOL_ORDER = Object.keys(WORKBENCH_TOOLS) as WorkbenchTool[]

export function isWorkbenchToolEnabled(
  tool: WorkbenchTool,
  context: WorkbenchContext,
): boolean {
  if (tool === 'overview') {
    return context.mode === 'coding' && Boolean(context.workspace)
  }
  if (tool === 'source-control' || tool === 'pull-requests') {
    return context.mode === 'coding'
  }
  if (tool === 'graph') return context.mode === 'coding' && Boolean(context.workspace)
  if (tool === 'progress') return context.mode === 'coding' && Boolean(context.sessionId)
  if (tool === 'files') return Boolean(context.sessionId || context.workspace)
  if (tool === 'terminal' || tool === 'browser' || tool === 'side-chat') {
    return Boolean(context.sessionId)
  }
  return true
}
