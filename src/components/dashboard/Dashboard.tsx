import { useEffect, useState } from 'react'
import { Button, Input, Tag, Spin, message, Modal } from 'antd'
import { useNavigate } from 'react-router-dom'
import { nanoid } from 'nanoid'
import { useProviderStore } from '../../stores/providerStore'
import { useSettingsStore } from '../../stores/settingsStore'

const icons = {
  plus: <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7 2V12M2 7H12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>,
  import: <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7 2V9M7 9L4.5 6.5M7 9L9.5 6.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" /><path d="M2 10V11.5C2 12.1 2.4 12.5 3 12.5H11C11.6 12.5 12 12.1 12 11.5V10" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" /></svg>,
  clock: <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><circle cx="5" cy="5" r="4" stroke="currentColor" strokeWidth="1.2" /><path d="M5 3V5.5L6.5 6.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" /></svg>,
  branch: (color: string) => <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><circle cx="4" cy="4" r="2" stroke={color} strokeWidth="1.3" /><circle cx="12" cy="4" r="2" stroke={color} strokeWidth="1.3" /><circle cx="8" cy="12" r="2" stroke={color} strokeWidth="1.3" /><path d="M4 6V8L8 10" stroke={color} strokeWidth="1.2" strokeLinecap="round" /><path d="M12 6V8L8 10" stroke={color} strokeWidth="1.2" strokeLinecap="round" /></svg>,
  nodes: <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><rect x="1" y="1" width="5" height="5" rx="1" stroke="currentColor" strokeWidth="1.2" /><rect x="8" y="8" width="5" height="5" rx="1" stroke="currentColor" strokeWidth="1.2" /><path d="M6 3.5H8M3.5 6V8" stroke="currentColor" strokeWidth="1" strokeLinecap="round" /></svg>,
  provider: <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="5.5" stroke="currentColor" strokeWidth="1.2" /><path d="M7 1.5V7H12.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" /><circle cx="7" cy="7" r="1.5" fill="currentColor" /></svg>,
  edges: <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2 7H12" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" /><path d="M9 4L12 7L9 10" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" /></svg>,
  settings: <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="2" stroke="currentColor" strokeWidth="1.2" /><path d="M7 1V2.5M7 11.5V13M1 7H2.5M11.5 7H13M2.9 2.9L4 4M10 10L11.1 11.1M11.1 2.9L10 4M4 10L2.9 11.1" stroke="currentColor" strokeWidth="1" strokeLinecap="round" /></svg>
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
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [showTemplates, setShowTemplates] = useState(false)
  const { providers } = useProviderStore()
  const toggleSettings = useSettingsStore(s => s.toggleSettings)

  useEffect(() => { loadWorkflows() }, [])

  const loadWorkflows = async () => {
    try { setWorkflows((await window.api.workflow.list()) as WorkflowSummary[]) }
    catch { message.error('Failed to load') }
    finally { setLoading(false) }
  }

  const handleCreate = () => navigate(`/workflows/${nanoid(10)}`)
  const handleCreateFromTemplate = (tid: string) => { setShowTemplates(false); navigate(`/workflows/${nanoid(10)}?template=${tid}`) }

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
  const activeProviders = providers.filter(p => p.apiKey || p.type === 'ollama' || p.type === 'claude-cli' || p.type === 'copilot-cli').length

  const statCard = (label: string, value: string | number, icon: React.ReactNode, color: string) => (
    <div style={{
      flex: 1, minWidth: 140, padding: '14px 16px',
      background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 10,
      display: 'flex', alignItems: 'center', gap: 12
    }}>
      <div style={{ width: 34, height: 34, borderRadius: 8, background: `${color}15`, display: 'flex', alignItems: 'center', justifyContent: 'center', color, flexShrink: 0 }}>
        {icon}
      </div>
      <div>
        <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1 }}>{value}</div>
        <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 2 }}>{label}</div>
      </div>
    </div>
  )

  return (
    <div style={{ height: 'calc(100vh - 48px)', overflow: 'auto', padding: '28px 36px' }}>
      <div style={{ maxWidth: 1200, margin: '0 auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <div>
            <h1 style={{ fontSize: 24, fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 4px 0', letterSpacing: '-0.02em' }}>Dashboard</h1>
            <p style={{ color: 'var(--text-tertiary)', fontSize: 13, margin: 0 }}>AI Automation Workflow for SDLC</p>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <Button icon={icons.import} onClick={handleImport} style={{ height: 34, fontSize: 12 }}>Import</Button>
            <Button onClick={() => setShowTemplates(true)} style={{ height: 34, fontSize: 12 }}>Templates</Button>
            <Button type="primary" icon={icons.plus} onClick={handleCreate} style={{ height: 34, fontSize: 12 }}>New Workflow</Button>
          </div>
        </div>

        {!loading && (
          <div style={{ display: 'flex', gap: 12, marginBottom: 24, flexWrap: 'wrap' }}>
            {statCard('Workflows', workflows.length, icons.branch('var(--accent)'), 'var(--accent)')}
            {statCard('Total Nodes', totalNodes, icons.nodes, '#fbbf24')}
            {statCard('Total Edges', totalEdges, icons.edges, '#34d399')}
            {statCard('AI Providers', activeProviders, icons.provider, '#c084fc')}
          </div>
        )}

        <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
          <Input placeholder="Search workflows..." value={search} onChange={(e) => setSearch(e.target.value)} style={{ flex: 1, height: 38, fontSize: 13 }} allowClear />
            <Button icon={icons.settings} onClick={toggleSettings} style={{ height: 38, fontSize: 12 }}>Settings</Button>
        </div>

        {loading ? (
          <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 100 }}><Spin /></div>
        ) : filtered.length === 0 ? (
          <div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            padding: '60px 0', background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 10
          }}>
            <div style={{ width: 48, height: 48, borderRadius: 12, background: 'var(--accent-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 14 }}>
              {icons.branch('var(--accent)')}
            </div>
            <h3 style={{ color: 'var(--text-primary)', fontSize: 15, fontWeight: 600, margin: '0 0 4px 0' }}>{search ? 'No results' : 'No workflows yet'}</h3>
            <p style={{ color: 'var(--text-tertiary)', fontSize: 12, margin: '0 0 16px 0' }}>{search ? 'Try different search' : 'Create your first workflow'}</p>
            {!search && <Button type="primary" icon={icons.plus} onClick={handleCreate} style={{ height: 32, fontSize: 12 }}>Create</Button>}
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
            <button
              onClick={handleCreate}
              aria-label="Create new workflow"
              style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                minHeight: 140, background: 'transparent', border: '1.5px dashed var(--border-secondary)',
                borderRadius: 10, cursor: 'pointer', transition: 'all 0.15s', color: 'var(--text-tertiary)', padding: 20
              }}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--accent)'; e.currentTarget.style.color = 'var(--accent)' }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--border-secondary)'; e.currentTarget.style.color = 'var(--text-tertiary)' }}
            >
              {icons.plus} <span style={{ fontSize: 12, fontWeight: 500, marginTop: 6 }}>New Workflow</span>
            </button>

            {filtered.map((wf) => {
              const nodeCount = (wf.nodes as unknown[])?.length || 0
              const edgeCount = (wf.edges as unknown[])?.length || 0
              const categories = new Set(((wf.nodes as Array<{ data?: { category?: string } }>) || []).map(n => n.data?.category).filter(Boolean))
              return (
                <div
                  key={wf.id}
                  role="button"
                  tabIndex={0}
                  aria-label={`Open workflow: ${wf.name}`}
                  onClick={() => navigate(`/workflows/${wf.id}`)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate(`/workflows/${wf.id}`) } }}
                  style={{
                    padding: 16, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)',
                    borderRadius: 10, cursor: 'pointer', transition: 'all 0.15s',
                    display: 'flex', flexDirection: 'column', gap: 10
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--border-secondary)'; e.currentTarget.style.transform = 'translateY(-1px)' }}
                  onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--border-primary)'; e.currentTarget.style.transform = 'translateY(0)' }}
                >
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
                    <div style={{ width: 32, height: 32, borderRadius: 8, background: 'var(--accent-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      {icons.branch('var(--accent)')}
                    </div>
                    <Tag style={{ color: 'var(--text-tertiary)', background: 'var(--bg-hover)', border: 'none', margin: 0, fontSize: 10 }}>draft</Tag>
                  </div>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 2 }}>{wf.name}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-tertiary)', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                      {wf.description || 'No description'}
                    </div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 10, color: 'var(--text-tertiary)', marginTop: 'auto', flexWrap: 'wrap' }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>{icons.clock} {new Date(wf.updatedAt).toLocaleDateString()}</span>
                    <span>·</span>
                    <span>{nodeCount} nodes</span>
                    <span>·</span>
                    <span>{edgeCount} edges</span>
                    {categories.size > 0 && (
                      <>
                        <span>·</span>
                        <span>{categories.size} types</span>
                      </>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <Modal title="Template Gallery" open={showTemplates} onCancel={() => setShowTemplates(false)} footer={null} width={580}>
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
              onMouseEnter={(e) => e.currentTarget.style.borderColor = 'var(--accent)'}
              onMouseLeave={(e) => e.currentTarget.style.borderColor = 'var(--border-primary)'}
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
