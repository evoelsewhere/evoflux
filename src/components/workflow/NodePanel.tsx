import { Form, Input, Select, Slider, Button } from 'antd'
import Editor from '@monaco-editor/react'
import { useWorkflowStore } from '../../stores/workflowStore'
import { useSettingsStore } from '../../stores/settingsStore'
import { getNodeDefinition } from './registry'
import { useTheme } from '../common/ThemeProvider'

const { TextArea } = Input

function TrashIcon() {
  return <svg width={12} height={12} viewBox="0 0 12 12" fill="none"><path d="M2 3H10M4.5 3V2C4.5 1.4 4.9 1 5.5 1H6.5C7.1 1 7.5 1.4 7.5 2V3M9.5 3V10C9.5 10.6 9.1 11 8.5 11H3.5C2.9 11 2.5 10.6 2.5 10V3" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" /><path d="M5 5.5V8.5M7 5.5V8.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" /></svg>
}

export default function NodePanel() {
  const { nodes, selectedNodeId, updateNodeData, removeNode } = useWorkflowStore()
  const { aiProvider } = useSettingsStore()
  const { mode } = useTheme()
  const selectedNode = nodes.find((n) => n.id === selectedNodeId)

  if (!selectedNode) {
    return (
      <div style={{
        width: 300, borderLeft: '1px solid var(--border-primary)',
        background: 'var(--bg-secondary)', padding: 24,
        display: 'flex', alignItems: 'center', justifyContent: 'center'
      }}>
        <span style={{ color: 'var(--text-tertiary)', fontSize: 13 }}>Select a node to edit</span>
      </div>
    )
  }

  const { data } = selectedNode
  const nodeType = data.type || 'default'
  const definition = getNodeDefinition(nodeType)
  const config = (data.config || {}) as Record<string, unknown>

  const handleChange = (field: string, value: unknown) => {
    updateNodeData(selectedNode.id, { config: { ...config, [field]: value } })
  }

  const handleLabelChange = (label: string) => {
    updateNodeData(selectedNode.id, { label })
  }

  const labelStyle: React.CSSProperties = { color: 'var(--text-secondary)', fontSize: 12, fontWeight: 500, marginBottom: 4 }
  const inputStyle = { background: 'var(--bg-input)', borderColor: 'var(--border-primary)', fontSize: 12 }

  return (
    <div style={{
      width: 300, borderLeft: '1px solid var(--border-primary)',
      background: 'var(--bg-secondary)', overflow: 'auto'
    }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '12px 16px', borderBottom: '1px solid var(--border-primary)'
      }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>Properties</div>
          {definition && (
            <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 2 }}>{definition.description}</div>
          )}
        </div>
        <Button danger type="text" icon={<TrashIcon />} onClick={() => removeNode(selectedNode.id)} size="small" style={{ color: 'var(--error)' }} />
      </div>

      <div style={{ padding: 16 }}>
        <Form layout="vertical" size="small">
          <div style={{ marginBottom: 12 }}>
            <div style={labelStyle}>Label</div>
            <Input value={data.label} onChange={(e) => handleLabelChange(e.target.value)} style={inputStyle} />
          </div>

          <div style={{ marginBottom: 12 }}>
            <div style={labelStyle}>Type</div>
            <Input value={nodeType} disabled style={{ ...inputStyle, color: 'var(--text-tertiary)' }} />
          </div>

          <div style={{ marginBottom: 12 }}>
            <div style={labelStyle}>Category</div>
            <Input value={data.category || ''} disabled style={{ ...inputStyle, color: 'var(--text-tertiary)' }} />
          </div>

          {/* LLM Config */}
          {nodeType === 'llm' && (
            <div style={{ padding: 12, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>AI Configuration</div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Provider</div>
                <Select value={String(config.provider || aiProvider)} onChange={(v) => handleChange('provider', v)} options={[{ label: 'OpenAI', value: 'openai' }, { label: 'Anthropic', value: 'anthropic' }, { label: 'Ollama', value: 'ollama' }, { label: 'Claude CLI', value: 'claude-cli' }, { label: 'Copilot CLI', value: 'copilot-cli' }]} style={{ width: '100%' }} />
              </div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Model</div>
                <Input value={String(config.model || '')} onChange={(e) => handleChange('model', e.target.value)} placeholder="gpt-4o / claude-sonnet-4-20250514" style={inputStyle} />
              </div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>System Prompt</div>
                <TextArea rows={3} value={String(config.system_prompt || '')} onChange={(e) => handleChange('system_prompt', e.target.value)} placeholder="You are a helpful assistant..." style={inputStyle} />
              </div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Prompt</div>
                <TextArea rows={5} value={String(config.prompt || '')} onChange={(e) => handleChange('prompt', e.target.value)} placeholder="Enter your prompt..." style={inputStyle} />
              </div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Temperature: {String(config.temperature || 0.7)}</div>
                <Slider min={0} max={2} step={0.1} value={Number(config.temperature || 0.7)} onChange={(v) => handleChange('temperature', v)} />
              </div>
              <div>
                <div style={labelStyle}>Max Tokens: {String(config.max_tokens || 2048)}</div>
                <Slider min={256} max={8192} step={256} value={Number(config.max_tokens || 2048)} onChange={(v) => handleChange('max_tokens', v)} />
              </div>
            </div>
          )}

          {/* Code Config */}
          {nodeType === 'code' && (
            <div style={{ padding: 12, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>Code Configuration</div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Language</div>
                <Select value={String(config.language || 'python')} onChange={(v) => handleChange('language', v)} options={[{ label: 'Python', value: 'python' }, { label: 'JavaScript', value: 'javascript' }]} style={{ width: '100%' }} />
              </div>
              <div>
                <div style={labelStyle}>Code</div>
                <div style={{ border: '1px solid var(--border-primary)', borderRadius: 6, overflow: 'hidden' }}>
                  <Editor
                    height="200px"
                    language={String(config.language || 'python') === 'python' ? 'python' : 'javascript'}
                    value={String(config.code || '')}
                    onChange={(v) => handleChange('code', v || '')}
                    theme={mode === 'dark' ? 'vs-dark' : 'vs'}
                    options={{
                      minimap: { enabled: false },
                      fontSize: 12,
                      lineNumbers: 'on',
                      scrollBeyondLastLine: false,
                      wordWrap: 'on',
                      padding: { top: 8, bottom: 8 },
                      lineDecorationsWidth: 0
                    }}
                  />
                </div>
              </div>
            </div>
          )}

          {/* Condition Config */}
          {nodeType === 'condition' && (
            <div style={{ padding: 12, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>Condition</div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Expression</div>
                <TextArea rows={3} value={String(config.expression || '')} onChange={(e) => handleChange('expression', e.target.value)} placeholder="value === 'hello'" style={{ ...inputStyle, fontFamily: 'monospace' }} />
              </div>
            </div>
          )}

          {/* ReAct Agent Config */}
          {nodeType === 'react-agent' && (
            <div style={{ padding: 12, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>ReAct Agent</div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Provider</div>
                <Select value={String(config.provider || aiProvider)} onChange={(v) => handleChange('provider', v)} options={[{ label: 'OpenAI', value: 'openai' }, { label: 'Anthropic', value: 'anthropic' }, { label: 'Ollama', value: 'ollama' }, { label: 'Claude CLI', value: 'claude-cli' }, { label: 'Copilot CLI', value: 'copilot-cli' }]} style={{ width: '100%' }} />
              </div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Model</div>
                <Input value={String(config.model || 'gpt-4o')} onChange={(e) => handleChange('model', e.target.value)} placeholder="gpt-4o" style={inputStyle} />
              </div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>System Prompt</div>
                <TextArea rows={4} value={String(config.system_prompt || '')} onChange={(e) => handleChange('system_prompt', e.target.value)} placeholder="You are a helpful agent..." style={inputStyle} />
              </div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Tools</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                  {['run_code', 'run_command', 'read_file', 'write_file', 'search_memory', 'http_request'].map(tool => {
                    const tools = (config.tools as string[]) || ['run_code', 'read_file', 'write_file']
                    const active = tools.includes(tool)
                    return (
                      <button
                        key={tool}
                        onClick={() => {
                          const next = active ? tools.filter(t => t !== tool) : [...tools, tool]
                          handleChange('tools', next)
                        }}
                        style={{
                          padding: '3px 8px', fontSize: 11, borderRadius: 6, cursor: 'pointer',
                          background: active ? 'var(--accent-muted)' : 'var(--bg-input)',
                          border: `1px solid ${active ? 'var(--accent)' : 'var(--border-primary)'}`,
                          color: active ? 'var(--accent)' : 'var(--text-secondary)',
                          fontWeight: 500
                        }}
                      >
                        {tool}
                      </button>
                    )
                  })}
                </div>
              </div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Max Iterations: {String(config.max_iterations || 25)}</div>
                <Slider min={1} max={50} value={Number(config.max_iterations || 25)} onChange={(v) => handleChange('max_iterations', v)} />
              </div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Max Time (seconds): {String(config.max_time_seconds || 300)}</div>
                <Slider min={30} max={600} step={30} value={Number(config.max_time_seconds || 300)} onChange={(v) => handleChange('max_time_seconds', v)} />
              </div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Use Memory</div>
                <Select value={String(config.use_memory || false)} onChange={(v) => handleChange('use_memory', v)} options={[{ label: 'Disabled', value: 'false' }, { label: 'Enabled', value: 'true' }]} style={{ width: '100%' }} />
              </div>
              <div>
                <div style={labelStyle}>Custom Tools (JSON Schema)</div>
                <div style={{ border: '1px solid var(--border-primary)', borderRadius: 6, overflow: 'hidden' }}>
                  <Editor
                    height="120px"
                    language="json"
                    value={JSON.stringify(config.custom_tools || [], null, 2)}
                    onChange={(v) => {
                      try { handleChange('custom_tools', JSON.parse(v || '[]')) } catch { /* ignore */ }
                    }}
                    theme={mode === 'dark' ? 'vs-dark' : 'vs'}
                    options={{ minimap: { enabled: false }, fontSize: 11, lineNumbers: 'off', scrollBeyondLastLine: false, padding: { top: 4, bottom: 4 } }}
                  />
                </div>
                <div style={{ fontSize: 10, color: 'var(--text-tertiary)', marginTop: 4 }}>
                  Define custom tools: [{'{'}"name": "...", "description": "...", "parameters": [...]{'}'}]
                </div>
              </div>
            </div>
          )}

          {/* HTTP Config */}
          {nodeType === 'http-request' && (
            <div style={{ padding: 12, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>HTTP Request</div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Method</div>
                <Select value={String(config.method || 'GET')} onChange={(v) => handleChange('method', v)} options={['GET', 'POST', 'PUT', 'DELETE', 'PATCH'].map(m => ({ label: m, value: m }))} style={{ width: '100%' }} />
              </div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>URL</div>
                <Input value={String(config.url || '')} onChange={(e) => handleChange('url', e.target.value)} placeholder="https://api.example.com" style={inputStyle} />
              </div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Headers (JSON)</div>
                <Editor
                  height="80px"
                  language="json"
                  value={typeof config.headers === 'string' ? String(config.headers) : JSON.stringify(config.headers || { 'Content-Type': 'application/json' }, null, 2)}
                  onChange={(v) => {
                    try { handleChange('headers', JSON.parse(v || '{}')) } catch { handleChange('headers', v || '{}') }
                  }}
                  theme={mode === 'dark' ? 'vs-dark' : 'vs'}
                  options={{ minimap: { enabled: false }, fontSize: 11, lineNumbers: 'off', scrollBeyondLastLine: false, padding: { top: 4, bottom: 4 } }}
                />
              </div>
              <div>
                <div style={labelStyle}>Body (JSON)</div>
                <Editor
                  height="100px"
                  language="json"
                  value={typeof config.body === 'string' ? String(config.body) : JSON.stringify(config.body || {}, null, 2)}
                  onChange={(v) => {
                    try { handleChange('body', JSON.parse(v || '{}')) } catch { handleChange('body', v || '') }
                  }}
                  theme={mode === 'dark' ? 'vs-dark' : 'vs'}
                  options={{ minimap: { enabled: false }, fontSize: 11, lineNumbers: 'off', scrollBeyondLastLine: false, padding: { top: 4, bottom: 4 } }}
                />
              </div>
            </div>
          )}

          {/* Shell Config */}
          {nodeType === 'shell' && (
            <div style={{ padding: 12, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>Shell Command</div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Command</div>
                <TextArea rows={3} value={String(config.command || '')} onChange={(e) => handleChange('command', e.target.value)} placeholder="ls -la" style={{ ...inputStyle, fontFamily: 'monospace' }} />
              </div>
              <div>
                <div style={labelStyle}>Timeout (ms): {String(config.timeout_ms || 30000)}</div>
                <Slider min={5000} max={120000} step={5000} value={Number(config.timeout_ms || 30000)} onChange={(v) => handleChange('timeout_ms', v)} />
              </div>
            </div>
          )}

          {/* File Explorer Config */}
          {nodeType === 'file-explorer' && (
            <div style={{ padding: 12, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>File Explorer</div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Root Path</div>
                <Input value={String(config.root_path || '')} onChange={(e) => handleChange('root_path', e.target.value)} placeholder="/path/to/project" style={inputStyle} />
              </div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>File Types (comma separated)</div>
                <Input value={String(config.file_types || '')} onChange={(e) => handleChange('file_types', e.target.value)} placeholder=".ts, .tsx, .js" style={inputStyle} />
              </div>
              <div>
                <div style={labelStyle}>Exclude Patterns</div>
                <Input value={String(config.exclude_patterns || 'node_modules, .git, dist')} onChange={(e) => handleChange('exclude_patterns', e.target.value)} style={inputStyle} />
              </div>
            </div>
          )}

          {/* Context Loader Config */}
          {nodeType === 'context-loader' && (
            <div style={{ padding: 12, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>Context Loader</div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Root Path</div>
                <Input value={String(config.root_path || '')} onChange={(e) => handleChange('root_path', e.target.value)} placeholder="/path/to/project" style={inputStyle} />
              </div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Max Files: {String(config.max_files || 50)}</div>
                <Slider min={5} max={200} value={Number(config.max_files || 50)} onChange={(v) => handleChange('max_files', v)} />
              </div>
              <div>
                <div style={labelStyle}>Max Total Chars: {String(config.max_total_chars || 100000)}</div>
                <Slider min={10000} max={500000} step={10000} value={Number(config.max_total_chars || 100000)} onChange={(v) => handleChange('max_total_chars', v)} />
              </div>
            </div>
          )}

          {/* Orchestrator Config */}
          {nodeType === 'agent-orchestrator' && (
            <div style={{ padding: 12, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>Agent Orchestrator</div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Task</div>
                <TextArea rows={3} value={String(config.task || '')} onChange={(e) => handleChange('task', e.target.value)} placeholder="Describe the task for the team..." style={inputStyle} />
              </div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Expected Output</div>
                <Input value={String(config.expected_output || '')} onChange={(e) => handleChange('expected_output', e.target.value)} placeholder="What success looks like" style={inputStyle} />
              </div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Process Type</div>
                <Select value={String(config.process || 'sequential')} onChange={(v) => handleChange('process', v)} options={[{ label: 'Sequential', value: 'sequential' }, { label: 'Hierarchical', value: 'hierarchical' }]} style={{ width: '100%' }} />
              </div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Planning</div>
                <Select value={String(config.planning || false)} onChange={(v) => handleChange('planning', v)} options={[{ label: 'Disabled', value: 'false' }, { label: 'Enabled', value: 'true' }]} style={{ width: '100%' }} />
              </div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Max Rounds: {String(config.max_rounds || 15)}</div>
                <Slider min={1} max={30} value={Number(config.max_rounds || 15)} onChange={(v) => handleChange('max_rounds', v)} />
              </div>

              {/* Agent List Editor */}
              <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--border-primary)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>Agents</div>
                  <button
                    onClick={() => {
                      const agents = ([...(config.agents as unknown[] || [])]) as Record<string, unknown>[]
                      agents.push({
                        id: `agent-${agents.length + 1}`,
                        name: `Agent ${agents.length + 1}`,
                        role: '',
                        goal: '',
                        backstory: '',
                        model: 'gpt-4o',
                        provider: 'openai',
                        tools: ['read_file', 'write_file'],
                        allowDelegation: false,
                        maxIterations: 10
                      })
                      handleChange('agents', agents)
                    }}
                    style={{
                      padding: '3px 8px', fontSize: 11, borderRadius: 6, cursor: 'pointer',
                      background: 'var(--accent)', color: 'var(--text-primary)', border: 'none', fontWeight: 500
                    }}
                  >
                    + Add Agent
                  </button>
                </div>

                {((config.agents as unknown[]) || []).map((agent, idx) => {
                  const a = agent as Record<string, unknown>
                  return (
                    <div key={idx} style={{
                      padding: 10, background: 'var(--bg-input)', border: '1px solid var(--border-primary)',
                      borderRadius: 8, marginBottom: 8
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                        <Input
                          value={String(a.name || '')}
                          onChange={(e) => {
                            const agents = [...(config.agents as unknown[] || [])] as Record<string, unknown>[]
                            agents[idx] = { ...agents[idx], name: e.target.value }
                            handleChange('agents', agents)
                          }}
                          placeholder="Agent Name"
                          style={{ ...inputStyle, fontWeight: 600, flex: 1, marginRight: 4 }}
                          size="small"
                        />
                        <button
                          onClick={() => {
                            const agents = [...(config.agents as unknown[] || [])] as Record<string, unknown>[]
                            agents.splice(idx, 1)
                            handleChange('agents', agents)
                          }}
                          style={{
                            width: 24, height: 24, display: 'flex', alignItems: 'center', justifyContent: 'center',
                            background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--error)', fontSize: 14
                          }}
                        >
                          ×
                        </button>
                      </div>
                      <div style={{ marginBottom: 6 }}>
                        <div style={{ ...labelStyle, fontSize: 10 }}>Role</div>
                        <Input
                          value={String(a.role || '')}
                          onChange={(e) => {
                            const agents = [...(config.agents as unknown[] || [])] as Record<string, unknown>[]
                            agents[idx] = { ...agents[idx], role: e.target.value }
                            handleChange('agents', agents)
                          }}
                          placeholder="e.g. Senior Backend Engineer"
                          size="small"
                          style={inputStyle}
                        />
                      </div>
                      <div style={{ marginBottom: 6 }}>
                        <div style={{ ...labelStyle, fontSize: 10 }}>Goal</div>
                        <Input
                          value={String(a.goal || '')}
                          onChange={(e) => {
                            const agents = [...(config.agents as unknown[] || [])] as Record<string, unknown>[]
                            agents[idx] = { ...agents[idx], goal: e.target.value }
                            handleChange('agents', agents)
                          }}
                          placeholder="Build robust, scalable APIs"
                          size="small"
                          style={inputStyle}
                        />
                      </div>
                      <div style={{ marginBottom: 6 }}>
                        <div style={{ ...labelStyle, fontSize: 10 }}>Model</div>
                        <Input
                          value={String(a.model || 'gpt-4o')}
                          onChange={(e) => {
                            const agents = [...(config.agents as unknown[] || [])] as Record<string, unknown>[]
                            agents[idx] = { ...agents[idx], model: e.target.value }
                            handleChange('agents', agents)
                          }}
                          size="small"
                          style={inputStyle}
                        />
                      </div>
                    </div>
                  )
                })}

                {((config.agents as unknown[]) || []).length === 0 && (
                  <div style={{ fontSize: 11, color: 'var(--text-tertiary)', textAlign: 'center', padding: '8px 0' }}>
                    No agents configured. Click "+ Add Agent" to add one.
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Knowledge Retrieval Config */}
          {nodeType === 'knowledge-retrieval' && (
            <div style={{ padding: 12, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>Knowledge Retrieval</div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Top K: {String(config.top_k || 5)}</div>
                <Slider min={1} max={20} value={Number(config.top_k || 5)} onChange={(v) => handleChange('top_k', v)} />
              </div>
              <div>
                <div style={labelStyle}>Layer</div>
                <Select value={String(config.layer || 'all')} onChange={(v) => handleChange('layer', v)} options={[{ label: 'All', value: 'all' }, { label: 'Semantic', value: 'semantic' }, { label: 'Episodic', value: 'episodic' }, { label: 'Procedural', value: 'procedural' }]} style={{ width: '100%' }} />
              </div>
            </div>
          )}

          {/* Trigger Config */}
          {(nodeType === 'manual-trigger') && (
            <div style={{ padding: 12, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>Trigger Variables</div>
              <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
                Define input variables in the workflow DSL. Users will fill these when running.
              </div>
            </div>
          )}

          {nodeType === 'schedule-trigger' && (
            <div style={{ padding: 12, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>Schedule</div>
              <div>
                <div style={labelStyle}>Cron Expression</div>
                <Input value={String(config.cron || '0 * * * *')} onChange={(e) => handleChange('cron', e.target.value)} placeholder="0 * * * *" style={{ ...inputStyle, fontFamily: 'monospace' }} />
              </div>
            </div>
          )}

          {/* Iteration/Loop Config */}
          {nodeType === 'loop' && (
            <div style={{ padding: 12, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>Loop</div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Condition</div>
                <TextArea rows={2} value={String(config.condition || '')} onChange={(e) => handleChange('condition', e.target.value)} placeholder="iteration < 10" style={{ ...inputStyle, fontFamily: 'monospace' }} />
              </div>
              <div>
                <div style={labelStyle}>Max Iterations: {String(config.max_iterations || 100)}</div>
                <Slider min={1} max={500} value={Number(config.max_iterations || 100)} onChange={(v) => handleChange('max_iterations', v)} />
              </div>
            </div>
          )}

          {/* Template Config */}
          {nodeType === 'template' && (
            <div style={{ padding: 12, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>Template</div>
              <div>
                <div style={labelStyle}>Template (use {'{{#nodeId.key#}}'} for variables)</div>
                <TextArea rows={5} value={String(config.template || '')} onChange={(e) => handleChange('template', e.target.value)} placeholder="Hello {{#start.name#}}!" style={{ ...inputStyle, fontFamily: 'monospace' }} />
              </div>
            </div>
          )}

          {/* Parameter Extractor Config */}
          {nodeType === 'parameter-extractor' && (
            <div style={{ padding: 12, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>Parameter Extractor</div>
              <div>
                <div style={labelStyle}>Parameters (JSON array)</div>
                <TextArea rows={4} value={JSON.stringify(config.parameters || [], null, 2)} onChange={(e) => { try { handleChange('parameters', JSON.parse(e.target.value)) } catch { /* ignore */ } }} placeholder='[{"name": "city", "type": "string", "description": "City name"}]' style={{ ...inputStyle, fontFamily: 'monospace' }} />
              </div>
            </div>
          )}

          {/* Question Classifier Config */}
          {nodeType === 'question-classifier' && (
            <div style={{ padding: 12, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>Question Classifier</div>
              <div>
                <div style={labelStyle}>Categories (comma separated)</div>
                <Input value={String((config.categories as string[])?.join(', ') || '')} onChange={(e) => handleChange('categories', e.target.value.split(',').map(s => s.trim()).filter(Boolean))} placeholder="bug, feature, question" style={inputStyle} />
              </div>
            </div>
          )}

          {/* File Reader Config */}
          {nodeType === 'file-reader' && (
            <div style={{ padding: 12, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)', borderRadius: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>File Reader</div>
              <div style={{ marginBottom: 10 }}>
                <div style={labelStyle}>Mode</div>
                <Select value={String(config.mode || 'auto')} onChange={(v) => handleChange('mode', v)} options={[{ label: 'Auto', value: 'auto' }, { label: 'Plain Text', value: 'plain' }, { label: 'Markdown', value: 'markdown' }, { label: 'Structured', value: 'structured' }]} style={{ width: '100%' }} />
              </div>
              <div>
                <div style={labelStyle}>Max Size (MB): {String(config.max_size_mb || 10)}</div>
                <Slider min={1} max={50} value={Number(config.max_size_mb || 10)} onChange={(v) => handleChange('max_size_mb', v)} />
              </div>
            </div>
          )}
        </Form>
      </div>
    </div>
  )
}
