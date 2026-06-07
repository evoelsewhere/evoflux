import { useState, useEffect } from 'react'
import { Input, Button } from 'antd'
import { SearchOutlined, DatabaseOutlined } from '@ant-design/icons'

interface MemoryStats {
  semanticCount: number
  episodicCount: number
  proceduralCount: number
  edgeCount: number
}

interface MemoryInspectorProps {
  workflowId: string
  isOpen: boolean
  onClose: () => void
}

export default function MemoryInspector({ workflowId, isOpen, onClose }: MemoryInspectorProps) {
  const [stats, setStats] = useState<MemoryStats | null>(null)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<unknown[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (isOpen && workflowId) loadStats()
  }, [isOpen, workflowId])

  const loadStats = async () => {
    try {
      const res = await window.api.memory.stats(workflowId)
      if (res.success) setStats(res.stats as MemoryStats)
    } catch { /* ignore */ }
  }

  const handleSearch = async () => {
    if (!query.trim()) return
    setLoading(true)
    try {
      const res = await window.api.memory.search(workflowId, query, { k: 10, layer: 'all' })
      if (res.success) setResults(res.results || [])
    } catch { setResults([]) }
    finally { setLoading(false) }
  }

  if (!isOpen) return null

  return (
    <div style={{
      position: 'absolute', top: 0, right: 0, width: 320, height: '100%',
      background: 'var(--bg-secondary)', borderLeft: '1px solid var(--border-primary)',
      display: 'flex', flexDirection: 'column', zIndex: 10
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 12px', borderBottom: '1px solid var(--border-primary)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <DatabaseOutlined style={{ color: 'var(--accent)', fontSize: 13 }} />
          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>Memory Inspector</span>
        </div>
        <button onClick={onClose} style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)', fontSize: 16 }}>×</button>
      </div>

      {stats && (
        <div style={{ padding: 12, borderBottom: '1px solid var(--border-primary)' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <StatCard label="Semantic" count={stats.semanticCount} color="var(--accent)" />
            <StatCard label="Episodic" count={stats.episodicCount} color="var(--success)" />
            <StatCard label="Procedural" count={stats.proceduralCount} color="var(--purple)" />
            <StatCard label="Edges" count={stats.edgeCount} color="var(--warning)" />
          </div>
        </div>
      )}

      <div style={{ padding: 12, borderBottom: '1px solid var(--border-primary)' }}>
        <Input
          prefix={<SearchOutlined style={{ color: 'var(--text-tertiary)', fontSize: 11 }} />}
          placeholder="Search memory..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onPressEnter={handleSearch}
          size="small"
          suffix={
            <Button size="small" type="text" onClick={handleSearch} loading={loading}>
              Search
            </Button>
          }
        />
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: 12 }}>
        {results.length === 0 ? (
          <div style={{ color: 'var(--text-tertiary)', fontSize: 12, textAlign: 'center', padding: '20px 0' }}>
            {query ? 'No results found' : 'Search to query memory'}
          </div>
        ) : (
          (results as Array<Record<string, unknown>>).map((r, i) => (
            <div key={i} style={{
              padding: 8, marginBottom: 6,
              background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)',
              borderRadius: 6, fontSize: 11
            }}>
              <div style={{ display: 'flex', gap: 6, marginBottom: 4 }}>
                <span style={{
                  color: r.type === 'semantic' ? 'var(--accent)' : r.type === 'episodic' ? 'var(--success)' : 'var(--purple)',
                  fontWeight: 600, fontSize: 10, textTransform: 'uppercase'
                }}>
                  {String(r.type)}
                </span>
                {r.score !== undefined && (
                  <span style={{ color: 'var(--text-tertiary)', fontSize: 10 }}>
                    score: {Number(r.score).toFixed(2)}
                  </span>
                )}
              </div>
              <div style={{ color: 'var(--text-secondary)', wordBreak: 'break-all' }}>
                {String(r.content || r.task_description || r.name || '').substring(0, 200)}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

function StatCard({ label, count, color }: { label: string; count: number; color: string }) {
  return (
    <div style={{
      padding: '8px 10px', background: 'var(--bg-elevated)',
      border: '1px solid var(--border-primary)', borderRadius: 6
    }}>
      <div style={{ fontSize: 16, fontWeight: 700, color }}>{count}</div>
      <div style={{ fontSize: 10, color: 'var(--text-tertiary)', fontWeight: 500 }}>{label}</div>
    </div>
  )
}
