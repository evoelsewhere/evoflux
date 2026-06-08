import { useEffect, useState } from 'react'
import { Button, Input, Spin, message, Modal } from 'antd'
import { useNavigate, useLocation } from 'react-router-dom'
import { nanoid } from 'nanoid'
import { useProviderStore } from '../../stores/providerStore'

const icons = {
  plus: <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 3V13M3 8H13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>,
  import: <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7 2V9M7 9L4.5 6.5M7 9L9.5 6.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" /><path d="M2 10V11.5C2 12.1 2.4 12.5 3 12.5H11C11.6 12.5 12 12.1 12 11.5V10" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" /></svg>,
  clock: <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><circle cx="5" cy="5" r="4" stroke="currentColor" strokeWidth="1.2" /><path d="M5 3V5.5L6.5 6.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" /></svg>,
  workflow: <svg width="18" height="18" viewBox="0 0 18 18" fill="none"><circle cx="5" cy="5" r="2.5" stroke="currentColor" strokeWidth="1.3" /><circle cx="13" cy="5" r="2.5" stroke="currentColor" strokeWidth="1.3" /><circle cx="9" cy="13" r="2.5" stroke="currentColor" strokeWidth="1.3" /><path d="M5 7.5V9.5L9 11" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" /><path d="M13 7.5V9.5L9 11" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" /></svg>,
  nodes: <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><rect x="1" y="1" width="5" height="5" rx="1" stroke="currentColor" strokeWidth="1.2" /><rect x="8" y="8" width="5" height="5" rx="1" stroke="currentColor" strokeWidth="1.2" /><path d="M6 3.5H8M3.5 6V8" stroke="currentColor" strokeWidth="1" strokeLinecap="round" /></svg>,
  edges: <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2 7H12" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" /><path d="M9 4L12 7L9 10" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" /></svg>,
  provider: <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="5.5" stroke="currentColor" strokeWidth="1.2" /><path d="M7 1.5V7H12.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" /><circle cx="7" cy="7" r="1.5" fill="currentColor" /></svg>,
  trash: <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2 3H10M4.5 3V2C4.5 1.4 4.9 1 5.5 1H6.5C7.1 1 7.5 1.4 7.5 2V3M9.5 3V10C9.5 10.6 9.1 11 8.5 11H3.5C2.9 11 2.5 10.6 2.5 10V3" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" /><path d="M5 5.5V8.5M7 5.5V8.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" /></svg>,
}

interface WorkflowSummary { id: string; name: string; description: string; updatedAt: string; nodes?: unknown[]; edges?: unknown[] }

const TEMPLATES = [
  { id: 'code-review', name: 'Code Review Pipeline', description: 'File Explorer → Context Loader → LLM → Condition', icon: '🔍', nodes: 6 },
  { id: 'coding-agent', name: 'ReAct Coding Agent', description: 'Start → ReAct Agent → End', icon: '🤖', nodes: 3 },
  { id: 'full-sdlc', name: 'Full SDLC Pipeline', description: 'Requirements → Design → Code → Test → Docs', icon: '🔄', nodes: 8 },
  { id: 'team-orchestrator', name: 'Agent Team', description: 'Supervisor + Architect + Dev + Tester', icon: '👥', nodes: 4 }
]

export default function Dashboard() {
  const navigate = useNavigate()
  const location = useLocation()
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [showTemplates, setShowTemplates] = useState(false)
  const { providers } = useProviderStore()

  useEffect(() => { loadWorkflows() }, [location.pathname])

  const loadWorkflows = async () => {
    try { setWorkflows((await window.api.workflow.list()) as WorkflowSummary[]) }
    catch { message.error('Failed to load') }
    finally { setLoading(false) }
  }

  const handleCreate = () => navigate(`/workflows/${nanoid(10)}`)
  const handleCreateFromTemplate = (tid: string) => { setShowTemplates(false); navigate(`/workflows/${nanoid(10)}?template=${tid}`) }

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    try { await window.api.workflow.delete(id); setWorkflows(prev => prev.filter(w => w.id !== id)) }
    catch { message.error('Delete failed') }
  }

  const handleImport = async () => {
    try {
      const result = await window.api.dsl.import()
      if (result.success && result.dsl) {
        const dsl = result.dsl as { name?: string }
        const id = nanoid(10)
        await window.api.workflow.save({ id, name: dsl.name || 'Imported', ...result.dsl })
        navigate(`/workflows/${id}`)
      }
    } catch { message.error('Import failed') }
  }

  const filtered = workflows.filter(w => !search || w.name.toLowerCase().includes(search.toLowerCase()))
  const totalNodes = workflows.reduce((sum, w) => sum + ((w.nodes as unknown[])?.length || 0), 0)
  const totalEdges = workflows.reduce((sum, w) => sum + ((w.edges as unknown[])?.length || 0), 0)

  return (
    <div style={{ height: '100vh', overflow: 'auto', background: 'var(--bg-primary)' }}>
      <div style={{ maxWidth: 960, margin: '0 auto', padding: '40px 32px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 36 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>Evoflux</div>
            <h1 style={{ fontSize: 28, fontWeight: 700, color: 'var(--text-primary)', margin: 0, letterSpacing: '-0.03em', lineHeight: 1.1 }}>Workflows</h1>
            <p style={{ color: 'var(--text-tertiary)', fontSize: 13, margin: '6px 0 0 0' }}>
              {workflows.length} workflow{workflows.length !== 1 ? 's' : ''} &middot; {totalNodes} nodes &middot; {totalEdges} edges
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button icon={icons.import} onClick={handleImport} style={{ height: 34, fontSize: 12 }}>Import</Button>
            <Button onClick={() => setShowTemplates(true)} style={{ height: 34, fontSize: 12 }}>Templates</Button>
            <Button type="primary" icon={icons.plus} onClick={handleCreate} style={{ height: 34, fontSize: 12, fontWeight: 600 }}>New Workflow</Button>
          </div>
        </div>

        <Input
          placeholder="Search workflows..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ marginBottom: 20, height: 40, fontSize: 13, background: 'var(--bg-elevated)', borderColor: 'var(--border-primary)', borderRadius: 8 }}
          allowClear
        />

        {loading ? (
          <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 120 }}><Spin /></div>
        ) : filtered.length === 0 ? (
          <div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            padding: '80px 0', borderRadius: 12
          }}>
            <div style={{ width: 56, height: 56, borderRadius: 14, background: 'var(--accent-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 16 }}>
              {icons.workflow}
            </div>
            <h3 style={{ color: 'var(--text-primary)', fontSize: 16, fontWeight: 600, margin: '0 0 4px 0' }}>{search ? 'No results' : 'No workflows yet'}</h3>
            <p style={{ color: 'var(--text-tertiary)', fontSize: 13, margin: '0 0 20px 0' }}>{search ? 'Try a different search' : 'Create your first workflow to get started'}</p>
            {!search && (
              <div style={{ display: 'flex', gap: 8 }}>
                <Button type="primary" icon={icons.plus} onClick={handleCreate} style={{ height: 34, fontSize: 12 }}>Create Workflow</Button>
                <Button onClick={() => setShowTemplates(true)} style={{ height: 34, fontSize: 12 }}>Browse Templates</Button>
              </div>
            )}
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <div
              role="button"
              tabIndex={0}
              onClick={handleCreate}
              onKeyDown={(e) => { if (e.key === 'Enter') handleCreate() }}
              style={{
                display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px',
                borderRadius: 8, cursor: 'pointer', transition: 'background 0.12s',
                border: '1px dashed var(--border-secondary)', marginBottom: 4
              }}
              onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-hover)'; e.currentTarget.style.borderColor = 'var(--accent)' }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.borderColor = 'var(--border-secondary)' }}
            >
              <div style={{ width: 32, height: 32, borderRadius: 8, background: 'var(--accent-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent)' }}>
                {icons.plus}
              </div>
              <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-tertiary)' }}>New Workflow</span>
            </div>

            {filtered.map((wf) => {
              const nodeCount = (wf.nodes as unknown[])?.length || 0
              const edgeCount = (wf.edges as unknown[])?.length || 0
              const categories = [...new Set(((wf.nodes as Array<{ data?: { category?: string } }>) || []).map(n => n.data?.category).filter(Boolean))]
              const categoryColors: Record<string, string> = { trigger: '#34d399', ai: '#60a5fa', logic: '#fbbf24', tools: '#2dd4bf', agent: '#c084fc' }
              return (
                <div
                  key={wf.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => navigate(`/workflows/${wf.id}`)}
                  onKeyDown={(e) => { if (e.key === 'Enter') navigate(`/workflows/${wf.id}`) }}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 14, padding: '12px 16px',
                    borderRadius: 8, cursor: 'pointer', transition: 'background 0.12s'
                  }}
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  <div style={{ width: 32, height: 32, borderRadius: 8, background: 'var(--accent-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent)', flexShrink: 0 }}>
                    {icons.workflow}
                  </div>

                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {wf.name}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {wf.description || `${nodeCount} nodes · ${edgeCount} edges`}
                    </div>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
                    {categories.slice(0, 3).map(cat => (
                      <div key={cat} style={{ width: 6, height: 6, borderRadius: '50%', background: (categoryColors as Record<string, string>)[cat!] || '#666' }} />
                    ))}
                  </div>

                  <div style={{ fontSize: 11, color: 'var(--text-tertiary)', flexShrink: 0, minWidth: 70, textAlign: 'right' }}>
                    {new Date(wf.updatedAt).toLocaleDateString()}
                  </div>

                  <button
                    onClick={(e) => handleDelete(e, wf.id)}
                    aria-label={`Delete ${wf.name}`}
                    style={{
                      width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center',
                      background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)',
                      borderRadius: 6, flexShrink: 0, transition: 'all 0.12s', opacity: 0
                    }}
                    onMouseEnter={e => { e.currentTarget.style.opacity = '1'; e.currentTarget.style.color = 'var(--error)'; e.currentTarget.style.background = 'var(--error-muted)' }}
                    onMouseLeave={e => { e.currentTarget.style.opacity = '0'; e.currentTarget.style.color = 'var(--text-tertiary)'; e.currentTarget.style.background = 'transparent' }}
                  >
                    {icons.trash}
                  </button>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <Modal title="Template Gallery" open={showTemplates} onCancel={() => setShowTemplates(false)} footer={null} width={540}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, paddingTop: 12 }}>
          {TEMPLATES.map((tpl) => (
            <button
              key={tpl.id}
              onClick={() => handleCreateFromTemplate(tpl.id)}
              style={{
                display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 6,
                padding: 14, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)',
                borderRadius: 8, cursor: 'pointer', transition: 'all 0.15s', textAlign: 'left'
              }}
              onMouseEnter={e => e.currentTarget.style.borderColor = 'var(--accent)'}
              onMouseLeave={e => e.currentTarget.style.borderColor = 'var(--border-primary)'}
            >
              <div style={{ fontSize: 22 }}>{tpl.icon}</div>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>{tpl.name}</div>
              <div style={{ fontSize: 11, color: 'var(--text-tertiary)', lineHeight: '16px' }}>{tpl.description}</div>
              <span style={{ fontSize: 10, color: 'var(--accent)', fontWeight: 500 }}>{tpl.nodes} nodes</span>
            </button>
          ))}
        </div>
      </Modal>
    </div>
  )
}
