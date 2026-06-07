import { useEffect, useRef, useState, useCallback } from 'react'
import { Input, Select, Slider } from 'antd'
import Editor from '@monaco-editor/react'
import { useWorkflowStore } from '../../stores/workflowStore'
import { useProviderStore, PROVIDER_LABELS, type ProviderInstance } from '../../stores/providerStore'
import { getNodeDefinition } from './registry'
import { useTheme } from '../common/ThemeProvider'
import type { NodeData } from '../../types/workflow'
import type { Node } from 'reactflow'

const { TextArea } = Input

interface NodePopupProps {
  node: Node<NodeData>
  onClose: () => void
  onDelete?: (nodeId: string) => void
}

const labelStyle: React.CSSProperties = { color: 'var(--text-secondary)', fontSize: 12, fontWeight: 500, marginBottom: 4 }
const inputStyle = { background: 'var(--bg-input)', borderColor: 'var(--border-primary)', fontSize: 12 }

function TrashIcon() {
  return <svg width={12} height={12} viewBox="0 0 12 12" fill="none"><path d="M2 3H10M4.5 3V2C4.5 1.4 4.9 1 5.5 1H6.5C7.1 1 7.5 1.4 7.5 2V3M9.5 3V10C9.5 10.6 9.1 11 8.5 11H3.5C2.9 11 2.5 10.6 2.5 10V3" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" /><path d="M5 5.5V8.5M7 5.5V8.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" /></svg>
}

export default function NodePopup({ node, onClose, onDelete }: NodePopupProps) {
  const ref = useRef<HTMLDivElement>(null)
  const { updateNodeData } = useWorkflowStore()
  const { providers, getDefaultProvider } = useProviderStore()
  const { mode } = useTheme()
  const [pos, setPos] = useState({ x: 0, y: 0 })

  const { data } = node
  const nodeType = data.type || 'default'
  const definition = getNodeDefinition(nodeType)
  const config = (data.config || {}) as Record<string, unknown>
  const defaultProv = getDefaultProvider()
  const providerOptions = providers.map(p => ({ label: `${p.name} (${PROVIDER_LABELS[p.type]})`, value: p.id }))

  const handleChange = useCallback((field: string, value: unknown) => {
    updateNodeData(node.id, { config: { ...config, [field]: value } })
  }, [node.id, config, updateNodeData])

  const handleLabelChange = useCallback((label: string) => {
    updateNodeData(node.id, { label })
  }, [node.id, updateNodeData])

  const handleDelete = useCallback(() => {
    if (onDelete) onDelete(node.id)
    else onClose()
  }, [node.id, onDelete, onClose])

  useEffect(() => {
    const el = document.querySelector(`[data-id="${node.id}"]`) as HTMLElement | null
    if (!el) return
    const rect = el.getBoundingClientRect()
    const popupW = 320
    const popupEstH = 400
    let x = rect.right + 12
    let y = rect.top
    if (x + popupW > window.innerWidth - 16) x = rect.left - popupW - 12
    if (x < 16) x = 16
    if (y + popupEstH > window.innerHeight - 16) y = window.innerHeight - popupEstH - 16
    if (y < 16) y = 16
    setPos({ x, y })
  }, [node.id, node.position])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (!target) return
      if (ref.current?.contains(target)) return
      const el = target as HTMLElement | null
      let node: HTMLElement | null = el
      while (node && node !== document.body) {
        if (node.classList && (
          node.classList.contains('ant-select-dropdown') ||
          node.classList.contains('ant-popover') ||
          node.classList.contains('ant-dropdown') ||
          node.classList.contains('ant-modal') ||
          node.classList.contains('ant-slider') ||
          node.classList.contains('ant-select-item') ||
          node.classList.contains('monaco-editor') ||
          node.classList.contains('context-view')
        )) return
        node = node.parentElement
      }
      onClose()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])

  return (
    <div
      ref={ref}
      style={{
        position: 'fixed',
        left: pos.x, top: pos.y,
        width: 320,
        maxHeight: 'calc(100vh - 32px)',
        background: 'var(--bg-elevated)',
        border: '1px solid var(--border-primary)',
        borderRadius: 12,
        boxShadow: '0 12px 40px rgba(0,0,0,0.5)',
        zIndex: 1000,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden'
      }}
    >
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '10px 14px', borderBottom: '1px solid var(--border-primary)', flexShrink: 0
      }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
            {definition?.label || data.label}
          </div>
          {definition && (
            <div style={{ fontSize: 10, color: 'var(--text-tertiary)', marginTop: 1 }}>{definition.description}</div>
          )}
        </div>
        <div style={{ display: 'flex', gap: 4, marginLeft: 8 }}>
          <button onClick={handleDelete} style={{
            width: 26, height: 26, display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--error)',
            borderRadius: 4, transition: 'background 0.1s'
          }} onMouseEnter={e => e.currentTarget.style.background = 'var(--error-muted)'}
             onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
            <TrashIcon />
          </button>
          <button onClick={onClose} style={{
            width: 26, height: 26, display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)',
            borderRadius: 4, fontSize: 16, lineHeight: 1, transition: 'background 0.1s'
          }} onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
             onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
            ×
          </button>
        </div>
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: 14 }}>
        <div style={{ marginBottom: 10 }}>
          <div style={labelStyle}>Label</div>
          <Input value={data.label} onChange={(e) => handleLabelChange(e.target.value)} style={inputStyle} size="small" />
        </div>

        {nodeType !== 'comment' && (
          <div style={{ marginBottom: 10, display: 'flex', gap: 8 }}>
            <div style={{ flex: 1 }}>
              <div style={labelStyle}>Type</div>
              <Input value={nodeType} disabled style={{ ...inputStyle, color: 'var(--text-tertiary)' }} size="small" />
            </div>
            <div style={{ flex: 1 }}>
              <div style={labelStyle}>Category</div>
              <Input value={data.category || ''} disabled style={{ ...inputStyle, color: 'var(--text-tertiary)' }} size="small" />
            </div>
          </div>
        )}

        {/* ── LLM ── */}
        {nodeType === 'llm' && (
          <Section title="AI Configuration">
            <Field label="Provider">
              <Select size="small" value={String(config.provider || defaultProv?.id || '')} onChange={(v) => handleChange('provider', v)}
                options={providerOptions} style={{ width: '100%' }} />
            </Field>
            <Field label="Model">
              <Input size="small" value={String(config.model || '')} onChange={(e) => handleChange('model', e.target.value)} placeholder="gpt-4o / claude-sonnet-4-20250514" style={inputStyle} />
            </Field>
            <Field label="System Prompt">
              <TextArea rows={2} value={String(config.system_prompt || '')} onChange={(e) => handleChange('system_prompt', e.target.value)} placeholder="You are a helpful assistant..." style={inputStyle} />
            </Field>
            <Field label="Prompt">
              <TextArea rows={4} value={String(config.prompt || '')} onChange={(e) => handleChange('prompt', e.target.value)} placeholder="Enter your prompt..." style={inputStyle} />
            </Field>
            <Field label={`Temperature: ${String(config.temperature ?? 0.7)}`}>
              <Slider min={0} max={2} step={0.1} value={Number(config.temperature ?? 0.7)} onChange={(v) => handleChange('temperature', v)} />
            </Field>
            <Field label={`Max Tokens: ${String(config.max_tokens ?? 2048)}`}>
              <Slider min={256} max={8192} step={256} value={Number(config.max_tokens ?? 2048)} onChange={(v) => handleChange('max_tokens', v)} />
            </Field>
            <Field label="Use Memory">
              <Select size="small" value={String(config.use_memory ?? false)} onChange={(v) => handleChange('use_memory', v === 'true')}
                options={[{ label: 'Disabled', value: 'false' }, { label: 'Enabled', value: 'true' }]} style={{ width: '100%' }} />
            </Field>
          </Section>
        )}

        {/* ── Code ── */}
        {nodeType === 'code' && (
          <Section title="Code Configuration">
            <Field label="Language">
              <Select size="small" value={String(config.language || 'python')} onChange={(v) => handleChange('language', v)}
                options={[{ label: 'Python', value: 'python' }, { label: 'JavaScript', value: 'javascript' }, { label: 'TypeScript', value: 'typescript' }, { label: 'Shell', value: 'shell' }]} style={{ width: '100%' }} />
            </Field>
            <Field label="Code">
              <div style={{ border: '1px solid var(--border-primary)', borderRadius: 6, overflow: 'hidden' }}>
                <Editor height="180px" language={String(config.language || 'python')}
                  value={String(config.code || '')} onChange={(v) => handleChange('code', v || '')}
                  theme={mode === 'dark' ? 'vs-dark' : 'vs'}
                  options={{ minimap: { enabled: false }, fontSize: 12, lineNumbers: 'on', scrollBeyondLastLine: false, wordWrap: 'on', padding: { top: 8, bottom: 8 }, lineDecorationsWidth: 0 }} />
              </div>
            </Field>
          </Section>
        )}

        {/* ── Condition ── */}
        {nodeType === 'condition' && (
          <Section title="Condition">
            <Field label="Expression">
              <TextArea rows={3} value={String(config.expression || '')}
                onChange={(e) => handleChange('expression', e.target.value)}
                placeholder="value === 'hello'" style={{ ...inputStyle, fontFamily: 'monospace' }} />
            </Field>
            <Field label="True Label">
              <Input size="small" value={String(config.true_label || 'Yes')} onChange={(e) => handleChange('true_label', e.target.value)} style={inputStyle} />
            </Field>
            <Field label="False Label">
              <Input size="small" value={String(config.false_label || 'No')} onChange={(e) => handleChange('false_label', e.target.value)} style={inputStyle} />
            </Field>
          </Section>
        )}

        {/* ── ReAct Agent ── */}
        {nodeType === 'react-agent' && (
          <Section title="ReAct Agent">
            <Field label="Provider">
              <Select size="small" value={String(config.provider || defaultProv?.id || '')} onChange={(v) => handleChange('provider', v)}
                options={providerOptions} style={{ width: '100%' }} />
            </Field>
            <Field label="Model">
              <Input size="small" value={String(config.model || 'gpt-4o')} onChange={(e) => handleChange('model', e.target.value)} placeholder="gpt-4o" style={inputStyle} />
            </Field>
            <Field label="System Prompt">
              <TextArea rows={3} value={String(config.system_prompt || '')} onChange={(e) => handleChange('system_prompt', e.target.value)} placeholder="You are a helpful agent..." style={inputStyle} />
            </Field>
            <Field label="Tools">
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {['run_code', 'run_command', 'read_file', 'write_file', 'search_memory', 'http_request'].map(tool => {
                  const tools = (config.tools as string[]) || ['run_code', 'read_file', 'write_file']
                  const active = tools.includes(tool)
                  return (
                    <button key={tool} onClick={() => handleChange('tools', active ? tools.filter(t => t !== tool) : [...tools, tool])}
                      style={{ padding: '3px 8px', fontSize: 10, borderRadius: 6, cursor: 'pointer',
                        background: active ? 'var(--accent-muted)' : 'var(--bg-input)',
                        border: `1px solid ${active ? 'var(--accent)' : 'var(--border-primary)'}`,
                        color: active ? 'var(--accent)' : 'var(--text-secondary)', fontWeight: 500 }}>
                      {tool}
                    </button>
                  )
                })}
              </div>
            </Field>
            <Field label={`Max Iterations: ${String(config.max_iterations ?? 25)}`}>
              <Slider min={1} max={50} value={Number(config.max_iterations ?? 25)} onChange={(v) => handleChange('max_iterations', v)} />
            </Field>
            <Field label={`Max Time (s): ${String(config.max_time_seconds ?? 300)}`}>
              <Slider min={30} max={600} step={30} value={Number(config.max_time_seconds ?? 300)} onChange={(v) => handleChange('max_time_seconds', v)} />
            </Field>
            <Field label="Use Memory">
              <Select size="small" value={String(config.use_memory ?? false)} onChange={(v) => handleChange('use_memory', v === 'true')}
                options={[{ label: 'Disabled', value: 'false' }, { label: 'Enabled', value: 'true' }]} style={{ width: '100%' }} />
            </Field>
          </Section>
        )}

        {/* ── HTTP Request ── */}
        {nodeType === 'http-request' && (
          <Section title="HTTP Request">
            <Field label="Method">
              <Select size="small" value={String(config.method || 'GET')} onChange={(v) => handleChange('method', v)}
                options={['GET', 'POST', 'PUT', 'DELETE', 'PATCH'].map(m => ({ label: m, value: m }))} style={{ width: '100%' }} />
            </Field>
            <Field label="URL">
              <Input size="small" value={String(config.url || '')} onChange={(e) => handleChange('url', e.target.value)} placeholder="https://api.example.com" style={inputStyle} />
            </Field>
            <Field label="Headers (JSON)">
              <Editor height="70px" language="json"
                value={typeof config.headers === 'string' ? String(config.headers) : JSON.stringify(config.headers || { 'Content-Type': 'application/json' }, null, 2)}
                onChange={(v) => { try { handleChange('headers', JSON.parse(v || '{}')) } catch { handleChange('headers', v || '{}') } }}
                theme={mode === 'dark' ? 'vs-dark' : 'vs'}
                options={{ minimap: { enabled: false }, fontSize: 11, lineNumbers: 'off', scrollBeyondLastLine: false, padding: { top: 4, bottom: 4 } }} />
            </Field>
            <Field label="Body (JSON)">
              <Editor height="80px" language="json"
                value={typeof config.body === 'string' ? String(config.body) : JSON.stringify(config.body || {}, null, 2)}
                onChange={(v) => { try { handleChange('body', JSON.parse(v || '{}')) } catch { handleChange('body', v || '') } }}
                theme={mode === 'dark' ? 'vs-dark' : 'vs'}
                options={{ minimap: { enabled: false }, fontSize: 11, lineNumbers: 'off', scrollBeyondLastLine: false, padding: { top: 4, bottom: 4 } }} />
            </Field>
            <Field label="Timeout (ms)">
              <Input size="small" type="number" value={String(config.timeout_ms || 30000)} onChange={(e) => handleChange('timeout_ms', Number(e.target.value))} style={inputStyle} />
            </Field>
          </Section>
        )}

        {/* ── Shell ── */}
        {nodeType === 'shell' && (
          <Section title="Shell Command">
            <Field label="Command">
              <TextArea rows={3} value={String(config.command || '')} onChange={(e) => handleChange('command', e.target.value)} placeholder="ls -la" style={{ ...inputStyle, fontFamily: 'monospace' }} />
            </Field>
            <Field label="Working Directory">
              <Input size="small" value={String(config.cwd || '')} onChange={(e) => handleChange('cwd', e.target.value)} placeholder="/path/to/dir" style={inputStyle} />
            </Field>
            <Field label={`Timeout (ms): ${String(config.timeout_ms ?? 30000)}`}>
              <Slider min={5000} max={120000} step={5000} value={Number(config.timeout_ms ?? 30000)} onChange={(v) => handleChange('timeout_ms', v)} />
            </Field>
          </Section>
        )}

        {/* ── File Explorer ── */}
        {nodeType === 'file-explorer' && (
          <Section title="File Explorer">
            <Field label="Root Path">
              <Input size="small" value={String(config.root_path || '')} onChange={(e) => handleChange('root_path', e.target.value)} placeholder="/path/to/project" style={inputStyle} />
            </Field>
            <Field label="File Types (comma separated)">
              <Input size="small" value={Array.isArray(config.file_types) ? (config.file_types as string[]).join(', ') : String(config.file_types || '')} onChange={(e) => handleChange('file_types', e.target.value.split(',').map(s => s.trim()).filter(Boolean))} placeholder=".ts, .tsx, .js" style={inputStyle} />
            </Field>
            <Field label="Exclude Patterns (comma separated)">
              <Input size="small" value={Array.isArray(config.exclude_patterns) ? (config.exclude_patterns as string[]).join(', ') : String(config.exclude_patterns || 'node_modules, .git, dist')} onChange={(e) => handleChange('exclude_patterns', e.target.value.split(',').map(s => s.trim()).filter(Boolean))} style={inputStyle} />
            </Field>
            <Field label={`Max Depth: ${String(config.max_depth ?? 10)}`}>
              <Slider min={1} max={50} value={Number(config.max_depth ?? 10)} onChange={(v) => handleChange('max_depth', v)} />
            </Field>
            <Field label={`Max Files: ${String(config.max_files ?? 1000)}`}>
              <Slider min={10} max={10000} step={50} value={Number(config.max_files ?? 1000)} onChange={(v) => handleChange('max_files', v)} />
            </Field>
            <Field label="Include Hidden">
              <Select size="small" value={String(config.include_hidden ?? false)} onChange={(v) => handleChange('include_hidden', v === 'true')}
                options={[{ label: 'No', value: 'false' }, { label: 'Yes', value: 'true' }]} style={{ width: '100%' }} />
            </Field>
          </Section>
        )}

        {/* ── File Reader ── */}
        {nodeType === 'file-reader' && (
          <Section title="File Reader">
            <Field label="File Path">
              <Input size="small" value={String(config.path || '')} onChange={(e) => handleChange('path', e.target.value)} placeholder="/path/to/file.txt" style={inputStyle} />
            </Field>
            <Field label="Mode">
              <Select size="small" value={String(config.mode || 'auto')} onChange={(v) => handleChange('mode', v)}
                options={[{ label: 'Auto', value: 'auto' }, { label: 'Plain Text', value: 'plain' }, { label: 'Markdown', value: 'markdown' }, { label: 'Structured', value: 'structured' }]} style={{ width: '100%' }} />
            </Field>
            <Field label={`Max Size (MB): ${String(config.max_size_mb ?? 10)}`}>
              <Slider min={1} max={50} value={Number(config.max_size_mb ?? 10)} onChange={(v) => handleChange('max_size_mb', v)} />
            </Field>
          </Section>
        )}

        {/* ── File Write ── */}
        {nodeType === 'file-write' && (
          <Section title="File Write">
            <Field label="File Path">
              <Input size="small" value={String(config.path || '')} onChange={(e) => handleChange('path', e.target.value)} placeholder="/path/to/output.txt" style={inputStyle} />
            </Field>
            <Field label="Content">
              <TextArea rows={4} value={String(config.content || '')} onChange={(e) => handleChange('content', e.target.value)} placeholder="Content to write..." style={inputStyle} />
            </Field>
            <Field label="Create Directories">
              <Select size="small" value={String(config.create_dirs ?? true)} onChange={(v) => handleChange('create_dirs', v === 'true')}
                options={[{ label: 'Yes', value: 'true' }, { label: 'No', value: 'false' }]} style={{ width: '100%' }} />
            </Field>
          </Section>
        )}

        {/* ── Context Loader ── */}
        {nodeType === 'context-loader' && (
          <Section title="Context Loader">
            <Field label="Root Path">
              <Input size="small" value={String(config.root_path || '')} onChange={(e) => handleChange('root_path', e.target.value)} placeholder="/path/to/project" style={inputStyle} />
            </Field>
            <Field label="File Types (comma separated)">
              <Input size="small" value={Array.isArray(config.file_types) ? (config.file_types as string[]).join(', ') : ''} onChange={(e) => handleChange('file_types', e.target.value.split(',').map(s => s.trim()).filter(Boolean))} placeholder="ts, tsx, js, py" style={inputStyle} />
            </Field>
            <Field label="Exclude Patterns (comma separated)">
              <Input size="small" value={Array.isArray(config.exclude_patterns) ? (config.exclude_patterns as string[]).join(', ') : 'node_modules, .git, dist'} onChange={(e) => handleChange('exclude_patterns', e.target.value.split(',').map(s => s.trim()).filter(Boolean))} style={inputStyle} />
            </Field>
            <Field label={`Max Files: ${String(config.max_files ?? 50)}`}>
              <Slider min={5} max={200} value={Number(config.max_files ?? 50)} onChange={(v) => handleChange('max_files', v)} />
            </Field>
            <Field label={`Max Total Chars: ${String(config.max_total_chars ?? 100000)}`}>
              <Slider min={10000} max={500000} step={10000} value={Number(config.max_total_chars ?? 100000)} onChange={(v) => handleChange('max_total_chars', v)} />
            </Field>
            <Field label="Include Directory Tree">
              <Select size="small" value={String(config.include_tree ?? true)} onChange={(v) => handleChange('include_tree', v === 'true')}
                options={[{ label: 'Yes', value: 'true' }, { label: 'No', value: 'false' }]} style={{ width: '100%' }} />
            </Field>
            <Field label="Include File Content">
              <Select size="small" value={String(config.include_file_content ?? true)} onChange={(v) => handleChange('include_file_content', v === 'true')}
                options={[{ label: 'Yes', value: 'true' }, { label: 'No', value: 'false' }]} style={{ width: '100%' }} />
            </Field>
            <Field label="Convert PDFs">
              <Select size="small" value={String(config.convert_pdfs ?? false)} onChange={(v) => handleChange('convert_pdfs', v === 'true')}
                options={[{ label: 'No', value: 'false' }, { label: 'Yes', value: 'true' }]} style={{ width: '100%' }} />
            </Field>
            <Field label="Convert Office Docs">
              <Select size="small" value={String(config.convert_office_docs ?? false)} onChange={(v) => handleChange('convert_office_docs', v === 'true')}
                options={[{ label: 'No', value: 'false' }, { label: 'Yes', value: 'true' }]} style={{ width: '100%' }} />
            </Field>
          </Section>
        )}

        {/* ── Agent Orchestrator ── */}
        {nodeType === 'agent-orchestrator' && (
          <Section title="Agent Orchestrator">
            <Field label="Task">
              <TextArea rows={3} value={String(config.task || '')} onChange={(e) => handleChange('task', e.target.value)} placeholder="Describe the task for the team..." style={inputStyle} />
            </Field>
            <Field label="Expected Output">
              <Input size="small" value={String(config.expected_output || '')} onChange={(e) => handleChange('expected_output', e.target.value)} placeholder="What success looks like" style={inputStyle} />
            </Field>
            <Field label="Process Type">
              <Select size="small" value={String(config.process || 'sequential')} onChange={(v) => handleChange('process', v)}
                options={[{ label: 'Sequential', value: 'sequential' }, { label: 'Hierarchical', value: 'hierarchical' }]} style={{ width: '100%' }} />
            </Field>
            <Field label={`Max Rounds: ${String(config.max_rounds ?? 15)}`}>
              <Slider min={1} max={30} value={Number(config.max_rounds ?? 15)} onChange={(v) => handleChange('max_rounds', v)} />
            </Field>
            <Field label={`Max Stalls: ${String(config.max_stalls ?? 3)}`}>
              <Slider min={1} max={10} value={Number(config.max_stalls ?? 3)} onChange={(v) => handleChange('max_stalls', v)} />
            </Field>
            <Field label="Planning">
              <Select size="small" value={String(config.planning ?? false)} onChange={(v) => handleChange('planning', v === 'true')}
                options={[{ label: 'Disabled', value: 'false' }, { label: 'Enabled', value: 'true' }]} style={{ width: '100%' }} />
            </Field>
            <Field label="Manager Model (Hierarchical)">
              <Input size="small" value={String(config.manager_model || 'gpt-4o')} onChange={(e) => handleChange('manager_model', e.target.value)} style={inputStyle} />
            </Field>
            <AgentListEditor config={config} onChange={handleChange} />
          </Section>
        )}

        {/* ── Knowledge Retrieval ── */}
        {nodeType === 'knowledge-retrieval' && (
          <Section title="Knowledge Retrieval">
            <Field label={`Top K: ${String(config.top_k ?? 5)}`}>
              <Slider min={1} max={20} value={Number(config.top_k ?? 5)} onChange={(v) => handleChange('top_k', v)} />
            </Field>
            <Field label="Layer">
              <Select size="small" value={String(config.layer || 'all')} onChange={(v) => handleChange('layer', v)}
                options={[{ label: 'All', value: 'all' }, { label: 'Semantic', value: 'semantic' }, { label: 'Episodic', value: 'episodic' }, { label: 'Procedural', value: 'procedural' }]} style={{ width: '100%' }} />
            </Field>
            <Field label="Query">
              <TextArea rows={2} value={String(config.query || '')} onChange={(e) => handleChange('query', e.target.value)} placeholder="Search query..." style={inputStyle} />
            </Field>
          </Section>
        )}

        {/* ── Webhook Trigger ── */}
        {nodeType === 'webhook-trigger' && (
          <Section title="Webhook Trigger">
            <Field label="Path">
              <Input size="small" value={String(config.path || '/webhook')} onChange={(e) => handleChange('path', e.target.value)} placeholder="/webhook" style={{ ...inputStyle, fontFamily: 'monospace' }} />
            </Field>
            <Field label="Method">
              <Select size="small" value={String(config.method || 'POST')} onChange={(v) => handleChange('method', v)}
                options={['GET', 'POST', 'PUT'].map(m => ({ label: m, value: m }))} style={{ width: '100%' }} />
            </Field>
            <Field label="Secret Token">
              <Input size="small" value={String(config.secret || '')} onChange={(e) => handleChange('secret', e.target.value)} placeholder="Optional auth token" style={inputStyle} />
            </Field>
          </Section>
        )}

        {/* ── Manual Trigger ── */}
        {nodeType === 'manual-trigger' && (
          <Section title="Trigger Variables">
            <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 8 }}>
              Define input variables for this workflow.
            </div>
            <Field label="Variables (JSON)">
              <Editor height="100px" language="json"
                value={JSON.stringify(config.variables || [], null, 2)}
                onChange={(v) => { try { handleChange('variables', JSON.parse(v || '[]')) } catch {} }}
                theme={mode === 'dark' ? 'vs-dark' : 'vs'}
                options={{ minimap: { enabled: false }, fontSize: 11, lineNumbers: 'off', scrollBeyondLastLine: false, padding: { top: 4, bottom: 4 } }} />
            </Field>
          </Section>
        )}

        {/* ── Schedule Trigger ── */}
        {nodeType === 'schedule-trigger' && (
          <Section title="Schedule">
            <Field label="Cron Expression">
              <Input size="small" value={String(config.cron || '0 * * * *')} onChange={(e) => handleChange('cron', e.target.value)} placeholder="0 * * * *" style={{ ...inputStyle, fontFamily: 'monospace' }} />
            </Field>
            <Field label="Timezone">
              <Input size="small" value={String(config.timezone || 'UTC')} onChange={(e) => handleChange('timezone', e.target.value)} placeholder="UTC" style={inputStyle} />
            </Field>
          </Section>
        )}

        {/* ── Iteration ── */}
        {nodeType === 'iteration' && (
          <Section title="Iteration (For-Each)">
            <Field label="Array Input">
              <Input size="small" value={String(config.array_input || '')} onChange={(e) => handleChange('array_input', e.target.value)} placeholder="{{#nodeId.items#}}" style={{ ...inputStyle, fontFamily: 'monospace' }} />
            </Field>
            <Field label={`Max Iterations: ${String(config.max_iterations ?? 100)}`}>
              <Slider min={1} max={500} value={Number(config.max_iterations ?? 100)} onChange={(v) => handleChange('max_iterations', v)} />
            </Field>
          </Section>
        )}

        {/* ── Loop ── */}
        {nodeType === 'loop' && (
          <Section title="Loop (While)">
            <Field label="Condition">
              <TextArea rows={2} value={String(config.condition || '')} onChange={(e) => handleChange('condition', e.target.value)} placeholder="iteration < 10" style={{ ...inputStyle, fontFamily: 'monospace' }} />
            </Field>
            <Field label={`Max Iterations: ${String(config.max_iterations ?? 100)}`}>
              <Slider min={1} max={500} value={Number(config.max_iterations ?? 100)} onChange={(v) => handleChange('max_iterations', v)} />
            </Field>
          </Section>
        )}

        {/* ── Variable Aggregator ── */}
        {nodeType === 'variable-aggregator' && (
          <Section title="Variable Aggregator">
            <Field label="Variables (JSON array of node refs)">
              <Editor height="100px" language="json"
                value={JSON.stringify(config.variables || [], null, 2)}
                onChange={(v) => { try { handleChange('variables', JSON.parse(v || '[]')) } catch {} }}
                theme={mode === 'dark' ? 'vs-dark' : 'vs'}
                options={{ minimap: { enabled: false }, fontSize: 11, lineNumbers: 'off', scrollBeyondLastLine: false, padding: { top: 4, bottom: 4 } }} />
            </Field>
            <Field label="Mode">
              <Select size="small" value={String(config.mode || 'concat')} onChange={(v) => handleChange('mode', v)}
                options={[{ label: 'Concat', value: 'concat' }, { label: 'First', value: 'first' }, { label: 'Array', value: 'array' }]} style={{ width: '100%' }} />
            </Field>
          </Section>
        )}

        {/* ── Variable Assigner ── */}
        {nodeType === 'variable-assigner' && (
          <Section title="Variable Assigner">
            <Field label="Variable Name">
              <Input size="small" value={String(config.variable_name || '')} onChange={(e) => handleChange('variable_name', e.target.value)} placeholder="myVar" style={inputStyle} />
            </Field>
            <Field label="Value">
              <TextArea rows={2} value={String(config.value || '')} onChange={(e) => handleChange('value', e.target.value)} placeholder="{{#nodeId.output#}} or literal" style={inputStyle} />
            </Field>
          </Section>
        )}

        {/* ── Template ── */}
        {nodeType === 'template' && (
          <Section title="Template">
            <Field label="Template (use {{#nodeId.key#}} for variables)">
              <TextArea rows={5} value={String(config.template || '')} onChange={(e) => handleChange('template', e.target.value)} placeholder="Hello {{#start.name#}}!" style={{ ...inputStyle, fontFamily: 'monospace' }} />
            </Field>
          </Section>
        )}

        {/* ── Parameter Extractor ── */}
        {nodeType === 'parameter-extractor' && (
          <Section title="Parameter Extractor">
            <Field label="Model">
              <Input size="small" value={String(config.model || 'gpt-4o-mini')} onChange={(e) => handleChange('model', e.target.value)} style={inputStyle} />
            </Field>
            <Field label="Input Text">
              <TextArea rows={2} value={String(config.input_text || '')} onChange={(e) => handleChange('input_text', e.target.value)} placeholder="{{#llm.output#}}" style={inputStyle} />
            </Field>
            <Field label="Parameters (JSON array)">
              <Editor height="120px" language="json"
                value={JSON.stringify(config.parameters || [], null, 2)}
                onChange={(v) => { try { handleChange('parameters', JSON.parse(v || '[]')) } catch {} }}
                theme={mode === 'dark' ? 'vs-dark' : 'vs'}
                options={{ minimap: { enabled: false }, fontSize: 11, lineNumbers: 'off', scrollBeyondLastLine: false, padding: { top: 4, bottom: 4 } }} />
            </Field>
          </Section>
        )}

        {/* ── Question Classifier ── */}
        {nodeType === 'question-classifier' && (
          <Section title="Question Classifier">
            <Field label="Model">
              <Input size="small" value={String(config.model || 'gpt-4o-mini')} onChange={(e) => handleChange('model', e.target.value)} style={inputStyle} />
            </Field>
            <Field label="Categories (comma separated)">
              <Input size="small" value={String((config.categories as string[])?.join(', ') || '')}
                onChange={(e) => handleChange('categories', e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
                placeholder="bug, feature, question" style={inputStyle} />
            </Field>
            <Field label="Instructions">
              <TextArea rows={2} value={String(config.instructions || '')} onChange={(e) => handleChange('instructions', e.target.value)} placeholder="Classify the user question..." style={inputStyle} />
            </Field>
          </Section>
        )}

        {/* ── Sub-Workflow ── */}
        {nodeType === 'sub-workflow' && (
          <Section title="Sub-Workflow">
            <Field label="Workflow ID">
              <Input size="small" value={String(config.workflow_id || '')} onChange={(e) => handleChange('workflow_id', e.target.value)} placeholder="workflow-id" style={inputStyle} />
            </Field>
            <Field label="Input Mapping (JSON)">
              <Editor height="80px" language="json"
                value={JSON.stringify(config.inputs || {}, null, 2)}
                onChange={(v) => { try { handleChange('inputs', JSON.parse(v || '{}')) } catch {} }}
                theme={mode === 'dark' ? 'vs-dark' : 'vs'}
                options={{ minimap: { enabled: false }, fontSize: 11, lineNumbers: 'off', scrollBeyondLastLine: false, padding: { top: 4, bottom: 4 } }} />
            </Field>
          </Section>
        )}

        {/* ── Comment ── */}
        {nodeType === 'comment' && (
          <Section title="Comment">
            <Field label="Text">
              <TextArea rows={4} value={String(config.text || data.text || '')} onChange={(e) => handleChange('text', e.target.value)} placeholder="Add notes..." style={inputStyle} />
            </Field>
          </Section>
        )}
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ padding: 10, background: 'var(--bg-card)', border: '1px solid var(--border-primary)', borderRadius: 8, marginBottom: 8 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 10 }}>{title}</div>
      {children}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={labelStyle}>{label}</div>
      {children}
    </div>
  )
}

function AgentListEditor({ config, onChange }: { config: Record<string, unknown>; onChange: (f: string, v: unknown) => void }) {
  const agents = (config.agents as Record<string, unknown>[]) || []
  return (
    <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--border-primary)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)' }}>Agents</div>
        <button onClick={() => {
          const next = [...agents, { id: `agent-${agents.length + 1}`, name: `Agent ${agents.length + 1}`, role: '', goal: '', model: 'gpt-4o', provider: 'openai', tools: ['read_file', 'write_file'] }]
          onChange('agents', next)
        }} style={{ padding: '2px 8px', fontSize: 10, borderRadius: 6, cursor: 'pointer', background: 'var(--accent)', color: '#fff', border: 'none', fontWeight: 500 }}>
          + Add
        </button>
      </div>
      {agents.map((a, idx) => (
        <div key={idx} style={{ padding: 8, background: 'var(--bg-input)', border: '1px solid var(--border-primary)', borderRadius: 6, marginBottom: 6 }}>
          <div style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
            <Input size="small" value={String(a.name || '')} onChange={(e) => {
              const next = [...agents]; next[idx] = { ...next[idx], name: e.target.value }; onChange('agents', next)
            }} placeholder="Name" style={{ ...inputStyle, fontWeight: 600, flex: 1 }} />
            <button onClick={() => { const next = [...agents]; next.splice(idx, 1); onChange('agents', next) }}
              style={{ width: 22, height: 22, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--error)', fontSize: 14 }}>×</button>
          </div>
          <Input size="small" value={String(a.role || '')} onChange={(e) => {
            const next = [...agents]; next[idx] = { ...next[idx], role: e.target.value }; onChange('agents', next)
          }} placeholder="Role" style={{ ...inputStyle, marginBottom: 4 }} />
          <Input size="small" value={String(a.model || 'gpt-4o')} onChange={(e) => {
            const next = [...agents]; next[idx] = { ...next[idx], model: e.target.value }; onChange('agents', next)
          }} placeholder="Model" style={inputStyle} />
        </div>
      ))}
      {agents.length === 0 && (
        <div style={{ fontSize: 10, color: 'var(--text-tertiary)', textAlign: 'center', padding: '6px 0' }}>No agents configured.</div>
      )}
    </div>
  )
}
