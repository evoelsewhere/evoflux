import { useState, useEffect, useCallback } from 'react'
import { Spin, message } from 'antd'

const icons = {
  plus: <svg width="20" height="20" viewBox="0 0 16 16" fill="none"><path d="M8 3V13M3 8H13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>,
  kb: <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><rect x="3" y="2" width="14" height="16" rx="2" stroke="currentColor" strokeWidth="1.3" /><path d="M6 6H14M6 9H14M6 12H10" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" /></svg>,
  trash: <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2 3H10M4.5 3V2C4.5 1.4 4.9 1 5.5 1H6.5C7.1 1 7.5 1.4 7.5 2V3M9.5 3V10C9.5 10.6 9.1 11 8.5 11H3.5C2.9 11 2.5 10.6 2.5 10V3" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" /><path d="M5 5.5V8.5M7 5.5V8.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" /></svg>,
  doc: <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><rect x="2" y="1" width="8" height="10" rx="1" stroke="currentColor" strokeWidth="1" /><path d="M4 4H8M4 6H8M4 8H6" stroke="currentColor" strokeWidth="0.8" strokeLinecap="round" /></svg>,
  chunk: <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><rect x="1" y="1" width="4" height="4" rx="1" stroke="currentColor" strokeWidth="0.8" /><rect x="7" y="1" width="4" height="4" rx="1" stroke="currentColor" strokeWidth="0.8" /><rect x="1" y="7" width="4" height="4" rx="1" stroke="currentColor" strokeWidth="0.8" /><rect x="7" y="7" width="4" height="4" rx="1" stroke="currentColor" strokeWidth="0.8" /></svg>,
}

interface KB {
  id: string
  name: string
  description: string
  stats_json: string
  created_at: number
  updated_at: number
}

interface KBListProps {
  onSelect: (kbId: string) => void
}

export default function KBList({ onSelect }: KBListProps) {
  const [kbs, setKbs] = useState<KB[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const list = await window.api.kb.list() as KB[]
      setKbs(list)
    } catch { message.error('Failed to load knowledge bases') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const handleCreate = async () => {
    try {
      const kb = await window.api.kb.create('New Knowledge Base', '') as KB
      setKbs(prev => [kb, ...prev])
      onSelect(kb.id)
    } catch { message.error('Failed to create') }
  }

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    try {
      await window.api.kb.delete(id)
      setKbs(prev => prev.filter(k => k.id !== id))
      message.success('Deleted')
    } catch { message.error('Delete failed') }
  }

  const parseStats = (statsJson: string) => {
    try { return JSON.parse(statsJson) } catch { return { totalDocs: 0, totalChunks: 0, totalSize: 0 } }
  }

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  if (loading) return <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 80 }}><Spin /></div>

  return (
    <div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <div
          role="button" tabIndex={0}
          onClick={handleCreate}
          onKeyDown={e => { if (e.key === 'Enter') handleCreate() }}
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
          <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-tertiary)' }}>New Knowledge Base</span>
        </div>

        {kbs.map(kb => {
          const stats = parseStats(kb.stats_json)
          return (
            <div
              key={kb.id}
              role="button" tabIndex={0}
              onClick={() => onSelect(kb.id)}
              onKeyDown={e => { if (e.key === 'Enter') onSelect(kb.id) }}
              style={{
                display: 'flex', alignItems: 'center', gap: 14, padding: '12px 16px',
                borderRadius: 8, cursor: 'pointer', transition: 'background 0.12s'
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              <div style={{ width: 32, height: 32, borderRadius: 8, background: 'var(--accent-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent)', flexShrink: 0 }}>
                {icons.kb}
              </div>

              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {kb.name}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 1 }}>
                  {kb.description || `${stats.totalDocs} docs · ${stats.totalChunks} chunks · ${formatSize(stats.totalSize)}`}
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 3, fontSize: 10, color: 'var(--text-tertiary)' }}>
                  {icons.doc} {stats.totalDocs}
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: 3, fontSize: 10, color: 'var(--text-tertiary)' }}>
                  {icons.chunk} {stats.totalChunks}
                </span>
              </div>

              <div style={{ fontSize: 11, color: 'var(--text-tertiary)', flexShrink: 0, minWidth: 70, textAlign: 'right' }}>
                {new Date(kb.updated_at).toLocaleDateString()}
              </div>

              <button
                onClick={e => handleDelete(e, kb.id)}
                aria-label={`Delete ${kb.name}`}
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

        {kbs.length === 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '60px 0' }}>
            <div style={{ width: 48, height: 48, borderRadius: 12, background: 'var(--accent-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 12, color: 'var(--accent)' }}>
              {icons.kb}
            </div>
            <h3 style={{ color: 'var(--text-primary)', fontSize: 14, fontWeight: 600, margin: '0 0 4px 0' }}>No knowledge bases</h3>
            <p style={{ color: 'var(--text-tertiary)', fontSize: 12, margin: 0 }}>Create one to start indexing documents</p>
          </div>
        )}
      </div>
    </div>
  )
}
