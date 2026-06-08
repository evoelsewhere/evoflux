import { useState, useEffect, useCallback } from 'react'
import { Spin, message } from 'antd'
import KBGitChanges from './KBGitChanges'

const icons = {
  back: <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M9 2L4 7L9 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>,
  folder: <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2 4V11C2 11.6 2.4 12 3 12H11C11.6 12 12 11.6 12 11V5C12 4.4 11.6 4 11 4H7L6 2H3C2.4 2 2 2.4 2 3V4Z" stroke="currentColor" strokeWidth="1.2" /></svg>,
  file: <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><rect x="3" y="1" width="8" height="12" rx="1" stroke="currentColor" strokeWidth="1.2" /><path d="M5 5H9M5 7H9M5 9H7" stroke="currentColor" strokeWidth="0.9" strokeLinecap="round" /></svg>,
  plus: <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7 3V11M3 7H11" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" /></svg>,
  search: <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="1.3" /><path d="M9.5 9.5L13 13" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" /></svg>,
  trash: <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2 3H10M4.5 3V2C4.5 1.4 4.9 1 5.5 1H6.5C7.1 1 7.5 1.4 7.5 2V3M9.5 3V10C9.5 10.6 9.1 11 8.5 11H3.5C2.9 11 2.5 10.6 2.5 10V3" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" /><path d="M5 5.5V8.5M7 5.5V8.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" /></svg>,
  refresh: <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M1 6C1 3.2 3.2 1 6 1C8.2 1 10.1 2.4 10.8 4.5M11 6C11 8.8 8.8 11 6 11C3.8 11 1.9 9.6 1.2 7.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" /><path d="M10 1.5V4.5H7M2 10.5V7.5H5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" /></svg>,
  chevDown: <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M2 4L5 7L8 4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" /></svg>,
  chevRight: <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M4 2L7 5L4 8" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" /></svg>,
}

interface KB { id: string; name: string; description: string; config_json: string; stats_json: string }
interface KBSource { id: string; path: string; type: string; status: string; file_count: number; error: string | null; git_branch: string | null; git_repo_path: string | null }
interface KBDocument { id: string; path: string; name: string; extension: string | null; size: number | null; chunk_count: number; status: string; content_preview: string | null }
interface KBChunk { id: string; chunk_index: number; content: string; metadata_json: string | null }
interface KBStats { totalDocs: number; indexedDocs: number; totalChunks: number; totalSize: number; indexedPercent: number }

interface KBDetailProps {
  kbId: string
  onBack: () => void
}

export default function KBDetail({ kbId, onBack }: KBDetailProps) {
  const [kb, setKb] = useState<KB | null>(null)
  const [sources, setSources] = useState<KBSource[]>([])
  const [documents, setDocuments] = useState<KBDocument[]>([])
  const [stats, setStats] = useState<KBStats>({ totalDocs: 0, indexedDocs: 0, totalChunks: 0, totalSize: 0, indexedPercent: 0 })
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<'tree' | 'docs' | 'search' | 'settings'>('tree')
  const [expandedSources, setExpandedSources] = useState<Set<string>>(new Set())
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set())
  const [selectedDoc, setSelectedDoc] = useState<string | null>(null)
  const [chunks, setChunks] = useState<KBChunk[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<Array<{ content: string; doc_name: string; hybrid_score: number; chunk_id: string }>>([])
  const [searching, setSearching] = useState(false)
  const [indexing, setIndexing] = useState(false)

  const load = useCallback(async () => {
    try {
      const [kbData, srcData, docData, statsData] = await Promise.all([
        window.api.kb.get(kbId),
        window.api.kb.listSources(kbId),
        window.api.kb.listDocuments(kbId),
        window.api.kb.getStats(kbId)
      ])
      setKb(kbData as KB)
      setSources(srcData as KBSource[])
      setDocuments(docData as KBDocument[])
      setStats(statsData as KBStats)
    } catch { message.error('Failed to load KB') }
    finally { setLoading(false) }
  }, [kbId])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    const cleanup = window.api.kb.onProgress((ev: unknown) => {
      const event = ev as { type: string; fileName?: string }
      if (event.type === 'kb:progress') {
        // Progress updates handled by indexing state
      }
    })
    return cleanup
  }, [])

  const loadChunks = async (docId: string) => {
    setSelectedDoc(docId)
    try {
      const ch = await window.api.kb.listChunks(docId) as KBChunk[]
      setChunks(ch)
    } catch { message.error('Failed to load chunks') }
  }

  const handleAddFolder = async () => {
    setIndexing(true)
    try {
      const result = await window.api.kb.addFolder(kbId)
      if (result && !(result as { error?: string }).error) {
        message.success(`Indexed ${(result as { docsIndexed?: number }).docsIndexed || 0} files`)
        await load()
      } else if ((result as { error?: string }).error) {
        message.error((result as { error: string }).error)
      }
    } catch { message.error('Failed to add folder') }
    finally { setIndexing(false) }
  }

  const handleAddFiles = async () => {
    setIndexing(true)
    try {
      const result = await window.api.kb.addFiles(kbId)
      if (result && !(result as { error?: string }).error) {
        message.success(`Indexed ${(result as { docsIndexed?: number }).docsIndexed || 0} files`)
        await load()
      }
    } catch { message.error('Failed to add files') }
    finally { setIndexing(false) }
  }

  const handleRemoveSource = async (sourceId: string) => {
    try {
      await window.api.kb.removeSource(sourceId)
      setSources(prev => prev.filter(s => s.id !== sourceId))
      await load()
    } catch { message.error('Failed to remove source') }
  }

  const handleSearch = async () => {
    if (!searchQuery.trim()) return
    setSearching(true)
    try {
      const results = await window.api.kb.search(kbId, searchQuery, { limit: 20 })
      if (Array.isArray(results)) setSearchResults(results)
    } catch { message.error('Search failed') }
    finally { setSearching(false) }
  }

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'f') {
        e.preventDefault()
        setActiveTab('search')
        setTimeout(() => {
          const input = document.querySelector('input[placeholder="Search knowledge base..."]') as HTMLInputElement
          input?.focus()
        }, 100)
      }
      if (e.key === 'Escape' && selectedDoc) {
        setSelectedDoc(null)
        setChunks([])
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [selectedDoc])

  const formatSize = (bytes: number | null) => {
    if (!bytes) return '—'
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  const statusBadge = (status: string) => {
    const colors: Record<string, { bg: string; fg: string }> = {
      pending: { bg: 'var(--bg-hover)', fg: 'var(--text-tertiary)' },
      indexing: { bg: '#60a5fa20', fg: '#60a5fa' },
      processing: { bg: '#60a5fa20', fg: '#60a5fa' },
      indexed: { bg: '#34d39920', fg: '#34d399' },
      error: { bg: '#f8717120', fg: '#f87171' }
    }
    const c = colors[status] || colors.pending
    return <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 3, background: c.bg, color: c.fg, fontWeight: 600 }}>{status}</span>
  }

  const buildTree = () => {
    const tree: Record<string, KBDocument[]> = {}
    for (const doc of documents) {
      const parts = doc.path.split('/')
      const dir = parts.length > 1 ? parts.slice(0, -1).join('/') : '/'
      if (!tree[dir]) tree[dir] = []
      tree[dir].push(doc)
    }
    return tree
  }

  if (loading) return <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 80 }}><Spin /></div>
  if (!kb) return <div style={{ color: 'var(--text-tertiary)', padding: 40, textAlign: 'center' }}>Knowledge base not found</div>

  const tree = buildTree()

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', borderBottom: '1px solid var(--border-primary)', flexShrink: 0 }}>
        <button onClick={onBack} style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)', padding: 4, borderRadius: 4, display: 'flex' }}
          onMouseEnter={e => e.currentTarget.style.color = 'var(--text-primary)'}
          onMouseLeave={e => e.currentTarget.style.color = 'var(--text-tertiary)'}>
          {icons.back}
        </button>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>{kb.name}</div>
          {kb.description && <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 1 }}>{kb.description}</div>}
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>{stats.totalDocs} docs</span>
          <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>{stats.totalChunks} chunks</span>
          <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>{formatSize(stats.totalSize)}</span>
          <span style={{ fontSize: 10, color: stats.indexedPercent === 100 ? '#34d399' : '#fbbf24', fontWeight: 600 }}>{stats.indexedPercent}%</span>
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Left: Sources */}
        <div style={{ width: 220, borderRight: '1px solid var(--border-primary)', display: 'flex', flexDirection: 'column', overflow: 'hidden', flexShrink: 0 }}>
          <div style={{ padding: '8px 10px', borderBottom: '1px solid var(--border-primary)', display: 'flex', gap: 4 }}>
            <button onClick={handleAddFolder} disabled={indexing} style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4, padding: '5px 0', fontSize: 11, fontWeight: 500, borderRadius: 5, background: 'var(--accent-muted)', border: '1px solid var(--accent)30', color: 'var(--accent)', cursor: 'pointer', opacity: indexing ? 0.5 : 1 }}>
              {icons.folder} Folder
            </button>
            <button onClick={handleAddFiles} disabled={indexing} style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4, padding: '5px 0', fontSize: 11, fontWeight: 500, borderRadius: 5, background: 'var(--bg-hover)', border: '1px solid var(--border-primary)', color: 'var(--text-secondary)', cursor: 'pointer', opacity: indexing ? 0.5 : 1 }}>
              {icons.file} Files
            </button>
          </div>

          <div style={{ flex: 1, overflow: 'auto', padding: 6 }}>
            {indexing && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 10px', fontSize: 11, color: '#60a5fa', marginBottom: 4 }}>
                <Spin size="small" /> Indexing...
              </div>
            )}
            {sources.map(src => (
              <div key={src.id}>
                <div
                  onClick={() => setExpandedSources(prev => { const s = new Set(prev); s.has(src.id) ? s.delete(src.id) : s.add(src.id); return s })}
                  style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 8px', borderRadius: 5, cursor: 'pointer', transition: 'background 0.1s', fontSize: 11, color: 'var(--text-primary)' }}
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  <span style={{ transform: expandedSources.has(src.id) ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s', display: 'flex' }}>{icons.chevRight}</span>
                  <span style={{ color: 'var(--accent)', display: 'flex' }}>{src.type === 'folder' ? icons.folder : icons.file}</span>
                  <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{src.path.split('/').pop() || src.path}</span>
                  {statusBadge(src.status)}
                </div>

                {expandedSources.has(src.id) && (
                  <div style={{ paddingLeft: 20 }}>
                    {src.git_branch && <div style={{ fontSize: 9, color: 'var(--text-tertiary)', padding: '2px 8px' }}>branch: {src.git_branch}</div>}
                    <div style={{ fontSize: 9, color: 'var(--text-tertiary)', padding: '2px 8px' }}>{src.file_count} files</div>
                    <button onClick={() => handleRemoveSource(src.id)} style={{ fontSize: 9, color: 'var(--error)', background: 'transparent', border: 'none', cursor: 'pointer', padding: '2px 8px' }}>Remove</button>
                  </div>
                )}
              </div>
            ))}
            {sources.length === 0 && !indexing && (
              <div style={{ fontSize: 11, color: 'var(--text-tertiary)', padding: '20px 10px', textAlign: 'center' }}>No sources added</div>
            )}

            {/* Git changes panel */}
            {sources.filter(s => s.git_repo_path).map(src => (
              <div key={`git-${src.id}`} style={{ borderTop: '1px solid var(--border-primary)', marginTop: 4 }}>
                <KBGitChanges kbId={kbId} sourceId={src.id} onSyncComplete={load} />
              </div>
            ))}
          </div>
        </div>

        {/* Right: Content area */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Tabs */}
          <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid var(--border-primary)', flexShrink: 0 }}>
            {(['tree', 'docs', 'search', 'settings'] as const).map(tab => (
              <button key={tab} onClick={() => setActiveTab(tab)} style={{
                padding: '8px 14px', fontSize: 11, fontWeight: 500, background: 'transparent',
                border: 'none', borderBottom: activeTab === tab ? '2px solid var(--accent)' : '2px solid transparent',
                color: activeTab === tab ? 'var(--accent)' : 'var(--text-tertiary)', cursor: 'pointer', transition: 'all 0.15s',
                textTransform: 'capitalize'
              }}>
                {tab === 'tree' ? 'Folder Tree' : tab === 'docs' ? 'Documents' : tab === 'search' ? 'Search' : 'Settings'}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div style={{ flex: 1, overflow: 'auto', padding: 12 }}>
            {/* Tree tab */}
            {activeTab === 'tree' && (
              <div>
                {Object.entries(tree).length === 0 ? (
                  <div style={{ fontSize: 12, color: 'var(--text-tertiary)', padding: '40px 0', textAlign: 'center' }}>
                    No documents indexed yet. Add a folder or files to get started.
                  </div>
                ) : (
                  Object.entries(tree).map(([dir, docs]) => (
                    <div key={dir} style={{ marginBottom: 4 }}>
                      <div
                        onClick={() => setExpandedFolders(prev => { const s = new Set(prev); s.has(dir) ? s.delete(dir) : s.add(dir); return s })}
                        style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 6px', borderRadius: 4, cursor: 'pointer', fontSize: 11, color: 'var(--text-secondary)', fontWeight: 500 }}
                        onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
                        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                      >
                        <span style={{ transform: expandedFolders.has(dir) ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s', display: 'flex' }}>{icons.chevRight}</span>
                        <span style={{ color: 'var(--accent)', display: 'flex' }}>{icons.folder}</span>
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{dir.split('/').pop() || '/'}</span>
                        <span style={{ fontSize: 9, color: 'var(--text-tertiary)', marginLeft: 'auto' }}>{docs.length}</span>
                      </div>

                      {expandedFolders.has(dir) && docs.map(doc => (
                        <div
                          key={doc.id}
                          onClick={() => loadChunks(doc.id)}
                          style={{
                            display: 'flex', alignItems: 'center', gap: 5, padding: '4px 6px 4px 24', borderRadius: 4, cursor: 'pointer', fontSize: 10,
                            color: selectedDoc === doc.id ? 'var(--accent)' : 'var(--text-tertiary)',
                            background: selectedDoc === doc.id ? 'var(--accent-muted)' : 'transparent'
                          }}
                          onMouseEnter={e => { if (selectedDoc !== doc.id) e.currentTarget.style.background = 'var(--bg-hover)' }}
                          onMouseLeave={e => { if (selectedDoc !== doc.id) e.currentTarget.style.background = 'transparent' }}
                        >
                          <span style={{ display: 'flex' }}>{icons.file}</span>
                          <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{doc.name}</span>
                          <span style={{ fontSize: 9 }}>{doc.chunk_count}c</span>
                          {statusBadge(doc.status)}
                        </div>
                      ))}
                    </div>
                  ))
                )}
              </div>
            )}

            {/* Docs tab */}
            {activeTab === 'docs' && (
              <div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 60px 70px 50px 60px', gap: 4, padding: '6px 8px', fontSize: 10, fontWeight: 600, color: 'var(--text-tertiary)', borderBottom: '1px solid var(--border-primary)', marginBottom: 4 }}>
                  <span>Name</span><span>Ext</span><span>Size</span><span>Chunks</span><span>Status</span>
                </div>
                {documents.map(doc => (
                  <div
                    key={doc.id}
                    onClick={() => loadChunks(doc.id)}
                    style={{
                      display: 'grid', gridTemplateColumns: '1fr 60px 70px 50px 60px', gap: 4, padding: '6px 8px', borderRadius: 4, cursor: 'pointer', fontSize: 10,
                      color: selectedDoc === doc.id ? 'var(--accent)' : 'var(--text-primary)',
                      background: selectedDoc === doc.id ? 'var(--accent-muted)' : 'transparent'
                    }}
                    onMouseEnter={e => { if (selectedDoc !== doc.id) e.currentTarget.style.background = 'var(--bg-hover)' }}
                    onMouseLeave={e => { if (selectedDoc !== doc.id) e.currentTarget.style.background = 'transparent' }}
                  >
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{doc.name}</span>
                    <span style={{ color: 'var(--text-tertiary)' }}>{doc.extension || '—'}</span>
                    <span style={{ color: 'var(--text-tertiary)' }}>{formatSize(doc.size)}</span>
                    <span style={{ color: 'var(--text-tertiary)' }}>{doc.chunk_count}</span>
                    <span>{statusBadge(doc.status)}</span>
                  </div>
                ))}
                {documents.length === 0 && (
                  <div style={{ fontSize: 12, color: 'var(--text-tertiary)', padding: '40px 0', textAlign: 'center' }}>No documents</div>
                )}
              </div>
            )}

            {/* Search tab */}
            {activeTab === 'search' && (
              <div>
                <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
                  <input
                    value={searchQuery}
                    onChange={e => setSearchQuery(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') handleSearch() }}
                    placeholder="Search knowledge base..."
                    style={{ flex: 1, padding: '7px 10px', fontSize: 12, background: 'var(--bg-input)', border: '1px solid var(--border-primary)', borderRadius: 6, color: 'var(--text-primary)', outline: 'none' }}
                  />
                  <button onClick={handleSearch} disabled={searching} style={{ padding: '7px 14px', fontSize: 11, fontWeight: 600, borderRadius: 6, background: 'var(--accent)', border: 'none', color: '#fff', cursor: 'pointer', opacity: searching ? 0.5 : 1 }}>
                    {searching ? '...' : 'Search'}
                  </button>
                </div>
                {searchResults.map(r => (
                  <div key={r.chunk_id} style={{ padding: '10px 12px', marginBottom: 6, background: 'var(--bg-card)', border: '1px solid var(--border-primary)', borderRadius: 6 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent)' }}>{r.doc_name}</span>
                      <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>{(r.hybrid_score * 100).toFixed(0)}%</span>
                    </div>
                    <pre style={{ fontSize: 10, color: 'var(--text-secondary)', margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 100, overflow: 'auto' }}>
                      {r.content.substring(0, 300)}{r.content.length > 300 ? '...' : ''}
                    </pre>
                  </div>
                ))}
                {searchResults.length === 0 && searchQuery && !searching && (
                  <div style={{ fontSize: 12, color: 'var(--text-tertiary)', padding: '40px 0', textAlign: 'center' }}>No results found</div>
                )}
              </div>
            )}

            {/* Settings tab */}
            {activeTab === 'settings' && (
              <div style={{ maxWidth: 400 }}>
                {/* Stats */}
                <div style={{ marginBottom: 16, padding: 10, background: 'var(--bg-card)', borderRadius: 6, border: '1px solid var(--border-primary)' }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 8 }}>Index Statistics</div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                    {[
                      { label: 'Documents', value: stats.totalDocs },
                      { label: 'Indexed', value: stats.indexedDocs },
                      { label: 'Chunks', value: stats.totalChunks },
                      { label: 'Total Size', value: formatSize(stats.totalSize) }
                    ].map(s => (
                      <div key={s.label} style={{ padding: '6px 8px', background: 'var(--bg-primary)', borderRadius: 4 }}>
                        <div style={{ fontSize: 9, color: 'var(--text-tertiary)', marginBottom: 2 }}>{s.label}</div>
                        <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>{s.value}</div>
                      </div>
                    ))}
                  </div>
                  <div style={{ marginTop: 8 }}>
                    <div style={{ fontSize: 9, color: 'var(--text-tertiary)', marginBottom: 3 }}>Index Progress</div>
                    <div style={{ height: 6, background: 'var(--bg-primary)', borderRadius: 3, overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${stats.indexedPercent}%`, background: stats.indexedPercent === 100 ? '#34d399' : 'var(--accent)', borderRadius: 3, transition: 'width 0.3s' }} />
                    </div>
                    <div style={{ fontSize: 9, color: 'var(--text-tertiary)', marginTop: 2 }}>{stats.indexedPercent}%</div>
                  </div>
                </div>

                {/* Chunk settings */}
                {[
                  { label: 'Chunk Size', key: 'chunkSize', default: 1000 },
                  { label: 'Chunk Overlap', key: 'chunkOverlap', default: 200 },
                  { label: 'Min Chunk Size', key: 'minChunkSize', default: 100 }
                ].map(({ label, key, default: def }) => {
                  let config: Record<string, unknown> = {}
                  try { config = JSON.parse(kb.config_json) } catch {}
                  const val = (config[key] as number) ?? def
                  return (
                    <div key={key} style={{ marginBottom: 12 }}>
                      <div style={{ fontSize: 11, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 4 }}>{label}</div>
                      <input
                        type="number"
                        value={val}
                        onChange={e => {
                          const newConfig = { ...config, [key]: parseInt(e.target.value) || def }
                          window.api.kb.update(kbId, { config: newConfig })
                        }}
                        style={{ width: 120, padding: '5px 8px', fontSize: 12, background: 'var(--bg-input)', border: '1px solid var(--border-primary)', borderRadius: 5, color: 'var(--text-primary)', outline: 'none' }}
                      />
                    </div>
                  )
                })}

                {/* Backup/Restore */}
                <div style={{ marginTop: 16, padding: 10, background: 'var(--bg-card)', borderRadius: 6, border: '1px solid var(--border-primary)' }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 8 }}>Backup & Restore</div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button onClick={async () => {
                      const r = await window.api.kb.export(kbId) as { success: boolean; path?: string; error?: string }
                      if (r.success) message.success(`Exported to ${r.path}`)
                      else if (r.error) message.error(r.error)
                    }} style={{ padding: '5px 12px', fontSize: 11, borderRadius: 5, background: 'var(--accent-muted)', border: '1px solid var(--accent)30', color: 'var(--accent)', cursor: 'pointer' }}>
                      Export .kb
                    </button>
                    <button onClick={async () => {
                      const r = await window.api.kb.import() as { success: boolean; kbId?: string; error?: string }
                      if (r.success) message.success('Imported successfully')
                      else if (r.error) message.error(r.error)
                    }} style={{ padding: '5px 12px', fontSize: 11, borderRadius: 5, background: 'var(--bg-hover)', border: '1px solid var(--border-primary)', color: 'var(--text-secondary)', cursor: 'pointer' }}>
                      Import .kb
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Chunks preview panel */}
          {selectedDoc && chunks.length > 0 && (
            <div style={{ height: 200, borderTop: '1px solid var(--border-primary)', overflow: 'auto', padding: 10, flexShrink: 0 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 6 }}>
                Chunks ({chunks.length})
              </div>
              {chunks.map(ch => {
                let meta: Record<string, unknown> = {}
                try { meta = JSON.parse(ch.metadata_json || '{}') } catch {}
                return (
                  <div key={ch.id} style={{ padding: '6px 8px', marginBottom: 4, background: 'var(--bg-card)', borderRadius: 4, border: '1px solid var(--border-primary)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                      <span style={{ fontSize: 9, fontWeight: 600, color: 'var(--accent)' }}>
                        #{ch.chunk_index} {(meta.heading as string) ? `· ${meta.heading}` : ''}
                      </span>
                      <span style={{ fontSize: 9, color: 'var(--text-tertiary)' }}>
                        L{(meta.lineStart as number) || 0}-{(meta.lineEnd as number) || 0}
                      </span>
                    </div>
                    <pre style={{ fontSize: 9, color: 'var(--text-secondary)', margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 50, overflow: 'hidden' }}>
                      {ch.content.substring(0, 200)}
                    </pre>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
