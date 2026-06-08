import { useState, useCallback, memo, useRef, useEffect } from 'react'
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
  const measureRef = useRef<HTMLDivElement>(null)

  const { data } = node
  const nodeType = data.type || 'default'
  const definition = getNodeDefinition(nodeType)
  const defaultProv = getDefaultProvider()
  const providerOptions = providers.map(p => ({ label: `${p.name} (${PROVIDER_LABELS[p.type]})`, value: p.id }))

  const [label, setLabel] = useState(data.label)
  const [config, setConfig] = useState<Record<string, unknown>>((data.config || {}) as Record<string, unknown>)
  const [popupW, setPopupW] = useState(0)
  const [popupH, setPopupH] = useState(0)
  const [userResized, setUserResized] = useState(false)

  useEffect(() => {
    if (!userResized && measureRef.current) {
      const rect = measureRef.current.getBoundingClientRect()
      setPopupW(Math.ceil(rect.width))
      setPopupH(Math.ceil(rect.height))
    }
  }, [label, config, userResized, nodeType])

  const handleConfigChange = useCallback((field: string, value: unknown) => {
    setConfig(prev => ({ ...prev, [field]: value }))
  }, [])

  const handleSave = useCallback(() => {
    onUpdateNodeData(node.id, { label, config })
    onClose()
  }, [node.id, label, config, onUpdateNodeData, onClose])

  const handleCancel = useCallback(() => { onClose() }, [onClose])

  const handleDelete = useCallback(() => {
    if (onDelete) onDelete(node.id)
    else onClose()
  }, [node.id, onDelete, onClose])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape') handleCancel()
    if ((e.metaKey || e.ctrlKey) && e.key === 's') { e.preventDefault(); handleSave() }
  }, [handleCancel, handleSave])

  const startResize = useCallback((e: React.MouseEvent, dir: 'right' | 'bottom' | 'corner') => {
    e.preventDefault()
    setUserResized(true)
    const startX = e.clientX; const startY = e.clientY
    const startW = popupW || 400; const startH = popupH || 400
    const minW = 340; const minH = 260
    const maxW = window.innerWidth - 40
    const maxH = window.innerHeight - 40

    const onMove = (ev: MouseEvent) => {
      if (dir === 'right' || dir === 'corner') setPopupW(Math.min(maxW, Math.max(minW, startW + ev.clientX - startX)))
      if (dir === 'bottom' || dir === 'corner') setPopupH(Math.min(maxH, Math.max(minH, startH + ev.clientY - startY)))
    }
    const onUp = () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp) }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [popupW, popupH])

  const w = userResized ? popupW : undefined
  const h = userResized ? popupH : undefined

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
      <div ref={measureRef} style={{
        position: 'absolute', visibility: 'hidden', pointerEvents: 'none',
        width: 'fit-content', minWidth: 340, maxWidth: 'min(720px, calc(100vw - 40px))',
        display: 'flex', flexDirection: 'column'
      }}>
        <div style={{ padding: '8px 12px' }}>
          <div style={{ fontSize: 13, fontWeight: 600 }}>{definition?.label || data.label}</div>
          {definition && <div style={{ fontSize: 10 }}>{definition.description}</div>}
        </div>
        <div style={{ padding: 10 }}>
          <div style={{ marginBottom: 8 }}><div style={{ height: 14, marginBottom: 3 }} /><div style={{ height: 28 }} /></div>
          <NodeConfigForms config={config} nodeType={nodeType} handleChange={() => {}} providerOptions={providerOptions} defaultProviderId={defaultProv?.id} />
        </div>
        <div style={{ padding: '8px 12px', display: 'flex', gap: 6 }}>
          <div style={{ width: 60, height: 26 }} />
          <div style={{ width: 50, height: 26 }} />
        </div>
      </div>

      <div ref={containerRef} style={{
        width: w, height: h,
        minWidth: 340, minHeight: 260,
        maxWidth: 'min(720px, calc(100vw - 40px))',
        maxHeight: 'calc(100vh - 60px)',
        background: 'var(--bg-elevated)',
        border: '1px solid var(--border-primary)',
        borderRadius: 10,
        boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
        display: 'flex', flexDirection: 'column', overflow: 'hidden',
        position: 'relative',
        ...(!userResized ? { width: popupW || 'fit-content', height: popupH || 'auto' } : {})
      }}>
        <div onMouseDown={e => startResize(e, 'right')} style={{
          position: 'absolute', top: 0, right: -3, width: 6, height: '100%',
          cursor: 'ew-resize', zIndex: 10
        }} />
        <div onMouseDown={e => startResize(e, 'bottom')} style={{
          position: 'absolute', bottom: -3, left: 0, width: '100%', height: 6,
          cursor: 'ns-resize', zIndex: 10
        }} />
        <div onMouseDown={e => startResize(e, 'corner')} style={{
          position: 'absolute', bottom: -2, right: -2, width: 16, height: 16,
          cursor: 'nwse-resize', zIndex: 11, display: 'flex', alignItems: 'flex-end', justifyContent: 'flex-end', padding: 2
        }}>
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" style={{ opacity: 0.35 }}>
            <path d="M8 2L2 8M8 5L5 8M8 8L8 8" stroke="var(--text-tertiary)" strokeWidth="1.2" strokeLinecap="round" />
          </svg>
        </div>

        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '8px 12px', borderBottom: '1px solid var(--border-primary)', flexShrink: 0
        }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
              {definition?.label || data.label}
            </div>
            {definition && (
              <div style={{ fontSize: 10, color: 'var(--text-tertiary)', marginTop: 1 }}>{definition.description}</div>
            )}
          </div>
          <div style={{ display: 'flex', gap: 3, marginLeft: 8 }}>
            {onDelete && (
              <button onClick={handleDelete} aria-label="Delete node" title="Delete node" style={{
                width: 24, height: 24, display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)',
                borderRadius: 4, transition: 'all 0.12s'
              }} onMouseEnter={e => { e.currentTarget.style.color = 'var(--error)'; e.currentTarget.style.background = 'var(--error-muted)' }}
                 onMouseLeave={e => { e.currentTarget.style.color = 'var(--text-tertiary)'; e.currentTarget.style.background = 'transparent' }}>
                <svg width={12} height={12} viewBox="0 0 12 12" fill="none"><path d="M2 3H10M4.5 3V2C4.5 1.4 4.9 1 5.5 1H6.5C7.1 1 7.5 1.4 7.5 2V3M9.5 3V10C9.5 10.6 9.1 11 8.5 11H3.5C2.9 11 2.5 10.6 2.5 10V3" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" /><path d="M5 5.5V8.5M7 5.5V8.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" /></svg>
              </button>
            )}
            <button onClick={handleCancel} aria-label="Close" style={{
              width: 24, height: 24, display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)',
              borderRadius: 4, fontSize: 16, lineHeight: 1, transition: 'background 0.12s'
            }} onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
               onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
              ×
            </button>
          </div>
        </div>

        <div style={{ flex: 1, overflow: 'auto', padding: 10 }}>
          <div style={{ marginBottom: 8 }}>
            <div style={{ color: 'var(--text-secondary)', fontSize: 11, fontWeight: 500, marginBottom: 3 }}>Label</div>
            <Input value={label} onChange={(e) => setLabel(e.target.value)}
              style={{ background: 'var(--bg-input)', borderColor: 'var(--border-primary)', fontSize: 12 }} size="small" />
          </div>

          {nodeType !== 'comment' && (
            <div style={{ marginBottom: 8, display: 'flex', gap: 6 }}>
              <div style={{ flex: 1 }}>
                <div style={{ color: 'var(--text-secondary)', fontSize: 11, fontWeight: 500, marginBottom: 3 }}>Type</div>
                <Input value={nodeType} disabled style={{ background: 'var(--bg-input)', borderColor: 'var(--border-primary)', fontSize: 12, color: 'var(--text-tertiary)' }} size="small" />
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ color: 'var(--text-secondary)', fontSize: 11, fontWeight: 500, marginBottom: 3 }}>Category</div>
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
          display: 'flex', justifyContent: 'flex-end', gap: 6,
          padding: '8px 12px', borderTop: '1px solid var(--border-primary)', flexShrink: 0
        }}>
          <button onClick={handleCancel} style={{
            padding: '4px 12px', fontSize: 11, fontWeight: 500, borderRadius: 5,
            background: 'var(--bg-hover)', border: '1px solid var(--border-primary)',
            color: 'var(--text-secondary)', cursor: 'pointer', transition: 'all 0.12s'
          }} onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-input)'}
             onMouseLeave={e => e.currentTarget.style.background = 'var(--bg-hover)'}>
            Cancel
          </button>
          <button onClick={handleSave} style={{
            padding: '4px 12px', fontSize: 11, fontWeight: 600, borderRadius: 5,
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
