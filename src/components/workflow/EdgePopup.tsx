import { useEffect, useRef, useState, useCallback, memo } from 'react'
import { Input, Switch, InputNumber } from 'antd'
import type { Edge } from 'reactflow'

interface EdgePopupProps {
  edge: Edge
  onClose: () => void
  onUpdate: (edgeId: string, data: Record<string, unknown>) => void
  onDelete: (edgeId: string) => void
}

function EdgePopupInner({ edge, onClose, onUpdate, onDelete }: EdgePopupProps) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ x: 0, y: 0 })
  const [condition, setCondition] = useState(edge.data?.condition || '')
  const [isBackEdge, setIsBackEdge] = useState(edge.data?.isBackEdge || false)
  const [maxIterations, setMaxIterations] = useState(edge.data?.maxIterations || 100)
  const [label, setLabel] = useState(String(edge.label || ''))

  useEffect(() => {
    const el = document.querySelector(`[data-id="${edge.id}"]`) as HTMLElement | null
    if (!el) {
      setPos({ x: window.innerWidth / 2 - 160, y: window.innerHeight / 2 - 150 })
      return
    }
    const rect = el.getBoundingClientRect()
    const popupW = 320
    let x = rect.left + rect.width / 2 - popupW / 2
    let y = rect.top - 12
    if (x < 16) x = 16
    if (x + popupW > window.innerWidth - 16) x = window.innerWidth - popupW - 16
    if (y < 16) y = rect.bottom + 12
    setPos({ x, y })
  }, [edge.id])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (!target) return
      if (ref.current?.contains(target)) return
      let n: HTMLElement | null = target
      while (n && n !== document.body) {
        if (n.classList && (
          n.classList.contains('ant-select-dropdown') ||
          n.classList.contains('ant-popover') ||
          n.classList.contains('ant-modal')
        )) return
        n = n.parentElement
      }
      onClose()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])

  const pushUpdate = useCallback((updates: Record<string, unknown>) => {
    onUpdate(edge.id, {
      condition: updates.condition !== undefined ? updates.condition : (condition || undefined),
      isBackEdge: updates.isBackEdge !== undefined ? updates.isBackEdge : isBackEdge,
      maxIterations: updates.maxIterations !== undefined ? updates.maxIterations : (isBackEdge ? maxIterations : undefined),
      label: updates.label !== undefined ? updates.label : (label || undefined)
    })
  }, [edge.id, condition, isBackEdge, maxIterations, label, onUpdate])

  const handleConditionChange = useCallback((val: string) => {
    setCondition(val)
    pushUpdate({ condition: val || undefined })
  }, [pushUpdate])

  const handleBackEdgeChange = useCallback((val: boolean) => {
    setIsBackEdge(val)
    pushUpdate({ isBackEdge: val, maxIterations: val ? maxIterations : undefined })
  }, [pushUpdate, maxIterations])

  const handleMaxIterChange = useCallback((val: number | null) => {
    const v = val || 100
    setMaxIterations(v)
    pushUpdate({ maxIterations: v })
  }, [pushUpdate])

  const handleLabelChange = useCallback((val: string) => {
    setLabel(val)
    pushUpdate({ label: val || undefined })
  }, [pushUpdate])

  const handleDelete = useCallback(() => {
    onDelete(edge.id)
  }, [edge.id, onDelete])

  return (
    <div ref={ref} style={{
      position: 'fixed', left: pos.x, top: pos.y, width: 320,
      background: 'var(--bg-elevated)',
      border: '1px solid var(--border-primary)', borderRadius: 12,
      boxShadow: '0 12px 40px rgba(0,0,0,0.5)', zIndex: 1000,
      display: 'flex', flexDirection: 'column', overflow: 'hidden'
    }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '10px 14px', borderBottom: '1px solid var(--border-primary)', flexShrink: 0
      }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
          Edge Properties
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          <button onClick={handleDelete} aria-label="Delete edge" style={{
            width: 26, height: 26, display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--error)',
            borderRadius: 4, fontSize: 12, transition: 'background 0.1s'
          }} onMouseEnter={e => e.currentTarget.style.background = 'var(--error-muted)'}
             onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
            <svg width={12} height={12} viewBox="0 0 12 12" fill="none"><path d="M2 3H10M4.5 3V2C4.5 1.4 4.9 1 5.5 1H6.5C7.1 1 7.5 1.4 7.5 2V3M9.5 3V10C9.5 10.6 9.1 11 8.5 11H3.5C2.9 11 2.5 10.6 2.5 10V3" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" /><path d="M5 5.5V8.5M7 5.5V8.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" /></svg>
          </button>
          <button onClick={onClose} aria-label="Close" style={{
            width: 26, height: 26, display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)',
            borderRadius: 4, fontSize: 16, lineHeight: 1, transition: 'background 0.1s'
          }} onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
             onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
            ×
          </button>
        </div>
      </div>

      <div style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div>
          <div style={{ color: 'var(--text-secondary)', fontSize: 12, fontWeight: 500, marginBottom: 4 }}>Label</div>
          <Input
            value={label}
            onChange={e => handleLabelChange(e.target.value)}
            placeholder="Edge label (optional)"
            size="small"
            style={{ background: 'var(--bg-input)', borderColor: 'var(--border-primary)', fontSize: 12 }}
          />
        </div>

        <div>
          <div style={{ color: 'var(--text-secondary)', fontSize: 12, fontWeight: 500, marginBottom: 4 }}>
            Condition
          </div>
          <Input
            value={condition}
            onChange={e => handleConditionChange(e.target.value)}
            placeholder="e.g. output.result === true"
            size="small"
            style={{ background: 'var(--bg-input)', borderColor: 'var(--border-primary)', fontSize: 12, fontFamily: 'monospace' }}
          />
          <div style={{ color: 'var(--text-tertiary)', fontSize: 10, marginTop: 3 }}>
            JS expression. Available: output, pool, iteration
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ color: 'var(--text-secondary)', fontSize: 12, fontWeight: 500 }}>Back Edge</div>
            <div style={{ color: 'var(--text-tertiary)', fontSize: 10 }}>Mark as loop-back edge</div>
          </div>
          <Switch
            size="small"
            checked={isBackEdge}
            onChange={handleBackEdgeChange}
          />
        </div>

        {isBackEdge && (
          <div>
            <div style={{ color: 'var(--text-secondary)', fontSize: 12, fontWeight: 500, marginBottom: 4 }}>
              Max Iterations
            </div>
            <InputNumber
              value={maxIterations}
              onChange={handleMaxIterChange}
              min={1}
              max={10000}
              size="small"
              style={{ width: '100%', background: 'var(--bg-input)', borderColor: 'var(--border-primary)' }}
            />
          </div>
        )}
      </div>
    </div>
  )
}

export default memo(EdgePopupInner)
