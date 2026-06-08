import { useState, useCallback, memo, useRef } from 'react'
import { Input } from 'antd'
import { useProviderStore, PROVIDER_LABELS } from '../../stores/providerStore'
import { getNodeDefinition } from './registry'
import NodeConfigForms from './node-configs/NodeConfigForms'
import type { NodeData } from '../../types/workflow'
import type { Node } from 'reactflow'

interface NodePopupProps {
  node: Node<NodeData>
  onClose: () => void
  onDelete?: (nodeId: string) => void
  onUpdateNodeData: (nodeId: string, data: Partial<NodeData>) => void
}

function NodePopupInner({ node, onClose, onDelete, onUpdateNodeData }: NodePopupProps) {
  const providers = useProviderStore(s => s.providers)
  const getDefaultProvider = useProviderStore(s => s.getDefaultProvider)
  const containerRef = useRef<HTMLDivElement>(null)

  const { data } = node
  const nodeType = data.type || 'default'
  const definition = getNodeDefinition(nodeType)
  const defaultProv = getDefaultProvider()
  const providerOptions = providers.map(p => ({ label: `${p.name} (${PROVIDER_LABELS[p.type]})`, value: p.id }))

  const [label, setLabel] = useState(data.label)
  const [config, setConfig] = useState<Record<string, unknown>>((data.config || {}) as Record<string, unknown>)

  const handleConfigChange = useCallback((field: string, value: unknown) => {
    setConfig(prev => ({ ...prev, [field]: value }))
  }, [])

  const handleSave = useCallback(() => {
    onUpdateNodeData(node.id, { label, config })
    onClose()
  }, [node.id, label, config, onUpdateNodeData, onClose])

  const handleCancel = useCallback(() => {
    onClose()
  }, [onClose])

  const handleDelete = useCallback(() => {
    if (onDelete) onDelete(node.id)
    else onClose()
  }, [node.id, onDelete, onClose])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape') handleCancel()
    if ((e.metaKey || e.ctrlKey) && e.key === 's') { e.preventDefault(); handleSave() }
  }, [handleCancel, handleSave])

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(3px)'
      }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) handleCancel() }}
      onKeyDown={handleKeyDown}
    >
      <div ref={containerRef} style={{
        width: 420, maxHeight: 'calc(100vh - 80px)',
        background: 'var(--bg-elevated)',
        border: '1px solid var(--border-primary)',
        borderRadius: 14,
        boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
        display: 'flex', flexDirection: 'column', overflow: 'hidden'
      }}>
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '12px 16px', borderBottom: '1px solid var(--border-primary)', flexShrink: 0
        }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>
              {definition?.label || data.label}
            </div>
            {definition && (
              <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 2 }}>{definition.description}</div>
            )}
          </div>
          <div style={{ display: 'flex', gap: 4, marginLeft: 8 }}>
            {onDelete && (
              <button onClick={handleDelete} aria-label="Delete node" title="Delete node" style={{
                width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)',
                borderRadius: 6, transition: 'all 0.12s'
              }} onMouseEnter={e => { e.currentTarget.style.color = 'var(--error)'; e.currentTarget.style.background = 'var(--error-muted)' }}
                 onMouseLeave={e => { e.currentTarget.style.color = 'var(--text-tertiary)'; e.currentTarget.style.background = 'transparent' }}>
                <svg width={13} height={13} viewBox="0 0 12 12" fill="none"><path d="M2 3H10M4.5 3V2C4.5 1.4 4.9 1 5.5 1H6.5C7.1 1 7.5 1.4 7.5 2V3M9.5 3V10C9.5 10.6 9.1 11 8.5 11H3.5C2.9 11 2.5 10.6 2.5 10V3" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" /><path d="M5 5.5V8.5M7 5.5V8.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" /></svg>
              </button>
            )}
            <button onClick={handleCancel} aria-label="Close" style={{
              width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)',
              borderRadius: 6, fontSize: 18, lineHeight: 1, transition: 'background 0.12s'
            }} onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
               onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
              ×
            </button>
          </div>
        </div>

        <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
          <div style={{ marginBottom: 12 }}>
            <div style={{ color: 'var(--text-secondary)', fontSize: 12, fontWeight: 500, marginBottom: 4 }}>Label</div>
            <Input value={label} onChange={(e) => setLabel(e.target.value)}
              style={{ background: 'var(--bg-input)', borderColor: 'var(--border-primary)', fontSize: 12 }} size="small" />
          </div>

          {nodeType !== 'comment' && (
            <div style={{ marginBottom: 12, display: 'flex', gap: 8 }}>
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
            handleChange={handleConfigChange}
            providerOptions={providerOptions}
            defaultProviderId={defaultProv?.id}
          />
        </div>

        <div style={{
          display: 'flex', justifyContent: 'flex-end', gap: 8,
          padding: '12px 16px', borderTop: '1px solid var(--border-primary)', flexShrink: 0
        }}>
          <button onClick={handleCancel} style={{
            padding: '6px 16px', fontSize: 12, fontWeight: 500, borderRadius: 7,
            background: 'var(--bg-hover)', border: '1px solid var(--border-primary)',
            color: 'var(--text-secondary)', cursor: 'pointer', transition: 'all 0.12s'
          }} onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-input)'}
             onMouseLeave={e => e.currentTarget.style.background = 'var(--bg-hover)'}>
            Cancel
          </button>
          <button onClick={handleSave} style={{
            padding: '6px 16px', fontSize: 12, fontWeight: 600, borderRadius: 7,
            background: 'var(--accent)', border: '1px solid var(--accent)',
            color: '#fff', cursor: 'pointer', transition: 'all 0.12s'
          }} onMouseEnter={e => e.currentTarget.style.opacity = '0.9'}
             onMouseLeave={e => e.currentTarget.style.opacity = '1'}>
            Save
          </button>
        </div>
      </div>
    </div>
  )
}

export default memo(NodePopupInner)
