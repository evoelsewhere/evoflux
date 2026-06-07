import { useState } from 'react'
import { Layout, Tooltip } from 'antd'
import { useTheme } from '../common/ThemeProvider'
import { useNavigate, useLocation } from 'react-router-dom'

const { Sider } = Layout

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
  back: (c: string) => <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M9 2L4 7L9 12" stroke={c} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
}

type SidebarAction = {
  id: string
  icon: (c: string) => React.ReactNode
  label: string
  onClick?: () => void
  active?: boolean
  danger?: boolean
  accent?: boolean
}

interface SidebarProps {
  editorMode?: boolean
  workflowName?: string
  isRunning?: boolean
  showCode?: boolean
  canUndo?: boolean
  canRedo?: boolean
  onSave?: () => void
  onRun?: () => void
  onStop?: () => void
  onToggleCode?: () => void
  onUndo?: () => void
  onRedo?: () => void
  onAutoLayout?: () => void
  onBack?: () => void
}

const BT = 'var(--text-secondary)'
const BT_H = 'var(--text-primary)'

export default function Sidebar(props: SidebarProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const { mode, toggleTheme } = useTheme()

  const isActive = (key: string) => {
    if (key === '/') return location.pathname === '/' || location.pathname === '/workflows'
    return location.pathname.startsWith(key)
  }

  const navItems = [
    { key: '/', icon: icons.home, label: 'Dashboard' },
    { key: '/workflows', icon: icons.workflow, label: 'Workflows' }
  ]

  const editorActions: SidebarAction[] = props.editorMode ? [
    { id: 'back', icon: icons.back, label: 'Back', onClick: props.onBack },
    { id: 'save', icon: icons.save, label: 'Save (Ctrl+S)', onClick: props.onSave },
    { id: 'sep1', icon: () => null, label: '' },
    { id: 'undo', icon: icons.undo, label: 'Undo (Ctrl+Z)', onClick: props.onUndo, active: props.canUndo },
    { id: 'redo', icon: icons.redo, label: 'Redo (Ctrl+Y)', onClick: props.onRedo, active: props.canRedo },
    { id: 'layout', icon: icons.layout, label: 'Auto Layout', onClick: props.onAutoLayout },
    { id: 'sep2', icon: () => null, label: '' },
    { id: 'code', icon: icons.code, label: 'Code View', onClick: props.onToggleCode, active: props.showCode, accent: props.showCode },
    { id: props.isRunning ? 'stop' : 'run', icon: props.isRunning ? icons.stop : icons.play, label: props.isRunning ? 'Stop' : 'Run', onClick: props.isRunning ? props.onStop : props.onRun, danger: props.isRunning, accent: !props.isRunning }
  ] : []

  const btnBase = (active: boolean, accent?: boolean): React.CSSProperties => ({
    width: 34, height: 34,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    background: accent ? 'var(--accent-muted)' : active ? 'var(--bg-hover)' : 'transparent',
    border: accent ? '1px solid var(--border-secondary)' : 'none',
    borderRadius: 6, cursor: 'pointer',
    color: active ? 'var(--text-primary)' : 'var(--text-tertiary)',
    transition: 'all 0.12s', position: 'relative' as const
  })

  return (
    <Sider width={52} style={{
      background: 'var(--bg-secondary)', borderRight: '1px solid var(--border-primary)',
      display: 'flex', flexDirection: 'column',
      justifyContent: 'space-between', height: '100vh', overflow: 'hidden'
    }}>
      <div>
        <div style={{
          height: 48, display: 'flex', alignItems: 'center', justifyContent: 'center',
          borderBottom: '1px solid var(--border-primary)', cursor: 'pointer'
        }} onClick={() => navigate('/')}>
          <div style={{
            width: 26, height: 26, borderRadius: 6,
            background: 'linear-gradient(135deg, #6366f1, #a855f7)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 12, fontWeight: 700, color: '#fff'
          }}>E</div>
        </div>

        <div style={{ padding: '6px 0', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1 }}>
          {navItems.map((item) => {
            const active = isActive(item.key)
            return (
              <Tooltip key={item.key} title={item.label} placement="right">
                <button onClick={() => navigate(item.key)} style={btnBase(active)}
                  onMouseEnter={(e) => { if (!active) { e.currentTarget.style.background = 'var(--bg-hover)'; e.currentTarget.style.color = BT_H } }}
                  onMouseLeave={(e) => { if (!active) { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = BT } }}>
                  {active && <div style={{ position: 'absolute', left: 0, top: '50%', transform: 'translateY(-50%)', width: 2, height: 14, background: 'var(--accent)', borderRadius: 1 }} />}
                  {item.icon(active ? 'var(--text-primary)' : 'var(--text-tertiary)')}
                </button>
              </Tooltip>
            )
          })}

          {editorActions.length > 0 && <div style={{ width: 24, height: 1, background: 'var(--border-primary)', margin: '6px 0' }} />}

          {editorActions.map((action) => {
            if (action.id.startsWith('sep')) return <div key={action.id} style={{ width: 24, height: 1, background: 'var(--border-primary)', margin: '4px 0' }} />
            const iconColor = action.danger ? 'var(--error)' : action.accent ? 'var(--accent)' : action.active ? 'var(--text-primary)' : 'var(--text-tertiary)'
            return (
              <Tooltip key={action.id} title={action.label} placement="right">
                <button onClick={action.onClick} disabled={!action.onClick}
                  style={{ ...btnBase(!!action.active, action.accent), color: action.danger ? 'var(--error)' : undefined }}
                  onMouseEnter={(e) => { if (!action.active && !action.accent) { e.currentTarget.style.background = 'var(--bg-hover)'; e.currentTarget.style.color = BT_H } }}
                  onMouseLeave={(e) => { if (!action.active && !action.accent) { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = BT } }}>
                  {action.icon(iconColor)}
                </button>
              </Tooltip>
            )
          })}
        </div>
      </div>

      <div style={{ padding: '6px 0 10px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1 }}>
        <Tooltip title={mode === 'dark' ? 'Light mode' : 'Dark mode'} placement="right">
          <button onClick={toggleTheme} style={btnBase(false)}
            onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--bg-hover)'; e.currentTarget.style.color = BT_H }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = BT }}>
            {mode === 'dark' ? icons.sun('var(--text-tertiary)') : icons.moon('var(--text-tertiary)')}
          </button>
        </Tooltip>
        <Tooltip title="Settings" placement="right">
          <button onClick={() => navigate('/settings')} style={btnBase(isActive('/settings'))}
            onMouseEnter={(e) => { if (!isActive('/settings')) { e.currentTarget.style.background = 'var(--bg-hover)'; e.currentTarget.style.color = BT_H } }}
            onMouseLeave={(e) => { if (!isActive('/settings')) { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = BT } }}>
            {icons.settings(isActive('/settings') ? 'var(--text-primary)' : 'var(--text-tertiary)')}
          </button>
        </Tooltip>
      </div>
    </Sider>
  )
}
