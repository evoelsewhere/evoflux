import { useState, useRef, useEffect } from 'react'
import { Input } from 'antd'
import { useTheme } from '../common/ThemeProvider'
import { useNavigate, useLocation } from 'react-router-dom'
import { NODE_CATEGORIES, searchNodes, type NodeDefinition } from '../workflow/registry'
import { useSettingsStore } from '../../stores/settingsStore'
import {
  NodeStartIcon, NodeGlobeIcon, NodeClockIcon, NodeLLMIcon,
  NodeExtractIcon, NodeTagIcon, NodeDatabaseIcon, NodeConditionIcon,
  NodeLoopIcon, NodeMergeIcon, NodeEditIcon, NodeTemplateIcon,
  NodeCodeIcon, NodeToolIcon, NodeFolderIcon,
  NodeTeamIcon, NodeSubWorkflowIcon
} from '../common/NodeIcons'

const NODE_ICON_MAP: Record<string, (sz: number, c: string) => React.ReactNode> = {
  'play-circle': (s, c) => <NodeStartIcon size={s} color={c} />,
  'global': (s, c) => <NodeGlobeIcon size={s} color={c} />,
  'clock-circle': (s, c) => <NodeClockIcon size={s} color={c} />,
  'robot': (s, c) => <NodeLLMIcon size={s} color={c} />,
  'scan': (s, c) => <NodeExtractIcon size={s} color={c} />,
  'tags': (s, c) => <NodeTagIcon size={s} color={c} />,
  'database': (s, c) => <NodeDatabaseIcon size={s} color={c} />,
  'branches': (s, c) => <NodeConditionIcon size={s} color={c} />,
  'reload': (s, c) => <NodeLoopIcon size={s} color={c} />,
  'sync': (s, c) => <NodeLoopIcon size={s} color={c} />,
  'merge-cells': (s, c) => <NodeMergeIcon size={s} color={c} />,
  'edit': (s, c) => <NodeEditIcon size={s} color={c} />,
  'file-text': (s, c) => <NodeTemplateIcon size={s} color={c} />,
  'code-sandbox': (s, c) => <NodeCodeIcon size={s} color={c} />,
  'code': (s, c) => <NodeCodeIcon size={s} color={c} />,
  'folder-open': (s, c) => <NodeFolderIcon size={s} color={c} />,
  'more': (s, c) => <NodeToolIcon size={s} color={c} />,
  'setting': (s, c) => <NodeToolIcon size={s} color={c} />,
  'apartment': (s, c) => <NodeSubWorkflowIcon size={s} color={c} />,
  'team': (s, c) => <NodeTeamIcon size={s} color={c} />,
  'unknown': (s, c) => <NodeToolIcon size={s} color={c} />
}

const CAT_COLORS: Record<string, string> = {
  trigger: '#34d399', ai: '#60a5fa', logic: '#fbbf24', tools: '#2dd4bf', agent: '#c084fc', other: '#a1a1aa'
}

const icons = {
  home: (c: string) => <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 8L8 2L14 8" stroke={c} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/><path d="M3.5 7V13.5H6.5V10H9.5V13.5H12.5V7" stroke={c} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  workflow: (c: string) => <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="4" cy="4" r="2" stroke={c} strokeWidth="1.3"/><circle cx="12" cy="4" r="2" stroke={c} strokeWidth="1.3"/><circle cx="8" cy="12" r="2" stroke={c} strokeWidth="1.3"/><path d="M4 6V8L8 10" stroke={c} strokeWidth="1.2" strokeLinecap="round"/><path d="M12 6V8L8 10" stroke={c} strokeWidth="1.2" strokeLinecap="round"/></svg>,
  settings: (c: string) => <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="2.5" stroke={c} strokeWidth="1.3"/><path d="M8 1V3M8 13V15M1 8H3M13 8H15M2.9 2.9L4.3 4.3M11.7 11.7L13.1 13.1M13.1 2.9L11.7 4.3M4.3 11.7L2.9 13.1" stroke={c} strokeWidth="1.2" strokeLinecap="round"/></svg>,
  sun: (c: string) => <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><circle cx="7.5" cy="7.5" r="3" stroke={c} strokeWidth="1.2"/><path d="M7.5 1.5V3M7.5 12V13.5M1.5 7.5H3M12 7.5H13.5M3.1 3.1L4.2 4.2M10.8 10.8L11.9 11.9M11.9 3.1L10.8 4.2M4.2 10.8L3.1 11.9" stroke={c} strokeWidth="1.1" strokeLinecap="round"/></svg>,
  moon: (c: string) => <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M12.5 8.5A5.5 5.5 0 116.5 2.5a4 4 0 006 6z" stroke={c} strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  save: (c: string) => <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M2.5 2H10L12.5 4.5V12.5C12.5 13.1 12.1 13.5 11.5 13.5H2.5C1.9 13.5 1.5 13.1 1.5 12.5V3C1.5 2.4 1.9 2 2.5 2Z" stroke={c} strokeWidth="1.2"/><rect x="3.5" y="7.5" width="8" height="4" rx="0.5" stroke={c} strokeWidth="1"/><path d="M5 2V5.5H10V2" stroke={c} strokeWidth="1"/></svg>,
  play: (c: string) => <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M4 2L12.5 7.5L4 13V2Z" fill={c}/></svg>,
  stop: (c: string) => <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><rect x="3" y="3" width="9" height="9" rx="1.5" fill={c}/></svg>,
  code: (c: string) => <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M5 3.5L1.5 7.5L5 11.5" stroke={c} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/><path d="M10 3.5L13.5 7.5L10 11.5" stroke={c} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  undo: (c: string) => <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M3.5 6H9.5C11.6 6 13 7.9 13 10C13 12.1 11.6 14 9.5 14H7" stroke={c} strokeWidth="1.3" strokeLinecap="round"/><path d="M6 4L3.5 6L6 8" stroke={c} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  redo: (c: string) => <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M11.5 6H5.5C3.4 6 2 7.9 2 10C2 12.1 3.4 14 5.5 14H8" stroke={c} strokeWidth="1.3" strokeLinecap="round"/><path d="M9 4L11.5 6L9 8" stroke={c} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  layout: (c: string) => <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><rect x="1.5" y="1.5" width="5" height="5" rx="1" stroke={c} strokeWidth="1.2"/><rect x="8.5" y="1.5" width="5" height="5" rx="1" stroke={c} strokeWidth="1.2"/><rect x="1.5" y="8.5" width="5" height="5" rx="1" stroke={c} strokeWidth="1.2"/><rect x="8.5" y="8.5" width="5" height="5" rx="1" stroke={c} strokeWidth="1.2"/></svg>,
  layoutH: (c: string) => <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><rect x="1" y="3" width="4" height="9" rx="1" stroke={c} strokeWidth="1.2"/><rect x="6.5" y="3" width="4" height="9" rx="1" stroke={c} strokeWidth="1.2"/><path d="M5 7.5H6.5" stroke={c} strokeWidth="1" strokeLinecap="round"/></svg>,
  back: (c: string) => <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M9 2L4 7L9 12" stroke={c} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  nodes: (c: string) => <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 3V13M3 8H13" stroke={c} strokeWidth="1.5" strokeLinecap="round"/><rect x="1" y="1" width="4" height="4" rx="1" stroke={c} strokeWidth="1.2"/><rect x="11" y="1" width="4" height="4" rx="1" stroke={c} strokeWidth="1.2"/><rect x="1" y="11" width="4" height="4" rx="1" stroke={c} strokeWidth="1.2"/><rect x="11" y="11" width="4" height="4" rx="1" stroke={c} strokeWidth="1.2"/></svg>,
  chat: (c: string) => <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 3C2 2.4 2.4 2 3 2H13C13.6 2 14 2.4 14 3V10C14 10.6 13.6 11 13 11H5L2 14V3Z" stroke={c} strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/><path d="M5 5H11M5 8H8" stroke={c} strokeWidth="1" strokeLinecap="round" /></svg>
}

type DockAction = {
  id: string
  icon: (c: string) => React.ReactNode
  label: string
  onClick?: () => void
  active?: boolean
  danger?: boolean
  accent?: boolean
  separatorBefore?: boolean
}

interface SidebarProps {
  editorMode?: boolean
  workflowName?: string
  isRunning?: boolean
  showCode?: boolean
  showAssistant?: boolean
  layoutDirection?: 'TB' | 'LR'
  canUndo?: boolean
  canRedo?: boolean
  onSave?: () => void
  onRun?: () => void
  onStop?: () => void
  onToggleCode?: () => void
  onToggleAssistant?: () => void
  onToggleLayout?: () => void
  onUndo?: () => void
  onRedo?: () => void
  onAutoLayout?: () => void
  onBack?: () => void
  onAddNode?: (type: string, definition: NodeDefinition) => void
}

export default function Sidebar(props: SidebarProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const { mode, toggleTheme } = useTheme()
  const toggleSettings = useSettingsStore(s => s.toggleSettings)
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [showNodes, setShowNodes] = useState(false)
  const [nodeSearch, setNodeSearch] = useState('')
  const nodesRef = useRef<HTMLDivElement>(null)

  const isActive = (key: string) => {
    if (key === '/') return location.pathname === '/' || location.pathname === '/workflows'
    return location.pathname.startsWith(key)
  }

  useEffect(() => {
    if (!showNodes) return
    const handler = (e: MouseEvent) => {
      if (nodesRef.current && !nodesRef.current.contains(e.target as HTMLElement)) setShowNodes(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [showNodes])

  const categories = nodeSearch
    ? [{ name: 'Search Results', icon: 'more', nodes: searchNodes(nodeSearch) }]
    : NODE_CATEGORIES

  const onDragStart = (e: React.DragEvent, nodeType: string, def: NodeDefinition) => {
    e.dataTransfer.setData('application/reactflow-type', nodeType)
    e.dataTransfer.setData('application/reactflow-def', JSON.stringify(def))
    e.dataTransfer.effectAllowed = 'move'
    setTimeout(() => setShowNodes(false), 100)
  }

  const navItems: DockAction[] = [
    { id: 'home', icon: icons.home, label: 'Dashboard', onClick: () => navigate('/'), active: isActive('/') },
    { id: 'workflows', icon: icons.workflow, label: 'Workflows', onClick: () => navigate('/workflows'), active: isActive('/workflows') }
  ]

  const editorActions: DockAction[] = props.editorMode ? [
    { id: 'nodes', icon: icons.nodes, label: 'Add Node', onClick: () => { setShowNodes(!showNodes); setNodeSearch('') }, active: showNodes, accent: showNodes, separatorBefore: true },
    { id: 'chat', icon: icons.chat, label: 'Assistant', onClick: props.onToggleAssistant, active: props.showAssistant, accent: props.showAssistant },
    { id: 'back', icon: icons.back, label: 'Back', onClick: props.onBack },
    { id: 'save', icon: icons.save, label: 'Save', onClick: props.onSave },
    { id: 'undo', icon: icons.undo, label: 'Undo', onClick: props.onUndo, active: props.canUndo },
    { id: 'redo', icon: icons.redo, label: 'Redo', onClick: props.onRedo, active: props.canRedo },
    { id: 'layout', icon: props.layoutDirection === 'LR' ? icons.layoutH : icons.layout, label: props.layoutDirection === 'LR' ? 'Horizontal' : 'Vertical', onClick: props.onToggleLayout },
    { id: 'code', icon: icons.code, label: 'Code', onClick: props.onToggleCode, active: props.showCode, accent: props.showCode, separatorBefore: true },
    { id: props.isRunning ? 'stop' : 'run', icon: props.isRunning ? icons.stop : icons.play, label: props.isRunning ? 'Stop' : 'Run', onClick: props.isRunning ? props.onStop : props.onRun, danger: props.isRunning, accent: !props.isRunning }
  ] : []

  const bottomItems: DockAction[] = [
    { id: 'theme', icon: mode === 'dark' ? icons.sun : icons.moon, label: mode === 'dark' ? 'Light' : 'Dark', onClick: toggleTheme, separatorBefore: true },
    { id: 'settings', icon: icons.settings, label: 'Settings', onClick: toggleSettings }
  ]

  const allItems = [...navItems, ...editorActions, ...bottomItems]

  const renderDockItem = (item: DockAction) => {
    const isHovered = hoveredId === item.id
    const iconColor = item.danger ? 'var(--error)' : item.accent ? 'var(--accent)' : item.active ? 'var(--text-primary)' : 'var(--text-tertiary)'
    const showLabel = isHovered

    return (
      <div key={item.id} style={{ position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        {showLabel && (
          <div style={{
            position: 'absolute', bottom: '100%', marginBottom: 6,
            padding: '3px 8px', borderRadius: 6,
            background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)',
            fontSize: 10, fontWeight: 500, color: 'var(--text-primary)',
            whiteSpace: 'nowrap', boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
            pointerEvents: 'none', zIndex: 10
          }}>
            {item.label}
          </div>
        )}
        <button
          onClick={item.onClick}
          onMouseEnter={() => setHoveredId(item.id)}
          onMouseLeave={() => setHoveredId(null)}
          aria-label={item.label}
          style={{
            width: 36, height: 36,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: item.accent ? 'var(--accent-muted)' : isHovered ? 'var(--bg-hover)' : 'transparent',
            border: item.accent ? '1px solid var(--accent)' : '1px solid transparent',
            borderRadius: 10, cursor: 'pointer',
            color: iconColor,
            transition: 'all 0.15s ease',
            transform: isHovered ? 'translateY(-2px) scale(1.1)' : 'translateY(0) scale(1)'
          }}>
          {item.icon(iconColor)}
        </button>
      </div>
    )
  }

  const renderSeparator = (key: string) => (
    <div key={key} style={{ width: 1, height: 24, background: 'var(--border-primary)', margin: '0 4px', alignSelf: 'center' }} />
  )

  const items: React.ReactNode[] = []
  allItems.forEach((item, i) => {
    if (item.separatorBefore) items.push(renderSeparator(`sep-${i}`))
    items.push(renderDockItem(item))
  })

  return (
    <div ref={nodesRef}>
      {showNodes && props.onAddNode && (
        <div style={{
          position: 'fixed', bottom: 64, left: '50%', transform: 'translateX(-50%)',
          width: 280, maxHeight: 440,
          background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)',
          borderRadius: 12, boxShadow: '0 12px 40px rgba(0,0,0,0.5)',
          display: 'flex', flexDirection: 'column', overflow: 'hidden', zIndex: 210
        }}>
          <div style={{ padding: '8px 10px', borderBottom: '1px solid var(--border-primary)' }}>
            <Input placeholder="Search nodes..." value={nodeSearch} onChange={(e) => setNodeSearch(e.target.value)} size="small" allowClear autoFocus style={{ fontSize: 12 }} />
          </div>
          <div style={{ flex: 1, overflow: 'auto', padding: '4px 0' }}>
            {categories.map((cat) => (
              <div key={cat.name} style={{ marginBottom: 2 }}>
                <div style={{ padding: '5px 10px', fontSize: 10, fontWeight: 600, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{cat.name}</div>
                {cat.nodes.map((node) => {
                  const color = CAT_COLORS[node.category] || '#888'
                  const iconFn = NODE_ICON_MAP[node.icon] || NODE_ICON_MAP['unknown']
                  return (
                    <button key={node.type} draggable onDragStart={(e) => onDragStart(e, node.type, node)} onClick={() => { props.onAddNode!(node.type, node); setShowNodes(false) }}
                      style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '6px 10px', background: 'transparent', border: 'none', cursor: 'grab', textAlign: 'left', transition: 'background 0.1s' }}
                      onMouseEnter={(e) => e.currentTarget.style.background = 'var(--bg-hover)'}
                      onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}>
                      <span style={{ display: 'flex', width: 16, justifyContent: 'center' }}>{iconFn(12, color)}</span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 11, fontWeight: 500, color: 'var(--text-primary)' }}>{node.label}</div>
                        <div style={{ fontSize: 9, color: 'var(--text-tertiary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{node.description}</div>
                      </div>
                    </button>
                  )
                })}
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{
        position: 'fixed', bottom: 12, left: '50%', transform: 'translateX(-50%)',
        display: 'flex', alignItems: 'center', gap: 4,
        padding: '6px 10px',
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border-primary)',
        borderRadius: 16,
        boxShadow: '0 8px 32px rgba(0,0,0,0.4), 0 0 0 1px rgba(255,255,255,0.05) inset',
        backdropFilter: 'blur(20px)',
        zIndex: 200
      }}>
        {items}
      </div>
    </div>
  )
}
