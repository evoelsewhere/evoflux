import { memo, useState, useCallback, useRef, useEffect } from 'react'
import { type NodeProps, useReactFlow } from 'reactflow'

function CommentNode({ id, data, selected }: NodeProps) {
  const { setNodes } = useReactFlow()
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(String(data.text || 'Double-click to edit...'))
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setText(String(data.text || 'Double-click to edit...'))
  }, [data.text])

  const saveText = useCallback(() => {
    setEditing(false)
    setNodes(prev => prev.map(n => n.id === id ? { ...n, data: { ...n.data, text, config: { ...((n.data as Record<string, unknown>).config as Record<string, unknown> || {}), text } } } : n))
  }, [id, text, setNodes])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { setText(String(data.text || '')); setEditing(false) }
    if ((e.metaKey || e.ctrlKey) && e.key === 's') { e.preventDefault(); saveText() }
  }, [data.text, saveText])

  useEffect(() => {
    if (editing && textareaRef.current && containerRef.current) {
      const container = containerRef.current
      textareaRef.current.style.height = container.clientHeight + 'px'
      textareaRef.current.focus()
      textareaRef.current.selectionStart = textareaRef.current.value.length
    }
  }, [editing])

  const nodeStyle: React.CSSProperties = {
    background: 'var(--warning-muted)',
    border: `1.5px solid ${selected ? 'var(--warning)' : 'transparent'}`,
    borderRadius: 6,
    padding: '6px 10px',
    minWidth: 120,
    maxWidth: 250,
    minHeight: 40,
    cursor: editing ? 'text' : 'pointer',
    boxShadow: selected ? '0 0 0 2px var(--warning-muted)' : 'var(--shadow-sm)'
  }

  return (
    <div ref={containerRef} style={nodeStyle} onDoubleClick={() => setEditing(true)}>
      {editing ? (
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={saveText}
          onKeyDown={handleKeyDown}
          style={{
            width: '100%', height: '100%', background: 'transparent',
            border: 'none', outline: 'none', resize: 'none',
            color: 'var(--text-primary)', fontSize: 11, fontFamily: 'inherit',
            lineHeight: '16px', padding: 0, margin: 0, overflow: 'hidden'
          }}
        />
      ) : (
        <div style={{
          color: 'var(--text-primary)', fontSize: 11, lineHeight: '16px',
          whiteSpace: 'pre-wrap', wordBreak: 'break-word'
        }}>
          {text || 'Double-click to edit...'}
        </div>
      )}
      <div style={{
        fontSize: 8, color: 'var(--text-tertiary)', marginTop: 4,
        textAlign: 'right', fontStyle: 'italic'
      }}>
        comment
      </div>
    </div>
  )
}

export default memo(CommentNode)
