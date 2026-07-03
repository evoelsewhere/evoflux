import { useState, memo } from 'react'

export interface DiffLine {
  type: 'add' | 'remove' | 'context'
  oldNum: number | null
  newNum: number | null
  content: string
}

export interface FileDiffData {
  path: string
  oldContent: string | null
  newContent: string
  added: number
  removed: number
}

function computeDiffLines(oldText: string, newText: string): DiffLine[] {
  const oldLines = oldText.split('\n')
  const newLines = newText.split('\n')
  const lines: DiffLine[] = []

  const maxLen = Math.max(oldLines.length, newLines.length)
  let oldIdx = 0
  let newIdx = 0

  const lcs = buildLCS(oldLines, newLines)
  let lcsIdx = 0

  while (oldIdx < oldLines.length || newIdx < newLines.length) {
    if (lcsIdx < lcs.length && oldIdx < oldLines.length && newIdx < newLines.length && oldLines[oldIdx] === lcs[lcsIdx] && newLines[newIdx] === lcs[lcsIdx]) {
      lines.push({ type: 'context', oldNum: oldIdx + 1, newNum: newIdx + 1, content: oldLines[oldIdx] })
      oldIdx++; newIdx++; lcsIdx++
    } else if (oldIdx < oldLines.length && (lcsIdx >= lcs.length || oldLines[oldIdx] !== lcs[lcsIdx])) {
      lines.push({ type: 'remove', oldNum: oldIdx + 1, newNum: null, content: oldLines[oldIdx] })
      oldIdx++
    } else if (newIdx < newLines.length) {
      lines.push({ type: 'add', oldNum: null, newNum: newIdx + 1, content: newLines[newIdx] })
      newIdx++
    } else {
      break
    }
  }

  return lines
}

function buildLCS(a: string[], b: string[]): string[] {
  const m = a.length; const n = b.length
  if (m === 0 || n === 0) return []
  if (m * n > 500000) {
    const set = new Set(a)
    return b.filter(l => set.has(l))
  }
  const dp: number[][] = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0))
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      dp[i][j] = a[i - 1] === b[j - 1] ? dp[i - 1][j - 1] + 1 : Math.max(dp[i - 1][j], dp[i][j - 1])
    }
  }
  const result: string[] = []
  let i = m, j = n
  while (i > 0 && j > 0) {
    if (a[i - 1] === b[j - 1]) { result.unshift(a[i - 1]); i--; j-- }
    else if (dp[i - 1][j] >= dp[i][j - 1]) i--
    else j--
  }
  return result
}

function DiffHunk({ lines }: { lines: DiffLine[] }) {
  return (
    <div style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace", fontSize: 11, lineHeight: '18px' }}>
      {lines.map((line, idx) => {
        const bg = line.type === 'add' ? '#1a3a2a' : line.type === 'remove' ? '#3a1a1a' : 'transparent'
        const bgLight = line.type === 'add' ? '#e6ffec' : line.type === 'remove' ? '#ffebe9' : 'transparent'
        const color = line.type === 'add' ? '#3fb950' : line.type === 'remove' ? '#f85149' : 'var(--text-secondary)'
        const prefix = line.type === 'add' ? '+' : line.type === 'remove' ? '-' : ' '
        return (
          <div key={idx} style={{ display: 'flex', background: `var(--theme-mode, ${bg})`, borderLeft: line.type === 'add' ? '3px solid #3fb950' : line.type === 'remove' ? '3px solid #f85149' : '3px solid transparent' }}>
            <span style={{ width: 40, textAlign: 'right', paddingRight: 6, color: 'var(--text-tertiary)', userSelect: 'none', flexShrink: 0, opacity: 0.6 }}>
              {line.oldNum ?? ''}
            </span>
            <span style={{ width: 40, textAlign: 'right', paddingRight: 6, color: 'var(--text-tertiary)', userSelect: 'none', flexShrink: 0, opacity: 0.6 }}>
              {line.newNum ?? ''}
            </span>
            <span style={{ width: 16, textAlign: 'center', color, flexShrink: 0, fontWeight: 600, userSelect: 'none' }}>
              {prefix}
            </span>
            <span style={{ flex: 1, color: line.type === 'context' ? 'var(--text-secondary)' : color, whiteSpace: 'pre', overflow: 'hidden', paddingLeft: 4 }}>
              {line.content || ' '}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function DiffViewerInner({ diff }: { diff: FileDiffData }) {
  const [expanded, setExpanded] = useState(true)
  const lines = computeDiffLines(diff.oldContent || '', diff.newContent)
  const ext = diff.path.split('.').pop() || ''

  return (
    <div style={{
      border: '1px solid var(--border-primary)', borderRadius: 8,
      overflow: 'hidden', marginBottom: 8
    }}>
      <div
        role="button"
        tabIndex={0}
        onClick={() => setExpanded(!expanded)}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpanded(!expanded) } }}
        style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '8px 12px', cursor: 'pointer',
          background: 'var(--bg-card)', borderBottom: expanded ? '1px solid var(--border-primary)' : 'none',
          userSelect: 'none'
        }}
      >
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" style={{ transform: expanded ? 'rotate(90deg)' : 'rotate(0)', transition: 'transform 0.15s', flexShrink: 0 }}>
          <path d="M3 1L7 5L3 9" stroke="var(--text-tertiary)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style={{ flexShrink: 0 }}>
          <path d="M3 2h5l3 3v7H3V2z" stroke="var(--text-tertiary)" strokeWidth="1.1" strokeLinejoin="round" />
          <path d="M8 2v3h3" stroke="var(--text-tertiary)" strokeWidth="1.1" strokeLinejoin="round" />
        </svg>
        <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-primary)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {diff.path}
        </span>
        {diff.oldContent === null && (
          <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 3, background: '#3fb95020', color: '#3fb950', fontWeight: 600 }}>NEW</span>
        )}
        <span style={{ fontSize: 10, color: '#3fb950', flexShrink: 0 }}>+{diff.added}</span>
        <span style={{ fontSize: 10, color: '#f85149', flexShrink: 0 }}>-{diff.removed}</span>
      </div>
      {expanded && (
        <div style={{ maxHeight: 400, overflow: 'auto', background: 'var(--bg-primary)' }}>
          <DiffHunk lines={lines} />
        </div>
      )}
    </div>
  )
}

export function DiffFileList({ diffs }: { diffs: FileDiffData[] }) {
  if (!diffs || diffs.length === 0) return null
  const totalAdded = diffs.reduce((s, d) => s + d.added, 0)
  const totalRemoved = diffs.reduce((s, d) => s + d.removed, 0)

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)' }}>
          {diffs.length} file{diffs.length > 1 ? 's' : ''} changed
        </span>
        <span style={{ fontSize: 10, color: '#3fb950' }}>+{totalAdded}</span>
        <span style={{ fontSize: 10, color: '#f85149' }}>-{totalRemoved}</span>
      </div>
      {diffs.map((d, i) => <DiffViewerInner key={i} diff={d} />)}
    </div>
  )
}

export default memo(DiffViewerInner)
