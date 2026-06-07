import { Input, Select, Slider } from 'antd'
import Editor from '@monaco-editor/react'
import { useTheme } from '../../common/ThemeProvider'
import { Section, Field, AgentListEditor, inputStyle } from './SectionField'

const { TextArea } = Input

interface ConfigFormProps {
  config: Record<string, unknown>
  nodeType: string
  handleChange: (field: string, value: unknown) => void
  providerOptions: Array<{ label: string; value: string }>
  defaultProviderId?: string
}

export default function NodeConfigForms({ config, nodeType, handleChange, providerOptions, defaultProviderId }: ConfigFormProps) {
  const { mode } = useTheme()

  return (
    <>
      {nodeType === 'llm' && (
        <Section title="AI Configuration">
          <Field label="Provider">
            <Select size="small" value={String(config.provider || defaultProviderId || '')} onChange={(v) => handleChange('provider', v)}
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

      {nodeType === 'react-agent' && (
        <Section title="ReAct Agent">
          <Field label="Provider">
            <Select size="small" value={String(config.provider || defaultProviderId || '')} onChange={(v) => handleChange('provider', v)}
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

      {nodeType === 'knowledge-retrieval' && (
        <Section title="Knowledge Retrieval">
          <Field label="Mode">
            <Select size="small" value={String(config.mode || 'search')} onChange={(v) => handleChange('mode', v)}
              options={[{ label: 'Search Memory', value: 'search' }, { label: 'Ingest Knowledge', value: 'ingest' }]} style={{ width: '100%' }} />
          </Field>
          {config.mode !== 'ingest' && (
            <>
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
            </>
          )}
          {config.mode === 'ingest' && (
            <>
              <Field label="Content Type">
                <Select size="small" value={String(config.content_type || 'document')} onChange={(v) => handleChange('content_type', v)}
                  options={[{ label: 'Document', value: 'document' }, { label: 'Fact', value: 'fact' }, { label: 'Code Snippet', value: 'code_snippet' }, { label: 'API Doc', value: 'api_doc' }, { label: 'Error Pattern', value: 'error_pattern' }]} style={{ width: '100%' }} />
              </Field>
              <Field label="Content">
                <TextArea rows={4} value={String(config.content || '')} onChange={(e) => handleChange('content', e.target.value)} placeholder="Knowledge to ingest into memory..." style={inputStyle} />
              </Field>
            </>
          )}
          <Field label="Workflow ID (optional)">
            <Input size="small" value={String(config.workflow_id || '')} onChange={(e) => handleChange('workflow_id', e.target.value)} placeholder="Default: current workflow" style={inputStyle} />
          </Field>
        </Section>
      )}

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

      {nodeType === 'manual-trigger' && (
        <Section title="Trigger Variables">
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 8 }}>
            Define input variables for this workflow.
          </div>
          <Field label="Variables (JSON)">
            <Editor height="100px" language="json"
              value={JSON.stringify(config.variables || [], null, 2)}
              onChange={(v) => { try { handleChange('variables', JSON.parse(v || '[]')) } catch { /* ignore invalid JSON */ } }}
              theme={mode === 'dark' ? 'vs-dark' : 'vs'}
              options={{ minimap: { enabled: false }, fontSize: 11, lineNumbers: 'off', scrollBeyondLastLine: false, padding: { top: 4, bottom: 4 } }} />
          </Field>
        </Section>
      )}

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

      {nodeType === 'variable-aggregator' && (
        <Section title="Variable Aggregator">
          <Field label="Variables (JSON array of node refs)">
            <Editor height="100px" language="json"
              value={JSON.stringify(config.variables || [], null, 2)}
              onChange={(v) => { try { handleChange('variables', JSON.parse(v || '[]')) } catch { /* ignore invalid JSON */ } }}
              theme={mode === 'dark' ? 'vs-dark' : 'vs'}
              options={{ minimap: { enabled: false }, fontSize: 11, lineNumbers: 'off', scrollBeyondLastLine: false, padding: { top: 4, bottom: 4 } }} />
          </Field>
        </Section>
      )}

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

      {nodeType === 'template' && (
        <Section title="Template">
          <Field label="Template (use {{#nodeId.key#}} for variables)">
            <TextArea rows={5} value={String(config.template || '')} onChange={(e) => handleChange('template', e.target.value)} placeholder="Hello {{#start.name#}}!" style={{ ...inputStyle, fontFamily: 'monospace' }} />
          </Field>
        </Section>
      )}

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
              onChange={(v) => { try { handleChange('parameters', JSON.parse(v || '[]')) } catch { /* ignore invalid JSON */ } }}
              theme={mode === 'dark' ? 'vs-dark' : 'vs'}
              options={{ minimap: { enabled: false }, fontSize: 11, lineNumbers: 'off', scrollBeyondLastLine: false, padding: { top: 4, bottom: 4 } }} />
          </Field>
        </Section>
      )}

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

      {nodeType === 'sub-workflow' && (
        <Section title="Sub-Workflow">
          <Field label="Workflow ID">
            <Input size="small" value={String(config.workflow_id || '')} onChange={(e) => handleChange('workflow_id', e.target.value)} placeholder="workflow-id" style={inputStyle} />
          </Field>
          <Field label="Input Mapping (JSON)">
            <Editor height="80px" language="json"
              value={JSON.stringify(config.inputs || {}, null, 2)}
              onChange={(v) => { try { handleChange('inputs', JSON.parse(v || '{}')) } catch { /* ignore invalid JSON */ } }}
              theme={mode === 'dark' ? 'vs-dark' : 'vs'}
              options={{ minimap: { enabled: false }, fontSize: 11, lineNumbers: 'off', scrollBeyondLastLine: false, padding: { top: 4, bottom: 4 } }} />
          </Field>
        </Section>
      )}

      {nodeType === 'comment' && (
        <Section title="Comment">
          <Field label="Text">
            <TextArea rows={4} value={String(config.text || '')} onChange={(e) => handleChange('text', e.target.value)} placeholder="Add notes..." style={inputStyle} />
          </Field>
        </Section>
      )}
    </>
  )
}
