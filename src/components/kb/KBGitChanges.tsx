import { useState, useEffect, useCallback } from 'react'
import { Spin, message } from 'antd'
import { diffLines, type Change } from 'diff'

const icons = {
  sync: <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M1 6C1 3.2 3.2 1 6 1C8.2 1 10.1 2.4 10.8 4.5M11 6C11 8.8 8.8 11 6 11C3.8 11 1.9 9.6 1.2 7.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" /><path d="M10 1.5V4.5H7M2 10.5V7.5H5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" /></svg>,
  close: <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M3 3L9 9M9 3L3 9" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" /></svg>,
  chevDown: <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M2 4L5 7L8 4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" /></svg>,
  chevRight: <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M4 2L7 5L4 8" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" /></svg>,
}

interface ChangedFile {
  status: 'M' | 'A' | 'D' | 'R' | 'C' | '?'
  path: string
}

interface GitChangesProps {
  kbId: string
  sourceId: string
  onSyncComplete?: () => void
}

export default function KBGitChanges({ kbId, sourceId, onSyncComplete }: GitChangesProps) {
  const [changes, setChanges] = useState<ChangedFile[]>([])
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [diffFile, setDiffFile] = useState<string | null>(null)
  const [diffContent, setDiffContent] = useState<string>('')
  const [diffLoading, setDiffLoading] = useState(false)
  const [commitInfo, setCommitInfo] = useState<{ commitHash?: string; branch?: string }>({})

  const loadStatus = useCallback(async () => {
    try {
      const result = await window.api.kb.getGitStatus(sourceId) as { changes?: ChangedFile[]; commitHash?: string; branch?: string; error?: string }
      if (result.error) { setLoading(false); return }
      setChanges(result.changes || [])
      setCommitInfo({ commitHash: result.commitHash, branch: result.branch })
    } catch { /* */ }
    finally { setLoading(false) }
  }, [sourceId])

  useEffect(() => { loadStatus() }, [loadStatus])

  const handleSync = async () => {
    setSyncing(true)
    try {
      const result = await window.api.kb.syncSource(kbId, sourceId) as { filesChanged?: number; chunksAdded?: number; error?: string }
      if (result.error) { message.error(result.error); return }
      message.success(`Synced: ${result.filesChanged || 0} files, +${result.chunksAdded || 0} chunks`)
      await loadStatus()
      onSyncComplete?.()
    } catch { message.error('Sync failed') }
    finally { setSyncing(false) }
  }

  const handleViewDiff = async (filePath: string) => {
    if (diffFile === filePath) { setDiffFile(null); return }
    setDiffFile(filePath)
    setDiffLoading(true)
    try {
      const diff = await window.api.kb.getFileDiff(sourceId, filePath) as string
      setDiffContent(diff)
    } catch { setDiffContent('Failed to load diff') }
    finally { setDiffLoading(false) }
  }

  const statusLabel = (s: string) => {
    switch (s) {
      case 'M': return { text: 'Modified', color: '#fbbf24' }
      case 'A': return { text: 'Added', color: '#34d399' }
      case 'D': return { text: 'Deleted', color: '#f87171' }
      default: return { text: s, color: 'var(--text-tertiary)' }
    }
  }

  const renderDiff = (diffText: string) => {
    if (!diffText) return <div style={{ fontSize: 11, color: 'var(--text-tertiary)', padding: 8 }}>No diff available</div>

    const lines = diffText.split('\n')
    return (
      <pre style={{ fontSize: 10, fontFamily: 'monospace', margin: 0, padding: 8, maxHeight: 250, overflow: 'auto', background: 'var(--bg-primary)', borderRadius: 4 }}>
        {lines.map((line, i) => {
          let color = 'var(--text-secondary)'
          let bg = 'transparent'
          if (line.startsWith('+') && !line.startsWith('+++')) { color = '#34d399'; bg = '#34d39910' }
          else if (line.startsWith('-') && !line.startsWith('---')) { color = '#f87171'; bg = '#f8717110' }
          else if (line.startsWith('@@')) { color = '#60a5fa'; bg = '#60a5fa10' }
          return <div key={i} style={{ color, background: bg, padding: '0 4px', borderRadius: 2 }}>{line || ' '}</div>
        })}
      </pre>
    )
  }

  if (loading) return <div style={{ padding: 12, display: 'flex', justifyContent: 'center' }}><Spin size="small" /></div>

  if (changes.length === 0) {
    return (
      <div style={{ padding: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)' }}>Git</span>
          {commitInfo.branch && <span style={{ fontSize: 9, color: 'var(--text-tertiary)' }}>{commitInfo.branch} @ {commitInfo.commitHash}</span>}
        </div>
        <div style={{ fontSize: 11, color: '#34d399', display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#34d399' }} />
          Up to date — no changes
        </div>
      </div>
    )
  }

  return (
    <div style={{ padding: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)' }}>Git Changes</span>
          <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 3, background: '#fbbf2420', color: '#fbbf24', fontWeight: 600 }}>{changes.length}</span>
        </div>
        {commitInfo.branch && <span style={{ fontSize: 9, color: 'var(--text-tertiary)' }}>{commitInfo.branch} @ {commitInfo.commitHash}</span>}
      </div>

      <button
        onClick={handleSync}
        disabled={syncing}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5,
          padding: '6px 0', marginBottom: 8, fontSize: 11, fontWeight: 600, borderRadius: 5,
          background: 'var(--accent)', border: 'none', color: '#fff', cursor: 'pointer',
          opacity: syncing ? 0.5 : 1
        }}
      >
        {syncing ? <Spin size="small" /> : icons.sync}
        {syncing ? 'Syncing...' : `Sync ${changes.length} files`}
      </button>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        {changes.map(cf => {
          const { text, color } = statusLabel(cf.status)
          return (
            <div key={cf.path}>
              <div
                onClick={() => handleViewDiff(cf.path)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 6, padding: '5px 8px', borderRadius: 4,
                  cursor: 'pointer', fontSize: 10, transition: 'background 0.1s'
                }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              >
                <span style={{ transform: diffFile === cf.path ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s', display: 'flex' }}>{icons.chevRight}</span>
                <span style={{ fontSize: 9, fontWeight: 700, color, minWidth: 12 }}>{cf.status}</span>
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text-secondary)' }}>{cf.path}</span>
              </div>

              {diffFile === cf.path && (
                <div style={{ marginLeft: 20, marginTop: 2, marginBottom: 4 }}>
                  {diffLoading ? <Spin size="small" /> : renderDiff(diffContent)}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
