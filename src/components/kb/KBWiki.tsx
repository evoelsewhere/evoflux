import { useState, useEffect, useCallback, useMemo } from 'react'
import { Spin, message } from 'antd'

interface WikiEntity { id: string; name: string; type: string; summary: string | null; description: string | null; metadata_json: string | null }
interface WikiRelationship { id: string; source_entity_id: string; target_entity_id: string; type: string; label: string | null; weight: number }
interface WikiPage { id: string; entity_id: string | null; title: string; content: string; type: string }
interface WikiGraph { entities: WikiEntity[]; relationships: WikiRelationship[] }

const ENTITY_TYPE_COLORS: Record<string, string> = {
  concept: '#60a5fa',
  api: '#34d399',
  class: '#c084fc',
  function: '#fbbf24',
  config: '#f87171',
  tool: '#2dd4bf',
  pattern: '#fb923c'
}

const ENTITY_TYPE_ICONS: Record<string, string> = {
  concept: '💡', api: '🔌', class: '📦', function: '⚡', config: '⚙️', tool: '🔧', pattern: '🔄'
}

interface KBWikiProps { kbId: string }

export default function KBWiki({ kbId }: KBWikiProps) {
  const [graph, setGraph] = useState<WikiGraph | null>(null)
  const [pages, setPages] = useState<WikiPage[]>([])
  const [loading, setLoading] = useState(true)
  const [activePage, setActivePage] = useState<WikiPage | null>(null)
  const [activeEntity, setActiveEntity] = useState<WikiEntity | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<WikiEntity[]>([])
  const [showTOC, setShowTOC] = useState(true)

  const load = useCallback(async () => {
    try {
      const [g, p] = await Promise.all([
        window.api.wiki.graph(kbId) as Promise<WikiGraph>,
        window.api.wiki.pages(kbId) as Promise<WikiPage[]>
      ])
      setGraph(g)
      setPages(p)
      const overview = p.find(pg => pg.type === 'overview')
      if (overview) setActivePage(overview)
    } catch { /* */ }
    finally { setLoading(false) }
  }, [kbId])

  useEffect(() => { load() }, [load])

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) { setSearchResults([]); return }
    const results = await window.api.wiki.search(kbId, searchQuery, 20) as WikiEntity[]
    setSearchResults(results)
  }, [kbId, searchQuery])

  const openEntityPage = useCallback((entity: WikiEntity) => {
    setActiveEntity(entity)
    const page = pages.find(p => p.entity_id === entity.id)
    setActivePage(page || null)
    setSearchResults([])
  }, [pages])

  const openPage = useCallback((page: WikiPage) => {
    setActivePage(page)
    setActiveEntity(null)
    setSearchResults([])
  }, [])

  const getEntityName = useCallback((id: string) => graph?.entities.find(e => e.id === id)?.name || id, [graph])

  const entityTypes = useMemo(() => graph ? [...new Set(graph.entities.map(e => e.type))].sort() : [], [graph])

  const entitiesByType = useMemo(() => {
    if (!graph) return {}
    const map: Record<string, WikiEntity[]> = {}
    for (const e of graph.entities) {
      if (!map[e.type]) map[e.type] = []
      map[e.type].push(e)
    }
    for (const type of Object.keys(map)) map[type].sort((a, b) => a.name.localeCompare(b.name))
    return map
  }, [graph])

  const renderMarkdown = (text: string) => {
    return text
      .replace(/^### (.*$)/gm, '<h3 style="font-size:14px;font-weight:600;color:var(--text-primary);margin:16px 0 6px 0">$1</h3>')
      .replace(/^## (.*$)/gm, '<h2 style="font-size:16px;font-weight:700;color:var(--text-primary);margin:20px 0 8px 0;padding-bottom:6px;border-bottom:1px solid var(--border-primary)">$1</h2>')
      .replace(/^# (.*$)/gm, '<h1 style="font-size:20px;font-weight:700;color:var(--text-primary);margin:0 0 12px 0">$1</h1>')
      .replace(/\*\*(.*?)\*\*/g, '<strong style="color:var(--text-primary)">$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/`(.*?)`/g, '<code style="background:var(--bg-primary);padding:1px 4px;border-radius:3px;font-size:11px;font-family:monospace">$1</code>')
      .replace(/^- (.*$)/gm, '<div style="padding-left:16px;margin:2px 0;color:var(--text-secondary)">• $1</div>')
      .replace(/^\d+\. (.*$)/gm, '<div style="padding-left:16px;margin:2px 0;color:var(--text-secondary)">$1</div>')
      .replace(/\n\n/g, '<br/><br/>')
      .replace(/\n/g, '<br/>')
  }

  if (loading) return <div style={{ display: 'flex', justifyContent: 'center', padding: 60 }}><Spin /></div>

  if (!graph || graph.entities.length === 0) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '80px 0' }}>
        <div style={{ fontSize: 40, marginBottom: 16 }}>📚</div>
        <h3 style={{ color: 'var(--text-primary)', fontSize: 16, fontWeight: 600, margin: '0 0 6px 0' }}>No wiki content yet</h3>
        <p style={{ color: 'var(--text-tertiary)', fontSize: 13, margin: 0, textAlign: 'center', maxWidth: 400 }}>
          Go to Settings → Wiki Graph, configure a provider and model, then click Build Wiki.
        </p>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      {/* Sidebar — Table of Contents */}
      {showTOC && (
        <div style={{ width: 260, borderRight: '1px solid var(--border-primary)', display: 'flex', flexDirection: 'column', overflow: 'hidden', flexShrink: 0 }}>
          {/* Search */}
          <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--border-primary)' }}>
            <input
              value={searchQuery}
              onChange={e => { setSearchQuery(e.target.value); if (e.target.value.length >= 2) handleSearch(); else setSearchResults([]) }}
              onKeyDown={e => { if (e.key === 'Enter') handleSearch(); if (e.key === 'Escape') { setSearchQuery(''); setSearchResults([]) } }}
              placeholder="Search wiki..."
              style={{ width: '100%', padding: '7px 10px', fontSize: 12, background: 'var(--bg-input)', border: '1px solid var(--border-primary)', borderRadius: 6, color: 'var(--text-primary)', outline: 'none' }}
            />
          </div>

          <div style={{ flex: 1, overflow: 'auto', padding: '8px 0' }}>
            {/* Search results */}
            {searchResults.length > 0 && (
              <div style={{ marginBottom: 8 }}>
                <div style={{ padding: '0 12px', fontSize: 10, fontWeight: 600, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>
                  Search Results ({searchResults.length})
                </div>
                {searchResults.map(entity => (
                  <button key={entity.id} onClick={() => openEntityPage(entity)} style={{
                    display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '6px 12px',
                    background: activeEntity?.id === entity.id ? 'var(--accent-muted)' : 'transparent',
                    border: 'none', cursor: 'pointer', textAlign: 'left', transition: 'background 0.1s'
                  }}
                    onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
                    onMouseLeave={e => e.currentTarget.style.background = activeEntity?.id === entity.id ? 'var(--accent-muted)' : 'transparent'}>
                    <span style={{ fontSize: 14 }}>{ENTITY_TYPE_ICONS[entity.type] || '📄'}</span>
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 500, color: activeEntity?.id === entity.id ? 'var(--accent)' : 'var(--text-primary)' }}>{entity.name}</div>
                      <div style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>{entity.type}</div>
                    </div>
                  </button>
                ))}
              </div>
            )}

            {/* Pages */}
            {pages.length > 0 && (
              <div style={{ marginBottom: 8 }}>
                <div style={{ padding: '0 12px', fontSize: 10, fontWeight: 600, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>
                  Pages
                </div>
                {pages.filter(p => p.type === 'overview').map(page => (
                  <button key={page.id} onClick={() => openPage(page)} style={{
                    display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '6px 12px',
                    background: activePage?.id === page.id && !activeEntity ? 'var(--accent-muted)' : 'transparent',
                    border: 'none', cursor: 'pointer', textAlign: 'left', transition: 'background 0.1s'
                  }}
                    onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
                    onMouseLeave={e => e.currentTarget.style.background = activePage?.id === page.id && !activeEntity ? 'var(--accent-muted)' : 'transparent'}>
                    <span style={{ fontSize: 14 }}>📋</span>
                    <div style={{ fontSize: 12, fontWeight: 500, color: activePage?.id === page.id && !activeEntity ? 'var(--accent)' : 'var(--text-primary)' }}>{page.title}</div>
                  </button>
                ))}
              </div>
            )}

            {/* Entity types */}
            {entityTypes.map(type => (
              <div key={type} style={{ marginBottom: 4 }}>
                <div style={{
                  padding: '5px 12px', fontSize: 10, fontWeight: 600, color: ENTITY_TYPE_COLORS[type] || 'var(--text-tertiary)',
                  textTransform: 'uppercase', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: 4
                }}>
                  <span>{ENTITY_TYPE_ICONS[type] || '📄'}</span>
                  {type}s
                  <span style={{ fontSize: 9, color: 'var(--text-tertiary)', marginLeft: 'auto' }}>{entitiesByType[type]?.length || 0}</span>
                </div>
                {(entitiesByType[type] || []).map(entity => (
                  <button key={entity.id} onClick={() => openEntityPage(entity)} style={{
                    display: 'flex', alignItems: 'center', gap: 6, width: '100%', padding: '4px 12px 4px 24px',
                    background: activeEntity?.id === entity.id ? 'var(--accent-muted)' : 'transparent',
                    border: 'none', cursor: 'pointer', textAlign: 'left', transition: 'background 0.1s'
                  }}
                    onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
                    onMouseLeave={e => e.currentTarget.style.background = activeEntity?.id === entity.id ? 'var(--accent-muted)' : 'transparent'}>
                    <span style={{ fontSize: 11, color: activeEntity?.id === entity.id ? 'var(--accent)' : 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {entity.name}
                    </span>
                  </button>
                ))}
              </div>
            ))}
          </div>

          <div style={{ padding: '8px 12px', borderTop: '1px solid var(--border-primary)', fontSize: 10, color: 'var(--text-tertiary)', display: 'flex', justifyContent: 'space-between' }}>
            <span>{graph.entities.length} entities</span>
            <span>{graph.relationships.length} relations</span>
          </div>
        </div>
      )}

      {/* Content area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Toolbar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 16px', borderBottom: '1px solid var(--border-primary)', flexShrink: 0 }}>
          <button onClick={() => setShowTOC(!showTOC)} style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)', fontSize: 14, padding: '2px 4px' }}>
            {showTOC ? '◀' : '▶'}
          </button>
          {activeEntity && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontSize: 14 }}>{ENTITY_TYPE_ICONS[activeEntity.type] || '📄'}</span>
              <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{activeEntity.name}</span>
              <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3, background: (ENTITY_TYPE_COLORS[activeEntity.type] || '#666') + '20', color: ENTITY_TYPE_COLORS[activeEntity.type] || '#666', fontWeight: 500 }}>{activeEntity.type}</span>
            </div>
          )}
          {activePage && !activeEntity && (
            <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{activePage.title}</span>
          )}
        </div>

        {/* Content */}
        <div style={{ flex: 1, overflow: 'auto', padding: '24px 32px' }}>
          {activeEntity ? (
            <div>
              {/* Entity header */}
              <div style={{ marginBottom: 20 }}>
                <h1 style={{ fontSize: 24, fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 4px 0' }}>{activeEntity.name}</h1>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, background: (ENTITY_TYPE_COLORS[activeEntity.type] || '#666') + '20', color: ENTITY_TYPE_COLORS[activeEntity.type] || '#666', fontWeight: 600, textTransform: 'capitalize' }}>{activeEntity.type}</span>
                </div>
              </div>

              {/* Summary */}
              {activeEntity.summary && (
                <div style={{ marginBottom: 20, padding: '12px 16px', background: 'var(--bg-card)', borderRadius: 8, border: '1px solid var(--border-primary)' }}>
                  <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: '20px' }}>{activeEntity.summary}</div>
                </div>
              )}

              {/* Description */}
              {activeEntity.description && (
                <div style={{ marginBottom: 20 }}>
                  <h2 style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)', margin: '0 0 8px 0', paddingBottom: 6, borderBottom: '1px solid var(--border-primary)' }}>Details</h2>
                  <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: '20px' }}>{activeEntity.description}</div>
                </div>
              )}

              {/* Relationships */}
              {graph && (() => {
                const rels = graph.relationships.filter(r => r.source_entity_id === activeEntity.id || r.target_entity_id === activeEntity.id)
                if (rels.length === 0) return null
                return (
                  <div style={{ marginBottom: 20 }}>
                    <h2 style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)', margin: '0 0 8px 0', paddingBottom: 6, borderBottom: '1px solid var(--border-primary)' }}>
                      Relationships ({rels.length})
                    </h2>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                      {rels.map(rel => {
                        const isSource = rel.source_entity_id === activeEntity.id
                        const otherName = getEntityName(isSource ? rel.target_entity_id : rel.source_entity_id)
                        const otherEntity = graph.entities.find(e => e.id === (isSource ? rel.target_entity_id : rel.source_entity_id))
                        return (
                          <button key={rel.id} onClick={() => otherEntity && openEntityPage(otherEntity)} style={{
                            display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
                            background: 'var(--bg-card)', border: '1px solid var(--border-primary)', borderRadius: 6,
                            cursor: 'pointer', textAlign: 'left', transition: 'all 0.15s', width: '100%'
                          }}
                            onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--accent)'; e.currentTarget.style.background = 'var(--bg-hover)' }}
                            onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border-primary)'; e.currentTarget.style.background = 'var(--bg-card)' }}>
                            <span style={{ fontSize: 14 }}>{ENTITY_TYPE_ICONS[otherEntity?.type || ''] || '📄'}</span>
                            <div style={{ flex: 1 }}>
                              <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-primary)' }}>{otherName}</div>
                              <div style={{ fontSize: 10, color: 'var(--accent)' }}>{isSource ? '→' : '←'} {rel.type}</div>
                            </div>
                            {rel.label && <span style={{ fontSize: 10, color: 'var(--text-tertiary)', maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{rel.label}</span>}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                )
              })()}

              {/* Wiki page */}
              {activePage && (
                <div>
                  <h2 style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)', margin: '0 0 8px 0', paddingBottom: 6, borderBottom: '1px solid var(--border-primary)' }}>Wiki Page</h2>
                  <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: '20px' }} dangerouslySetInnerHTML={{ __html: renderMarkdown(activePage.content) }} />
                </div>
              )}
            </div>
          ) : activePage ? (
            <div>
              <h1 style={{ fontSize: 24, fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 16px 0' }}>{activePage.title}</h1>
              <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: '20px' }} dangerouslySetInnerHTML={{ __html: renderMarkdown(activePage.content) }} />
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '80px 0' }}>
              <div style={{ fontSize: 40, marginBottom: 16 }}>📚</div>
              <h3 style={{ color: 'var(--text-primary)', fontSize: 16, fontWeight: 600, margin: '0 0 6px 0' }}>Welcome to the Wiki</h3>
              <p style={{ color: 'var(--text-tertiary)', fontSize: 13, margin: 0 }}>Select an entity or page from the sidebar to get started.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
