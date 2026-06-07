import { Input, Button } from 'antd'
import { useWorkflowStore } from '../../stores/workflowStore'
import { useSettingsStore } from '../../stores/settingsStore'
import { useProviderStore, PROVIDER_LABELS } from '../../stores/providerStore'
import { getNodeDefinition } from './registry'
import NodeConfigForms from './node-configs/NodeConfigForms'

function TrashIcon() {
  return <svg width={12} height={12} viewBox="0 0 12 12" fill="none"><path d="M2 3H10M4.5 3V2C4.5 1.4 4.9 1 5.5 1H6.5C7.1 1 7.5 1.4 7.5 2V3M9.5 3V10C9.5 10.6 9.1 11 8.5 11H3.5C2.9 11 2.5 10.6 2.5 10V3" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" /><path d="M5 5.5V8.5M7 5.5V8.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" /></svg>
}

export default function NodePanel() {
  const nodes = useWorkflowStore(s => s.nodes)
  const selectedNodeId = useWorkflowStore(s => s.selectedNodeId)
  const updateNodeData = useWorkflowStore(s => s.updateNodeData)
  const removeNode = useWorkflowStore(s => s.removeNode)
  const providers = useProviderStore(s => s.providers)
  const getDefaultProvider = useProviderStore(s => s.getDefaultProvider)
  const aiProvider = useSettingsStore(s => s.aiProvider)
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
  const defaultProv = getDefaultProvider()
  const providerOptions = providers.map(p => ({ label: `${p.name} (${PROVIDER_LABELS[p.type]})`, value: p.id }))

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

        <NodeConfigForms
          config={config}
          nodeType={nodeType}
          handleChange={handleChange}
          providerOptions={providerOptions}
          defaultProviderId={defaultProv?.id || aiProvider}
        />
      </div>
    </div>
  )
}
