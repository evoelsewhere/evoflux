import { useEffect, useRef } from 'react'

export interface RunEvent {
  type: string
  nodeId?: string
  timestamp: number
  content?: string
  error?: Error
}

interface RunMonitorProps {
  events: RunEvent[]
  isRunning: boolean
  onClose: () => void
}

const EVENT_COLORS: Record<string, string> = {
  'graph:start': 'var(--accent)',
  'graph:complete': 'var(--success)',
  'graph:aborted': 'var(--warning)',
  'node:start': 'var(--accent)',
  'node:complete': 'var(--success)',
  'node:error': 'var(--error)',
  'thought': 'var(--purple)',
  'action': 'var(--warning)',
  'observation': 'var(--cyan)'
}

export default function RunMonitor({ events, isRunning, onClose }: RunMonitorProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [events])

  return (
    <div style={{
      borderTop: '1px solid var(--border-primary)',
      background: 'var(--bg-secondary)',
      height: 200,
      display: 'flex',
      flexDirection: 'column'
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '6px 12px',
        borderBottom: '1px solid var(--border-primary)',
        flexShrink: 0
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>
            Run Log
          </span>
          {isRunning && (
            <div style={{
              width: 6, height: 6, borderRadius: '50%',
              background: 'var(--accent)', animation: 'pulse 1.5s infinite'
            }} />
          )}
          <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
            {events.length} events
          </span>
        </div>
        <button
          onClick={onClose}
          style={{
            background: 'transparent', border: 'none', cursor: 'pointer',
            color: 'var(--text-tertiary)', fontSize: 16, lineHeight: 1
          }}
        >
          ×
        </button>
      </div>

      <div ref={scrollRef} style={{ flex: 1, overflow: 'auto', padding: '6px 12px' }}>
        {events.length === 0 ? (
          <div style={{ color: 'var(--text-tertiary)', fontSize: 12, padding: '20px 0', textAlign: 'center' }}>
            No events yet. Click Run to start.
          </div>
        ) : (
          events.map((event, i) => (
            <div key={i} style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 8,
              padding: '3px 0',
              fontSize: 11,
              fontFamily: "'JetBrains Mono', 'Fira Code', monospace"
            }}>
              <span style={{ color: 'var(--text-tertiary)', flexShrink: 0, width: 60 }}>
                {new Date(event.timestamp).toLocaleTimeString()}
              </span>
              <span style={{
                color: EVENT_COLORS[event.type] || 'var(--text-secondary)',
                flexShrink: 0,
                width: 90,
                fontWeight: 500
              }}>
                {event.type}
              </span>
              {event.nodeId && (
                <span style={{ color: 'var(--text-tertiary)', flexShrink: 0 }}>
                  [{event.nodeId}]
                </span>
              )}
              <span style={{ color: 'var(--text-secondary)', flex: 1, wordBreak: 'break-all' }}>
                {event.content || (event.error ? event.error.message : '')}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
