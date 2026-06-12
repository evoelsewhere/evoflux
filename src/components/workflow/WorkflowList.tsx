import { useEffect, useState, useRef } from 'react'
import { Button, Tag, Spin, Popconfirm, message } from 'antd'
import {
  PlusOutlined,
  ClockCircleOutlined,
  BranchesOutlined,
  MoreOutlined,
  ImportOutlined
} from '@ant-design/icons'
import { useNavigate, useLocation } from 'react-router-dom'
import { nanoid } from 'nanoid'
import Breadcrumb from '../common/Breadcrumb'

interface WorkflowSummary {
  id: string
  name: string
  description: string
  updatedAt: string
  nodes?: unknown[]
}

export default function WorkflowList() {
  const navigate = useNavigate()
  const location = useLocation()
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([])
  const [loading, setLoading] = useState(true)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => { loadWorkflows() }, [location.pathname])

  const loadWorkflows = async () => {
    try {
      const list = (await window.api.workflow.list()) as WorkflowSummary[]
      setWorkflows(list)
    } catch { message.error('Failed to load workflows') }
    finally { setLoading(false) }
  }

  const handleCreate = () => navigate(`/workflows/${nanoid(10)}`)

  const handleImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = async (ev) => {
      try {
        const json = JSON.parse(ev.target?.result as string)
        if (!Array.isArray(json.nodes)) throw new Error('Invalid workflow: missing nodes')
        const wfId = nanoid(10)
        const nodes = json.nodes.map((n: Record<string, unknown>) => ({
          id: String(n.id),
          type: n.type === 'comment' ? 'comment' : 'default',
          position: (n.position as { x: number; y: number }) || { x: 0, y: 0 },
          data: {
            label: String((n.data as Record<string, unknown>)?.label || (n as Record<string, unknown>).label || 'Node'),
            type: String((n.data as Record<string, unknown>)?.type || 'default'),
            icon: (n.data as Record<string, unknown>)?.icon as string,
            category: (n.data as Record<string, unknown>)?.category as string,
            config: ((n.data as Record<string, unknown>)?.config || (n as Record<string, unknown>).config || {}) as Record<string, unknown>,
            text: (n.data as Record<string, unknown>)?.text as string
          }
        }))
        const edges = (json.edges || []).map((e: Record<string, unknown>) => ({
          id: String(e.id),
          source: String(e.source),
          target: String(e.target),
          sourceHandle: e.sourceHandle as string | undefined,
          targetHandle: e.targetHandle as string | undefined,
          type: String(e.type || 'custom'),
          animated: e.animated !== false
        }))
        try {
          await window.api.workflow.save({ id: wfId, name: json.name || file.name.replace('.json', ''), nodes, edges })
        } catch { /* import save failed */ }
        navigate(`/workflows/${wfId}`)
        message.success(`Imported: ${json.name || file.name}`)
      } catch (err) {
        message.error(`Import failed: ${(err as Error).message}`)
      }
    }
    reader.readAsText(file)
    e.target.value = ''
  }

  const handleDelete = async (id: string, e?: React.MouseEvent) => {
    e?.stopPropagation()
    try {
      await window.api.workflow.delete(id)
      setWorkflows((prev) => prev.filter((w) => w.id !== id))
      message.success('Workflow deleted')
    } catch { message.error('Failed to delete workflow') }
  }

  return (
    <div style={{ height: 'calc(100vh - 48px)', display: 'flex', flexDirection: 'column' }}>
      <Breadcrumb />
      <div style={{ flex: 1, overflow: 'auto', padding: '24px 40px' }}>
        <div style={{ maxWidth: 1200, margin: '0 auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
            <div>
              <h1 style={{ fontSize: 24, fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 4px 0', letterSpacing: '-0.02em' }}>Workflows</h1>
              <p style={{ color: 'var(--text-tertiary)', fontSize: 13, margin: 0 }}>{workflows.length} workflow{workflows.length !== 1 ? 's' : ''}</p>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <input ref={fileRef} type="file" accept=".json" style={{ display: 'none' }} onChange={handleImport} />
              <Button icon={<ImportOutlined />} onClick={() => fileRef.current?.click()} style={{ height: 36, fontSize: 13, fontWeight: 500 }}>Import</Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate} style={{ height: 36, fontSize: 13, fontWeight: 500 }}>New Workflow</Button>
            </div>
          </div>

          {loading ? (
            <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 120 }}><Spin /></div>
          ) : workflows.length === 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '80px 0', background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 12 }}>
              <div style={{ width: 48, height: 48, borderRadius: 12, background: 'var(--accent-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 16 }}>
                <BranchesOutlined style={{ color: 'var(--accent)', fontSize: 20 }} />
              </div>
              <h3 style={{ color: 'var(--text-primary)', fontSize: 16, fontWeight: 600, margin: '0 0 6px 0' }}>No workflows yet</h3>
              <p style={{ color: 'var(--text-tertiary)', fontSize: 13, margin: '0 0 20px 0' }}>Create your first AI-powered SDLC workflow</p>
              <div style={{ display: 'flex', gap: 8 }}>
                <Button icon={<ImportOutlined />} onClick={() => fileRef.current?.click()} style={{ height: 36 }}>Import JSON</Button>
                <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate} style={{ height: 36 }}>Create Workflow</Button>
              </div>
            </div>
          ) : (
            <div style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 12, overflow: 'hidden' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 120px 120px 80px', padding: '10px 20px', borderBottom: '1px solid var(--border-primary)', fontSize: 12, fontWeight: 500, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                <span>Name</span><span>Status</span><span>Updated</span><span></span>
              </div>
              {workflows.map((wf, i) => (
                <div
                  key={wf.id}
                  onClick={() => navigate(`/workflows/${wf.id}`)}
                  style={{ display: 'grid', gridTemplateColumns: '1fr 120px 120px 80px', padding: '14px 20px', cursor: 'pointer', transition: 'background 0.1s', borderBottom: i < workflows.length - 1 ? '1px solid var(--border-primary)' : 'none', alignItems: 'center' }}
                  onMouseEnter={(e) => e.currentTarget.style.background = 'var(--bg-hover)'}
                  onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <div style={{ width: 32, height: 32, borderRadius: 8, background: 'var(--accent-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                      <BranchesOutlined style={{ color: 'var(--accent)', fontSize: 14 }} />
                    </div>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-primary)' }}>{wf.name}</div>
                      {wf.description && <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 2, maxWidth: 400, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{wf.description}</div>}
                    </div>
                  </div>
                  <div><Tag style={{ color: 'var(--text-tertiary)', background: 'var(--bg-hover)', border: 'none', margin: 0 }}>draft</Tag></div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: 'var(--text-tertiary)' }}>
                    <ClockCircleOutlined style={{ fontSize: 11 }} />
                    {new Date(wf.updatedAt).toLocaleDateString()}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                    <Popconfirm title="Delete workflow?" description="This action cannot be undone." onConfirm={(e) => handleDelete(wf.id, e as unknown as React.MouseEvent)} onCancel={(e) => e?.stopPropagation()} okText="Delete" cancelText="Cancel" okButtonProps={{ danger: true }}>
                      <button onClick={(e) => e.stopPropagation()} aria-label="Delete workflow" style={{ width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', border: 'none', borderRadius: 6, cursor: 'pointer', color: 'var(--text-tertiary)', transition: 'all 0.1s' }} onMouseEnter={(e) => { e.currentTarget.style.background = '#f8717120'; e.currentTarget.style.color = '#f87171' }} onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-tertiary)' }}>
                        <svg width="14" height="14" viewBox="0 0 12 12" fill="none"><path d="M2 3H10M4.5 3V2C4.5 1.4 4.9 1 5.5 1H6.5C7.1 1 7.5 1.4 7.5 2V3M9.5 3V10C9.5 10.6 9.1 11 8.5 11H3.5C2.9 11 2.5 10.6 2.5 10V3" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" /><path d="M5 5.5V8.5M7 5.5V8.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" /></svg>
                      </button>
                    </Popconfirm>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
