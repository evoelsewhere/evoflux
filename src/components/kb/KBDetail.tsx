import { useState, useEffect, useCallback } from 'react'
import { Spin, message } from 'antd'
import KBGitChanges from './KBGitChanges'
import KBWiki from './KBWiki'
import { useProviderStore, PROVIDER_LABELS } from '../../stores/providerStore'

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
  const [activeTab, setActiveTab] = useState<'tree' | 'docs' | 'search' | 'wiki' | 'settings'>('tree')
  const [expandedSources, setExpandedSources] = useState<Set<string>>(new Set())
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set())
  const [selectedDoc, setSelectedDoc] = useState<string | null>(null)
  const [chunks, setChunks] = useState<KBChunk[]>([])
  const [detailDoc, setDetailDoc] = useState<KBDocument | null>(null)
  const [detailChunks, setDetailChunks] = useState<KBChunk[]>([])
  const [detailLoading, setDetailLoading] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<Array<{ content: string; doc_name: string; hybrid_score: number; chunk_id: string }>>([])
  const [searching, setSearching] = useState(false)
  const [indexing, setIndexing] = useState(false)
  const [editingName, setEditingName] = useState(false)
  const [editName, setEditName] = useState('')
  const [indexProgress, setIndexProgress] = useState<{ fileName: string; current: number; total: number } | null>(null)
  const [config, setConfig] = useState<Record<string, unknown>>({})
  const [availableModels, setAvailableModels] = useState<string[]>([])
  const [wikiBuilding, setWikiBuilding] = useState(false)
  const [wikiProgress, setWikiProgress] = useState<{ batch: number; total: number; entities: number; relationships: number; saved?: boolean; error?: string } | null>(null)
  const providers = useProviderStore(s => s.providers)

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
      let parsed: Record<string, unknown> = {}
      try { parsed = JSON.parse((kbData as KB).config_json) } catch {}
      setConfig(parsed)
    } catch { message.error('Failed to load KB') }
    finally { setLoading(false) }
  }, [kbId])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    const cleanup = window.api.kb.onProgress((ev: unknown) => {
      const event = ev as { type: string; fileName?: string; fileIndex?: number; totalFiles?: number; status?: string; batch?: number; total?: number; entities?: number; relationships?: number; saved?: boolean; error?: string }
      if (event.type === 'kb:progress' || event.type === 'kb:sync') {
        if (event.status === 'complete' || event.status === 'nochange') {
          setIndexing(false)
          setIndexProgress(null)
          load()
        } else if (event.status === 'error') {
          // Keep indexing state, error is shown in message
        } else if (event.fileName && event.fileIndex !== undefined && event.totalFiles) {
          setIndexing(true)
          setIndexProgress({ fileName: event.fileName, current: event.fileIndex + 1, total: event.totalFiles })
        }
      }
      if (event.type === 'wiki:progress') {
        if (event.status === 'start') {
          setWikiBuilding(true)
          setWikiProgress({ batch: 0, total: event.total || 0, entities: 0, relationships: 0 })
        } else if (event.status === 'batch') {
          setWikiProgress({ batch: (event.batch || 0) + 1, total: event.total || 0, entities: event.entities || 0, relationships: event.relationships || 0, saved: event.saved })
        } else if (event.status === 'error') {
          setWikiProgress(prev => prev ? { ...prev, error: event.error } : null)
        } else if (event.status === 'complete') {
          setWikiBuilding(false)
          setWikiProgress(null)
          message.success(`Wiki built: ${event.entities || 0} entities, ${event.relationships || 0} relations`)
          load()
        }
      }
    })
    return cleanup
  }, [load])

  const loadChunks = async (docId: string) => {
    setSelectedDoc(docId)
    try {
      const ch = await window.api.kb.listChunks(docId) as KBChunk[]
      setChunks(ch)
    } catch { message.error('Failed to load chunks') }
  }

  const openDocDetail = async (doc: KBDocument) => {
    setDetailDoc(doc)
    setDetailLoading(true)
    try {
      const ch = await window.api.kb.listChunks(doc.id) as KBChunk[]
      setDetailChunks(ch)
    } catch { setDetailChunks([]) }
    finally { setDetailLoading(false) }
  }

  const updateConfig = useCallback((key: string, val: unknown) => {
    setConfig(prev => {
      const next = { ...prev, [key]: val }
      window.api.kb.update(kbId, { config: next })
      return next
    })
  }, [kbId])

  const updateWikiConfig = useCallback((key: string, val: unknown) => {
    setConfig(prev => {
      const wiki = { ...((prev.wiki || {}) as Record<string, unknown>), [key]: val }
      const next = { ...prev, wiki }
      window.api.kb.update(kbId, { config: next })
      return next
    })
  }, [kbId])

  useEffect(() => {
    const wikiConfig = (config.wiki || {}) as Record<string, unknown>
    const providerId = wikiConfig.providerId as string
    if (!providerId) { setAvailableModels([]); return }
    const provider = providers.find(p => p.id === providerId)
    if (provider) setAvailableModels(provider.models)
    else {
      window.api.ai.listModels(providerId).then((models: unknown) => {
        if (Array.isArray(models)) setAvailableModels(models as string[])
      }).catch(() => setAvailableModels([]))
    }
  }, [(config.wiki as Record<string, unknown>)?.providerId, providers])

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
    return <span style={{ fontSize: 12, padding: '1px 5px', borderRadius: 3, background: c.bg, color: c.fg, fontWeight: 600 }}>{status}</span>
  }

  interface TreeNode { name: string; path: string; children: TreeNode[]; doc?: KBDocument; depth: number }

  const buildTree = (): TreeNode[] => {
    const root: TreeNode[] = []
    const dirMap = new Map<string, TreeNode>()

    const sourceRoots = sources.map(s => s.path).sort((a, b) => b.length - a.length)

    const getRelativePath = (fullPath: string): string => {
      for (const root of sourceRoots) {
        if (fullPath.startsWith(root)) {
          const rel = fullPath.substring(root.length)
          return rel.startsWith('/') ? rel.substring(1) : rel
        }
      }
      const parts = fullPath.split('/')
      return parts.length > 1 ? parts.slice(-2).join('/') : fullPath
    }

    const sortedDocs = [...documents].sort((a, b) => a.path.localeCompare(b.path))

    for (const doc of sortedDocs) {
      const relPath = getRelativePath(doc.path)
      const parts = relPath.split('/')
      let currentPath = ''
      let parentChildren = root

      for (let i = 0; i < parts.length - 1; i++) {
        currentPath = currentPath ? currentPath + '/' + parts[i] : parts[i]
        if (!dirMap.has(currentPath)) {
          const dirNode: TreeNode = { name: parts[i], path: currentPath, children: [], depth: i }
          dirMap.set(currentPath, dirNode)
          parentChildren.push(dirNode)
        }
        parentChildren = dirMap.get(currentPath)!.children
      }

      parentChildren.push({ name: parts[parts.length - 1], path: relPath, children: [], doc, depth: parts.length - 1 })
    }

    return root
  }

  function MCPSettings() {
    const [mcpRunning, setMcpRunning] = useState(false)
    const [mcpLoading, setMcpLoading] = useState(false)

    useEffect(() => {
      window.api?.mcp?.status?.()?.then?.((s: { running: boolean }) => setMcpRunning(s.running))?.catch?.(() => {})
    }, [])

    const toggleMCP = async () => {
      if (!window.api?.mcp) { message.error('MCP not available — restart app'); return }
      setMcpLoading(true)
      try {
        if (mcpRunning) {
          const r = await window.api.mcp.stop() as { success: boolean; error?: string }
          if (r.success) setMcpRunning(false)
          else message.error(r.error)
        } else {
          const r = await window.api.mcp.start() as { success: boolean; error?: string }
          if (r.success) setMcpRunning(true)
          else message.error(r.error)
        }
      } catch { message.error('MCP toggle failed') }
      finally { setMcpLoading(false) }
    }

    const configJson = JSON.stringify({
      mcpServers: {
        'evolux-kb': {
          command: 'node',
          args: ['<path-to-evolux>/out/mcp/index.js']
        }
      }
    }, null, 2)

    return (
      <div style={{ marginBottom: 16, padding: 12, background: 'var(--bg-card)', borderRadius: 6, border: '1px solid var(--border-primary)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>MCP Server</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{
              fontSize: 10, padding: '2px 8px', borderRadius: 10,
              background: mcpRunning ? '#34d39920' : 'var(--bg-hover)',
              color: mcpRunning ? '#34d399' : 'var(--text-tertiary)',
              fontWeight: 600
            }}>
              {mcpRunning ? 'Running' : 'Stopped'}
            </span>
            <button
              onClick={toggleMCP}
              disabled={mcpLoading}
              style={{
                padding: '5px 14px', fontSize: 12, borderRadius: 5, fontWeight: 500,
                background: mcpRunning ? '#f8717120' : 'var(--accent-muted)',
                border: `1px solid ${mcpRunning ? '#f8717130' : 'var(--accent)30'}`,
                color: mcpRunning ? '#f87171' : 'var(--accent)',
                cursor: 'pointer', opacity: mcpLoading ? 0.5 : 1
              }}
            >
              {mcpRunning ? 'Stop' : 'Start'}
            </button>
          </div>
        </div>

        <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 10 }}>
          Expose knowledge base to external AI tools (Claude Desktop, Cursor, Windsurf) via Model Context Protocol.
        </div>

        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 4 }}>Exposed Tools</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
            {['kb_search', 'kb_list', 'kb_get_info', 'kb_list_documents', 'kb_get_document', 'kb_get_chunks'].map(tool => (
              <div key={tool} style={{ fontSize: 11, color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center', gap: 4 }}>
                <span style={{ width: 4, height: 4, borderRadius: '50%', background: mcpRunning ? '#34d399' : 'var(--text-tertiary)' }} />
                <code style={{ fontFamily: 'monospace', fontSize: 10 }}>{tool}</code>
              </div>
            ))}
          </div>
        </div>

        <div>
          <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 4 }}>Config for Claude Desktop / Cursor</div>
          <pre style={{
            fontSize: 10, fontFamily: 'monospace', padding: 8, margin: 0,
            background: 'var(--bg-primary)', borderRadius: 4,
            border: '1px solid var(--border-primary)',
            color: 'var(--text-secondary)', whiteSpace: 'pre-wrap',
            maxHeight: 120, overflow: 'auto'
          }}>
            {configJson}
          </pre>
          <button
            onClick={() => { navigator.clipboard.writeText(configJson); message.success('Copied') }}
            style={{ marginTop: 6, padding: '4px 10px', fontSize: 10, borderRadius: 4, background: 'var(--bg-hover)', border: '1px solid var(--border-primary)', color: 'var(--text-secondary)', cursor: 'pointer' }}
          >
            Copy Config
          </button>
        </div>
      </div>
    )
  }

  if (loading) return <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 80 }}><Spin /></div>
  if (!kb) return <div style={{ color: 'var(--text-tertiary)', padding: 40, textAlign: 'center' }}>Knowledge base not found</div>

  const tree = buildTree()

  function TreeNodeComponent({ node, expandedFolders, setExpandedFolders, onFileClick, selectedDoc, depth = 0 }: { node: TreeNode; expandedFolders: Set<string>; setExpandedFolders: React.Dispatch<React.SetStateAction<Set<string>>>; onFileClick: (doc: KBDocument) => void; selectedDoc: string | null; depth?: number }) {
    const isDir = node.children.length > 0 && !node.doc
    const isExpanded = expandedFolders.has(node.path)
    const indent = depth * 20

    if (isDir) {
      return (
        <div>
          <div
            onClick={() => setExpandedFolders(prev => { const s = new Set(prev); s.has(node.path) ? s.delete(node.path) : s.add(node.path); return s })}
            style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 6px', paddingLeft: 8 + indent, borderRadius: 4, cursor: 'pointer', fontSize: 12, color: 'var(--text-secondary)', fontWeight: 500 }}
            onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
          >
            <span style={{ transform: isExpanded ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s', display: 'flex', flexShrink: 0 }}>{icons.chevRight}</span>
            <span style={{ color: 'var(--accent)', display: 'flex', flexShrink: 0 }}>{icons.folder}</span>
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{node.name}</span>
            <span style={{ fontSize: 10, color: 'var(--text-tertiary)', marginLeft: 'auto', flexShrink: 0 }}>{node.children.length}</span>
          </div>
          {isExpanded && node.children.map(child => (
            <TreeNodeComponent key={child.path} node={child} expandedFolders={expandedFolders} setExpandedFolders={setExpandedFolders} onFileClick={onFileClick} selectedDoc={selectedDoc} depth={depth + 1} />
          ))}
        </div>
      )
    }

    const doc = node.doc!
    return (
      <div
        onClick={() => onFileClick(doc)}
        style={{
          display: 'flex', alignItems: 'center', gap: 5, padding: '4px 6px', paddingLeft: 8 + indent + 16, borderRadius: 4, cursor: 'pointer', fontSize: 11,
          color: selectedDoc === doc.id ? 'var(--accent)' : 'var(--text-tertiary)',
          background: selectedDoc === doc.id ? 'var(--accent-muted)' : 'transparent'
        }}
        onMouseEnter={e => { if (selectedDoc !== doc.id) e.currentTarget.style.background = 'var(--bg-hover)' }}
        onMouseLeave={e => { if (selectedDoc !== doc.id) e.currentTarget.style.background = 'transparent' }}
      >
        <span style={{ display: 'flex', flexShrink: 0 }}>{icons.file}</span>
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{node.name}</span>
        <span style={{ fontSize: 9, flexShrink: 0 }}>{doc.chunk_count}c</span>
        {statusBadge(doc.status)}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', borderBottom: '1px solid var(--border-primary)', flexShrink: 0 }}>
        <button onClick={onBack} style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)', padding: 4, borderRadius: 4, display: 'flex' }}
          onMouseEnter={e => e.currentTarget.style.color = 'var(--text-primary)'}
          onMouseLeave={e => e.currentTarget.style.color = 'var(--text-tertiary)'}>
          {icons.back}
        </button>
        <div style={{ flex: 1, minWidth: 0 }}>
          {editingName ? (
            <input
              value={editName}
              onChange={e => setEditName(e.target.value)}
              onBlur={async () => {
                setEditingName(false)
                if (editName.trim() && editName !== kb.name) {
                  await window.api.kb.update(kbId, { name: editName.trim() })
                  setKb(prev => prev ? { ...prev, name: editName.trim() } : prev)
                }
              }}
              onKeyDown={e => {
                if (e.key === 'Enter') { (e.target as HTMLInputElement).blur() }
                if (e.key === 'Escape') { setEditName(kb.name); setEditingName(false) }
              }}
              autoFocus
              style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)', background: 'var(--bg-input)', border: '1px solid var(--accent)', borderRadius: 4, padding: '2px 6px', outline: 'none', width: '100%', maxWidth: 300 }}
            />
          ) : (
            <div
              onClick={() => { setEditName(kb.name); setEditingName(true) }}
              style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)', cursor: 'text', padding: '2px 0', borderRadius: 4, transition: 'background 0.1s' }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              title="Click to rename"
            >
              {kb.name}
            </div>
          )}
          {kb.description && !editingName && <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 2 }}>{kb.description}</div>}
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>{stats.totalDocs} docs</span>
          <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>{stats.totalChunks} chunks</span>
          <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>{formatSize(stats.totalSize)}</span>
          <span style={{ fontSize: 12, color: stats.indexedPercent === 100 ? '#34d399' : '#fbbf24', fontWeight: 600 }}>{stats.indexedPercent}%</span>
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Left: Sources */}
        <div style={{ width: 280, borderRight: '1px solid var(--border-primary)', display: 'flex', flexDirection: 'column', overflow: 'hidden', flexShrink: 0 }}>
          <div style={{ padding: '8px 10px', borderBottom: '1px solid var(--border-primary)', display: 'flex', gap: 4 }}>
            <button onClick={handleAddFolder} disabled={indexing} style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4, padding: '5px 0', fontSize: 12, fontWeight: 500, borderRadius: 5, background: 'var(--accent-muted)', border: '1px solid var(--accent)30', color: 'var(--accent)', cursor: 'pointer', opacity: indexing ? 0.5 : 1 }}>
              {icons.folder} Folder
            </button>
            <button onClick={handleAddFiles} disabled={indexing} style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4, padding: '5px 0', fontSize: 12, fontWeight: 500, borderRadius: 5, background: 'var(--bg-hover)', border: '1px solid var(--border-primary)', color: 'var(--text-secondary)', cursor: 'pointer', opacity: indexing ? 0.5 : 1 }}>
              {icons.file} Files
            </button>
          </div>

          <div style={{ flex: 1, overflow: 'auto', padding: 6 }}>
            {sources.map(src => (
              <div key={src.id}>
                <div
                  onClick={() => setExpandedSources(prev => { const s = new Set(prev); s.has(src.id) ? s.delete(src.id) : s.add(src.id); return s })}
                  style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 8px', borderRadius: 5, cursor: 'pointer', transition: 'background 0.1s', fontSize: 12, color: 'var(--text-primary)' }}
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
                    {src.git_branch && <div style={{ fontSize: 12, color: 'var(--text-tertiary)', padding: '2px 8px' }}>branch: {src.git_branch}</div>}
                    <div style={{ fontSize: 12, color: 'var(--text-tertiary)', padding: '2px 8px' }}>{src.file_count} files</div>
                    <button onClick={() => handleRemoveSource(src.id)} style={{ fontSize: 12, color: 'var(--error)', background: 'transparent', border: 'none', cursor: 'pointer', padding: '2px 8px' }}>Remove</button>
                  </div>
                )}
              </div>
            ))}
            {sources.length === 0 && !indexing && (
              <div style={{ fontSize: 12, color: 'var(--text-tertiary)', padding: '20px 10px', textAlign: 'center' }}>No sources added</div>
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
            {(['tree', 'docs', 'search', 'wiki', 'settings'] as const).map(tab => (
              <button key={tab} onClick={() => setActiveTab(tab)} style={{
                padding: '8px 14px', fontSize: 12, fontWeight: 500, background: 'transparent',
                border: 'none', borderBottom: activeTab === tab ? '2px solid var(--accent)' : '2px solid transparent',
                color: activeTab === tab ? 'var(--accent)' : 'var(--text-tertiary)', cursor: 'pointer', transition: 'all 0.15s',
                textTransform: 'capitalize'
              }}>
                {tab === 'tree' ? 'Folder Tree' : tab === 'docs' ? 'Documents' : tab === 'search' ? 'Search' : tab === 'wiki' ? 'Wiki' : 'Settings'}
              </button>
            ))}
          </div>

          {/* Wiki build progress — persistent across all tabs */}
          {wikiBuilding && wikiProgress && (
            <div style={{
              padding: '8px 14px', flexShrink: 0,
              background: 'var(--accent-muted)',
              borderBottom: '1px solid var(--accent)30',
              display: 'flex', alignItems: 'center', gap: 12
            }}>
              <div style={{ width: 12, height: 12, borderRadius: '50%', border: '2px solid var(--accent)', borderTopColor: 'transparent', animation: 'node-spin 1s linear infinite', flexShrink: 0 }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
                  <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent)' }}>Building Wiki</span>
                  {wikiProgress.total > 0 && (
                    <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>
                      Batch {wikiProgress.batch}/{wikiProgress.total} ({Math.round((wikiProgress.batch / wikiProgress.total) * 100)}%)
                    </span>
                  )}
                  <span style={{ fontSize: 10, color: 'var(--text-tertiary)', marginLeft: 'auto' }}>
                    {wikiProgress.entities} entities · {wikiProgress.relationships} relations
                  </span>
                </div>
                {wikiProgress.total > 0 && (
                  <div style={{ height: 3, background: 'var(--bg-primary)', borderRadius: 2, overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${(wikiProgress.batch / wikiProgress.total) * 100}%`, background: 'var(--accent)', borderRadius: 2, transition: 'width 0.3s' }} />
                  </div>
                )}
              </div>
              {wikiProgress.saved !== undefined && (
                <span style={{ fontSize: 10, color: wikiProgress.saved ? '#34d399' : 'var(--text-tertiary)', flexShrink: 0 }}>
                  {wikiProgress.saved ? '✓' : '⏭'}
                </span>
              )}
            </div>
          )}

          {/* Indexing progress — persistent across all tabs */}
          {indexing && indexProgress && (
            <div style={{
              padding: '6px 14px', flexShrink: 0,
              background: '#60a5fa10',
              borderBottom: '1px solid #60a5fa20',
              display: 'flex', alignItems: 'center', gap: 10
            }}>
              <div style={{ width: 10, height: 10, borderRadius: '50%', border: '2px solid #60a5fa', borderTopColor: 'transparent', animation: 'node-spin 1s linear infinite', flexShrink: 0 }} />
              <span style={{ fontSize: 11, color: '#60a5fa', fontWeight: 500 }}>Indexing</span>
              <span style={{ fontSize: 10, color: 'var(--text-tertiary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
                {indexProgress.fileName.split('/').pop()}
              </span>
              <span style={{ fontSize: 10, color: 'var(--text-tertiary)', flexShrink: 0 }}>
                {indexProgress.current}/{indexProgress.total}
              </span>
            </div>
          )}

          {/* Tab content */}
          <div style={{ flex: 1, overflow: 'auto', padding: 12 }}>
            {/* Tree tab */}
            {activeTab === 'tree' && (
              <div>
                {documents.length === 0 ? (
                  <div style={{ fontSize: 12, color: 'var(--text-tertiary)', padding: '40px 0', textAlign: 'center' }}>
                    No documents indexed yet. Add a folder or files to get started.
                  </div>
                ) : (
                  buildTree().map(node => <TreeNodeComponent key={node.path} node={node} expandedFolders={expandedFolders} setExpandedFolders={setExpandedFolders} onFileClick={openDocDetail} selectedDoc={selectedDoc} />)
                )}
              </div>
            )}

            {/* Docs tab */}
            {activeTab === 'docs' && (
              <div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 60px 70px 50px 60px', gap: 4, padding: '6px 8px', fontSize: 12, fontWeight: 600, color: 'var(--text-tertiary)', borderBottom: '1px solid var(--border-primary)', marginBottom: 4 }}>
                  <span>Name</span><span>Ext</span><span>Size</span><span>Chunks</span><span>Status</span>
                </div>
                {documents.map(doc => (
                  <div
                    key={doc.id}
                    onClick={() => loadChunks(doc.id)}
                    style={{
                      display: 'grid', gridTemplateColumns: '1fr 60px 70px 50px 60px', gap: 4, padding: '6px 8px', borderRadius: 4, cursor: 'pointer', fontSize: 12,
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
                  <button onClick={handleSearch} disabled={searching} style={{ padding: '7px 14px', fontSize: 12, fontWeight: 600, borderRadius: 6, background: 'var(--accent)', border: 'none', color: '#fff', cursor: 'pointer', opacity: searching ? 0.5 : 1 }}>
                    {searching ? '...' : 'Search'}
                  </button>
                </div>
                {searchResults.map(r => (
                  <div key={r.chunk_id} style={{ padding: '10px 12px', marginBottom: 6, background: 'var(--bg-card)', border: '1px solid var(--border-primary)', borderRadius: 6 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--accent)' }}>{r.doc_name}</span>
                      <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>{(r.hybrid_score * 100).toFixed(0)}%</span>
                    </div>
                    <pre style={{ fontSize: 12, color: 'var(--text-secondary)', margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 100, overflow: 'auto' }}>
                      {r.content.substring(0, 300)}{r.content.length > 300 ? '...' : ''}
                    </pre>
                  </div>
                ))}
                {searchResults.length === 0 && searchQuery && !searching && (
                  <div style={{ fontSize: 12, color: 'var(--text-tertiary)', padding: '40px 0', textAlign: 'center' }}>No results found</div>
                )}
              </div>
            )}

            {/* Wiki tab */}
            {activeTab === 'wiki' && (
              <KBWiki kbId={kbId} />
            )}

            {/* Settings tab */}
            {activeTab === 'settings' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                {/* Stats — full width */}
                <div style={{ padding: 12, background: 'var(--bg-card)', borderRadius: 6, border: '1px solid var(--border-primary)' }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 8 }}>Index Statistics</div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 8 }}>
                    {[
                      { label: 'Documents', value: stats.totalDocs },
                      { label: 'Indexed', value: stats.indexedDocs },
                      { label: 'Chunks', value: stats.totalChunks },
                      { label: 'Total Size', value: formatSize(stats.totalSize) }
                    ].map(s => (
                      <div key={s.label} style={{ padding: '8px 10px', background: 'var(--bg-primary)', borderRadius: 4 }}>
                        <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 2 }}>{s.label}</div>
                        <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary)' }}>{s.value}</div>
                      </div>
                    ))}
                  </div>
                  <div style={{ marginTop: 8 }}>
                    <div style={{ height: 6, background: 'var(--bg-primary)', borderRadius: 3, overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${stats.indexedPercent}%`, background: stats.indexedPercent === 100 ? '#34d399' : 'var(--accent)', borderRadius: 3, transition: 'width 0.3s' }} />
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 3 }}>{stats.indexedPercent}% indexed</div>
                  </div>
                </div>

                {/* 2-column grid */}
                {(() => {
                  return (
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                      {/* Left column */}
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                        {/* Chunking */}
                        <div style={{ padding: 12, background: 'var(--bg-card)', borderRadius: 6, border: '1px solid var(--border-primary)' }}>
                          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 10 }}>Chunking</div>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                            <div>
                              <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 4 }}>Strategy</div>
                              <select value={String(config.strategy || 'auto')} onChange={e => updateConfig('strategy', e.target.value)} style={{ width: '100%', padding: '6px 8px', fontSize: 12, background: 'var(--bg-input)', border: '1px solid var(--border-primary)', borderRadius: 5, color: 'var(--text-primary)', outline: 'none' }}>
                                <option value="auto">Auto (detect by file type)</option>
                                <option value="heading">Heading (markdown)</option>
                                <option value="paragraph">Paragraph</option>
                                <option value="character">Character</option>
                                <option value="code">Code (function/class)</option>
                              </select>
                            </div>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                              <div>
                                <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 4 }}>Chunk Size</div>
                                <input type="number" value={Number(config.chunkSize ?? 1000)} onChange={e => updateConfig('chunkSize', parseInt(e.target.value) || 1000)} style={{ width: '100%', padding: '6px 8px', fontSize: 12, background: 'var(--bg-input)', border: '1px solid var(--border-primary)', borderRadius: 5, color: 'var(--text-primary)', outline: 'none' }} />
                              </div>
                              <div>
                                <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 4 }}>Overlap</div>
                                <input type="number" value={Number(config.chunkOverlap ?? 200)} onChange={e => updateConfig('chunkOverlap', parseInt(e.target.value) || 200)} style={{ width: '100%', padding: '6px 8px', fontSize: 12, background: 'var(--bg-input)', border: '1px solid var(--border-primary)', borderRadius: 5, color: 'var(--text-primary)', outline: 'none' }} />
                              </div>
                            </div>
                            <div>
                              <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 4 }}>Min Chunk Size</div>
                              <input type="number" value={Number(config.minChunkSize ?? 100)} onChange={e => updateConfig('minChunkSize', parseInt(e.target.value) || 100)} style={{ width: '100%', padding: '6px 8px', fontSize: 12, background: 'var(--bg-input)', border: '1px solid var(--border-primary)', borderRadius: 5, color: 'var(--text-primary)', outline: 'none' }} />
                            </div>
                          </div>
                        </div>

                        {/* File Extraction */}
                        <div style={{ padding: 12, background: 'var(--bg-card)', borderRadius: 6, border: '1px solid var(--border-primary)' }}>
                          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 10 }}>File Extraction</div>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                            <div>
                              <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 4 }}>Max File Size</div>
                              <select value={String(config.maxFileSize ?? 1048576)} onChange={e => updateConfig('maxFileSize', parseInt(e.target.value))} style={{ width: '100%', padding: '6px 8px', fontSize: 12, background: 'var(--bg-input)', border: '1px solid var(--border-primary)', borderRadius: 5, color: 'var(--text-primary)', outline: 'none' }}>
                                <option value="262144">256 KB</option>
                                <option value="524288">512 KB</option>
                                <option value="1048576">1 MB</option>
                                <option value="2097152">2 MB</option>
                                <option value="5242880">5 MB</option>
                                <option value="10485760">10 MB</option>
                              </select>
                            </div>
                            <div>
                              <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 4 }}>Exclude Patterns (one per line)</div>
                              <textarea
                                value={Array.isArray(config.excludePatterns) ? (config.excludePatterns as string[]).join('\n') : 'node_modules\n.git\ndist\nout\nbuild\ncoverage\n__pycache__\n.venv\nvenv'}
                                onChange={e => updateConfig('excludePatterns', e.target.value.split('\n').filter(Boolean))}
                                rows={5}
                                style={{ width: '100%', padding: '6px 8px', fontSize: 12, fontFamily: 'monospace', background: 'var(--bg-input)', border: '1px solid var(--border-primary)', borderRadius: 5, color: 'var(--text-primary)', outline: 'none', resize: 'vertical' }}
                              />
                            </div>
                          </div>
                        </div>
                      </div>

                      {/* Right column */}
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                        {/* Search */}
                        <div style={{ padding: 12, background: 'var(--bg-card)', borderRadius: 6, border: '1px solid var(--border-primary)' }}>
                          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 10 }}>Search</div>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                            <div>
                              <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 4 }}>Vector Weight: {Number(config.vectorWeight ?? 0.6).toFixed(2)}</div>
                              <input type="range" min="0" max="1" step="0.05" value={Number(config.vectorWeight ?? 0.6)} onChange={e => updateConfig('vectorWeight', parseFloat(e.target.value))} style={{ width: '100%' }} />
                            </div>
                            <div>
                              <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 4 }}>BM25 Weight: {Number(config.bm25Weight ?? 0.4).toFixed(2)}</div>
                              <input type="range" min="0" max="1" step="0.05" value={Number(config.bm25Weight ?? 0.4)} onChange={e => updateConfig('bm25Weight', parseFloat(e.target.value))} style={{ width: '100%' }} />
                            </div>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                              <div>
                                <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 4 }}>Default Limit</div>
                                <input type="number" value={Number(config.defaultLimit ?? 10)} onChange={e => updateConfig('defaultLimit', parseInt(e.target.value) || 10)} style={{ width: '100%', padding: '6px 8px', fontSize: 12, background: 'var(--bg-input)', border: '1px solid var(--border-primary)', borderRadius: 5, color: 'var(--text-primary)', outline: 'none' }} />
                              </div>
                              <div>
                                <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 4 }}>Min Score: {Number(config.minScore ?? 0).toFixed(2)}</div>
                                <input type="range" min="0" max="1" step="0.05" value={Number(config.minScore ?? 0)} onChange={e => updateConfig('minScore', parseFloat(e.target.value))} style={{ width: '100%' }} />
                              </div>
                            </div>
                          </div>
                        </div>

                        {/* Embedding */}
                        <div style={{ padding: 12, background: 'var(--bg-card)', borderRadius: 6, border: '1px solid var(--border-primary)' }}>
                          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 10 }}>Embedding</div>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                              <div>
                                <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 4 }}>Model</div>
                                <div style={{ fontSize: 12, color: 'var(--text-primary)', fontWeight: 500 }}>multilingual-e5-small</div>
                              </div>
                              <div>
                                <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 4 }}>Dimension</div>
                                <div style={{ fontSize: 12, color: 'var(--text-primary)', fontWeight: 500 }}>384</div>
                              </div>
                            </div>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                              <div>
                                <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 4 }}>Status</div>
                                <div style={{ fontSize: 12, color: '#34d399', fontWeight: 500 }}>Local (offline)</div>
                              </div>
                              <div>
                                <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 4 }}>Cache</div>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                  <input type="checkbox" checked={config.embeddingCache !== false} onChange={e => updateConfig('embeddingCache', e.target.checked)} />
                                  <span style={{ fontSize: 12, color: 'var(--text-primary)' }}>Skip unchanged</span>
                                </div>
                              </div>
                            </div>
                          </div>
                        </div>

                        {/* Backup/Restore */}
                        <div style={{ padding: 12, background: 'var(--bg-card)', borderRadius: 6, border: '1px solid var(--border-primary)' }}>
                          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 8 }}>Backup & Restore</div>
                          <div style={{ display: 'flex', gap: 8 }}>
                            <button onClick={async () => {
                              const r = await window.api.kb.export(kbId) as { success: boolean; path?: string; error?: string }
                              if (r.success) message.success(`Exported to ${r.path}`)
                              else if (r.error) message.error(r.error)
                            }} style={{ flex: 1, padding: '6px 14px', fontSize: 12, borderRadius: 5, background: 'var(--accent-muted)', border: '1px solid var(--accent)30', color: 'var(--accent)', cursor: 'pointer', fontWeight: 500 }}>
                              Export .kb
                            </button>
                            <button onClick={async () => {
                              const r = await window.api.kb.import() as { success: boolean; kbId?: string; error?: string }
                              if (r.success) message.success('Imported successfully')
                              else if (r.error) message.error(r.error)
                            }} style={{ flex: 1, padding: '6px 14px', fontSize: 12, borderRadius: 5, background: 'var(--bg-hover)', border: '1px solid var(--border-primary)', color: 'var(--text-secondary)', cursor: 'pointer', fontWeight: 500 }}>
                              Import .kb
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  )
                })()}

                {/* Wiki Graph */}
                {(() => {
                  const wikiConfig = (config.wiki || {}) as Record<string, unknown>
                  const wikiEnabled = wikiConfig.enabled === true

                  return (
                    <div style={{ marginBottom: 16, padding: 12, background: 'var(--bg-card)', borderRadius: 6, border: '1px solid var(--border-primary)' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>Wiki Graph</div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Enable</span>
                          <input type="checkbox" checked={wikiEnabled} onChange={e => updateWikiConfig('enabled', e.target.checked)} />
                        </div>
                      </div>

                      {wikiEnabled && (
                        <>
                          <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 10 }}>
                            Build a knowledge graph from indexed documents using LLM. Extracts entities, relationships, and generates wiki pages.
                          </div>
                          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
                            <div>
                              <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 4 }}>Provider</div>
                              <select
                                value={String(wikiConfig.providerId || '')}
                                onChange={e => { updateWikiConfig('providerId', e.target.value); updateWikiConfig('model', '') }}
                                style={{ width: '100%', padding: '6px 8px', fontSize: 12, background: 'var(--bg-input)', border: '1px solid var(--border-primary)', borderRadius: 5, color: 'var(--text-primary)', outline: 'none' }}
                              >
                                <option value="">Select provider...</option>
                                {providers.map(p => (
                                  <option key={p.id} value={p.id}>{p.name} ({PROVIDER_LABELS[p.type]})</option>
                                ))}
                              </select>
                            </div>
                            <div>
                              <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 4 }}>Model</div>
                              {availableModels.length > 0 ? (
                                <select
                                  value={String(wikiConfig.model || '')}
                                  onChange={e => updateWikiConfig('model', e.target.value)}
                                  style={{ width: '100%', padding: '6px 8px', fontSize: 12, background: 'var(--bg-input)', border: '1px solid var(--border-primary)', borderRadius: 5, color: 'var(--text-primary)', outline: 'none' }}
                                >
                                  <option value="">Select model...</option>
                                  {availableModels.map(m => <option key={m} value={m}>{m}</option>)}
                                </select>
                              ) : (
                                <input
                                  value={String(wikiConfig.model || '')}
                                  onChange={e => updateWikiConfig('model', e.target.value)}
                                  placeholder="Type model name"
                                  style={{ width: '100%', padding: '6px 8px', fontSize: 12, background: 'var(--bg-input)', border: '1px solid var(--border-primary)', borderRadius: 5, color: 'var(--text-primary)', outline: 'none' }}
                                />
                              )}
                            </div>
                          </div>
                          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                            <button
                              onClick={async () => {
                                if (!wikiConfig.providerId) { message.error('Select a provider first'); return }
                                setWikiBuilding(true)
                                setWikiProgress({ batch: 0, total: 0, entities: 0, relationships: 0 })
                                const r = await window.api.wiki.build(kbId, { providerId: String(wikiConfig.providerId), model: String(wikiConfig.model || '') }) as { success?: boolean; entities?: number; relationships?: number; pages?: number; error?: string }
                                setWikiBuilding(false)
                                setWikiProgress(null)
                                if (r.success) message.success(`Wiki built: ${r.entities} entities, ${r.relationships} relations, ${r.pages} pages`)
                                else if (r.error) message.error(r.error)
                              }}
                              disabled={wikiBuilding}
                              style={{ padding: '6px 14px', fontSize: 12, borderRadius: 5, background: 'var(--accent-muted)', border: '1px solid var(--accent)30', color: 'var(--accent)', cursor: 'pointer', fontWeight: 500, opacity: wikiBuilding ? 0.5 : 1 }}
                            >
                              {wikiBuilding ? 'Building...' : 'Build Wiki'}
                            </button>
                            <button
                              onClick={async () => {
                                await window.api.wiki.delete(kbId)
                                message.success('Wiki deleted')
                              }}
                              disabled={wikiBuilding}
                              style={{ padding: '6px 14px', fontSize: 12, borderRadius: 5, background: 'var(--bg-hover)', border: '1px solid var(--border-primary)', color: 'var(--text-secondary)', cursor: 'pointer', fontWeight: 500, opacity: wikiBuilding ? 0.5 : 1 }}
                            >
                              Delete Wiki
                            </button>
                          </div>

                          {/* Wiki build progress */}
                          {wikiBuilding && wikiProgress && (
                            <div style={{ marginTop: 10, padding: '8px 10px', background: 'var(--bg-primary)', borderRadius: 5, border: '1px solid var(--border-primary)' }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                                <div style={{ width: 10, height: 10, borderRadius: '50%', border: '2px solid var(--accent)', borderTopColor: 'transparent', animation: 'node-spin 1s linear infinite' }} />
                                <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent)' }}>
                                  Building wiki...
                                </span>
                              </div>
                              {wikiProgress.total > 0 && (
                                <>
                                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                                    <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>
                                      Batch {wikiProgress.batch}/{wikiProgress.total}
                                    </span>
                                    <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>
                                      {Math.round((wikiProgress.batch / wikiProgress.total) * 100)}%
                                    </span>
                                  </div>
                                  <div style={{ height: 4, background: 'var(--bg-card)', borderRadius: 2, overflow: 'hidden', marginBottom: 6 }}>
                                    <div style={{ height: '100%', width: `${(wikiProgress.batch / wikiProgress.total) * 100}%`, background: 'var(--accent)', borderRadius: 2, transition: 'width 0.3s' }} />
                                  </div>
                                </>
                              )}
                              <div style={{ display: 'flex', gap: 12 }}>
                                <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>
                                  Entities: <strong style={{ color: 'var(--text-primary)' }}>{wikiProgress.entities}</strong>
                                </span>
                                <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>
                                  Relations: <strong style={{ color: 'var(--text-primary)' }}>{wikiProgress.relationships}</strong>
                                </span>
                                {wikiProgress.saved !== undefined && (
                                  <span style={{ fontSize: 10, color: wikiProgress.saved ? '#34d399' : 'var(--text-tertiary)' }}>
                                    {wikiProgress.saved ? '✓ saved' : '⏭ skipped'}
                                  </span>
                                )}
                              </div>
                              {wikiProgress.error && (
                                <div style={{ marginTop: 4, fontSize: 10, color: '#f87171' }}>
                                  Error: {wikiProgress.error}
                                </div>
                              )}
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  )
                })()}

                {/* MCP Server — full width */}
                <MCPSettings />

                {/* Danger Zone — full width */}
                <div style={{ padding: 12, background: 'var(--bg-card)', borderRadius: 6, border: '1px solid #f8717130' }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#f87171', marginBottom: 8 }}>Danger Zone</div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button onClick={async () => {
                      if (!confirm('Reindex all documents? This will delete all existing chunks and re-process every file.')) return
                      message.info('Reindex started...')
                    }} style={{ padding: '6px 14px', fontSize: 12, borderRadius: 5, background: '#fbbf2420', border: '1px solid #fbbf2430', color: '#fbbf24', cursor: 'pointer', fontWeight: 500 }}>
                      Reindex All
                    </button>
                    <button onClick={async () => {
                      if (!confirm('Delete this knowledge base? This cannot be undone.')) return
                      await window.api.kb.delete(kbId)
                      message.success('Deleted')
                    }} style={{ padding: '6px 14px', fontSize: 12, borderRadius: 5, background: '#f8717120', border: '1px solid #f8717130', color: '#f87171', cursor: 'pointer', fontWeight: 500 }}>
                      Delete KB
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Chunks preview panel */}
          {selectedDoc && chunks.length > 0 && (activeTab === 'tree' || activeTab === 'docs') && (
            <div style={{ height: 200, borderTop: '1px solid var(--border-primary)', overflow: 'auto', padding: 10, flexShrink: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 6 }}>
                Chunks ({chunks.length})
              </div>
              {chunks.map(ch => {
                let meta: Record<string, unknown> = {}
                try { meta = JSON.parse(ch.metadata_json || '{}') } catch {}
                return (
                  <div key={ch.id} style={{ padding: '6px 8px', marginBottom: 4, background: 'var(--bg-card)', borderRadius: 4, border: '1px solid var(--border-primary)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                      <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--accent)' }}>
                        #{ch.chunk_index} {(meta.heading as string) ? `· ${meta.heading}` : ''}
                      </span>
                      <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
                        L{(meta.lineStart as number) || 0}-{(meta.lineEnd as number) || 0}
                      </span>
                    </div>
                    <pre style={{ fontSize: 12, color: 'var(--text-secondary)', margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 50, overflow: 'hidden' }}>
                      {ch.content.substring(0, 200)}
                    </pre>
                  </div>
                )
              })}
            </div>
           )}
        </div>
      </div>

      {/* File Detail Popup */}
      {detailDoc && (
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 1000,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(3px)'
          }}
          onMouseDown={e => { if (e.target === e.currentTarget) setDetailDoc(null) }}
        >
          <div style={{
            width: '70vw', maxHeight: '80vh',
            background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)',
            borderRadius: 10, boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
            display: 'flex', flexDirection: 'column', overflow: 'hidden'
          }}>
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 16px', borderBottom: '1px solid var(--border-primary)', flexShrink: 0 }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>{detailDoc.name}</div>
                <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 2 }}>{detailDoc.path}</div>
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{detailDoc.extension || '—'}</span>
                <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{formatSize(detailDoc.size)}</span>
                <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{detailDoc.chunk_count} chunks</span>
                {statusBadge(detailDoc.status)}
                <button onClick={() => setDetailDoc(null)} style={{ width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)', borderRadius: 6, fontSize: 18 }}>
                  ×
                </button>
              </div>
            </div>

            {/* Content preview */}
            {detailDoc.content_preview && (
              <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border-primary)', flexShrink: 0, maxHeight: 120, overflow: 'auto' }}>
                <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-tertiary)', marginBottom: 4 }}>Content Preview</div>
                <pre style={{ fontSize: 11, color: 'var(--text-secondary)', margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'inherit' }}>
                  {detailDoc.content_preview}
                </pre>
              </div>
            )}

            {/* Chunks */}
            <div style={{ flex: 1, overflow: 'auto', padding: 12 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 8 }}>
                Chunks ({detailChunks.length})
              </div>
              {detailLoading ? (
                <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}><Spin /></div>
              ) : detailChunks.length === 0 ? (
                <div style={{ fontSize: 12, color: 'var(--text-tertiary)', padding: '20px 0', textAlign: 'center' }}>No chunks</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {detailChunks.map(ch => {
                    let meta: Record<string, unknown> = {}
                    try { meta = JSON.parse(ch.metadata_json || '{}') } catch {}
                    return (
                      <div key={ch.id} style={{ padding: '8px 10px', background: 'var(--bg-card)', borderRadius: 6, border: '1px solid var(--border-primary)' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                          <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--accent)' }}>
                            Chunk #{ch.chunk_index} {(meta.heading as string) ? `· ${meta.heading}` : ''}
                          </span>
                          <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>
                            L{(meta.lineStart as number) || 0}–{(meta.lineEnd as number) || 0}
                          </span>
                        </div>
                        <pre style={{ fontSize: 11, color: 'var(--text-secondary)', margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 120, overflow: 'auto', fontFamily: 'inherit' }}>
                          {ch.content}
                        </pre>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
