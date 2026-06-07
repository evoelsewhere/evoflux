import { memo, useState } from 'react'
import { type NodeProps } from 'reactflow'

function CommentNode({ data, selected }: NodeProps) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(String(data.text || 'Double-click to edit...'))

  return (
    <div
      style={{
        background: 'var(--warning-muted)',
        border: `1.5px solid ${selected ? 'var(--warning)' : 'transparent'}`,
        borderRadius: 8,
        padding: '10px 14px',
        minWidth: 150,
        maxWidth: 250,
        minHeight: 60,
        cursor: editing ? 'text' : 'pointer',
        boxShadow: selected ? '0 0 0 3px var(--warning-muted)' : 'var(--shadow-sm)'
      }}
      onDoubleClick={() => setEditing(true)}
      onBlur={() => setEditing(false)}
    >
      {editing ? (
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          autoFocus
          style={{
            width: '100%', minHeight: 40, background: 'transparent',
            border: 'none', outline: 'none', resize: 'vertical',
            color: 'var(--text-primary)', fontSize: 12, fontFamily: 'inherit',
            lineHeight: '18px'
          }}
        />
      ) : (
        <div style={{
          color: 'var(--text-primary)', fontSize: 12, lineHeight: '18px',
          whiteSpace: 'pre-wrap', wordBreak: 'break-word'
        }}>
          {text}
        </div>
      )}
      <div style={{
        fontSize: 9, color: 'var(--text-tertiary)', marginTop: 6,
        textAlign: 'right', fontStyle: 'italic'
      }}>
        comment
      </div>
    </div>
  )
}

export default memo(CommentNode)
