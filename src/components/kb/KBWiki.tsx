import { useState, useEffect, useCallback } from 'react'
import { Spin, message } from 'antd'

const icons = {
  wiki: <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="5.5" stroke="currentColor" strokeWidth="1.2" /><path d="M4 6C4 6 5 4 7 4C9 4 10 6 10 6" stroke="currentColor" strokeWidth="1" strokeLinecap="round" /><circle cx="5" cy="5.5" r="0.8" fill="currentColor" /><circle cx="9" cy="5.5" r="0.8" fill="currentColor" /><path d="M5 9C5 9 6 10 7 10C8 10 9 9 9 9" stroke="currentColor" strokeWidth="1" strokeLinecap="round" /></svg>,
  search: <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><circle cx="5" cy="5" r="3.5" stroke="currentColor" strokeWidth="1.2" /><path d="M8 8L11 11" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" /></svg>,
  chevRight: <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M4 2L7 5L4 8" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" /></svg>,
  back: <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M8 2L3 6L8 10" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" /></svg>,
}

interface WikiEntity { id: string; name: string; type: string; summary: string | null; metadata_json: string | null }
interface WikiRelationship { id: string; source_entity_id: string; target_entity_id: string; type: string; label: string | null; weight: number }
interface WikiPage { id: string; entity_id: string | null; title: string; content: string; type: string }
interface WikiGraph { entities: WikiEntity[]; relationships: WikiRelationship[] }

interface KBWikiProps {
  kbId: string
}

export default function KBWiki({ kbId }: KBWikiProps) {
  const [graph, setGraph] = useState<WikiGraph | null>(null)
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<WikiEntity[]>([])
  const [selectedEntity, setSelectedEntity] = useState<WikiEntity | null>(null)
  const [entityRels, setEntityRels] = useState<WikiRelationship[]>([])
  const [entityPage, setEntityPage] = useState<WikiPage | null>(null)
  const [overviewPage, setOverviewPage] = useState<WikiPage | null>(null)
  const [entityLoading, setEntityLoading] = useState(false)
  const [activeType, setActiveType] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [g, overview] = await Promise.all([
        window.api.wiki.graph(kbId) as Promise<WikiGraph>,
        window.api.wiki.overview(kbId) as Promise<WikiPage | null>
      ])
      setGraph(g)
      setOverviewPage(overview)
    } catch { /* */ }
    finally { setLoading(false) }
  }, [kbId])

  useEffect(() => { load() }, [load])

  const handleSearch = async () => {
    if (!searchQuery.trim()) { setSearchResults([]); return }
    const results = await window.api.wiki.search(kbId, searchQuery, 20) as WikiEntity[]
    setSearchResults(results)
  }

  const openEntity = async (entity: WikiEntity) => {
    setSelectedEntity(entity)
    setEntityLoading(true)
    try {
      const [rels, page] = await Promise.all([
        window.api.wiki.entityRelationships(entity.id) as Promise<WikiRelationship[]>,
        window.api.wiki.pageByEntity(entity.id) as Promise<WikiPage | null>
      ])
      setEntityRels(rels)
      setEntityPage(page)
    } catch { setEntityRels([]); setEntityPage(null) }
    finally { setEntityLoading(false) }
  }

  const getEntityName = (id: string) => graph?.entities.find(e => e.id === id)?.name || id

  const entityTypes = graph ? [...new Set(graph.entities.map(e => e.type))].sort() : []
  const filteredEntities = graph ? (
    activeType ? graph.entities.filter(e => e.type === activeType) : graph.entities
  ).sort((a, b) => a.name.localeCompare(b.name)) : []

  if (loading) return <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}><Spin /></div>

  if (!graph || graph.entities.length === 0) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '60px 0' }}>
        <div style={{ width: 48, height: 48, borderRadius: 12, background: 'var(--accent-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 12, color: 'var(--accent)' }}>
          {icons.wiki}
        </div>
        <h3 style={{ color: 'var(--text-primary)', fontSize: 14, fontWeight: 600, margin: '0 0 4px 0' }}>Wiki not built yet</h3>
        <p style={{ color: 'var(--text-tertiary)', fontSize: 12, margin: 0, textAlign: 'center' }}>
          Enable Wiki in Settings tab and click Build Wiki to generate a knowledge graph.
        </p>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      {/* Left sidebar */}
      <div style={{ width: 220, borderRight: '1px solid var(--border-primary)', display: 'flex', flexDirection: 'column', overflow: 'hidden', flexShrink: 0 }}>
        <div style={{ padding: '8px 10px', borderBottom: '1px solid var(--border-primary)' }}>
          <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
            <input
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleSearch() }}
              placeholder="Search entities..."
              style={{ flex: 1, padding: '5px 8px', fontSize: 11, background: 'var(--bg-input)', border: '1px solid var(--border-primary)', borderRadius: 4, color: 'var(--text-primary)', outline: 'none' }}
            />
            <button onClick={handleSearch} style={{ padding: '5px 8px', background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)', display: 'flex' }}>
              {icons.search}
            </button>
          </div>
        </div>

        <div style={{ flex: 1, overflow: 'auto', padding: 6 }}>
          {/* Overview link */}
          {overviewPage && (
            <div
              onClick={() => { setSelectedEntity(null); setEntityPage(overviewPage) }}
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 8px', borderRadius: 4, cursor: 'pointer', fontSize: 12, color: 'var(--accent)', fontWeight: 500, marginBottom: 4 }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              {icons.wiki}
              <span>Overview</span>
            </div>
          )}

          {/* Type filters */}
          {entityTypes.map(type => (
            <div key={type}>
              <div
                onClick={() => setActiveType(activeType === type ? null : type)}
                style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 8px', borderRadius: 4, cursor: 'pointer', fontSize: 11, color: 'var(--text-secondary)', fontWeight: 500, marginTop: 4 }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              >
                <span style={{ transform: activeType === type ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s', display: 'flex' }}>{icons.chevRight}</span>
                <span style={{ textTransform: 'capitalize' }}>{type}</span>
                <span style={{ fontSize: 10, color: 'var(--text-tertiary)', marginLeft: 'auto' }}>
                  {graph.entities.filter(e => e.type === type).length}
                </span>
              </div>

              {activeType === type && graph.entities.filter(e => e.type === type).sort((a, b) => a.name.localeCompare(b.name)).map(entity => (
                <div
                  key={entity.id}
                  onClick={() => openEntity(entity)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 5, padding: '4px 8px 4px 24', borderRadius: 4, cursor: 'pointer', fontSize: 11,
                    color: selectedEntity?.id === entity.id ? 'var(--accent)' : 'var(--text-tertiary)',
                    background: selectedEntity?.id === entity.id ? 'var(--accent-muted)' : 'transparent'
                  }}
                  onMouseEnter={e => { if (selectedEntity?.id !== entity.id) e.currentTarget.style.background = 'var(--bg-hover)' }}
                  onMouseLeave={e => { if (selectedEntity?.id !== entity.id) e.currentTarget.style.background = 'transparent' }}
                >
                  <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{entity.name}</span>
                </div>
              ))}
            </div>
          ))}

          {/* Search results */}
          {searchResults.length > 0 && (
            <div style={{ marginTop: 8, borderTop: '1px solid var(--border-primary)', paddingTop: 6 }}>
              <div style={{ fontSize: 10, color: 'var(--text-tertiary)', padding: '0 8px', marginBottom: 4 }}>Search Results ({searchResults.length})</div>
              {searchResults.map(entity => (
                <div
                  key={entity.id}
                  onClick={() => openEntity(entity)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 5, padding: '4px 8px', borderRadius: 4, cursor: 'pointer', fontSize: 11,
                    color: selectedEntity?.id === entity.id ? 'var(--accent)' : 'var(--text-tertiary)',
                    background: selectedEntity?.id === entity.id ? 'var(--accent-muted)' : 'transparent'
                  }}
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{entity.name}</span>
                  <span style={{ fontSize: 9, color: 'var(--text-tertiary)' }}>{entity.type}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div style={{ padding: '6px 10px', borderTop: '1px solid var(--border-primary)', fontSize: 10, color: 'var(--text-tertiary)' }}>
          {graph.entities.length} entities · {graph.relationships.length} relations
        </div>
      </div>

      {/* Right content */}
      <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        {selectedEntity ? (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
              <button onClick={() => setSelectedEntity(null)} style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)', display: 'flex' }}>{icons.back}</button>
              <div>
                <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary)' }}>{selectedEntity.name}</div>
                <div style={{ fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'capitalize' }}>{selectedEntity.type}</div>
              </div>
            </div>

            {selectedEntity.summary && (
              <div style={{ marginBottom: 16, padding: 10, background: 'var(--bg-card)', borderRadius: 6, border: '1px solid var(--border-primary)' }}>
                <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: '18px' }}>{selectedEntity.summary}</div>
              </div>
            )}

            {entityRels.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 8 }}>Relationships ({entityRels.length})</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {entityRels.map(rel => {
                    const isSource = rel.source_entity_id === selectedEntity.id
                    const otherName = getEntityName(isSource ? rel.target_entity_id : rel.source_entity_id)
                    return (
                      <div key={rel.id} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px', background: 'var(--bg-card)', borderRadius: 4, border: '1px solid var(--border-primary)', fontSize: 12 }}>
                        <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{selectedEntity.name}</span>
                        <span style={{ color: 'var(--accent)', fontSize: 10 }}>{isSource ? '→' : '←'} {rel.type}</span>
                        <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{otherName}</span>
                        {rel.label && <span style={{ color: 'var(--text-tertiary)', fontSize: 10, marginLeft: 'auto' }}>{rel.label}</span>}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {entityLoading ? (
              <div style={{ display: 'flex', justifyContent: 'center', padding: 20 }}><Spin size="small" /></div>
            ) : entityPage ? (
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 8 }}>Wiki Page</div>
                <pre style={{ fontSize: 12, color: 'var(--text-secondary)', margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'inherit', lineHeight: '20px', padding: 12, background: 'var(--bg-card)', borderRadius: 6, border: '1px solid var(--border-primary)' }}>
                  {entityPage.content}
                </pre>
              </div>
            ) : null}
          </div>
        ) : entityPage ? (
          <div>
            <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 12 }}>{entityPage.title}</div>
            <pre style={{ fontSize: 12, color: 'var(--text-secondary)', margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'inherit', lineHeight: '20px', padding: 12, background: 'var(--bg-card)', borderRadius: 6, border: '1px solid var(--border-primary)' }}>
              {entityPage.content}
            </pre>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '60px 0' }}>
            <div style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>Select an entity or view the overview page</div>
          </div>
        )}
      </div>
    </div>
  )
}
