import { useEffect, useRef, useState, useCallback, memo } from 'react'
import { Input } from 'antd'
import { useWorkflowStore } from '../../stores/workflowStore'
import { useProviderStore, PROVIDER_LABELS } from '../../stores/providerStore'
import { getNodeDefinition } from './registry'
import NodeConfigForms from './node-configs/NodeConfigForms'
import type { NodeData } from '../../types/workflow'
import type { Node } from 'reactflow'

interface NodePopupProps {
  node: Node<NodeData>
  onClose: () => void
  onDelete?: (nodeId: string) => void
}

function TrashIcon() {
  return <svg width={12} height={12} viewBox="0 0 12 12" fill="none"><path d="M2 3H10M4.5 3V2C4.5 1.4 4.9 1 5.5 1H6.5C7.1 1 7.5 1.4 7.5 2V3M9.5 3V10C9.5 10.6 9.1 11 8.5 11H3.5C2.9 11 2.5 10.6 2.5 10V3" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" /><path d="M5 5.5V8.5M7 5.5V8.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" /></svg>
}

function NodePopupInner({ node, onClose, onDelete }: NodePopupProps) {
  const ref = useRef<HTMLDivElement>(null)
  const updateNodeData = useWorkflowStore(s => s.updateNodeData)
  const providers = useProviderStore(s => s.providers)
  const getDefaultProvider = useProviderStore(s => s.getDefaultProvider)
  const [pos, setPos] = useState({ x: 0, y: 0 })

  const liveNode = useWorkflowStore(s => s.nodes.find(n => n.id === node.id))
  const data = liveNode?.data || node.data
  const nodeType = data.type || 'default'
  const definition = getNodeDefinition(nodeType)
  const config = (data.config || {}) as Record<string, unknown>
  const defaultProv = getDefaultProvider()
  const providerOptions = providers.map(p => ({ label: `${p.name} (${PROVIDER_LABELS[p.type]})`, value: p.id }))

  const handleChange = useCallback((field: string, value: unknown) => {
    const currentConfig = (useWorkflowStore.getState().nodes.find(n => n.id === node.id)?.data?.config || {}) as Record<string, unknown>
    updateNodeData(node.id, { config: { ...currentConfig, [field]: value } })
  }, [node.id, updateNodeData])

  const handleLabelChange = useCallback((label: string) => {
    updateNodeData(node.id, { label })
  }, [node.id, updateNodeData])

  const handleDelete = useCallback(() => {
    if (onDelete) onDelete(node.id)
    else onClose()
  }, [node.id, onDelete, onClose])

  useEffect(() => {
    const el = document.querySelector(`[data-id="${node.id}"]`) as HTMLElement | null
    if (!el) return
    const rect = el.getBoundingClientRect()
    const popupW = 320
    const popupEstH = 400
    let x = rect.right + 12
    let y = rect.top
    if (x + popupW > window.innerWidth - 16) x = rect.left - popupW - 12
    if (x < 16) x = 16
    if (y + popupEstH > window.innerHeight - 16) y = window.innerHeight - popupEstH - 16
    if (y < 16) y = 16
    setPos({ x, y })
  }, [node.id, node.position])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (!target) return
      if (ref.current?.contains(target)) return
      let n: HTMLElement | null = target
      while (n && n !== document.body) {
        if (n.classList && (
          n.classList.contains('ant-select-dropdown') || n.classList.contains('ant-select-item') ||
          n.classList.contains('ant-select-item-option') || n.classList.contains('ant-select-selection-item') ||
          n.classList.contains('ant-select-selection-search') || n.classList.contains('ant-select-clear') ||
          n.classList.contains('ant-popover') || n.classList.contains('ant-dropdown') ||
          n.classList.contains('ant-modal') || n.classList.contains('ant-slider') ||
          n.classList.contains('ant-slider-handle') || n.classList.contains('monaco-editor') ||
          n.classList.contains('context-view') || n.classList.contains('rc-virtual-list') ||
          n.classList.contains('rc-virtual-list-holder')
        )) return
        n = n.parentElement
      }
      onClose()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])

  return (
    <div ref={ref} style={{
      position: 'fixed', left: pos.x, top: pos.y, width: 320,
      maxHeight: 'calc(100vh - 32px)', background: 'var(--bg-elevated)',
      border: '1px solid var(--border-primary)', borderRadius: 12,
      boxShadow: '0 12px 40px rgba(0,0,0,0.5)', zIndex: 1000,
      display: 'flex', flexDirection: 'column', overflow: 'hidden'
    }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '10px 14px', borderBottom: '1px solid var(--border-primary)', flexShrink: 0
      }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
            {definition?.label || data.label}
          </div>
          {definition && (
            <div style={{ fontSize: 10, color: 'var(--text-tertiary)', marginTop: 1 }}>{definition.description}</div>
          )}
        </div>
        <div style={{ display: 'flex', gap: 4, marginLeft: 8 }}>
          <button onClick={handleDelete} aria-label="Delete node" style={{
            width: 26, height: 26, display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--error)',
            borderRadius: 4, transition: 'background 0.1s'
          }} onMouseEnter={e => e.currentTarget.style.background = 'var(--error-muted)'}
             onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
            <TrashIcon />
          </button>
          <button onClick={onClose} aria-label="Close popup" style={{
            width: 26, height: 26, display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)',
            borderRadius: 4, fontSize: 16, lineHeight: 1, transition: 'background 0.1s'
          }} onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
             onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
            ×
          </button>
        </div>
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: 14 }}>
        <div style={{ marginBottom: 10 }}>
          <div style={{ color: 'var(--text-secondary)', fontSize: 12, fontWeight: 500, marginBottom: 4 }}>Label</div>
          <Input value={data.label} onChange={(e) => handleLabelChange(e.target.value)} style={{ background: 'var(--bg-input)', borderColor: 'var(--border-primary)', fontSize: 12 }} size="small" />
        </div>

        {nodeType !== 'comment' && (
          <div style={{ marginBottom: 10, display: 'flex', gap: 8 }}>
            <div style={{ flex: 1 }}>
              <div style={{ color: 'var(--text-secondary)', fontSize: 12, fontWeight: 500, marginBottom: 4 }}>Type</div>
              <Input value={nodeType} disabled style={{ background: 'var(--bg-input)', borderColor: 'var(--border-primary)', fontSize: 12, color: 'var(--text-tertiary)' }} size="small" />
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ color: 'var(--text-secondary)', fontSize: 12, fontWeight: 500, marginBottom: 4 }}>Category</div>
              <Input value={data.category || ''} disabled style={{ background: 'var(--bg-input)', borderColor: 'var(--border-primary)', fontSize: 12, color: 'var(--text-tertiary)' }} size="small" />
            </div>
          </div>
        )}

        <NodeConfigForms
          config={config}
          nodeType={nodeType}
          handleChange={handleChange}
          providerOptions={providerOptions}
          defaultProviderId={defaultProv?.id}
        />
      </div>
    </div>
  )
}

export default memo(NodePopupInner)
