import { useState, useRef, useEffect, useCallback } from 'react'
import { Input, Select, Spin } from 'antd'
import { useAssistantStore, type ChatMessage } from '../../stores/assistantStore'
import { useProviderStore, PROVIDER_LABELS } from '../../stores/providerStore'
import { runAssistant, type RunAssistantOptions } from '../../assistant/engine'
import type { WorkflowToolContext } from '../../assistant/tools'
import type { NodeData } from '../../types/workflow'
import type { Node, Edge } from 'reactflow'

const { TextArea } = Input

const assistantIcon = (c: string) => (
  <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
    <circle cx="9" cy="9" r="7" stroke={c} strokeWidth="1.3" />
    <circle cx="7" cy="7.5" r="1" fill={c} />
    <circle cx="11" cy="7.5" r="1" fill={c} />
    <path d="M6 11C6.8 12.2 11.2 12.2 12 11" stroke={c} strokeWidth="1.2" strokeLinecap="round" />
  </svg>
)

const thoughtIcon = (c: string) => (
  <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
    <circle cx="5" cy="4" r="3" stroke={c} strokeWidth="1" />
    <path d="M3.5 7H6.5" stroke={c} strokeWidth="1" strokeLinecap="round" />
  </svg>
)

const sendIcon = (c: string) => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
    <path d="M1 7H10M10 7L6.5 3.5M10 7L6.5 10.5" stroke={c} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

const closeIcon = (c: string) => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
    <path d="M3 3L11 11M11 3L3 11" stroke={c} strokeWidth="1.5" strokeLinecap="round" />
  </svg>
)

const clearIcon = (c: string) => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
    <path d="M2 3H10M4.5 3V2C4.5 1.4 4.9 1 5.5 1H6.5C7.1 1 7.5 1.4 7.5 2V3M9.5 3V10C9.5 10.6 9.1 11 8.5 11H3.5C2.9 11 2.5 10.6 2.5 10V3" stroke={c} strokeWidth="1" strokeLinecap="round" />
  </svg>
)

interface AssistantPanelProps {
  nodes: Node<NodeData>[]
  edges: Edge[]
  toolContext: WorkflowToolContext
  onClose: () => void
  onNodesChanged: () => void
}

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === 'user'
  const isTool = msg.role === 'tool'

  if (isTool) {
    return (
      <div style={{ padding: '3px 16px', marginBottom: 2 }}>
        <div style={{
          fontSize: 10, fontFamily: "'JetBrains Mono', monospace", color: 'var(--text-tertiary)',
          background: 'var(--bg-input)', borderRadius: 6, padding: '5px 8px',
          maxHeight: 100, overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all', lineHeight: '14px'
        }}>
          <span style={{ color: msg.toolName === 'error' ? 'var(--error)' : 'var(--accent)', fontWeight: 600 }}>
            {msg.toolName && `[${msg.toolName}] `}
          </span>
          {msg.content}
        </div>
      </div>
    )
  }

  return (
    <div style={{
      display: 'flex', justifyContent: isUser ? 'flex-end' : 'flex-start',
      padding: '2px 16px', marginBottom: 4
    }}>
      <div style={{
        maxWidth: '80%', padding: '8px 12px', borderRadius: isUser ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
        background: isUser ? 'var(--accent)' : 'var(--bg-card)',
        border: isUser ? 'none' : '1px solid var(--border-primary)',
        color: isUser ? '#fff' : 'var(--text-primary)',
        fontSize: 12, lineHeight: '18px', whiteSpace: 'pre-wrap', wordBreak: 'break-word'
      }}>
        {msg.thought && !isUser && (
          <div style={{ fontSize: 10, color: 'var(--purple)', marginBottom: 4, display: 'flex', alignItems: 'center', gap: 4 }}>
            {thoughtIcon('var(--purple)')}
            <span style={{ fontStyle: 'italic' }}>{msg.thought}</span>
          </div>
        )}
        {msg.content}
        {msg.isStreaming && <span style={{ opacity: 0.5 }}> ▍</span>}
      </div>
    </div>
  )
}

export default function AssistantPanel({ nodes, edges, toolContext, onClose, onNodesChanged }: AssistantPanelProps) {
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const { messages, isThinking, currentStep, selectedProviderId, selectedModel, addMessage, setSelectedProvider, setSelectedModel, clearMessages } = useAssistantStore()
  const { providers } = useProviderStore()

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages, isThinking])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as HTMLElement)) {
        const el = e.target as HTMLElement
        if (el.closest('.ant-select-dropdown, .ant-popover')) return
        onClose()
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])

  const handleSend = useCallback(async () => {
    const text = input.trim()
    if (!text || isThinking) return
    setInput('')

    addMessage({ role: 'user', content: text })
    addMessage({ role: 'assistant', content: '', isStreaming: true })

    const options: RunAssistantOptions = {
      userMessage: text, nodes, edges, context: toolContext,
      onThought: (thought) => { useAssistantStore.getState().updateLastAssistant({ thought, content: '' }) },
      onToolCall: (name, args) => { addMessage({ role: 'tool', content: JSON.stringify(args, null, 2), toolName: name }) },
      onToolResult: (name, result) => { addMessage({ role: 'tool', content: result.substring(0, 500), toolName: name }); onNodesChanged() },
      onFinish: (answer) => { useAssistantStore.getState().updateLastAssistant({ content: answer, isStreaming: false }) },
      onError: (error) => { useAssistantStore.getState().updateLastAssistant({ content: `Error: ${error}`, isStreaming: false }) }
    }
    await runAssistant(options)
  }, [input, isThinking, nodes, edges, toolContext, addMessage, onNodesChanged])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  const providerOptions = providers.map(p => ({ label: `${p.name} (${PROVIDER_LABELS[p.type]})`, value: p.id }))
  const selectedProv = providers.find(p => p.id === selectedProviderId)
  const modelOptions = selectedProv?.models.map(m => ({ label: m, value: m })) || []

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000,
      background: 'rgba(0,0,0,0.4)', backdropFilter: 'blur(4px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center'
    }}>
      <div ref={panelRef} style={{
        width: 480, maxHeight: '80vh', height: 600,
        background: 'var(--bg-secondary)', border: '1px solid var(--border-primary)',
        borderRadius: 16, boxShadow: '0 24px 64px rgba(0,0,0,0.5)',
        display: 'flex', flexDirection: 'column', overflow: 'hidden'
      }}>
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '12px 16px', borderBottom: '1px solid var(--border-primary)', flexShrink: 0
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 28, height: 28, borderRadius: 8, background: 'var(--accent-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              {assistantIcon('var(--accent)')}
            </div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', lineHeight: 1 }}>Assistant</div>
              <div style={{ fontSize: 10, color: 'var(--text-tertiary)', marginTop: 1 }}>
                {isThinking ? currentStep || 'Thinking...' : `${messages.length} messages`}
              </div>
            </div>
            {isThinking && <Spin size="small" style={{ marginLeft: 4 }} />}
          </div>
          <div style={{ display: 'flex', gap: 4 }}>
            <button onClick={clearMessages} title="Clear chat"
              style={{ width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)', borderRadius: 6, transition: 'background 0.1s' }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
              {clearIcon('var(--text-tertiary)')}
            </button>
            <button onClick={onClose} title="Close"
              style={{ width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)', borderRadius: 6, transition: 'background 0.1s' }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
              {closeIcon('var(--text-tertiary)')}
            </button>
          </div>
        </div>

        <div style={{ padding: '6px 16px', borderBottom: '1px solid var(--border-primary)', display: 'flex', gap: 6, flexShrink: 0 }}>
          <Select size="small" value={selectedProviderId || undefined} onChange={(v) => { setSelectedProvider(v); setSelectedModel('') }}
            placeholder="Provider" options={providerOptions} style={{ flex: 1 }} />
          <Select size="small" value={selectedModel || undefined} onChange={setSelectedModel}
            placeholder="Model" options={modelOptions} style={{ flex: 1 }} />
        </div>

        <div ref={scrollRef} style={{ flex: 1, overflow: 'auto', paddingTop: 8 }}>
          {messages.length === 0 && (
            <div style={{ padding: '48px 24px', textAlign: 'center' }}>
              <div style={{ width: 48, height: 48, borderRadius: 14, background: 'var(--accent-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 14px' }}>
                {assistantIcon('var(--accent)')}
              </div>
              <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>Workflow Assistant</div>
              <div style={{ fontSize: 12, color: 'var(--text-tertiary)', lineHeight: '18px', maxWidth: 280, margin: '0 auto' }}>
                Ask me to create, modify, or analyze your workflow. I use tools to make changes step by step.
              </div>
            </div>
          )}
          {messages.map((msg) => <MessageBubble key={msg.id} msg={msg} />)}
        </div>

        <div style={{ padding: '10px 16px', borderTop: '1px solid var(--border-primary)', flexShrink: 0 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
            <TextArea value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={handleKeyDown}
              placeholder={isThinking ? 'Thinking...' : 'Ask me to create or modify a workflow...'}
              disabled={isThinking} autoSize={{ minRows: 1, maxRows: 4 }}
              style={{ fontSize: 12, background: 'var(--bg-input)', borderColor: 'var(--border-primary)', borderRadius: 10, flex: 1 }} />
            <button onClick={handleSend} disabled={!input.trim() || isThinking}
              style={{
                width: 34, height: 34, borderRadius: 10, flexShrink: 0,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                cursor: input.trim() && !isThinking ? 'pointer' : 'not-allowed',
                background: input.trim() && !isThinking ? 'var(--accent)' : 'var(--bg-hover)',
                border: 'none', transition: 'all 0.15s'
              }}>
              {sendIcon(input.trim() && !isThinking ? '#fff' : 'var(--text-tertiary)')}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
