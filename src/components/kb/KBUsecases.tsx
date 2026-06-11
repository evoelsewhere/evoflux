import { useState, useEffect, useCallback } from 'react'
import { Spin, message } from 'antd'

interface UsecaseInfo {
  name: string
  description: string
  path: string
  tags: string[]
}

interface KBUsecasesProps {
  projectPath: string
  onSelect?: (name: string) => void
}

export default function KBUsecases({ projectPath, onSelect }: KBUsecasesProps) {
  const [usecases, setUsecases] = useState<UsecaseInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedName, setSelectedName] = useState<string | null>(null)
  const [selectedContent, setSelectedContent] = useState<string>('')
  const [selectedLoading, setSelectedLoading] = useState(false)

  const load = useCallback(async () => {
    if (!projectPath) { setLoading(false); return }
    try {
      const result = await window.api.usecase.list(projectPath)
      if (Array.isArray(result)) setUsecases(result)
    } catch { /* */ }
    finally { setLoading(false) }
  }, [projectPath])

  useEffect(() => { load() }, [load])

  const openUsecase = async (name: string) => {
    setSelectedName(name)
    setSelectedLoading(true)
    try {
      const def = await window.api.usecase.get(projectPath, name) as { body?: string; context_template?: string; error?: string }
      if (def.error) { message.error(def.error); return }
      setSelectedContent(def.context_template || def.body || 'No content')
    } catch { setSelectedContent('Failed to load') }
    finally { setSelectedLoading(false) }
  }

  if (loading) return <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}><Spin /></div>

  if (!projectPath) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '40px 0' }}>
        <div style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>Set a project path to view usecases</div>
      </div>
    )
  }

  if (usecases.length === 0) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '40px 0' }}>
        <svg width="40" height="40" viewBox="0 0 40 40" fill="none" style={{ marginBottom: 12 }}>
          <rect x="6" y="4" width="28" height="32" rx="4" stroke="var(--accent)" strokeWidth="2" />
          <path d="M12 12H28M12 17H28M12 22H20" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
        <h3 style={{ color: 'var(--text-primary)', fontSize: 14, fontWeight: 600, margin: '0 0 4px 0' }}>No usecases found</h3>
        <p style={{ color: 'var(--text-tertiary)', fontSize: 12, margin: 0, textAlign: 'center', maxWidth: 300 }}>
          Create .evoflux/usecases/*.md files in your project to define reusable workflow patterns.
        </p>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      {/* List */}
      <div style={{ width: 220, borderRight: '1px solid var(--border-primary)', overflow: 'auto', padding: 8 }}>
        <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-tertiary)', padding: '4px 8px', marginBottom: 4 }}>
          USECASES ({usecases.length})
        </div>
        {usecases.map(uc => (
          <button key={uc.name} onClick={() => { openUsecase(uc.name); onSelect?.(uc.name) }} style={{
            display: 'flex', flexDirection: 'column', gap: 2, width: '100%', padding: '8px 10px',
            background: selectedName === uc.name ? 'var(--accent-muted)' : 'transparent',
            border: 'none', cursor: 'pointer', textAlign: 'left', borderRadius: 6, marginBottom: 2, transition: 'background 0.1s'
          }}
            onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
            onMouseLeave={e => e.currentTarget.style.background = selectedName === uc.name ? 'var(--accent-muted)' : 'transparent'}>
            <span style={{ fontSize: 12, fontWeight: 600, color: selectedName === uc.name ? 'var(--accent)' : 'var(--text-primary)' }}>{uc.name}</span>
            {uc.description && <span style={{ fontSize: 10, color: 'var(--text-tertiary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{uc.description}</span>}
            {uc.tags.length > 0 && (
              <div style={{ display: 'flex', gap: 3, marginTop: 2, flexWrap: 'wrap' }}>
                {uc.tags.slice(0, 3).map(tag => (
                  <span key={tag} style={{ fontSize: 9, padding: '1px 5px', borderRadius: 3, background: 'var(--bg-hover)', color: 'var(--text-tertiary)' }}>{tag}</span>
                ))}
              </div>
            )}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        {selectedName ? (
          <div>
            <h3 style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 12px 0' }}>{selectedName}</h3>
            {selectedLoading ? (
              <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}><Spin size="small" /></div>
            ) : (
              <pre style={{
                fontSize: 12, color: 'var(--text-secondary)', margin: 0,
                whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'inherit',
                lineHeight: '18px', padding: 12, background: 'var(--bg-card)',
                borderRadius: 6, border: '1px solid var(--border-primary)'
              }}>
                {selectedContent}
              </pre>
            )}
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '60px 0' }}>
            <div style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>Select a usecase to view its content</div>
          </div>
        )}
      </div>
    </div>
  )
}
