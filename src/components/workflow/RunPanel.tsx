import { useEffect, useRef, useState, memo } from 'react'
import { Spin } from 'antd'
import type { NodeData } from '../../types/workflow'
import type { Node } from 'reactflow'

export interface RunEvent {
  type: string
  nodeId?: string
  timestamp: number
  content?: string
  output?: Record<string, unknown>
  error?: Error | string
}

interface RunPanelProps {
  events: RunEvent[]
  nodes: Node<NodeData>[]
  nodeStatuses: Record<string, 'idle' | 'running' | 'completed' | 'error'>
  nodeOutputs: Record<string, unknown>
  isRunning: boolean
  elapsed: number
  onStop: () => void
  onClose: () => void
  onNodeClick: (nodeId: string) => void
}

const STATUS_CONFIG = {
  idle: { color: 'var(--text-tertiary)', icon: '○', label: 'Pending' },
  running: { color: '#60a5fa', icon: '◉', label: 'Running' },
  completed: { color: '#34d399', icon: '●', label: 'Done' },
  error: { color: '#f87171', icon: '✕', label: 'Error' }
}

function formatElapsed(ms: number): string {
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  return `${m}m ${s % 60}s`
}

function OutputPreview({ output }: { output: unknown }) {
  if (!output) return null
  const str = typeof output === 'string' ? output : JSON.stringify(output, null, 2)
  const truncated = str.length > 300 ? str.substring(0, 300) + '...' : str
  return (
    <div style={{
      marginTop: 6, padding: '6px 8px',
      background: 'var(--bg-input)', borderRadius: 6,
      fontSize: 10, fontFamily: "'JetBrains Mono', monospace",
      color: 'var(--text-secondary)', maxHeight: 120, overflow: 'auto',
      whiteSpace: 'pre-wrap', wordBreak: 'break-all', lineHeight: '15px'
    }}>
      {truncated}
    </div>
  )
}

function RunPanelInner({ events, nodes, nodeStatuses, nodeOutputs, isRunning, elapsed, onStop, onClose, onNodeClick }: RunPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [showLog, setShowLog] = useState(false)

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [events])

  const totalNodes = nodes.filter(n => n.data.type !== 'comment').length
  const completedCount = Object.values(nodeStatuses).filter(s => s === 'completed').length
  const errorCount = Object.values(nodeStatuses).filter(s => s === 'error').length
  const progress = totalNodes > 0 ? (completedCount / totalNodes) * 100 : 0

  const lastEvent = events.length > 0 ? events[events.length - 1] : null
  const statusText = isRunning
    ? `Running ${completedCount}/${totalNodes} nodes`
    : errorCount > 0
      ? `Failed at ${errorCount} node`
      : completedCount === totalNodes && totalNodes > 0
        ? 'Completed successfully'
        : 'Ready'

  return (
    <div style={{
      background: 'var(--bg-secondary)',
      display: 'flex', flexDirection: 'column',
      height: '100%', overflow: 'hidden'
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 14px', borderBottom: '1px solid var(--border-primary)', flexShrink: 0
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 8, height: 8, borderRadius: '50%',
            background: isRunning ? '#60a5fa' : errorCount > 0 ? '#f87171' : completedCount === totalNodes && totalNodes > 0 ? '#34d399' : 'var(--text-tertiary)',
            boxShadow: isRunning ? '0 0 8px #60a5fa' : 'none',
            animation: isRunning ? 'pulse 1.5s infinite' : 'none'
          }} />
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>Run</span>
          <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{formatElapsed(elapsed)}</span>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          {isRunning && (
            <button onClick={onStop} style={{
              padding: '4px 12px', fontSize: 11, borderRadius: 5, cursor: 'pointer',
              background: '#f8717120', border: '1px solid #f8717140', color: '#f87171', fontWeight: 500
            }}>
              Stop
            </button>
          )}
          <button onClick={onClose} style={{
            width: 24, height: 24, display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)',
            borderRadius: 4, fontSize: 14, lineHeight: 1
          }}>×</button>
        </div>
      </div>

      {/* Progress bar */}
      <div style={{ padding: '0 14px', flexShrink: 0 }}>
        <div style={{ height: 3, background: 'var(--border-primary)', borderRadius: 2, marginTop: 8 }}>
          <div style={{
            height: '100%', borderRadius: 2, width: `${progress}%`,
            background: errorCount > 0 ? '#f87171' : '#34d399',
            transition: 'width 0.3s ease'
          }} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, marginBottom: 8 }}>
          <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>{statusText}</span>
          <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>{Math.round(progress)}%</span>
        </div>
      </div>

      {/* Node list */}
      <div style={{ flex: 1, overflow: 'auto', padding: '0 14px' }}>
        {nodes.filter(n => n.data.type !== 'comment').map((node) => {
          const status = nodeStatuses[node.id] || 'idle'
          const cfg = STATUS_CONFIG[status]
          const isSelected = selectedNodeId === node.id
          const hasOutput = nodeOutputs[node.id] !== undefined
          return (
            <div key={node.id}>
              <div
                onClick={() => { setSelectedNodeId(isSelected ? null : node.id); onNodeClick(node.id) }}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  padding: '6px 8px', borderRadius: 6, cursor: 'pointer',
                  background: isSelected ? 'var(--bg-hover)' : 'transparent',
                  transition: 'background 0.1s', marginBottom: 1
                }}
                onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = 'var(--bg-hover)' }}
                onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = 'transparent' }}
              >
                <span style={{ fontSize: 10, color: cfg.color, width: 14, textAlign: 'center', flexShrink: 0, animation: status === 'running' ? 'pulse 1s infinite' : 'none' }}>
                  {cfg.icon}
                </span>
                <span style={{ fontSize: 11, fontWeight: 500, color: 'var(--text-primary)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {node.data.label}
                </span>
                {status === 'running' && <Spin size="small" />}
                {hasOutput && status === 'completed' && (
                  <span style={{ fontSize: 9, color: 'var(--text-tertiary)', flexShrink: 0 }}>output</span>
                )}
                {status === 'error' && (
                  <span style={{ fontSize: 9, color: '#f87171', flexShrink: 0 }}>error</span>
                )}
              </div>
              {isSelected && hasOutput && <OutputPreview output={nodeOutputs[node.id]} />}
              {isSelected && status === 'error' && lastEvent?.error && (
                <div style={{
                  marginTop: 4, padding: '6px 8px', background: '#f8717110', borderRadius: 6,
                  fontSize: 10, color: '#f87171', fontFamily: 'monospace'
                }}>
                  {typeof lastEvent.error === 'string' ? lastEvent.error : lastEvent.error.message}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Event log toggle */}
      <div style={{ borderTop: '1px solid var(--border-primary)', flexShrink: 0 }}>
        <button onClick={() => setShowLog(!showLog)} style={{
          width: '100%', padding: '6px 14px', background: 'transparent', border: 'none',
          cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          fontSize: 10, color: 'var(--text-tertiary)', fontWeight: 500
        }}>
          <span>Event Log ({events.length})</span>
          <span style={{ transform: showLog ? 'rotate(180deg)' : 'rotate(0)', transition: 'transform 0.15s' }}>▲</span>
        </button>
        {showLog && (
          <div ref={scrollRef} style={{ maxHeight: 140, overflow: 'auto', padding: '0 14px 8px' }}>
            {events.map((ev, i) => (
              <div key={i} style={{ display: 'flex', gap: 6, fontSize: 9, fontFamily: 'monospace', padding: '1px 0', color: 'var(--text-tertiary)' }}>
                <span style={{ flexShrink: 0, width: 50 }}>{new Date(ev.timestamp).toLocaleTimeString()}</span>
                <span style={{ flexShrink: 0, width: 80, color: ev.type.includes('error') ? '#f87171' : ev.type.includes('complete') ? '#34d399' : 'var(--text-secondary)' }}>{ev.type}</span>
                {ev.nodeId && <span style={{ color: 'var(--accent)' }}>[{ev.nodeId}]</span>}
                <span style={{ flex: 1, wordBreak: 'break-all' }}>{ev.content || ''}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default memo(RunPanelInner)
