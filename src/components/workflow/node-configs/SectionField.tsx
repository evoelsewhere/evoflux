import { Input } from 'antd'

const labelStyle: React.CSSProperties = { color: 'var(--text-secondary)', fontSize: 12, fontWeight: 500, marginBottom: 4 }
const inputStyle = { background: 'var(--bg-input)', borderColor: 'var(--border-primary)', fontSize: 12 }

export { labelStyle, inputStyle }

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ padding: 10, background: 'var(--bg-card)', border: '1px solid var(--border-primary)', borderRadius: 8, marginBottom: 8 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 10 }}>{title}</div>
      {children}
    </div>
  )
}

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={labelStyle}>{label}</div>
      {children}
    </div>
  )
}

export function AgentListEditor({ config, onChange }: { config: Record<string, unknown>; onChange: (f: string, v: unknown) => void }) {
  const agents = (config.agents as Record<string, unknown>[]) || []
  return (
    <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--border-primary)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)' }}>Agents</div>
        <button onClick={() => {
          const next = [...agents, { id: `agent-${agents.length + 1}`, name: `Agent ${agents.length + 1}`, role: '', goal: '', model: 'gpt-4o', provider: 'openai', tools: ['read_file', 'write_file'] }]
          onChange('agents', next)
        }} style={{ padding: '2px 8px', fontSize: 10, borderRadius: 6, cursor: 'pointer', background: 'var(--accent)', color: '#fff', border: 'none', fontWeight: 500 }}>
          + Add
        </button>
      </div>
      {agents.map((a, idx) => (
        <div key={idx} style={{ padding: 8, background: 'var(--bg-input)', border: '1px solid var(--border-primary)', borderRadius: 6, marginBottom: 6 }}>
          <div style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
            <Input size="small" value={String(a.name || '')} onChange={(e) => {
              const next = [...agents]; next[idx] = { ...next[idx], name: e.target.value }; onChange('agents', next)
            }} placeholder="Name" style={{ ...inputStyle, fontWeight: 600, flex: 1 }} />
            <button onClick={() => { const next = [...agents]; next.splice(idx, 1); onChange('agents', next) }}
              style={{ width: 22, height: 22, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--error)', fontSize: 14 }}>×</button>
          </div>
          <Input size="small" value={String(a.role || '')} onChange={(e) => {
            const next = [...agents]; next[idx] = { ...next[idx], role: e.target.value }; onChange('agents', next)
          }} placeholder="Role" style={{ ...inputStyle, marginBottom: 4 }} />
          <Input size="small" value={String(a.model || 'gpt-4o')} onChange={(e) => {
            const next = [...agents]; next[idx] = { ...next[idx], model: e.target.value }; onChange('agents', next)
          }} placeholder="Model" style={inputStyle} />
        </div>
      ))}
      {agents.length === 0 && (
        <div style={{ fontSize: 10, color: 'var(--text-tertiary)', textAlign: 'center', padding: '6px 0' }}>No agents configured.</div>
      )}
    </div>
  )
}
