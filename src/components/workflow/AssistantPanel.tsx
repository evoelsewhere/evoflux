import { useState, useRef, useEffect, useCallback } from 'react'
import { Input, Select, Spin } from 'antd'
import { useAssistantStore, type ChatMessage } from '../../stores/assistantStore'
import { useProviderStore, PROVIDER_LABELS } from '../../stores/providerStore'
import { runAssistant, type RunAssistantOptions } from '../../assistant/engine'
import type { WorkflowToolContext } from '../../assistant/tools'
import type { NodeData } from '../../types/workflow'
import type { Node, Edge } from 'reactflow'

const { TextArea } = Input

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
      <div style={{ padding: '4px 12px', marginBottom: 4 }}>
        <div style={{
          fontSize: 10, fontFamily: 'monospace', color: 'var(--text-tertiary)',
          background: 'var(--bg-input)', borderRadius: 6, padding: '6px 8px',
          maxHeight: 120, overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all'
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
      padding: '2px 12px', marginBottom: 4
    }}>
      <div style={{
        maxWidth: '85%', padding: '8px 12px', borderRadius: 12,
        background: isUser ? 'var(--accent)' : 'var(--bg-card)',
        border: isUser ? 'none' : '1px solid var(--border-primary)',
        color: isUser ? '#fff' : 'var(--text-primary)',
        fontSize: 12, lineHeight: '18px', whiteSpace: 'pre-wrap', wordBreak: 'break-word'
      }}>
        {msg.thought && !isUser && (
          <div style={{ fontSize: 10, color: 'var(--purple)', marginBottom: 4, fontStyle: 'italic' }}>
            💭 {msg.thought}
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
  const { messages, isThinking, currentStep, selectedProviderId, selectedModel, addMessage, setThinking, setSelectedProvider, setSelectedModel, clearMessages } = useAssistantStore()
  const { providers } = useProviderStore()

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, isThinking])

  const handleSend = useCallback(async () => {
    const text = input.trim()
    if (!text || isThinking) return
    setInput('')

    addMessage({ role: 'user', content: text })
    addMessage({ role: 'assistant', content: '', isStreaming: true })

    const options: RunAssistantOptions = {
      userMessage: text,
      nodes, edges,
      context: toolContext,
      onThought: (thought) => {
        useAssistantStore.getState().updateLastAssistant({ thought, content: '' })
      },
      onToolCall: (name, args) => {
        addMessage({ role: 'tool', content: JSON.stringify(args, null, 2), toolName: name })
      },
      onToolResult: (name, result) => {
        addMessage({ role: 'tool', content: result.substring(0, 500), toolName: name })
        onNodesChanged()
      },
      onFinish: (answer) => {
        useAssistantStore.getState().updateLastAssistant({ content: answer, isStreaming: false })
      },
      onError: (error) => {
        useAssistantStore.getState().updateLastAssistant({ content: `Error: ${error}`, isStreaming: false })
      }
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
      position: 'fixed', top: 0, right: 0, width: 380, height: '100vh',
      background: 'var(--bg-secondary)', borderLeft: '1px solid var(--border-primary)',
      display: 'flex', flexDirection: 'column', zIndex: 300,
      boxShadow: '-8px 0 32px rgba(0,0,0,0.3)'
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 14px', borderBottom: '1px solid var(--border-primary)', flexShrink: 0
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>Assistant</div>
          {isThinking && <Spin size="small" />}
          {currentStep && <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>{currentStep}</span>}
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          <button onClick={clearMessages} style={{ padding: '2px 8px', fontSize: 10, background: 'transparent', border: '1px solid var(--border-primary)', borderRadius: 4, cursor: 'pointer', color: 'var(--text-tertiary)' }}>Clear</button>
          <button onClick={onClose} style={{ width: 24, height: 24, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)', fontSize: 14 }}>×</button>
        </div>
      </div>

      <div style={{ padding: '6px 14px', borderBottom: '1px solid var(--border-primary)', display: 'flex', gap: 6, flexShrink: 0 }}>
        <Select size="small" value={selectedProviderId || undefined} onChange={(v) => { setSelectedProvider(v); setSelectedModel('') }}
          placeholder="Provider" options={providerOptions} style={{ flex: 1 }} />
        <Select size="small" value={selectedModel || undefined} onChange={setSelectedModel}
          placeholder="Model" options={modelOptions} style={{ flex: 1 }} />
      </div>

      <div ref={scrollRef} style={{ flex: 1, overflow: 'auto', paddingTop: 8 }}>
        {messages.length === 0 && (
          <div style={{ padding: '40px 20px', textAlign: 'center' }}>
            <div style={{ fontSize: 28, marginBottom: 12 }}>🤖</div>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>Workflow Assistant</div>
            <div style={{ fontSize: 11, color: 'var(--text-tertiary)', lineHeight: '16px' }}>
              Ask me to create, modify, or analyze your workflow. I use tools to make changes step by step.
            </div>
          </div>
        )}
        {messages.map((msg) => <MessageBubble key={msg.id} msg={msg} />)}
      </div>

      <div style={{ padding: '10px 14px', borderTop: '1px solid var(--border-primary)', flexShrink: 0 }}>
        <TextArea value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={handleKeyDown}
          placeholder={isThinking ? 'Thinking...' : 'Ask me to create or modify a workflow...'}
          disabled={isThinking} autoSize={{ minRows: 1, maxRows: 4 }}
          style={{ fontSize: 12, background: 'var(--bg-input)', borderColor: 'var(--border-primary)' }} />
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 6 }}>
          <button onClick={handleSend} disabled={!input.trim() || isThinking}
            style={{
              padding: '5px 16px', fontSize: 11, borderRadius: 6, cursor: input.trim() && !isThinking ? 'pointer' : 'not-allowed',
              background: input.trim() && !isThinking ? 'var(--accent)' : 'var(--bg-hover)',
              border: 'none', color: input.trim() && !isThinking ? '#fff' : 'var(--text-tertiary)',
              fontWeight: 600
            }}>
            {isThinking ? 'Thinking...' : 'Send'}
          </button>
        </div>
      </div>
    </div>
  )
}
