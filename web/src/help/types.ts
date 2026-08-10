import type { WorkbenchTool } from '@/stores/useUIStore'

export type HelpCategoryId =
  | 'getting-started'
  | 'modes'
  | 'chat'
  | 'composer'
  | 'slash'
  | 'sessions'
  | 'workbench'
  | 'coding'
  | 'memory'
  | 'scheduler'
  | 'browser'
  | 'plugins'
  | 'settings'
  | 'shortcuts'
  | 'troubleshooting'

export type HelpBlock =
  | { type: 'p'; text: string }
  | { type: 'heading'; text: string }
  | { type: 'code'; code: string; language?: string; caption?: string }
  | { type: 'table'; columns: string[]; rows: string[][] }
  | {
      type: 'callout'
      tone?: 'info' | 'warning'
      title: string
      text: string
    }
  | { type: 'tips'; items: string[] }
  | { type: 'shortcuts'; rows: { keys: string; action: string }[] }
  | { type: 'slash'; commands: { cmd: string; desc: string }[] }

export type HelpOpenAction =
  | { type: 'settings'; path: string }
  | { type: 'workbench'; tool: WorkbenchTool }
  | { type: 'palette' }
  | { type: 'route'; to: string }

export interface HelpCategory {
  id: HelpCategoryId
  label: string
  description: string
}

export interface HelpArticle {
  id: string
  category: HelpCategoryId
  title: string
  summary: string
  keywords: string[]
  setup?: string
  tricks?: string[]
  blocks: HelpBlock[]
  related?: string[]
  openAction?: HelpOpenAction
}
