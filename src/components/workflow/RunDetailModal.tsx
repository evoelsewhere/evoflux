import { useState, useRef, useEffect, memo } from 'react'
import { Spin } from 'antd'
import { DiffFileList, type FileDiffData } from './DiffViewer'
import type { NodeData } from '../../types/workflow'
import type { Node } from 'reactflow'

export interface RunEvent {
  type: string
  nodeId?: string
  edgeId?: string
  timestamp: number
  content?: string
  output?: Record<string, unknown>
  error?: Error | string
  iteration?: number
}

interface RunDetailModalProps {
  open: boolean
  events: RunEvent[]
  nodes: Node<NodeData>[]
  nodeStatuses: Record<string, 'idle' | 'running' | 'completed' | 'error'>
  nodeOutputs: Record<string, unknown>
  nodeProgress: Record<string, unknown[]>
  isRunning: boolean
  elapsed: number
  onStop: () => void
  onClose: () => void
}

const STATUS_CONFIG = {
  idle: { color: 'var(--text-tertiary)', icon: '○', label: 'Pending', bg: 'var(--bg-hover)' },
  running: { color: '#60a5fa', icon: '◉', label: 'Running', bg: '#60a5fa15' },
  completed: { color: '#34d399', icon: '●', label: 'Done', bg: '#34d39915' },
  error: { color: '#f87171', icon: '✕', label: 'Error', bg: '#f8717115' }
}

const TOOL_META: Record<string, { icon: string; color: string; label: string }> = {
  read_file:       { icon: '📖', color: '#60a5fa', label: 'Read' },
  write_file:      { icon: '✏️', color: '#f59e0b', label: 'Write' },
  edit_file:       { icon: '🔧', color: '#f59e0b', label: 'Edit' },
  bash:            { icon: '⚡', color: '#a78bfa', label: 'Bash' },
  grep:            { icon: '🔍', color: '#2dd4bf', label: 'Search' },
  find:            { icon: '📂', color: '#2dd4bf', label: 'Find' },
  list_dir:        { icon: '📁', color: '#2dd4bf', label: 'List' },
  git_checkpoint:  { icon: '💾', color: '#34d399', label: 'Commit' },
  git_diff:        { icon: '📊', color: '#34d399', label: 'Diff' },
  run_tests:       { icon: '🧪', color: '#f472b6', label: 'Test' },
  think:           { icon: '💭', color: '#94a3b8', label: 'Think' },
  get_file_tree:   { icon: '🌳', color: '#2dd4bf', label: 'Tree' },
}

function formatElapsed(ms: number): string {
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  return `${m}m ${s % 60}s`
}

function AgentEventRow({ ev, idx }: { ev: Record<string, unknown>; idx: number }) {
  const agentEvent = String(ev.agentEvent || '')
  const content = String(ev.content || '')
  const tool = ev.tool ? String(ev.tool) : ''
  const toolArgs = ev.toolArgs as Record<string, unknown> | undefined
  const toolResult = ev.toolResult as { success?: boolean; output?: string; error?: string } | undefined
  const iteration = ev.iteration as number | undefined
  const fileDiffs = ev.fileDiffs as FileDiffData[] | undefined
  const meta = tool ? TOOL_META[tool] : null
  const isError = agentEvent === 'error' || (agentEvent === 'tool_result' && toolResult && !toolResult.success)

  const [expanded, setExpanded] = useState(false)

  if (agentEvent === 'thinking') {
    return (
      <div key={idx} style={{
        display: 'flex', alignItems: 'center', gap: 8, padding: '3px 8px',
        fontSize: 10, color: 'var(--text-tertiary)', opacity: 0.7
      }}>
        <span style={{ animation: 'pulse 1.5s infinite' }}>💭</span>
        <span>{content}</span>
      </div>
    )
  }

  if (agentEvent === 'tool_call') {
    const argsPreview = toolArgs ? Object.entries(toolArgs).map(([k, v]) => {
      const val = typeof v === 'string' ? (v.length > 60 ? v.substring(0, 60) + '...' : v) : JSON.stringify(v)
      return `${k}=${val}`
    }).join(', ') : ''

    return (
      <div key={idx} style={{
        padding: '6px 8px', borderRadius: 6, marginBottom: 2,
        background: meta ? `${meta.color}08` : 'var(--bg-card)',
        border: `1px solid ${meta?.color || 'var(--border-primary)'}15`
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14 }}>{meta?.icon || '🔧'}</span>
          <span style={{ fontSize: 11, fontWeight: 600, color: meta?.color || 'var(--text-primary)' }}>{meta?.label || tool}</span>
          {tool === 'bash' && toolArgs?.command ? (
            <span style={{ fontSize: 10, color: 'var(--text-secondary)', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
              $ {String(toolArgs.command)}
            </span>
          ) : null}
          {(tool === 'read_file' || tool === 'write_file' || tool === 'edit_file') && toolArgs?.path ? (
            <span style={{ fontSize: 10, color: 'var(--text-secondary)', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
              {String(toolArgs.path)}
            </span>
          ) : null}
          {iteration ? <span style={{ fontSize: 9, color: 'var(--text-tertiary)', marginLeft: 'auto' }}>#{iteration}</span> : null}
        </div>
        {toolArgs && tool !== 'bash' && (
          <div style={{ marginTop: 4, fontSize: 10, color: 'var(--text-tertiary)', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {argsPreview}
          </div>
        )}
      </div>
    )
  }

  if (agentEvent === 'tool_result') {
    const output = toolResult?.output || content
    const hasLongOutput = output.length > 200
    return (
      <div key={idx} style={{
        padding: '4px 8px 4px 28px', marginBottom: 2
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 10, color: toolResult?.success ? '#34d399' : '#f87171' }}>{toolResult?.success ? '✓' : '✗'}</span>
          <span style={{ fontSize: 10, color: 'var(--text-tertiary)', fontWeight: 500 }}>{tool}</span>
          {hasLongOutput && (
            <button onClick={() => setExpanded(!expanded)} style={{
              fontSize: 9, color: 'var(--accent)', background: 'transparent', border: 'none', cursor: 'pointer', padding: 0
            }}>{expanded ? 'collapse' : 'expand'}</button>
          )}
          {toolResult?.error && <span style={{ fontSize: 10, color: '#f87171', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{toolResult.error}</span>}
        </div>
        {(expanded || !hasLongOutput) && output && (
          <pre style={{
            marginTop: 4, padding: '4px 6px', fontSize: 10, lineHeight: '15px',
            fontFamily: "'JetBrains Mono', monospace", color: 'var(--text-secondary)',
            background: 'var(--bg-primary)', borderRadius: 4, border: '1px solid var(--border-primary)',
            maxHeight: 200, overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all', margin: 0
          }}>
            {toolResult?.success === false ? (toolResult.error || output) : output.substring(0, expanded ? 5000 : 500)}
          </pre>
        )}
      </div>
    )
  }

  if (agentEvent === 'complete') {
    return (
      <div key={idx} style={{
        padding: '8px 10px', borderRadius: 6, marginTop: 4,
        background: '#34d39910', border: '1px solid #34d39925'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14 }}>✅</span>
          <span style={{ fontSize: 11, fontWeight: 600, color: '#34d399' }}>Task Complete</span>
        </div>
        <div style={{ marginTop: 4, fontSize: 11, color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}>{content}</div>
      </div>
    )
  }

  if (agentEvent === 'error') {
    return (
      <div key={idx} style={{
        padding: '8px 10px', borderRadius: 6, marginTop: 4,
        background: '#f8717110', border: '1px solid #f8717125'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14 }}>❌</span>
          <span style={{ fontSize: 11, fontWeight: 600, color: '#f87171' }}>Error</span>
        </div>
        <div style={{ marginTop: 4, fontSize: 11, color: '#f87171', whiteSpace: 'pre-wrap' }}>{content}</div>
      </div>
    )
  }

  if (agentEvent === 'checkpoint') {
    return (
      <div key={idx} style={{
        padding: '6px 10px', borderRadius: 6, marginBottom: 2,
        background: '#34d39908', border: '1px solid #34d39915'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14 }}>💾</span>
          <span style={{ fontSize: 11, fontWeight: 500, color: '#34d399' }}>Checkpoint</span>
        </div>
        <div style={{ marginTop: 2, fontSize: 10, color: 'var(--text-tertiary)' }}>{content}</div>
      </div>
    )
  }

  if (agentEvent === 'needs_info') {
    return (
      <div key={idx} style={{
        padding: '8px 10px', borderRadius: 6, marginTop: 4,
        background: '#fbbf2410', border: '1px solid #fbbf2425'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14 }}>❓</span>
          <span style={{ fontSize: 11, fontWeight: 600, color: '#fbbf24' }}>Needs More Info</span>
        </div>
        <div style={{ marginTop: 4, fontSize: 11, color: 'var(--text-secondary)' }}>{content}</div>
      </div>
    )
  }

  if (agentEvent === 'message') {
    return (
      <div key={idx} style={{ padding: '4px 8px', fontSize: 11, color: 'var(--text-tertiary)', fontStyle: 'italic' }}>
        💬 {content}
      </div>
    )
  }

  return (
    <div key={idx} style={{ padding: '3px 8px', fontSize: 10, color: 'var(--text-tertiary)' }}>
      [{agentEvent}] {content}
    </div>
  )
}

function LiveAgentLog({ progressEvents, status }: { progressEvents: unknown[]; status: string }) {
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [progressEvents.length])

  if (progressEvents.length === 0) {
    if (status === 'running') {
      return (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 12 }}>
          <Spin size="large" />
          <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>Agent is starting...</span>
        </div>
      )
    }
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-tertiary)', fontSize: 12 }}>
        No agent activity recorded
      </div>
    )
  }

  const lastEvent = progressEvents[progressEvents.length - 1] as Record<string, unknown>
  const isLive = status === 'running'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {isLive && lastEvent?.agentEvent ? (
        <div style={{
          padding: '6px 12px', borderBottom: '1px solid var(--border-primary)', flexShrink: 0,
          display: 'flex', alignItems: 'center', gap: 8, fontSize: 11
        }}>
          <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#60a5fa', animation: 'pulse 1s infinite' }} />
          <span style={{ color: 'var(--text-secondary)' }}>
            {lastEvent.agentEvent === 'thinking' ? 'Thinking...'
              : lastEvent.agentEvent === 'tool_call' ? `${TOOL_META[String(lastEvent.tool || '')]?.label || 'Using'} ${String(lastEvent.tool || '')}`
              : lastEvent.agentEvent === 'tool_result' ? 'Processing result...'
              : String(lastEvent.agentEvent)}
          </span>
          {lastEvent.iteration ? <span style={{ color: 'var(--text-tertiary)', marginLeft: 'auto' }}>Step {String(lastEvent.iteration)}</span> : null}
        </div>
      ) : null}

      <div ref={scrollRef} style={{ flex: 1, overflow: 'auto', padding: '8px 4px' }}>
        {progressEvents.map((ev, i) => <AgentEventRow key={i} ev={ev as Record<string, unknown>} idx={i} />)}
      </div>
    </div>
  )
}

function CompletedAgentView({ output }: { output: Record<string, unknown> }) {
  const events = (output.events as Array<{ type: string; content?: string; tool?: string }>) || []
  const fileDiffs = (output.file_diffs as FileDiffData[]) || []
  const summary = String(output.summary || '')
  const filesChanged = (output.files_changed as string[]) || []
  const [tab, setTab] = useState<'log' | 'diffs' | 'output'>('log')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid var(--border-primary)', flexShrink: 0 }}>
        {([['log', 'Agent Log'], ['diffs', `Changes (${fileDiffs.length})`], ['output', 'Output']] as const).map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)} style={{
            padding: '8px 16px', fontSize: 11, fontWeight: tab === key ? 600 : 400,
            color: tab === key ? 'var(--text-primary)' : 'var(--text-tertiary)',
            background: tab === key ? 'var(--bg-card)' : 'transparent',
            border: 'none', borderBottom: tab === key ? '2px solid var(--accent)' : '2px solid transparent',
            cursor: 'pointer', transition: 'all 0.15s'
          }}>
            {label}
          </button>
        ))}
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: 12 }}>
        {tab === 'log' && (
          <div>
            {events.map((ev, i) => (
              <div key={i} style={{
                display: 'flex', gap: 8, padding: '4px 6px', borderRadius: 4, marginBottom: 2,
                background: (ev.type === 'error' || (ev.type === 'tool_result' && ev.content?.includes('Error'))) ? '#f8717110' : 'transparent'
              }}>
                <span style={{ flexShrink: 0, width: 20, textAlign: 'center' }}>
                  {ev.type === 'thinking' ? '💭' : ev.type === 'tool_call' ? '🔧' : ev.type === 'tool_result' ? '📋' : ev.type === 'complete' ? '✅' : ev.type === 'error' ? '❌' : ev.type === 'checkpoint' ? '💾' : '💬'}
                </span>
                <span style={{ flexShrink: 0, width: 70, color: 'var(--text-tertiary)', fontSize: 10, fontWeight: 500 }}>{ev.type}</span>
                {ev.tool && <span style={{ flexShrink: 0, color: 'var(--accent)', fontSize: 10, fontWeight: 600 }}>{ev.tool}</span>}
                <span style={{ flex: 1, color: 'var(--text-secondary)', wordBreak: 'break-all', whiteSpace: 'pre-wrap', fontSize: 11 }}>{ev.content || ''}</span>
              </div>
            ))}
          </div>
        )}

        {tab === 'diffs' && (
          <div>
            {fileDiffs.length > 0 ? (
              <>
                {filesChanged.length > 0 && (
                  <div style={{ marginBottom: 12, padding: '8px 10px', background: 'var(--bg-card)', borderRadius: 6, border: '1px solid var(--border-primary)' }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>Files Modified</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {filesChanged.map((f, i) => (
                        <span key={i} style={{ fontSize: 10, padding: '2px 6px', background: 'var(--bg-input)', borderRadius: 4, color: 'var(--text-secondary)', fontFamily: 'monospace' }}>{f}</span>
                      ))}
                    </div>
                  </div>
                )}
                <DiffFileList diffs={fileDiffs} />
              </>
            ) : (
              <div style={{ color: 'var(--text-tertiary)', fontSize: 11, padding: 20, textAlign: 'center' }}>No file diffs captured</div>
            )}
          </div>
        )}

        {tab === 'output' && (
          <div>
            {summary && (
              <div style={{ marginBottom: 12, padding: 10, background: 'var(--bg-card)', borderRadius: 6, border: '1px solid var(--border-primary)' }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>Summary</div>
                <div style={{ fontSize: 12, color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', lineHeight: '18px' }}>{summary}</div>
              </div>
            )}
            {filesChanged.length > 0 && (
              <div style={{ marginBottom: 12, padding: 10, background: 'var(--bg-card)', borderRadius: 6, border: '1px solid var(--border-primary)' }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 6 }}>Files Changed ({filesChanged.length})</div>
                {filesChanged.map((f, i) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '3px 0', fontSize: 11 }}>
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M3 1h4l3 3v7H3V1z" stroke="var(--text-tertiary)" strokeWidth="1" strokeLinejoin="round" /><path d="M7 1v3h3" stroke="var(--text-tertiary)" strokeWidth="1" strokeLinejoin="round" /></svg>
                    <span style={{ color: 'var(--text-secondary)', fontFamily: 'monospace' }}>{f}</span>
                  </div>
                ))}
              </div>
            )}
            <div style={{ padding: 10, background: 'var(--bg-card)', borderRadius: 6, border: '1px solid var(--border-primary)' }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>Raw Output</div>
              <pre style={{ fontSize: 10, color: 'var(--text-secondary)', margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxHeight: 300, overflow: 'auto', fontFamily: 'monospace', lineHeight: '16px' }}>
                {JSON.stringify(output, null, 2)}
              </pre>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function NodeDetailPanel({ node, output, progressEvents, status }: { node: Node<NodeData>; output: unknown; progressEvents: unknown[]; status: string }) {
  const isAgent = node.data.type === 'ai-agent' || node.data.type === 'agent-orchestrator'

  if (isAgent) {
    if (status === 'completed' || status === 'error') {
      const finalOutput = (typeof output === 'object' && output !== null) ? output as Record<string, unknown> : { summary: String(output || '') }
      return <CompletedAgentView output={finalOutput} />
    }
    return <LiveAgentLog progressEvents={progressEvents} status={status} />
  }

  if (status === 'running') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 12 }}>
        <Spin size="large" />
        <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>Processing...</span>
      </div>
    )
  }

  if (!output) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-tertiary)', fontSize: 12 }}>
        {status === 'idle' ? 'Waiting to execute...' : 'No output available'}
      </div>
    )
  }

  const str = typeof output === 'string' ? output : JSON.stringify(output, null, 2)
  return (
    <div style={{ padding: 12 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 8 }}>Output</div>
      <pre style={{
        fontSize: 11, color: 'var(--text-secondary)', margin: 0,
        whiteSpace: 'pre-wrap', wordBreak: 'break-all',
        fontFamily: "'JetBrains Mono', monospace", lineHeight: '18px',
        padding: 10, background: 'var(--bg-card)', borderRadius: 6,
        border: '1px solid var(--border-primary)', maxHeight: 500, overflow: 'auto'
      }}>
        {str}
      </pre>
    </div>
  )
}

function RunDetailModalInner({ open, events, nodes, nodeStatuses, nodeOutputs, nodeProgress, isRunning, elapsed, onStop, onClose }: RunDetailModalProps) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [showEventLog, setShowEventLog] = useState(false)
  const logRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (isRunning && !selectedNodeId) {
      const runningNode = nodes.find(n => nodeStatuses[n.id] === 'running')
      if (runningNode) setSelectedNodeId(runningNode.id)
    }
  }, [isRunning, nodeStatuses, nodes, selectedNodeId])

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [events])

  useEffect(() => {
    if (!open) setSelectedNodeId(null)
  }, [open])

  if (!open) return null

  const nonCommentNodes = nodes.filter(n => n.data.type !== 'comment')
  const totalNodes = nonCommentNodes.length
  const completedCount = Object.values(nodeStatuses).filter(s => s === 'completed').length
  const errorCount = Object.values(nodeStatuses).filter(s => s === 'error').length
  const runningCount = Object.values(nodeStatuses).filter(s => s === 'running').length
  const progress = totalNodes > 0 ? ((completedCount + errorCount) / totalNodes) * 100 : 0

  const selectedNode = selectedNodeId ? nodes.find(n => n.id === selectedNodeId) : null
  const selectedOutput = selectedNodeId ? nodeOutputs[selectedNodeId] : null
  const selectedProgress = selectedNodeId ? (nodeProgress[selectedNodeId] || []) : []
  const selectedStatus = selectedNodeId ? (nodeStatuses[selectedNodeId] || 'idle') : 'idle'

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 2000,
      display: 'flex', alignItems: 'center', justifyContent: 'center'
    }} onKeyDown={(e) => { if (e.key === 'Escape') onClose() }}>
      <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)' }} onClick={onClose} />

      <div style={{
        position: 'relative', zIndex: 1,
        width: 'calc(100vw - 60px)', height: 'calc(100vh - 60px)',
        maxWidth: 1400, maxHeight: 900,
        background: 'var(--bg-secondary)', border: '1px solid var(--border-primary)',
        borderRadius: 12, boxShadow: '0 25px 80px rgba(0,0,0,0.6)',
        display: 'flex', flexDirection: 'column', overflow: 'hidden'
      }} onClick={(e) => e.stopPropagation()}>

        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '12px 16px', borderBottom: '1px solid var(--border-primary)', flexShrink: 0
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{
              width: 8, height: 8, borderRadius: '50%',
              background: isRunning ? '#60a5fa' : errorCount > 0 ? '#f87171' : '#34d399',
              boxShadow: isRunning ? '0 0 8px #60a5fa' : 'none',
              animation: isRunning ? 'pulse 1.5s infinite' : 'none'
            }} />
            <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>
              {isRunning ? 'Running...' : errorCount > 0 ? 'Completed with Errors' : 'Completed'}
            </span>
            <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>{formatElapsed(elapsed)}</span>
            {isRunning && (
              <span style={{ fontSize: 11, color: 'var(--text-tertiary)', marginLeft: 4 }}>
                {completedCount}/{totalNodes} nodes • {runningCount} running
              </span>
            )}
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            {isRunning && (
              <button onClick={onStop} style={{
                padding: '5px 14px', fontSize: 11, borderRadius: 5, cursor: 'pointer',
                background: '#f8717120', border: '1px solid #f8717140', color: '#f87171', fontWeight: 500
              }}>Stop</button>
            )}
            <button onClick={onClose} style={{
              width: 26, height: 26, display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)',
              borderRadius: 4, fontSize: 16, lineHeight: 1
            }}>×</button>
          </div>
        </div>

        <div style={{ padding: '0 16px', flexShrink: 0 }}>
          <div style={{ height: 3, background: 'var(--border-primary)', borderRadius: 2, marginTop: 8 }}>
            <div style={{
              height: '100%', borderRadius: 2, width: `${progress}%`,
              background: errorCount > 0 ? '#f87171' : '#34d399',
              transition: 'width 0.3s ease'
            }} />
          </div>
        </div>

        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          <div style={{
            width: 260, borderRight: '1px solid var(--border-primary)',
            display: 'flex', flexDirection: 'column', flexShrink: 0, overflow: 'hidden'
          }}>
            <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--border-primary)', flexShrink: 0 }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)' }}>Nodes</span>
            </div>
            <div style={{ flex: 1, overflow: 'auto', padding: '6px 8px' }}>
              {nonCommentNodes.map((node) => {
                const status = nodeStatuses[node.id] || 'idle'
                const cfg = STATUS_CONFIG[status]
                const isSelected = selectedNodeId === node.id
                const progressCount = (nodeProgress[node.id] || []).length
                return (
                  <div
                    key={node.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => setSelectedNodeId(isSelected ? null : node.id)}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelectedNodeId(isSelected ? null : node.id) } }}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8,
                      padding: '7px 8px', borderRadius: 6, cursor: 'pointer',
                      background: isSelected ? cfg.bg : 'transparent',
                      border: isSelected ? `1px solid ${cfg.color}30` : '1px solid transparent',
                      transition: 'all 0.1s', marginBottom: 2
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
                    {status === 'running' && progressCount > 0 && (
                      <span style={{ fontSize: 9, color: '#60a5fa', flexShrink: 0 }}>{progressCount}</span>
                    )}
                    {status === 'running' && <Spin size="small" />}
                    {status === 'completed' && nodeOutputs[node.id] !== undefined && (
                      <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 3, background: '#34d39920', color: '#34d399', fontWeight: 600 }}>OK</span>
                    )}
                    {status === 'error' && (
                      <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 3, background: '#f8717120', color: '#f87171', fontWeight: 600 }}>ERR</span>
                    )}
                  </div>
                )
              })}
            </div>

            <div style={{ borderTop: '1px solid var(--border-primary)', flexShrink: 0 }}>
              <button onClick={() => setShowEventLog(!showEventLog)} style={{
                width: '100%', padding: '7px 12px', background: 'transparent', border: 'none',
                cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                fontSize: 10, color: 'var(--text-tertiary)', fontWeight: 500
              }}>
                <span>Event Log ({events.length})</span>
                <span style={{ transform: showEventLog ? 'rotate(180deg)' : 'rotate(0)', transition: 'transform 0.15s' }}>▲</span>
              </button>
              {showEventLog && (
                <div ref={logRef} style={{ maxHeight: 150, overflow: 'auto', padding: '0 12px 8px' }}>
                  {events.map((ev, i) => (
                    <div key={i} style={{ display: 'flex', gap: 4, fontSize: 9, fontFamily: 'monospace', padding: '1px 0', color: 'var(--text-tertiary)' }}>
                      <span style={{ flexShrink: 0, width: 46 }}>{new Date(ev.timestamp).toLocaleTimeString()}</span>
                      <span style={{ flexShrink: 0, width: 72, color: ev.type.includes('error') ? '#f87171' : ev.type.includes('complete') ? '#34d399' : 'var(--text-secondary)' }}>{ev.type}</span>
                      {ev.nodeId && <span style={{ color: 'var(--accent)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>[{ev.nodeId}]</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            {selectedNode ? (
              <>
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '10px 16px', borderBottom: '1px solid var(--border-primary)', flexShrink: 0
                }}>
                  <span style={{ fontSize: 10, color: STATUS_CONFIG[selectedStatus].color }}>{STATUS_CONFIG[selectedStatus].icon}</span>
                  <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{selectedNode.data.label}</span>
                  <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: 'var(--bg-card)', border: '1px solid var(--border-primary)', color: 'var(--text-tertiary)' }}>{selectedNode.data.type}</span>
                  {selectedStatus === 'error' && selectedNode.data.error && (
                    <span style={{ fontSize: 10, color: '#f87171', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>{selectedNode.data.error}</span>
                  )}
                </div>
                <div style={{ flex: 1, overflow: 'hidden' }}>
                  <NodeDetailPanel node={selectedNode} output={selectedOutput} progressEvents={selectedProgress} status={selectedStatus} />
                </div>
              </>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 8 }}>
                <svg width="32" height="32" viewBox="0 0 14 14" fill="none" style={{ opacity: 0.3 }}>
                  <circle cx="7" cy="7" r="5.5" stroke="var(--text-tertiary)" strokeWidth="1.2" />
                  <path d="M5 6l2 2 2-2" stroke="var(--text-tertiary)" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>Select a node to view details</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default memo(RunDetailModalInner)
