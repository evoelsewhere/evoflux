export interface UnifiedDiffLine {
  type: 'add' | 'del' | 'ctx' | 'info'
  content: string
}

export interface UnifiedDiffHunk {
  header: string
  oldStart: number
  newStart: number
  lines: UnifiedDiffLine[]
}

/** Parse the bounded unified patches returned by local Git and review providers. */
export function parseUnifiedDiff(raw: string): UnifiedDiffHunk[] {
  if (!raw) return []
  const hunks: UnifiedDiffHunk[] = []
  let current: UnifiedDiffHunk | null = null

  for (const line of raw.split('\n')) {
    if (line.startsWith('@@ ')) {
      const match = line.match(/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$/)
      if (match) {
        current = {
          header: line,
          oldStart: Number.parseInt(match[1], 10),
          newStart: Number.parseInt(match[3], 10),
          lines: [],
        }
        hunks.push(current)
      }
      continue
    }
    if (!current) continue
    if (line.startsWith('-')) {
      current.lines.push({ type: 'del', content: line.slice(1) })
    } else if (line.startsWith('+')) {
      current.lines.push({ type: 'add', content: line.slice(1) })
    } else if (line.startsWith(' ')) {
      current.lines.push({ type: 'ctx', content: line.slice(1) })
    } else if (line.startsWith('\\')) {
      current.lines.push({ type: 'info', content: line })
    }
  }
  return hunks
}
