import { useState, useMemo, useCallback } from 'react'
import Editor from '@monaco-editor/react'
import { message } from 'antd'
import { useTheme } from './ThemeProvider'
import type { Node, Edge } from 'reactflow'

interface CodeEditorProps {
  nodes: Node[]
  edges: Edge[]
  onApply?: (nodes: Node[], edges: Edge[]) => void
}

function serialize(nodes: Node[], edges: Edge[]): string {
  return JSON.stringify({
    name: 'workflow', version: '1.0',
    nodes: nodes.map((n) => ({
      id: n.id, type: n.type, position: n.position,
      data: { label: n.data.label, type: n.data.type, icon: n.data.icon, category: n.data.category, config: n.data.config, text: n.data.text }
    })),
    edges: edges.map((e) => ({
      id: e.id, source: e.source, target: e.target,
      sourceHandle: e.sourceHandle, targetHandle: e.targetHandle,
      type: e.type, animated: e.animated, label: e.label
    }))
  }, null, 2)
}

export default function CodeEditor({ nodes, edges, onApply }: CodeEditorProps) {
  const { mode } = useTheme()
  const initial = useMemo(() => serialize(nodes, edges), [nodes, edges])
  const [code, setCode] = useState(initial)
  const [dirty, setDirty] = useState(false)

  const handleChange = useCallback((v: string | undefined) => {
    setCode(v || '')
    setDirty(v !== initial)
  }, [initial])

  const handleApply = useCallback(() => {
    try {
      const parsed = JSON.parse(code)
      if (!Array.isArray(parsed.nodes)) throw new Error('Missing nodes array')
      if (!Array.isArray(parsed.edges)) throw new Error('Missing edges array')

      const parsedNodes: Node[] = parsed.nodes.map((n: Record<string, unknown>) => ({
        id: String(n.id),
        type: n.type === 'comment' ? 'comment' : 'default',
        position: (n.position as { x: number; y: number }) || { x: 0, y: 0 },
        data: {
          label: String((n.data as Record<string, unknown>)?.label || (n as Record<string, unknown>).label || 'Node'),
          type: String((n.data as Record<string, unknown>)?.type || 'default'),
          icon: (n.data as Record<string, unknown>)?.icon as string,
          category: (n.data as Record<string, unknown>)?.category as string,
          config: ((n.data as Record<string, unknown>)?.config || (n as Record<string, unknown>).config || {}) as Record<string, unknown>,
          text: (n.data as Record<string, unknown>)?.text as string
        }
      }))

      const parsedEdges: Edge[] = parsed.edges.map((e: Record<string, unknown>) => ({
        id: String(e.id),
        source: String(e.source),
        target: String(e.target),
        sourceHandle: e.sourceHandle as string | undefined,
        targetHandle: e.targetHandle as string | undefined,
        type: String(e.type || 'custom'),
        animated: e.animated !== false
      }))

      onApply?.(parsedNodes, parsedEdges)
      setDirty(false)
      message.success('Applied')
    } catch (err) {
      message.error(`Invalid JSON: ${(err as Error).message}`)
    }
  }, [code, onApply])

  const handleReset = useCallback(() => {
    setCode(initial)
    setDirty(false)
  }, [initial])

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{
        padding: '8px 16px', background: 'var(--bg-secondary)',
        borderBottom: '1px solid var(--border-primary)',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center'
      }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)' }}>Workflow JSON</span>
        <div style={{ display: 'flex', gap: 6 }}>
          {dirty && (
            <button onClick={handleReset} aria-label="Reset changes" style={{
              padding: '3px 10px', fontSize: 11, borderRadius: 5, cursor: 'pointer',
              background: 'transparent', border: '1px solid var(--border-secondary)',
              color: 'var(--text-secondary)', fontWeight: 500, transition: 'all 0.1s'
            }} onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-hover)' }}
               onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}>
              Reset
            </button>
          )}
          <button onClick={handleApply} aria-label="Apply changes" style={{
            padding: '3px 10px', fontSize: 11, borderRadius: 5, cursor: 'pointer',
            background: dirty ? 'var(--accent)' : 'var(--bg-hover)',
            border: 'none', color: dirty ? '#fff' : 'var(--text-tertiary)',
            fontWeight: 500, transition: 'all 0.1s'
          }}>
            Apply
          </button>
        </div>
      </div>
      <div style={{ flex: 1 }}>
        <Editor
          height="100%"
          defaultLanguage="json"
          value={code}
          onChange={handleChange}
          theme={mode === 'dark' ? 'vs-dark' : 'vs'}
          options={{
            minimap: { enabled: false },
            fontSize: 12,
            lineNumbers: 'on',
            scrollBeyondLastLine: false,
            wordWrap: 'on',
            padding: { top: 12 },
            lineDecorationsWidth: 0,
            lineNumbersMinChars: 3,
            tabSize: 2
          }}
        />
      </div>
    </div>
  )
}
